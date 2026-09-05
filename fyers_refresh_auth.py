import os
import urllib.parse
import secrets
import webbrowser

params = {
    "client_id": os.environ["FYERS_APP_ID"],
    "redirect_uri": os.environ["FYERS_REDIRECT_URI"],
    "response_type": "code",
    "state": "refresh_" + secrets.token_urlsafe(12),
}

url = (
    "https://api-t1.fyers.in/api/v3/generate-authcode?"
    + urllib.parse.urlencode(params)
)

print(url)
webbrowser.open(url)
