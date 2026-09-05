import os
from fyers_apiv3 import fyersModel

APP_ID = os.environ["FYERS_APP_ID"]
SECRET_ID = os.environ["FYERS_SECRET_ID"]

print("READY")

# This only inspects the response shape after you supply a fresh auth code.
auth_code = input("AUTH_CODE = ").strip()

session = fyersModel.SessionModel(
    client_id=APP_ID,
    secret_key=SECRET_ID,
    redirect_uri="http://127.0.0.1:8765/callback",
    response_type="code",
    grant_type="authorization_code",
)

session.set_token(auth_code)
r = session.generate_token()

print("STATUS =", r.get("s"))
print("FIELDS =", sorted(r.keys()))
print("HAS_ACCESS_TOKEN =", bool(r.get("access_token")))
print("HAS_REFRESH_TOKEN =", bool(r.get("refresh_token")))
print("REFRESH_TOKEN_TYPE =", type(r.get("refresh_token")).__name__ if r.get("refresh_token") is not None else "None")
