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
    # get all instruments for quantVault series 
    apiInstrumentsQuantVault()
    # quantVault series in Json
    apiSeries()  
    # quantVault series in Csv
    apiSeriesCsv()

#Quant Vault : 
#Get all instruments with type = "quantvault"
#See "description" field : Model Type | Model | Asset Class | Classification | Asset | Region | Country | Fields
#Filter on "Model" and "Asset Class"
#Get data on one of the codes with apiSeries() or apiSeriesCsv()

def apiInstrumentsQuantVault():
    try: 
        response = apiGet(url_endpoints,'/v1/instruments?type=quantVault', acceptApplicationJson(headers), "instrumentsQuantVault.json", http_proxy)
    except Exception as e:
        print("An error occurred during an endpoint call (authentication ok), please retry or contact or support team")
        print(e)

def apiSeries():
    try: 
        # body to be changed if you want different dates
        
        body = {
            "code": "BNPCFCLF",
            "startDate": "2024-06-01",
            "endDate": "2024-07-01"
        }
        response = apiPost(url_endpoints, 
                           "/v1/series",
                           acceptApplicationJson(headers),
                           json.dumps(body),
                           "series_quantVault" + body["code"] + "_" + body["startDate"] + "_" + body["endDate"] + ".json",
                           http_proxy)
    except Exception as e:
        print("An error occurred during an endpoint call (authentication ok), please retry or contact or support team")
        print(e)


def apiSeriesCsv():
    try: 
        # body to be changed if you want different dates
        body = {
            "code": "BNPCFCLF",
            "startDate": "2024-06-01",
            "endDate": "2024-07-01"
        }
        response = apiPost(url_endpoints, 
                           "/v1/series",
                           acceptTextCsv(headers),
                           json.dumps(body),
                           "series_quantVault" + body["code"] + "_" + body["startDate"] + "_" + body["endDate"] + ".csv",
                           http_proxy)
    except Exception as e:
        print("An error occurred during an endpoint call (authentication ok), please retry or contact or support team")
        print(e)

if __name__ == "__main__":
    url_endpoints, headers, http_proxy = main(sys.argv[1:])
    apis_call()
