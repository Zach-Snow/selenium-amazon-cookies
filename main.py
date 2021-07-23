import os
import requests
from requests.exceptions import ConnectionError
from json.decoder import JSONDecodeError
import cloudscraper
import seleniumrequests
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import ElementNotInteractableException
from dotenv import load_dotenv

load_dotenv()
from typing import Dict
from utils import load_random_headers
from bs4 import BeautifulSoup
from empty_json_response import EmptyJSONResponse
from utils import get_cookiejar_from_list
from database import db
from routes import HELIUM_API_DOMAIN
import json
from time import time, sleep
from datetime import timedelta
import numpy as np
import hjson
from pprint import pprint
from termcolor import colored
from exception import PostException, ResponseException

tld = hjson.load(open("data/tld.hjson", "rb"), object_pairs_hook=dict)
flag = hjson.load(open("data/flag.hjson", "rb"), object_pairs_hook=dict)
ipify_api_key = os.getenv("APIKEY_IPIFY")
MAX_GET_ATTEMPTS = int(os.getenv("MAX_GET_ATTEMPTS"))
MAX_GET_404_ATTEMPTS = int(os.getenv("MAX_GET_404_ATTEMPTS"))
MAX_POST_200_ATTEMPTS = int(os.getenv("MAX_POST_200_ATTEMPTS"))
MAX_POST_503_ATTEMPTS = int(os.getenv("MAX_POST_503_ATTEMPTS"))


