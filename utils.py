import os
import random
import numpy as np
from typing import Dict, List
from bs4 import BeautifulSoup
from flask import url_for
import hjson
from dotenv import load_dotenv

load_dotenv()
import http
import requests
import hashlib
import pymongo
from datetime import datetime, timedelta
from time import time
from database import db
from json.decoder import JSONDecodeError

PORT = os.getenv("PORT")
PROBABILITY_CREATE_NEW_ACCOUNT = float(os.getenv("PROBABILITY_CREATE_NEW_ACCOUNT"))
FORCE_SIGNUP = eval(os.getenv("FORCE_SIGNUP").capitalize())

cities = list(db.city.find({"country": "DE"}, {"_id": False, "city": True}))
cities = [item["city"] for item in cities]


def extract_brand(brand: str, country: str) -> str:
    '''
    Sometimes it doesn't work even though the site clearly has a brand name available !!!
    E.g. https://www.amazon.fr/dp/B08X1VB2MF
    The errors are:
    AttributeError: element <{id: bylineInfo}> not found.
    AttributeError: element <{id: brand}> not found.
    '''
    # brand is the full string containing the actual brand
    brand = str(brand)  # in case it's unicode-encoded (u"...")
    brand = brand.replace("\xa0", " ")
    return {
        "DE": "".join(word.replace("-Store", "") for word in brand.split(" ") if
                      word not in ("Besuchen", "Sie", "den", "Marke:")),
        "IT": "".join(word for word in brand.split(" ") if word not in ("Visita", "lo", "Store", "di", "Marca:")),
        "FR": "".join(
            word for word in brand.split(" ") if word not in ("Visiter", "la", "boutique", "Marque", ":", "Marque:")),
        "ES": "".join(word for word in brand.split(" ") if word not in ("Visita", "la", "Store", "de", "Marca:")),
        "US": "".join(word for word in brand.split(" ") if word not in ("Visit", "the", "Store", "Brand:")),
        "UK": "".join(word for word in brand.split(" ") if word not in ("Visit", "the", "Store", "Brand:")),
    }[country]


def generate_app_id() -> str:
    length = random.randint(62, 64)
    array = (random.randint(0, 15) for _ in range(length))
    return "".join("0123456789abcdef"[i] for i in array)


def build_url(method_name) -> str:
    # later: https instead of http
    # later: app.amazingbrands.group instead of localhost
    global PORT
    return f"http://localhost:{PORT}{url_for(method_name)}"


def requests_cookie_format(cookie: Dict[str, str]) -> Dict[str, str]:
    if "expiry" in cookie.keys():
        cookie["expires"] = cookie["expiry"]
        del cookie["expiry"]
    if "httpOnly" in cookie.keys():
        cookie["rest"] = {"HttpOnly": cookie["httpOnly"]}
        del cookie["httpOnly"]
    return cookie


def find_captcha_in_source_code(page_source: str) -> Dict[str, str]:
    soup = BeautifulSoup(page_source, "html.parser")
    img_url = soup.find("form", {"action": "/errors/validateCaptcha"}).find("img")
    src = ""
    if img_url:
        src = img_url.get("src")
    return src


