import os
from dotenv import load_dotenv
load_dotenv()

HELIUM_API_DOMAIN = "http://localhost:5000" # get PORT from .env

routes = {
    "get_state":       "/api/state",
    "get_ip":          "/api/ip",
    "get_invocations": "/api/invocations",
    "get_item":        "/api/item",
    "get_searchpage":  "/api/searchpage",
    "get_storefront":  "/api/storefront",
}
