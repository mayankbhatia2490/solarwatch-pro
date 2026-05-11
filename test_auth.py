import time
import hashlib
import requests
import urllib.parse

USERNAME = "mayank bhatia"
PASSWORD = "Solar2025"
BASE_URL = "http://web.shinemonitor.com/public/"

def get_salt():
    return int(round(time.time() * 1000))

def request_token(usr, comp_key, password=PASSWORD):
    salt = get_salt()
    powSha1 = hashlib.sha1()
    powSha1.update(password.encode('utf-8'))
    pwd_hash = str(powSha1.hexdigest())
    # The action string that gets signed needs to perfectly match what's in the URL
    action = f'&action=auth&usr={usr}&company-key={comp_key}'
    
    # Check if we should urlencode here or not for the signature? 
    # sittzon did not urlencode for the signature string:
    pwdaction = str(salt) + pwd_hash + action
    
    auth_sign = hashlib.sha1()
    auth_sign.update(pwdaction.encode('utf-8'))
    sign = str(auth_sign.hexdigest())
    
    # We must urlencode the username for the actual HTTP request
    # wait, sittzon's script uses `requests.get` with the unencoded url string!
    # "requests" automatically encodes the spaces. But if the sign is computed on the UNENCODED string, it matches the server un-encoding it.
    
    auth_url = f"{BASE_URL}?sign={sign}&salt={salt}{action}"
    
    print(f"Key: '{comp_key}' Pwd: '{password}' -> ", end="")
    try:
        r = requests.get(auth_url, timeout=5)
        print(r.text)
    except Exception as e:
        print("Error:", e)

# Let's test a few
company_keys = ["", "eybond", "SmartClient", "15", "smartclient", "shinemonitor"]
for k in company_keys:
    request_token(USERNAME, k)

# Also test password without SHA1 hash just in case the API expects plaintext password hash directly (sittzon hashes the password, but maybe they type the sha1 hash into the config?)
print("Testing plaintext password in SHA1 instead of hashing it:")
for k in ["eybond"]:
    # The code hashes the password parameter. What if the config is supposed to hold the MD5/SHA1 of the password?
    pass
