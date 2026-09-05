import os
from fyers_apiv3 import fyersModel

s = fyersModel.SessionModel(
    client_id=os.environ["FYERS_APP_ID"],
    secret_key=os.environ["FYERS_SECRET_ID"],
    redirect_uri="http://127.0.0.1:8765/callback",
    response_type="code",
    grant_type="authorization_code",
)
print(s.generate_authcode())
