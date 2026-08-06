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
    # get all instruments for irs series 
    apiInstrumentsCommoVol()
    # irs serie in Json
    apiSeries()  
    # irs serie in Csv
    apiSeriesCsv()


def apiInstrumentsCommoVol():
    try: 
        response = apiGet(url_endpoints, '/v1/instruments?type=commoVol', acceptApplicationJson(headers), "instrumentsCommoVol.json", http_proxy)
    except Exception as e:
        print("An error occurred during an endpoint call (authentication ok), please retry or contact or support team")
        print(e)

def apiSeries():
    try: 
        # body to be changed if you want different dates or different code
        body = {
            "code": "FXO.XAG.USD.VOL.18M.ATM.CLOSE.LONDON_CLOSE.TENOR.STD.DFLT",
            "startDate": "2024-06-01",
            "endDate": "2024-10-01"
        }
        response = apiPost(url_endpoints, 
                           "/v1/series",
                           acceptApplicationJson(headers),
                           json.dumps(body),
                           "series_irs" + body["code"] + "_" + body["startDate"] + "_" + body["endDate"] + ".json",
                           http_proxy)
    except Exception as e:
        print("An error occurred during an endpoint call (authentication ok), please retry or contact or support team")
        print(e)


def apiSeriesCsv():
    try: 
        # body to be changed if you want different dates or different code
        body = {
            "code": "FXO.XAG.USD.VOL.18M.ATM.CLOSE.LONDON_CLOSE.TENOR.STD.DFLT",
            "startDate": "2024-06-01",
            "endDate": "2024-10-01"
        }
        response = apiPost(url_endpoints, 
                           "/v1/series",
                           acceptTextCsv(headers),
                           json.dumps(body),
                           "series_irs" + body["code"] + "_" + body["startDate"] + "_" + body["endDate"] + ".csv",
                           http_proxy)
    except Exception as e:
        print("An error occurred during an endpoint call (authentication ok), please retry or contact or support team")
        print(e)

if __name__ == "__main__":
    url_endpoints, headers, http_proxy = main(sys.argv[1:])
    apis_call()
