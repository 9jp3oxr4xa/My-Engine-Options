import os
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
from fyers_apiv3 import fyersModel

HOST = "127.0.0.1"
PORT = 8765
REDIRECT_URI = f"http://{HOST}:{PORT}/callback"

APP_ID = os.environ.get("FYERS_APP_ID", "").strip()
SECRET_ID = os.environ.get("FYERS_SECRET_ID", "").strip()

if not APP_ID:
    raise SystemExit("FAIL: FYERS_APP_ID missing")
if not SECRET_ID:
    raise SystemExit("FAIL: FYERS_SECRET_ID missing")

auth_code_holder = {"code": None, "error": None}

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        q = parse_qs(urlparse(self.path).query)

        code = q.get("auth_code", [None])[0]
        err  = q.get("error", [None])[0]

        if code:
            auth_code_holder["code"] = code
            body = b"FYERS LOGIN SUCCESS. You may close this browser tab."
            self.send_response(200)
        else:
            auth_code_holder["error"] = err or "auth_code missing"
            body = b"FYERS LOGIN FAILED. Check the terminal."
            self.send_response(400)

        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass

server = HTTPServer((HOST, PORT), Handler)

print("=== FYERS AUTO LOGIN ===")
print("REDIRECT_URI =", REDIRECT_URI)

session = fyersModel.SessionModel(
    client_id=APP_ID,
    secret_key=SECRET_ID,
    redirect_uri=REDIRECT_URI,
    response_type="code",
    grant_type="authorization_code",
)

login_url = session.generate_authcode()
print("LOGIN URL:")
print(login_url)
print()

threading.Thread(
    target=server.handle_request,
    daemon=True
).start()

print("CALLBACK LISTENER READY")
print(f"http://{HOST}:{PORT}/callback")
print("Opening browser...")
webbrowser.open(login_url)

for _ in range(180):
    if auth_code_holder["code"] or auth_code_holder["error"]:
        break
    import time
    time.sleep(1)

server.server_close()

if not auth_code_holder["code"]:
    raise SystemExit(
        "FAIL: FYERS auth_code not received: "
        + str(auth_code_holder["error"])
    )

auth_code = auth_code_holder["code"]

print("AUTH_CODE_RECEIVED=YES")
print("EXCHANGING_TOKEN...")

session.set_token(auth_code)
response = session.generate_token()

if not isinstance(response, dict):
    raise SystemExit("FAIL: Unexpected FYERS token response")

token = str(response.get("access_token", "")).strip()

if not token:
    raise SystemExit("FAIL: FYERS access_token missing in response")

# Pass the token safely to the parent launcher through a temporary file.
token_file = os.path.join(os.environ.get("TEMP", "."), "dhan_fyers_token.tmp")
with open(token_file, "w", encoding="utf-8") as f:
    f.write(token)

print("ACCESS_TOKEN_RECEIVED=YES")
print("TOKEN_FILE=", token_file)