def load_random_account_email(service: str = "helium") -> Dict[str, str]:
    '''
    All accounts for that service that are not in hibernation or that have been hibernating for more than 24 hours.
    By "hibernate", I mean an account that has reached its daily limit and should therefore not be used in the next 24 hours
    until its daily usage has been reset to 0.
    If no such account exists, generate a new one. But this account is not yet registered at the site. We therefore set the
    status to "pending". Later on in the backend, it will check if the status is "pending" and if so, it will fill in the signup
    form to register the account with the site and set the status to "created".
    '''
    global PROBABILITY_CREATE_NEW_ACCOUNT, FORCE_SIGNUP

    service_accounts = list(db.account.find({
        "service": service,
        "status": "created",
        "active": {"$eq": False},
        # If "active" is true, this means the account is currently being used by one of the containers. If the container
        # exits unorderly, it may fail to reset the "active" parameter back to false. Because of this, the container is also
        # whenever the API is quitted, the database is "cleaned up" which includes checking all the "active" accounts. If
        # their login_cookies_timestamp is older than 2 days, they are set to "inactive" ("active" = false)
        "$or": [
            {"hibernation": None},
            {"hibernation": {"$lt": datetime.now() - timedelta(days=1)}}
        ]
    }))

    # The status must be "created"! Not "pending" which only happens when I create a new account below and the status should
    # immediately be set to "created" as soon the pending account is received by the backend and then registered on Helium10
    # by the backend. Old used up accounts have the status "frozen".
    # With a certain small probability, it's going to create a new account regardless of whether one already exists
    if FORCE_SIGNUP or len(service_accounts) == 0 or np.random.uniform() < PROBABILITY_CREATE_NEW_ACCOUNT:
        # Create new account:
        # If no account was found with these specific characteristics, create a new one and store it in the database
        session = requests.Session()
        session.headers.update({
                                   "user-agent": "Mozilla/5.0 (X11; Ubuntu; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/78.0.3904.108 Safari/537.36 RuxitSynthetic/1.0 v8542696046251871504 t6331743126571670211"})
        firstname, lastname = session.get("https://namey.muffinlabs.com/name.json?with_surname=true").json()[0].split(
            " ")
        mail_providers = {
            # "web.de": 1,
            "gmail.com": 5,
            "gmx.net": 3,
            "aol.com": 3,
            "yahoo.com": 4,
            "outlook.com": 3,
            "live.com": 3,
            "hotmail.com": 3,
            "protonmail.com": 1,
            "tutanota.com": 1,
            "yandex.com": 1,
        }

        def softmax(x, t=1.0):
            # t: temperature paramter
            return np.exp(np.divide(x, t)) / np.exp(np.divide(x, t)).sum()

        # Just to quickly turn the weights I assigned to the mail providers into probabilities using softmax:
        probs = softmax(np.array(list(mail_providers.values())), t=3.0)
        account_email = (firstname + "." + lastname).lower()
        account_email += (("." if np.random.uniform() < 0.75 else "_") if np.random.uniform() < 0.2 else "")
        account_email += str(random.randint(10, 10000))
        account_email += "@" + np.random.choice(list(mail_providers.keys()), p=probs)
        # Some mail accounts are sampled with greater probability than others
        '''
        Password is simply the MD5 hash of the email but without the @ sign, dots and underscores.
        This way, I can easily reconstruct the password to an old account if I need to even if I deleted the password.
        '''
        hash = hashlib.md5()
        hash.update(account_email.replace("@", "").replace(".", "").replace("_", "").encode("utf-8"))
        password = hash.hexdigest()
        # The full account dictionary:
        random_account = {
            "firstname": firstname,
            "lastname": lastname,
            "email": account_email,
            "password": password,
            "service": service,
            "status": "pending",
            # the status is later set to "created" in the backend, once the account has actually been created on the site
            "hibernation": None,
            # datetime object of when the account "went to sleep" (when its daily limit was reached)
            "login_cookies": None,
            "login_cookies_timestamp": 0,
            "signup_timestamp": int(time()),
        }
        # And finally, let's write it to the database:
        db.account.insert_one(random_account)
    else:
        random_account = random.choice(service_accounts)
        account_email = random_account["email"]
    # Now that we have picked a random account:
    if random_account["hibernation"] is not None and random_account["hibernation"] < datetime.now() - timedelta(days=1):
        # This means we can safely set the "hibernation" back to None since the daily usage has been reset by now (since
        # we haven't used this account for at least 24 hours).
        db.account.delete_one({"email": random_account["email"]})
        random_account["hibernation"] = None
        db.account.insert_one(random_account)
    return account_email


def load_random_headers() -> Dict[str, str]:
    '''
    Sample a random header from the database
    Later, perhaps also feed back the probability of success and then sample according to the resulting probability distribution
    (success distribution) plus some exploration factor (see bandit problems).
    '''
    random_headers = list(db.header.aggregate([{"$sample": {"size": 1}}]))[0]
    return {
        "user-agent": random_headers["user-agent"],
        "sec-fetch-site": "same-origin"
    }


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


def freeze_all() -> None:
    '''
    Freeze all accounts with status "created".
    '''
    for account in db.account.find({"status": "created"}):
        del account["_id"]
        db.account.delete_one(account)
        account["status"] = "frozen"
        db.account.insert_one(account)


