import os
import webbrowser
from fyers_apiv3 import fyersModel

APP_ID = os.environ["FYERS_APP_ID"]
SECRET_ID = os.environ["FYERS_SECRET_ID"]

REDIRECT_URI = "https://trade.fyers.in/api-login/redirect-uri/index.html"

session = fyersModel.SessionModel(
    client_id=APP_ID,
    secret_key=SECRET_ID,
    redirect_uri=REDIRECT_URI,
    response_type="code",
    grant_type="authorization_code",
)

url = session.generate_authcode()

print("=== FYERS FRESH LOGIN ===")
print("Opening FYERS...")
webbrowser.open(url, new=1)
print()
print("Login normally in the browser.")
print("After login, FYERS will redirect to its registered page.")
print("Copy ONLY the auth_code from the redirected URL into the prompt.")
print()

auth_code = input("AUTH_CODE = ").strip()

if not auth_code:
    raise SystemExit("AUTH_CODE_EMPTY")

session.set_token(auth_code)
response = session.generate_token()

if response.get("s") != "ok":
    print("TOKEN_EXCHANGE_FAILED")
    print("STATUS=", response.get("s"))
    print("CODE=", response.get("code"))
    raise SystemExit(1)

access_token = str(response.get("access_token", "")).strip()

if not access_token:
    raise SystemExit("ACCESS_TOKEN_EMPTY")

with open("fyers_access_token.txt", "w", encoding="utf-8") as f:
    f.write(access_token)

print("TOKEN_CREATED=PASS")
print("ACCESS_TOKEN_SAVED=PASS")
