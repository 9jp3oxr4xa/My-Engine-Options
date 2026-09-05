import os
import hashlib
import requests

app_id = os.environ["FYERS_APP_ID"]
secret = os.environ["FYERS_SECRET_ID"]
code = os.environ["FYERS_AUTH_CODE"]

app_hash = hashlib.sha256(
    f"{app_id}:{secret}".encode("utf-8")
).hexdigest()

r = requests.post(
    "https://api-t1.fyers.in/api/v3/validate-authcode",
    json={
        "grant_type": "authorization_code",
        "appIdHash": app_hash,
        "code": code,
    },
    timeout=20,
)

data = r.json()

print("HTTP_STATUS =", r.status_code)
print("STATUS =", data.get("s"))
print("CODE =", data.get("code"))
print("MESSAGE =", data.get("message"))

if data.get("s") != "ok":
    raise SystemExit(f"FYERS_TOKEN_REFRESH_FAILED: {data}")

with open(r".\fyers_access_token.txt", "w", encoding="utf-8") as f:
    f.write(data["access_token"])

print("FYERS_TOKEN_REFRESH=PASS")
print("TOKEN_SAVED=PASS")
