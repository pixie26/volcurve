import sys
import requests
from requests.auth import HTTPBasicAuth
import urllib3
import json
import random

from utilities import apiGet
from utilities import apiPost
from utilities import acceptTextCsv
from utilities import acceptApplicationJson
from shared_auth import oauth2
from main import main

def apis_call():
    # get all the currency pairs in json
    apiInstrumentsFxVol()

    # get all the currency pairs in csv
    apiInstrumentsFxVolCsv()
    
    # in Json
    apiFxVolatility()  
    # in Csv
    apiFxVolatilityCsv()


def apiInstrumentsFxVol():
    try: 
        response = apiGet(url_endpoints, '/v1/instruments?type=fxVolSurface&type=commoVolSurface', acceptApplicationJson(headers), "instrumentsFxVolSurfaces.json", http_proxy)
    except Exception as e:
        print("An error occurred during an endpoint call (authentication ok), please retry or contact or support team")
        print(e)

def apiInstrumentsFxVolCsv():
    try: 
        response = apiGet(url_endpoints, '/v1/instruments?type=fxVolSurface&type=commoVolSurface', acceptTextCsv(headers), "instrumentsFxVolSurfaces.csv", http_proxy)
    except Exception as e:
        print("An error occurred during an endpoint call (authentication ok), please retry or contact or support team")
        print(e)

def apiFxVolatility():
    try: 
        body = {
            "code": "EURUSD",
            "startDate": "2026-04-27",
            "endDate": "2026-05-04",
            "output": "RR_BF_Vol",  # can be RR_BF_Vol, or Put_Call_Vol 
            "close": "EMEA",      # can be EMEA, APAC, AMER 
            "strikes": [ "ATM", "RR25", "RR10", "BF25", "BF10" ],   # optional, among [ "ATM", "RR25", "RR10", "BF25", "BF10" ] for RR_BF_Vol, and among [ "PUT10", "PUT25", "ATM", "CALL10", "CALL25" ] for Put_Call_Vol
            "lowExpiry": "1D",      # optional among [1D, 1W, 2W, 1M, 2M, 3M, 6M, 9M, 12M, 18M, 2Y, 3Y, 5Y, 7Y, 10Y, 15Y, 20Y, 25Y, 30Y]
            "highExpiry": "10Y"     # optional among [1D, 1W, 2W, 1M, 2M, 3M, 6M, 9M, 12M, 18M, 2Y, 3Y, 5Y, 7Y, 10Y, 15Y, 20Y, 25Y, 30Y]
        }

        response = apiPost(url_endpoints,
                           "/v1/fx/implied-volatility",
                           acceptApplicationJson(headers),
                           json.dumps(body),
                           "fxVolatility_" + body["code"] + "_" + body["startDate"] + "_" + body["endDate"] + ".json",
                           http_proxy)
    except Exception as e:
        print("An error occurred during an endpoint call (authentication ok), please retry or contact or support team")
        print(e)


def apiFxVolatilityCsv():
    try: 
        body = {
            "code": "EURUSD",
            "startDate": "2026-04-27",
            "endDate": "2026-05-04",
            "output": "RR_BF_Vol",  # can be RR_BF_Vol, or Put_Call_Vol 
            "close": "EMEA",      # can be EMEA, APAC or AMER 
            "strikes": [ "ATM", "RR25", "RR10", "BF25", "BF10" ],   # optional, among [ "ATM", "RR25", "RR10", "BF25", "BF10" ] for RR_BF_Vol, and among [ "PUT10", "PUT25", "ATM", "CALL10", "CALL25" ] for Put_Call_Vol
            "lowExpiry": "1D",      # optional among [1D, 1W, 2W, 1M, 2M, 3M, 6M, 9M, 12M, 18M, 2Y, 3Y, 5Y, 7Y, 10Y, 15Y, 20Y, 25Y, 30Y]
            "highExpiry": "10Y"     # optional among [1D, 1W, 2W, 1M, 2M, 3M, 6M, 9M, 12M, 18M, 2Y, 3Y, 5Y, 7Y, 10Y, 15Y, 20Y, 25Y, 30Y]
        }

        response = apiPost(url_endpoints,
                           "/v1/fx/implied-volatility",
                           acceptTextCsv(headers),
                           json.dumps(body),
                           "fxVolatility_" + body["code"] + "_" + body["startDate"] + "_" + body["endDate"] + ".csv",
                           http_proxy)
    except Exception as e:
        print("An error occurred during an endpoint call (authentication ok), please retry or contact or support team")
        print(e)

if __name__ == "__main__":
    url_endpoints, headers, http_proxy = main(sys.argv[1:])
    apis_call()
