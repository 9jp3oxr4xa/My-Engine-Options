import os
from fyers_apiv3 import fyersModel

session = fyersModel.SessionModel(
    client_id=os.environ["FYERS_APP_ID"],
    secret_key=os.environ["FYERS_SECRET_ID"],
    redirect_uri="https://fyers.in",
    response_type="code",
    grant_type="authorization_code",
)

print(session.generate_authcode())
