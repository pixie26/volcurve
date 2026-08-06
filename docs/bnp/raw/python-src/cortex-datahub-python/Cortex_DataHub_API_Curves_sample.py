import sys
import requests
from requests.auth import HTTPBasicAuth
import json
import random
from utilities import apiPost
from utilities import acceptTextCsv
from utilities import acceptApplicationJson
from main import main

def apis_call():
    # curves in Json
    apiCurves()  
    # curves in Csv
    apiCurvesCsv()

def apiCurves():
    try: 
        # body to be changed if you want different ranges (dates, maturity)
        body = {
            "code": "SX5E",
            "codeType": "bbg",
            "kinds": ["VAR_SWAP_CURVE", "VOL_SWAP_CURVE", "CAPPED_VAR_SWAP_CURVE", "CAPPED_VOL_SWAP_CURVE", "FORWARD_CURVE"],
            "startDate": "2025-09-18",
            "endDate": "2025-09-18",
            "lowMaturity": "10M",
            "highMaturity": "24M"
        }
        response = apiPost(url_endpoints,
                           "/v1/curves",
                           acceptApplicationJson(headers),
                           json.dumps(body),
                           "curves_" + body["code"] + "_" + body["startDate"] + "_" + body["endDate"] + ".json",
                           http_proxy)
    except Exception as e:
        print("An error occurred during an endpoint call (authentication ok), please retry or contact or support team")
        print(e)


def apiCurvesCsv():
    try: 
        # body to be changed if you want different ranges (dates, maturity)
        body = {
            "code": "SX5E",
            "codeType": "bbg",
            "kinds": ["VAR_SWAP_CURVE", "VOL_SWAP_CURVE", "CAPPED_VAR_SWAP_CURVE", "CAPPED_VOL_SWAP_CURVE", "FORWARD_CURVE"],
            "startDate": "2025-09-01",
            "endDate": "2025-09-19",
            "lowMaturity": "10M",
            "highMaturity": "24M"
        }
        response = apiPost(url_endpoints,
                           "/v1/curves",
                           acceptTextCsv(headers),
                           json.dumps(body),
                           "curves_" + body["code"] + "_" + body["startDate"] + "_" + body["endDate"] + ".csv",
                           http_proxy)
    except Exception as e:
        print("An error occurred during an endpoint call (authentication ok), please retry or contact or support team")
        print(e)

if __name__ == "__main__":
    url_endpoints, headers, http_proxy = main(sys.argv[1:])
    apis_call()
