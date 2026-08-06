import sys
import requests
from requests.auth import HTTPBasicAuth
import urllib3
import json
import random
from datetime import datetime, timedelta

# Global variables for token management
current_token = None
token_expiry = None
consumer_key = None
consumer_secret = None
auth_url = None
http_proxy = None

def initialize_token_management(ck, cs, proxy, url):
    global consumer_key, consumer_secret, http_proxy, auth_url
    consumer_key = ck
    consumer_secret = cs
    http_proxy = proxy
    auth_url = url

def oauth2():
    global current_token, token_expiry

    try:
        print("\nYour consumerKey = " + consumer_key)
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        data = {"grant_type": "client_credentials"}

        # Make OAuth2 authentication request
        response = requests.post(
            auth_url,
            auth=HTTPBasicAuth(consumer_key, consumer_secret),
            verify=False,
            headers=headers,
            data=data,
            proxies=http_proxy
        )

        # Get your token
        access_token = response.json().get('access_token')
        expires_in = response.json().get('expires_in')

        # Store the token and its expiration date
        current_token = access_token
        token_expiry = datetime.now() + timedelta(seconds=expires_in)

        print("New access token valid for " + str(expires_in) + " seconds: " + access_token)
        return authorizationBearer(access_token)

    except Exception as e:
        print("An error occurred during the authentication, please double check your customer key and secret.")
        print("If this error persists, contact our support team")
        print(e)
        sys.exit(2)


def authorizationBearer(current_token):
    return {'Authorization':'Bearer ' + current_token}

def check_and_refresh_token():
    global current_token, token_expiry

    # If no token or expiration date is set, get a new one
    if not current_token or not token_expiry:
        return oauth2()

    # If token expires in less than 1 minute, get a new one
    if datetime.now() >= token_expiry - timedelta(seconds=60):
        print("Token is about to expire, refreshing...")
        return oauth2()

    # Otherwise, return the current token
    return authorizationBearer(current_token)