import os
import webbrowser
from fyers_apiv3 import fyersModel

app_id = os.environ["FYERS_APP_ID"]

session = fyersModel.SessionModel(
    client_id=app_id,
    redirect_uri="https://fyers.in",
    response_type="code",
    state="NUCLEAR1",
    grant_type="authorization_code",
)

url = session.generate_authcode()

print("=== FRESH FYERS AUTH URL ===")
print(url)
print("=== OPENING BROWSER ===")

webbrowser.open(url)
