import os
import urllib.parse
import secrets
import webbrowser

app_id = os.environ["FYERS_APP_ID"]
redirect_uri = os.environ["FYERS_REDIRECT_URI"]
state = "nse_" + secrets.token_urlsafe(12)

params = {
    "client_id": app_id,
    "redirect_uri": redirect_uri,
    "response_type": "code",
    "state": state,
}

url = (
    "https://api-t1.fyers.in/api/v3/generate-authcode?"
    + urllib.parse.urlencode(params)
)

print("AUTH_URL=")
print(url)
print("STATE=", state)

webbrowser.open(url)
