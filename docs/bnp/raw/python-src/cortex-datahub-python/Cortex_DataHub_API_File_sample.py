import sys
import requests
from requests.auth import HTTPBasicAuth
import urllib3
import json
import random
from utilities import apiGet
from utilities import acceptApplicationOctetStream
from utilities import acceptApplicationJson
from shared_auth import oauth2
from main import main

def apis_call():
    # FILE ENDPOINTS
    apiFile()

def apiFile():
    try:
        # call first endpoint
        response = apiGet(url_endpoints, '/v1/market-data/dates', 
                          acceptApplicationJson(headers), 
                          "dates.json",
                          http_proxy)
        # check the result
        dates = response.json().get('dates')
        if len(dates) == 0: 
            print("\n no date available to go further")
            return 
        # get last date in the list
        date = dates[-1]

        # call second endpoint, get the list of the available documents for a date
        response = apiGet(url_endpoints, '/v1/market-data/dates/' + str(date) + '/documents', 
                          acceptApplicationJson(headers), 
                          "documents.json",
                          http_proxy)
        # check the result
        documents = response.json().get('documents')
        if len(documents) == 0:
            print("\n no document available to go further")
            return
        # get the last document from the list
        document = documents[-1]
        
        # call third endpoint, get a document from a date and a name
        response = apiGet(url_endpoints, '/v1/market-data/dates/' + str(date) + '/documents/' + str(document),
                          # enforce to get raw data
                          acceptApplicationOctetStream(headers),
                          str(document),
                          http_proxy)

    except Exception as e:
        print("An error occurred during an endpoint call (authentication ok), please retry or contact or support team")
        print(e)
        sys.exit(2)
    
if __name__ == "__main__":
    url_endpoints, headers, http_proxy = main(sys.argv[1:])
    apis_call()
