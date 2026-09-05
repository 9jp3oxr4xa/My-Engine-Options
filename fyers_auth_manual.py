import urllib.parse
import webbrowser
import secrets

APP_ID = "X53PITZA3A-100"
REDIRECT_URI = "https://fyers.in"
STATE = secrets.token_urlsafe(16)

params = {
    "client_id": APP_ID,
    "redirect_uri": REDIRECT_URI,
    "response_type": "code",
    "state": STATE,
}

url = (
    "https://api-t1.fyers.in/api/v3/generate-authcode?"
    + urllib.parse.urlencode(params)
)

print("STATE =", STATE)
print("AUTH_URL =", url)

webbrowser.open(url)
