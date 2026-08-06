import sys
import requests
from requests.auth import HTTPBasicAuth
import urllib3
import json
import random
from shared_auth import check_and_refresh_token

def apiGet(url_endpoints, uri, headers, docName, http_proxy):
    url = url_endpoints + uri
    print('GET ' + url)

    # Check and refresh token if needed
    auth_header = check_and_refresh_token()

    # Update headers with current token
    headers.update(auth_header)

    response = requests.get(url, headers=headers, verify=False, proxies=http_proxy)
    saveResults(response, docName)

    return response

def apiPost(url_endpoints, uri, headers, data, docName, http_proxy):
    url = url_endpoints + uri
    print('POST ' + url)

    # Check and refresh token if needed
    auth_header = check_and_refresh_token()

    # Update headers with current token
    headers.update(auth_header)

    response = requests.post(url, headers=headers, verify=False, proxies=http_proxy, data=data)
    saveResults(response, docName)

    return response

def saveResults(response, docName):
    if (response.status_code != 200):
        raise Exception(response.content)
    file = open(docName, 'wb')  # use "wb" - binary write mode
    file.write(response.content)  # response.content to get bytes with the raw response
    file.close()
    print("file " + docName + " saved")

def acceptApplicationJson(headers):
    headers['Content-Type'] = 'application/json'
    headers['Accept'] = 'application/json'
    return headers

def acceptTextCsv(headers):
    headers['Content-Type'] = 'application/json'
    headers['Accept'] = 'text/csv'
    return headers

def acceptApplicationOctetStream(headers):
    headers['Content-Type'] = 'application/json'
    headers['Accept'] = 'application/octet-stream'
    return headers