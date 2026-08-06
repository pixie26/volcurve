import sys
import requests
from requests.auth import HTTPBasicAuth
import urllib3
import json
import random
import schedule
import time
import datetime
from utilities import apiPost
from utilities import apiGet
from utilities import acceptTextCsv
from utilities import acceptApplicationJson
from shared_auth import oauth2
from main import main

def apis_call():
    # VOLATILITY in Json
    apiImpliedVolatility()

def apiImpliedVolatility():
    for code in ["EU_STOXX50E", "GB_FTSE100", "FR_CAC", "DE_DAX", "EU_SD3E", "GB_AZN", "NL_ASML", "DE_SIE", "FR_SAN", "DE_RHM", "DE_ENR"]:
        try:
            todayStr = datetime.date.today().strftime('%Y-%m-%d')
            curr_time = time.strftime("%H%M%S", time.localtime())

            body = {
                "code": code,
                "strikeRule": "relative_to_forward",
                "startDate": todayStr,
                "endDate": todayStr,
                "lowStrike": "50_0",
                "highStrike": "150_0",
                "lowMaturity": "1W",
                "highMaturity": "120M",
                "layout": "matrix"
            }

            response = apiPost(
                url_endpoints,
                "/v1/implied-volatility",
                acceptApplicationJson(headers),
                json.dumps(body),
                "volatility_" + body["code"] + "_" + body["startDate"] + "_" + body["endDate"] + "_" + curr_time + ".json",
                http_proxy
            )
        except Exception as e:
            print("An error occurred during an endpoint call (authentication ok), please retry or contact support team")
            print(e)

if __name__ == "__main__":
    url_endpoints, headers, http_proxy = main(sys.argv[1:])

    print("Ctrl+C to stop")

    apis_call()

    # Schedule task to run every 15 minutes
    schedule.every(15).minutes.do(apis_call)

    # Keep the program running to allow scheduled tasks to execute
    while True:
        schedule.run_pending()
        time.sleep(1)