def parse_impressum(soup: BeautifulSoup) -> Dict:
    impressum_german_to_english = {
        "geschäftsname": "companyName",
        "geschäftsart": "companyType",
        "handelsregisternummer": "commercialRegisterNumber",
        "ustid": "taxID",
        "unternehmensvertreter": "companyRepresentative",
        "kundendienstadresse": "customerServiceAddress",
        "geschäftsadresse": "companyAddress",
        "telefonnummer": "phoneNumber"
    }

    impressum = {k: None for k in impressum_german_to_english.values()}
    impressum["country"] = None
    impressum["aboutSeller"] = None

    seller_profile_container = soup.find("div", {"id": "seller-profile-container"})
    if seller_profile_container:

        seller_profile_container_str = str(seller_profile_container.find("ul"))
        # To make sure there's enough whitespaces:
        seller_profile_container_str = seller_profile_container_str.replace("<li>", "<li> ").replace("<\li>",
                                                                                                     " <\li>").replace(
            "\n", " ")

        if "Impressum & Info zum Verkäufer" in seller_profile_container.find("h3").get_text():
            impressum_items = [
                BeautifulSoup("<span>" + item, "html.parser").get_text().split(":")
                for item in seller_profile_container_str.split('<span class="a-text-bold">')
                if ":</span>" in item
            ]
            impressum.update({
                impressum_german_to_english[item[0].lower()]: item[1].strip()
                for item in impressum_items
            })
            # Country code: Assuming we care about country code of "Geschäftsadresse":
            impressum["country"] = impressum["companyAddress"][-2:] if impressum[
                "companyAddress"] else None  # final 2 letters in company address

        about_seller = seller_profile_container.find("div", {"id": "about-seller"})
        if about_seller:
            if about_seller.find("span", {"id": "about-seller-expanded"}):
                # CASE: long description
                about_seller_text = about_seller.find("span", {"id": "about-seller-expanded"})
            elif about_seller.find("span", {"id": "about-seller-text"}):
                # CASE: very short description, so there's no "expandable text"
                about_seller_text = about_seller.find("span", {"id": "about-seller-text"})
            if about_seller_text:
                about_seller_text = about_seller_text.get_text()
                about_seller_text = " ".join(
                    about_seller_text.replace("\n", " ").replace("\r", " ").replace("\xa0", " ").strip().split())
                impressum["aboutSeller"] = about_seller_text

        # Try to figure out the country in some other way:
        if impressum["country"] is None:

            if impressum["companyAddress"] is not None:
                # CASE: If the country is None but the address is not None, we can try to figure out the country just from the state/region/city:
                # Check all big German cities and see if the city is in impressum["companyAddress"]:
                for city in cities:
                    if city.lower() in impressum["companyAddress"].lower().split():
                        impressum["country"] = "DE"
                        print(f"Found German city '{city}' in 'companyAddress' section.'")
                        print(impressum["companyAddress"])
                        break

            elif impressum["aboutSeller"] is not None:
                # CASE: If the country and companyAddress are both None:
                # Look at "aboutSeller" instead:
                if "deutschland" in impressum["aboutSeller"].lower() or "germany" in impressum["aboutSeller"]:
                    # Check if the word "deutschland" or "germany" is mentioned in the "About Seller" section
                    impressum["country"] = "DE"
                    print("Found 'Deutschland' or 'Germany' in 'About Seller' section.")
                    print(impressum["aboutSeller"])
                else:
                    # Check if a German city is mentioned in the "About Seller" section:
                    for city in cities:
                        if city.lower() in impressum["aboutSeller"].lower().split():
                            impressum["country"] = "DE"
                            print(f"Found German city '{city}' in 'About Seller' section.'")
                            print(impressum["aboutSeller"])
                            break

    return impressum


def parse_feedback(soup: BeautifulSoup) -> Dict:
    '''
    Parse feedback HTML code (from response object) into its constituent parts and return a dictionary.
    This dictionary will then be appended to the overall data dictionary in the parse method which, at the
    end of the parse method, will be yielded (and also written to the database).
    '''
    feedback = dict()

    def parse_feedback_table_row(row: List, feedback_type: str) -> Dict:
        return {
            f"{feedback_type}Feedback30Days": row[1],
            f"{feedback_type}Feedback90Days": row[2],
            f"{feedback_type}Feedback12Months": row[3],
            f"{feedback_type}FeedbackRuntime": row[4]
        }

    def string_percentage_to_float(s: str) -> float:
        try:
            return float(s.replace("%", "")) / 100
        except:
            return None

    for item in soup.find("table", {"id": "feedback-summary-table"}).find_all("tr"):
        row = []
        for cell in item.find_all("td"):
            text = cell.get_text().strip()
            row.append(text)
        if len(row) > 0:
            if row[0] == "Positiv":
                for key, value in parse_feedback_table_row(row, "positive").items():
                    value = string_percentage_to_float(value)
                    feedback[key] = value
            elif row[0] == "Negativ":
                for key, value in parse_feedback_table_row(row, "negative").items():
                    value = string_percentage_to_float(value)
                    feedback[key] = value
            elif row[0] == "Neutral":
                for key, value in parse_feedback_table_row(row, "neutral").items():
                    value = string_percentage_to_float(value)
                    feedback[key] = value
            elif row[0] == "Anzahl":
                for key, value in parse_feedback_table_row(row, "num").items():
                    value = value.replace(".", "")  # remove thousands separator
                    try:
                        value = int(string_percentage_to_float(value) * 100)
                    except:
                        value = None
                    feedback[key] = value

    return feedback
