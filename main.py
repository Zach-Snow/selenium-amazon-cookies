import requests
import http
import hjson
import seleniumrequests
from typing import Dict, List
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import ElementNotInteractableException
from typing import Dict
from database import db
from time import time, sleep
from termcolor import colored

tld = hjson.load(open("data/tld.hjson", "rb"), object_pairs_hook=dict)
flag = hjson.load(open("data/flag.hjson", "rb"), object_pairs_hook=dict)


def get_cookiejar_from_list(cookies_list: List[Dict]) -> requests.cookies.RequestsCookieJar:
    '''
    This method takes a list of cookie dictionaries (e.g. as it might be returned by a selenium webdriver's .get_cookies method)
    and first turns each individual cookie dictionary into a cookie object and then turns the list of cookie objects into a
    cookiejar. This cookiejar can then be used by a request.Session object's cookies.
    '''
    _jar = requests.cookies.RequestsCookieJar()  # empty cookiejar
    # I now have to reshape each cookie dictionary in this list and turn it into a cookie object. I can then add each
    # cookie object into the cookiejar.
    for cookie_dict in cookies_list:
        _cookie_dict = {}
        _cookie_dict["name"] = cookie_dict["name"]
        _cookie_dict["domain"] = cookie_dict["domain"]
        _cookie_dict["value"] = cookie_dict["value"]
        _cookie_dict["path"] = cookie_dict["path"]
        _cookie_dict["secure"] = cookie_dict["secure"]
        _cookie_dict["expires"] = cookie_dict[
            "expiry"] if "expiry" in cookie_dict.keys() else None  # !!?!!?!? Will this work ???
        _cookie_dict["port"] = None
        _cookie_dict["port_specified"] = False
        _cookie_dict["version"] = 0
        _cookie_dict["domain_specified"] = ("domain" in cookie_dict.keys())
        _cookie_dict["domain_initial_dot"] = (cookie_dict["domain"][0] == ".")
        _cookie_dict["path_specified"] = ("path" in cookie_dict.keys())
        _cookie_dict["discard"] = False
        _cookie_dict["comment"] = None
        _cookie_dict["comment_url"] = None
        _cookie_dict["rest"] = {}
        if "httpOnly" in cookie_dict.keys():
            _cookie_dict["rest"]["httpOnly"] = cookie_dict["httpOnly"]
        if "sameSite" in cookie_dict.keys():
            _cookie_dict["rest"]["sameSite"] = cookie_dict["sameSite"]
        _cookie_dict["rfc2109"] = False
        _jar.set_cookie(http.cookiejar.Cookie(**_cookie_dict))
    return _jar


def fetch_cookies(country: str) -> None:
    # Sample a random zip code from the zip database collection (which in turn can be obtained via the fetch_zip_codes.py script
    # using the zipcodebase API). Then, using a selenium webdriver, type in the zip code into Amazon and store the resulting
    # location cookies in the database and put them into the session. The webdriver can then be closed.
    global flag, tld
    cookies = []

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
    print(cookies)

    # 4. Put cookies into our session.

    # print(self.cookies)

    # 5. Close selenium webdriver.
    driver.quit()

    # 6. Store cookies in cookie collection.
    if len(cookies) > 0:
        # If it worked, the cookiejar should now be bigger than before
        print("in if block")
        db.cookie.insert_one({
            "cookies": cookies,
            "country": country,
            "timestamp": int(time()),
            "type": "location",
            "zip": zip_code,
        })
    else:
        # If it didn't work, try again:
        cookies = []
        fetch_cookies(country)


fetch_cookies("DE")

