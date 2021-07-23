import os
import pymongo
from dotenv import load_dotenv
from time import time
from datetime import timedelta

load_dotenv()

DB_USERNAME = os.getenv("DB_USERNAME")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_CLUSTER = os.getenv("DB_CLUSTER")

mongo = pymongo.MongoClient(
    f"mongodb+srv://{DB_USERNAME}:{DB_PASSWORD}@{DB_CLUSTER}.x8qup.mongodb.net/amaazingbrands?retryWrites=true&w=majority",
    connect=False)

db = pymongo.database.Database(mongo, "amazingbrands")


def cleanup_database():
    db.account.delete_many({"status": "pending"})
    db.amazon_item.delete_many({"brand": "n/a"})
    db.amazon_item.delete_many({"brand": {"$exists": False}})
    db.item.delete_many({"$or": [
        {"salesHistory.last30DaysSales": -1},
        {"salesHistory.last30DaysSales": {"$exists": False}}
    ]})
    '''
    The API may fail to reset an account's activity back to false if it exits in an unorderly fashion.
    Therefore, everytime the API exits orderly, it checks all accounts in the database: all accounts that are active but whose
    login_cookies_timestamp is older than 2 days are reset to inactive.
    '''
    falsely_active_accounts = list(db.account.find({
        "active": True,
        "login_cookies_timestamp": {"$lt": time() - timedelta(days=2).total_seconds()}
    }))
    if len(falsely_active_accounts) > 0:
        for i, _ in enumerate(falsely_active_accounts):
            falsely_active_accounts[i]["active"] = False
        db.account.delete_many({
            "active": True,
            "login_cookies_timestamp": {"$lt": time() - timedelta(days=2).total_seconds()}
        })
        db.account.insert_many(falsely_active_accounts)


def freeze_all() -> None:
    '''
    Freeze all accounts with status "created".
    '''
    for account in db.account.find({"status": "created"}):
        del account["_id"]
        db.account.delete_one(account)
        account["status"] = "frozen"
        db.account.insert_one(account)
