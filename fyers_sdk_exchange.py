import os
from fyers_apiv3 import fyersModel

session = fyersModel.SessionModel(
    client_id=os.environ["FYERS_APP_ID"],
    secret_key=os.environ["FYERS_SECRET_ID"],
    redirect_uri="https://fyers.in",
    response_type="code",
    grant_type="authorization_code",
)

session.set_token(os.environ["FYERS_AUTH_CODE"])

resp = session.generate_token()

print("STATUS =", resp.get("s"))
print("CODE =", resp.get("code"))
print("MESSAGE =", resp.get("message"))

if resp.get("s") != "ok":
    print("FAILED =", resp)
    raise SystemExit(1)

with open(".\fyers_access_token.txt", "w", encoding="utf-8") as f:
    f.write(resp["access_token"])

print("FYERS_TOKEN=PASS")
print("TOKEN_SAVED=PASS")
