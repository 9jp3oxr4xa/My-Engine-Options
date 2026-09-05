import os
import hashlib
import requests

app_id = os.environ["FYERS_APP_ID"]
secret = os.environ["FYERS_APP_SECRET"]
auth_code = os.environ["FYERS_AUTH_CODE"]

# IMPORTANT: full App ID, including -100
app_id_hash = hashlib.sha256(
    f"{app_id}:{secret}".encode("utf-8")
).hexdigest()

payload = {
    "grant_type": "authorization_code",
    "appIdHash": app_id_hash,
    "code": auth_code,
}

url = "https://api-t1.fyers.in/api/v3/validate-authcode"

r = requests.post(
    url,
    json=payload,
    headers={"Content-Type": "application/json"},
    timeout=20,
)

print("HTTP_STATUS =", r.status_code)

data = r.json()

print("STATUS =", data.get("s"))
print("MESSAGE =", data.get("message"))

if data.get("s") != "ok":
    print("VALIDATION_FAILED =", data)
    raise SystemExit(1)

token = data["access_token"]

print("TOKEN_EXCHANGE=PASS")
print("TOKEN_LENGTH =", len(token))

with open(".\\fyers_access_token.txt", "w", encoding="utf-8") as f:
    f.write(token)

print("TOKEN_SAVED=PASS")
