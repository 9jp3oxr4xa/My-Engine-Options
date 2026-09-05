import os
from fyers_apiv3 import fyersModel

app_id = os.environ["FYERS_APP_ID"]

session = fyersModel.SessionModel(
    client_id=app_id,
    redirect_uri="https://fyers.in",
    response_type="code",
    grant_type="authorization_code",
)

url = session.generate_authcode()

print("\n=== FYERS GENERATED AUTH URL ===")
print(url)

print("\n=== URL CHECK ===")
print("HAS generate-authcode =", "generate-authcode" in url)
print("HAS client_id         =", "client_id=" in url)
print("HAS redirect_uri      =", "redirect_uri=" in url)
print("HAS response_type     =", "response_type=code" in url)
print("HAS state             =", "state=" in url)