class Session(cloudscraper.CloudScraper):

    def __init__(self):
        super().__init__()
        print(colored("INIT", "blue"), "session")
        self.headers = load_random_headers()
        '''
        self.located = {
            "DE": False,
            "UK": False,
            "FR": False,
            "IT": False,
            "ES": False,
            "US": False,
        }
        '''
        self.location = {
            "DE": None,
            "UK": None,
            "FR": None,
            "IT": None,
            "ES": None,
            "US": None,
        }

    @property
    def ip(self) -> Dict:
        try:
            # response = self.get("https://api.ipify.org?format=json", set_location=False, handle_captcha=False)
            # response = self.get(f"https://geo.ipify.org/api/v1?apiKey={ipify_api_key}", set_location=False, handle_captcha=False)
            response = self.get("http://ip-api.com/json/")
            return json.loads(BeautifulSoup(response.text, "html.parser").get_text())
        except:
            return {}

    def loc(self, country) -> Dict:
        '''
        Open Amazon for the given country (unless it's already open) and return the location that Amazon displays.
        This can be used to verify if we successfully set the location using cookies.
        '''
        global tld
        response = self.get(f"https://www.amazon.{tld[country]}", set_location=False)
        soup = BeautifulSoup(response.text, "html.parser")
        location_element = soup.find("span", {"id": "glow-ingress-line2"})
        location = None
        if location_element:
            location = location_element.get_text().replace("\n", "").strip()
        self.location[country] = location
        return {country: location}

    def get(self, url, params=None, set_location=True, handle_captcha=True, enforce_json=False,
            **kwargs) -> requests.Response:
        try:
            response = self._get(url, params=params, set_location=set_location, handle_captcha=handle_captcha, **kwargs)
            if enforce_json:
                try:
                    response.json()
                    return response
                except JSONDecodeError as e:
                    print(colored("JSONDecodeError", "red"), e)
                    return EmptyJSONResponse()
                    # try again?
            else:
                return response
        except ConnectionError as e:
            print(colored("ConnectionError", "red"), e)
            return EmptyJSONResponse()

    def _get(self, url, params=None, set_location=True, handle_captcha=True, **kwargs) -> requests.Response:
        global MAX_GET_ATTEMPTS, MAX_POST_200_ATTEMPTS, MAX_POST_503_ATTEMPTS

        print(colored("GET", "blue"), url)

        if "amazon." in url:
            sleep(0.15)  # to make it a bit more realistic, not too fast

            # 1. Handling Amazon location cookies:
            if set_location:
                if "amazon.de" in url:
                    self.locate("DE")
                elif "amazon.co.uk" in url:
                    self.locate("UK")
                elif "amazon.fr" in url:
                    self.locate("FR")
                elif "amazon.it" in url:
                    self.locate("IT")
                elif "amazon.es" in url:
                    self.locate("ES")
                elif "amazon.com" in url and "images-na.ssl-images-amazon.com" not in url:
                    self.locate("US")

            # 2. Making the actual request:
            response = super().get(url, params=params, **kwargs)
            status = response.status_code

            # 3. Handling 503 errors:
            get_counter = 0
            get_404_counter = 0
            if status != 200:
                print(colored("  HANDLE", "blue"), f"{status} status")
                while status != 200 and get_counter < MAX_GET_ATTEMPTS:
                    # if status==200, it could be a captcha, but then the POST block deals with that
                    response = super().get(url, params=params, **kwargs)
                    status = response.status_code
                    print(
                        f"    ({get_counter}) {status} ({len(response.text)}) {'is_captcha=' + str('images-na.ssl-images-amazon.com/captcha/' in response.text) if status == 200 else ''}")
                    if status == 503:
                        sleep(np.random.uniform(3, 5))
                    elif status == 404:
                        if get_404_counter > MAX_GET_404_ATTEMPTS:
                            with open(f"troubleshoot/({status}) {int(time())}.html", "w") as f:
                                f.write(response.text)
                            return EmptyJSONResponse()
                        get_404_counter += 1
                    else:
                        print("Status:", status)
                        # raise Exception
                    get_counter += 1
                if get_counter >= MAX_GET_ATTEMPTS:
                    raise ResponseException(f"{status} Status Error")

            # 4. Handling captchas (which, when trying to handle them, can lead to 503 errors):
            post_200_counter = 0
            post_503_counter = 0
            if handle_captcha and "images-na.ssl-images-amazon.com/captcha/" in response.text:
                print(colored("  HANDLE", "blue"), "captcha")
                status = None
                payload = Session.get_captcha_payload(response)
                while (status != 200 or "images-na.ssl-images-amazon.com/captcha/" in response.text) and (
                        post_200_counter < MAX_POST_200_ATTEMPTS and post_503_counter < MAX_POST_503_ATTEMPTS):
                    if "images-na.ssl-images-amazon.com/captcha/" in response.text:
                        payload = Session.get_captcha_payload(response)
                    print(colored("  POST", "blue"), "captcha solution")
                    response = super().post(url,
                                            data=payload)  # if 503, also POST but with last iteration's captcha solution, until status 200 comes, then if it's a captcha, solve and POST this new solution
                    status = response.status_code
                    sleep(np.random.uniform(3, 5))
                    if status == 503:
                        # "InternalServerError"
                        print(
                            f"  ({post_503_counter}) {status} ({len(response.text)}) is_captcha={'images-na.ssl-images-amazon.com/captcha/' in response.text}")
                        post_503_counter += 1
                    elif status == 200:
                        print(f"    ({post_200_counter}) {status} ({len(response.text)})")
                        post_200_counter += 1
                        # If the status==2, the captcha was either solved, or there's a new captcha:
                    elif status == 405:
                        # "Method not allowed", e.g. trying to POST the captcha solution to a route that doesn't handle POST requests
                        print(colored("  PostException", "red"), "at", url)
                        raise PostException("PostException")
                    else:
                        print(colored("  STATUS", "red"), status)
                        #
                        #
                        #
                        #
                        raise Exception(f"{status} Status Error (Unknown cause)")
                if post_200_counter >= MAX_POST_200_ATTEMPTS or post_503_counter >= MAX_POST_503_ATTEMPTS:
                    raise ResponseException(f"{status} Status Error")

            # 5. Conclusion:
            if (
                    get_counter < MAX_GET_ATTEMPTS and post_200_counter < MAX_POST_200_ATTEMPTS and post_503_counter < MAX_POST_503_ATTEMPTS) or (
                    status == 200 and "images-na.ssl-images-amazon.com/captcha/" not in response.text):
                pass
                # print(colored("  SUCCESS", "green"))
                # soup = BeautifulSoup(response.text, "html.parser")
                # print(soup)
            else:
                print(colored("  FAIL", "red"))
                filepath = f"troubleshoot/(captcha) {int(time())}.html"
                print(colored("  STORE", "blue"), f"log file to {filepath}")
                with open(filepath, "w") as f:
                    f.write(response.text)

        else:
            # If the request doesn't go to Amazon, just use the regular Session object and wrap the response in my own
            response = super().get(url, params=params, **kwargs)

        return response

    def post(self, url, data=None, json=None, **kwargs):
        print(colored("POST", "blue"), url)
        return super().post(url, data=data, json=json, **kwargs)

    def locate(self, country: str) -> None:
        global flag
        # if not self.located[country]:
        if not self.location[country]:

            if np.random.uniform(0, 1) < 0.05:
                # With 5% probability, delete a location cookie that is older than 1 week
                current_timestamp = int(time())
                db.cookie.delete_one({"timestamp": {"$lt": current_timestamp - timedelta(days=7).total_seconds()}})
                print(colored("  DELETE", "blue"), "1 random old location cookie from the database")

            sample = list(db.cookie.aggregate([{"$match": {"country": country}}, {"$sample": {"size": 1}}]))

            if len(sample) == 0 or np.random.uniform(0, 1) < 0.1:
                # With 10% probability or if no cookies are available for that country, fetch completely new ones from Amazon
                # using a random zip code from the database:
                # self.fetch_cookies(country)
                # cookies should now be in session.cookies
                pass

            else:
                # Otherwise (90% probability), simply get existing cookies from the database
                cookiedoc = sample[0]  # cookie document from the database
                self.cookies.update(get_cookiejar_from_list(cookiedoc["cookies"]))

            location = self.loc(country)
            if "German" not in location[country] and "Alemania" not in location[country] and "Allemagne" not in \
                    location[country] and "Lieferadresse" not in location[country]:
                # self.located[country] = True
                self.location.update(location)  # let's see what Amazon says my location is
                print(colored("  SET", "blue"),
                      f"Amazon location cookies for {flag[country]} to {self.location[country]}")

            else:
                # Try again:
                self.locate(country)

    def reset_cookies(self):
        self.cookies = get_cookiejar_from_list([])  # empty cookiejar
        # self.located = {country: False for country in self.located.keys()} # we are no longer located!
        self.location = {country: None for country in self.location.keys()}  # we are no longer located!

    def get_captcha_payload(response: requests.Response) -> Dict:
        if "images-na.ssl-images-amazon.com/captcha/" in response.text:

            soup = BeautifulSoup(response.text, "html.parser")
            image_url = ""
            for img in soup.find_all("img", {"src": True}):
                image_url = img.get("src")
                if "images-na.ssl-images-amazon.com/captcha" in image_url:
                    break

            if image_url != "":
                captcha_response = requests.get(f"{HELIUM_API_DOMAIN}/api/solvecaptcha?url={image_url}").json()
                captcha_solution = captcha_response["captcha_solution"]
                amzn = soup.find("input", {"name": "amzn"}).get("value")
                amzn_r = soup.find("input", {"name": "amzn-r"}).get("value")
            else:
                amzn = ""
                amzn_r = ""
                captcha_solution = ""

            data = {
                "amzn": amzn,
                "amzn-r": amzn_r,
                "field-keywords": captcha_solution,
            }

            return data

    def fetch_cookies(self, country: str) -> None:
        # Sample a random zip code from the zip database collection (which in turn can be obtained via the fetch_zip_codes.py script
        # using the zipcodebase API). Then, using a selenium webdriver, type in the zip code into Amazon and store the resulting
        # location cookies in the database and put them into the session. The webdriver can then be closed.
        global flag, tld
        start_cookiejar_length = len(self.cookies)

        # 1. Fetch random zip code from zip collection
        #    and make sure that we don't already have cookies for that zip code in the cookie collection. If we do, fetch a different random zip code.
        zip_code = None
        while zip_code in [cookie["zip"] for cookie in
                           list(db.cookie.find({"country": country, "type": "location"}))] or zip_code is None:
            zip_code = list(db.zip.aggregate([{"$match": {"country": country}}, {"$sample": {"size": 1}}]))[0]["zip"]
        print(colored("  FETCH", "blue"), f"new cookies on Amazon {flag[country]} for zip {zip_code}")

        # 2. Create selenium webdriver and type zip code into location selection
        options = Options()
        options.headless = True
        driver = seleniumrequests.Chrome(options=options)

        # 3. Get selenium webdriver cookies from Amazon and put them in the correct format
        driver.get(f"https://www.amazon.{tld[country]}/")
        delivery_location_field = driver.find_element_by_id("nav-global-location-popover-link")
        location_before_cookie = delivery_location_field.text.replace("\n", " ").strip()
        delivery_location_field.click()
        sleep(1)
        try:
            input_field = driver.find_element_by_id("GLUXZipUpdateInput")
            input_field.clear()
        except ElementNotInteractableException:
            current_zip_code = driver.find_element_by_id("GLUXZipConfirmationValue").text
            print(f"zip code is currently set to {current_zip_code}")
            print(colored("  RESET", "blue"), "zip code")
            delivery_location_reset = driver.find_element_by_id("GLUXChangePostalCodeLink")
            delivery_location_reset.click()
            sleep(1)
            # Try the thing from above again:
            input_field = driver.find_element_by_id("GLUXZipUpdateInput")
            print(input_field)
            input_field.clear()
        # This only works once the delivery location input field is interactable
        input_field.send_keys(zip_code)
        driver.find_element_by_id("GLUXZipUpdate").find_element_by_css_selector("input").click()
        cookies = driver.get_cookies()

        # 4. Put cookies into our session.
        self.cookies.update(get_cookiejar_from_list(cookies))
        # print(self.cookies)

        # 5. Close selenium webdriver.
        driver.quit()

        # 6. Store cookies in cookie collection.
        if len(self.cookies) > start_cookiejar_length:
            # If it worked, the cookiejar should now be bigger than before
            db.cookie.insert_one({
                "cookies": cookies,
                "country": country,
                "timestamp": int(time()),
                "type": "location",
                "zip": zip_code,
            })
        else:
            # If it didn't work, try again:
            self.reset_cookies()
            self.fetch_cookies(country)
