from fyers_apiv3 import fyersModel
import webbrowser
import os

APP_ID = os.environ["FYERS_APP_ID"]
REDIRECT_URI = "https://trade.fyers.in/api-login/redirect-uri/index.html"

session = fyersModel.SessionModel(
    client_id=APP_ID,
    redirect_uri=REDIRECT_URI,
    response_type="code",
    state="sample_state",
    grant_type="authorization_code",
)

url = session.generate_authcode()

print("\n=== FYERS LOGIN URL ===")
print(url)

webbrowser.open(url, new=1)

print("\nLOGIN:")
print("1. Complete FYERS web login / 2FA.")
print("2. Browser redirects to:")
print(REDIRECT_URI)
print("3. Copy ONLY the value after auth_code=")
print("4. Paste it below.\n")

auth_code = input("AUTH_CODE = ").strip()

if not auth_code:
    raise SystemExit("AUTH_CODE_EMPTY")

print("\nAUTH_CODE_RECEIVED=PASS")
print("Run the existing exchange step with this auth_code.")
