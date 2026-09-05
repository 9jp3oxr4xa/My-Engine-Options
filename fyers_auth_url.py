import os
from fyers_apiv3 import fyersModel

session = fyersModel.SessionModel(
    client_id=os.environ["FYERS_APP_ID"],
    redirect_uri=os.environ["FYERS_REDIRECT_URI"],
    response_type="code",
    grant_type="authorization_code",
)

print(session.generate_authcode())
