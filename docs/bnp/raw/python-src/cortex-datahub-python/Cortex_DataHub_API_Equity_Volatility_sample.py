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
    # get all instruments for equity in Json
    apiInstrumentsEquity()
    
    # get all instruments for equity in Csv
    apiInstrumentsEquityCsv()
    
    # VOLATILITY in Json
    apiImpliedVolatility()
    
    # VOLATILITY in Csv
    apiImpliedVolatilityCsv()
    
    # VOLATILITY Fixed strikes and maturities
    apiImpliedVolatilityFixedMaturitiesAndStrikes()
    
    # VOLATILITY sliding strikes and fixed maturities
    apiImpliedVolatilityFixedMaturitiesAndSlidingStrikes()
    
    #VOLATILITY on dividend
    apiImpliedVolatilityOnDiv()
 
# to access vol/var swap see Cortex_DataHub_API_Curves_sample.py   

def apiInstrumentsEquity():
    try: 
        response = apiGet(url_endpoints,'/v1/instruments?type=equity', acceptApplicationJson(headers), "instrumentsEquity.json", http_proxy)
    except Exception as e:
        print("An error occurred during an endpoint call (authentication ok), please retry or contact or support team")
        print(e)


def apiInstrumentsEquityCsv():
    try: 
        response = apiGet(url_endpoints,'/v1/instruments?type=equity', acceptTextCsv(headers), "instrumentsEquity.csv", http_proxy)
    except Exception as e:
        print("An error occurred during an endpoint call (authentication ok), please retry or contact or support team")
        print(e)

def apiImpliedVolatility():
    try: 
        # body to be changed if you want different ranges (dates, strike, maturity)
        body = {
            "code": "BNPP.PA",
            "codeType": "ric",
            "strikeRule": "relative_to_forward",
            "startDate": "2020-12-01",
            "endDate": "2023-12-01",
            "lowStrike": "50_0",
            "highStrike": "150_0",
            "lowMaturity": "1W",
            "highMaturity": "120M",
            "layout": "matrix"
        }
        response = apiPost(url_endpoints,
                           "/v1/implied-volatility",
                           acceptApplicationJson(headers),
                           json.dumps(body),
                           "volatility_" + body["code"] + "_" + body["startDate"] + "_" + body["endDate"] + ".json",
                           http_proxy)
    except Exception as e:
        print("An error occurred during an endpoint call (authentication ok), please retry or contact or support team")
        print(e)


def apiImpliedVolatilityCsv():
    try: 
        # body to be changed if you want different ranges (dates, strike, maturity)
        body = {
            "code": "BNPP.PA",
            "codeType": "ric",
            "strikeRule": "relative_to_spot_ref",
            "startDate": "2024-06-01",
            "endDate": "2024-06-30",
            "lowStrike": "50_0",
            "highStrike": "150_0",
            "lowMaturity": "1W",
            "highMaturity": "120M"
        }
        response = apiPost(url_endpoints,
                           "/v1/implied-volatility",
                           acceptTextCsv(headers),
                           json.dumps(body),
                           "volatility_" + body["code"] + "_" + body["startDate"] + "_" + body["endDate"] + ".csv",
                           http_proxy)
    except Exception as e:
        print("An error occurred during an endpoint call (authentication ok), please retry or contact or support team")
        print(e)

def apiImpliedVolatilityFixedMaturitiesAndStrikes():
    try: 
        # body to be changed if you want different ranges (dates, strike, maturity)
        body = {
            "code": "BNPP.PA",
            "codeType": "ric",
            "strikeRule": "fixed",
            "startDate": "2024-07-31",
            "endDate": "2024-08-31",
            "lowFixedStrike": "50",
            "highFixedStrike": "80",
            "lowFixedMaturity": "2024-07-31",
            "highFixedMaturity": "2025-07-31",
            "layout": "matrix"
        }
        response = apiPost(url_endpoints,
                           "/v1/implied-volatility",
                           acceptApplicationJson(headers),
                           json.dumps(body),
                           "volatility_fixed_" + body["code"] + "_" + body["startDate"] + "_" + body["endDate"] + ".json",
                           http_proxy)
        
    except Exception as e:
        print("An error occurred during an endpoint call (authentication ok), please retry or contact or support team")
        print(e)
        
def apiImpliedVolatilityFixedMaturitiesAndSlidingStrikes():
    try: 
        # body to be changed if you want different ranges (dates, strike, maturity)
        body = {
            "code": "EU_STOXX50E",
            "codeType": "bnpp",
            "strikeRule": "relative_to_spot_ref",
            "maturityRule": "fixed",
            "startDate": "2025-09-04",
            "endDate": "2025-09-04",
            "lowFixedMaturity": "2025-09-04",
            "highFixedMaturity": "2100-01-01",
            "lowStrike": "50_0",
            "highStrike": "150_0"
           
        }
        response = apiPost(url_endpoints,
                           "/v1/implied-volatility",
                           acceptApplicationJson(headers),
                           json.dumps(body),
                           "volatility_fixed_maturity_" + body["code"] + "_" + body["startDate"] + "_" + body["endDate"] + ".json",
                           http_proxy)
        
    except Exception as e:
        print("An error occurred during an endpoint call (authentication ok), please retry or contact or support team")
        print(e)
        
        
def apiImpliedVolatilityOnDiv():
    try: 
        # body to be changed if you want different ranges (dates, strike, maturity)
        body = {
            "code": "EU_STOXX50E_dividend",
            "startDate": "2025-09-18",
            "endDate": "2025-09-18",
            "lowMaturity": "1M",
            "highMaturity": "60M",
            "lowStrike": "50_0",
            "highStrike": "125_0",
            "strikeRule": "relative_to_spot_ref",
            "layout": "matrix"     
        }
        response = apiPost(url_endpoints,
                           "/v1/implied-volatility",
                           acceptApplicationJson(headers),
                           json.dumps(body),
                           "volatility_fixed_maturity_" + body["code"] + "_" + body["startDate"] + "_" + body["endDate"] + ".json",
                           http_proxy)
            
    except Exception as e:
        print("An error occurred during an endpoint call (authentication ok), please retry or contact or support team")
        print(e)

if __name__ == "__main__":
    url_endpoints, headers, http_proxy = main(sys.argv[1:])
    apis_call()
