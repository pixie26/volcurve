import sys
import requests
from requests.auth import HTTPBasicAuth
import urllib3
import json
import random

from utilities import apiPost
from utilities import apiGet
from utilities import acceptTextCsv
from utilities import acceptApplicationJson
from shared_auth import oauth2
from main import main

def apis_call():
    # get instruments in Json
    apiInstrumentsRateVol()
    
    # get instruments in Csv
    apiInstrumentsRateVolCsv()
    
    # VOLATILITY in Json
    apiRateVolatility()
    
    # VOLATILITY in Csv
    apiRateVolatilityCsv()

def apiInstrumentsRateVol():
    try: 
        response = apiGet(url_endpoints,'/v1/instruments?type=rateVol', acceptApplicationJson(headers), "instrumentsRateVol.json", http_proxy)
    except Exception as e:
        print("An error occurred during an endpoint call (authentication ok), please retry or contact or support team")
        print(e)


def apiInstrumentsRateVolCsv():
    try: 
        response = apiGet(url_endpoints,'/v1/instruments?type=rateVol', acceptTextCsv(headers), "instrumentsRateVol.csv", http_proxy)
    except Exception as e:
        print("An error occurred during an endpoint call (authentication ok), please retry or contact or support team")
        print(e)

def apiRateVolatility():
    try: 
        body = {
            "code": "EUR3M",
            "startDate": "2026-04-27",
            "endDate": "2026-05-04",
            "output": "Volatility", # can be, Volatility, Call, Put, Straddle 
            "lowStrike": "M150",    # optional
            "highStrike": "150",    # optional
            "lowExpiry": "1M",      # optional
            "highExpiry": "20Y"     # optional
        }

        response = apiPost(url_endpoints,
                           "/v1/rate/volatility",
                           acceptApplicationJson(headers),
                           json.dumps(body),
                           "rateVolatility_" + body["code"] + "_" + body["startDate"] + "_" + body["endDate"] + ".json",
                           http_proxy)
    except Exception as e:
        print("An error occurred during an endpoint call (authentication ok), please retry or contact or support team")
        print(e)


def apiRateVolatilityCsv():
    try: 
        body = {
            "code": "EUR3M",
            "startDate": "2026-04-27",
            "endDate": "2026-05-04",
            "output": "Volatility", # can be, Volatility, Call, Put, Straddle 
            "lowStrike": "M150",    # optional
            "highStrike": "150",    # optional
            "lowExpiry": "1M",      # optional
            "highExpiry": "20Y"     # optional
        }

        response = apiPost(url_endpoints,
                           "/v1/rate/volatility",
                           acceptTextCsv(headers),
                           json.dumps(body),
                           "rateVolatility_" + body["code"] + "_" + body["startDate"] + "_" + body["endDate"] + ".csv",
                           http_proxy)
    except Exception as e:
        print("An error occurred during an endpoint call (authentication ok), please retry or contact or support team")
        print(e)

if __name__ == "__main__":
    url_endpoints, headers, http_proxy = main(sys.argv[1:])
    apis_call()
