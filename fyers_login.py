"""FYERS-only interactive login helper.

Generates the official FYERS login URL, captures auth_code on the registered
loopback redirect (http://127.0.0.1:8765/callback), exchanges it for a fresh
access token with the official fyers_apiv3 SDK, and writes ONLY that token to
the file path given as argv[1].

Never prints the token. Never touches Dhan. Fails closed on every error.
"""

from __future__ import annotations

import os
import secrets
import socket
import sys
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, NoReturn, Optional

REDIRECT_URI = "http://127.0.0.1:8765/callback"
BIND_HOST = "127.0.0.1"
BIND_PORT = 8765
CALLBACK_PATH = "/callback"
LOGIN_TIMEOUT_S = 300


def out(message: str) -> None:
    sys.stdout.write(message + "\n")
    sys.stdout.flush()


def fail(code: str, detail: str = "") -> NoReturn:
    out("FYERS_LOGIN_FAIL=" + code)
    if detail:
        out("DETAIL=" + detail)
    raise SystemExit(1)


RESULT: Dict[str, Optional[str]] = {"auth_code": None, "state": None, "error": None}
DONE = threading.Event()


class ExclusiveHTTPServer(HTTPServer):
    # False so a second listener can never hijack port 8765 on Windows.
    allow_reuse_address = False


class CallbackHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def _reply(self, status: int, body: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != CALLBACK_PATH:
            self._reply(404, b"NOT_FOUND", "text/plain; charset=utf-8")
            return

        qs = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        status = (qs.get("s", [""])[0] or "").strip().lower()
        auth_code = (qs.get("auth_code", [""])[0] or "").strip()
        state = (qs.get("state", [""])[0] or "").strip()
        err = (qs.get("error", [""])[0] or "").strip()
        err_code = (qs.get("error_code", [""])[0] or "").strip()
        err_msg = (qs.get("message", [""])[0] or "").strip()

        if err:
            RESULT["error"] = "CALLBACK_ERROR:" + err
        elif err_code:
            RESULT["error"] = "CALLBACK_ERROR_CODE:" + err_code
        elif status and status != "ok":
            RESULT["error"] = "CALLBACK_STATUS_NOT_OK:" + status
        elif not auth_code:
            RESULT["error"] = "AUTH_CODE_MISSING"
            if err_msg:
                RESULT["error"] = "AUTH_CODE_MISSING:" + err_msg
        else:
            RESULT["auth_code"] = auth_code
            RESULT["state"] = state

        if RESULT["auth_code"]:
            page = (
                b"<html><body style=\"font-family:Segoe UI,Arial;text-align:center;"
                b"margin-top:90px\"><h1>FYERS LOGIN CAPTURED</h1>"
                b"<p>Return to the PowerShell window. You may close this tab.</p>"
                b"</body></html>"
            )
        else:
            page = (
                b"<html><body style=\"font-family:Segoe UI,Arial;text-align:center;"
                b"margin-top:90px\"><h1>FYERS LOGIN FAILED</h1>"
                b"<p>Return to the PowerShell window for the exact reason.</p>"
                b"</body></html>"
            )
        self._reply(200, page, "text/html; charset=utf-8")
        DONE.set()


def port_is_free() -> bool:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind((BIND_HOST, BIND_PORT))
    except OSError:
        return False
    finally:
        try:
            probe.close()
        except OSError:
            pass
    return True


def main() -> int:
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        fail("TOKEN_SINK_ARG_MISSING")
    token_sink = sys.argv[1].strip()

    app_id = os.environ.get("FYERS_APP_ID", "").strip()
    secret_id = os.environ.get("FYERS_SECRET_ID", "").strip()
    if not app_id:
        fail("FYERS_APP_ID_MISSING")
    if not secret_id:
        fail("FYERS_SECRET_ID_MISSING")

    try:
        from fyers_apiv3 import fyersModel
    except Exception as exc:
        fail("FYERS_SDK_IMPORT_FAILED", str(exc))

    if not port_is_free():
        fail("PORT_8765_IN_USE",
             "close the process holding 127.0.0.1:8765 and retry")

    state = secrets.token_urlsafe(24)
    try:
        session = fyersModel.SessionModel(
            client_id=app_id,
            secret_key=secret_id,
            redirect_uri=REDIRECT_URI,
            response_type="code",
            grant_type="authorization_code",
            state=state,
        )
        auth_url = session.generate_authcode()
    except Exception as exc:
        fail("AUTH_URL_GENERATION_FAILED", str(exc))

    if not isinstance(auth_url, str) or not auth_url.startswith("http"):
        fail("AUTH_URL_INVALID", str(auth_url))

    try:
        server = ExclusiveHTTPServer((BIND_HOST, BIND_PORT), CallbackHandler)
    except OSError as exc:
        fail("CALLBACK_BIND_FAILED", str(exc))

    server.timeout = 1.0
    worker = threading.Thread(target=server.serve_forever,
                              kwargs={"poll_interval": 0.25},
                              name="fyers-callback", daemon=True)
    worker.start()

    out("REDIRECT_URI=" + REDIRECT_URI)
    out("CALLBACK_LISTENING=1")
    out("AUTH_URL_READY=1")

    opened = False
    try:
        opened = bool(webbrowser.open(auth_url, new=1))
    except Exception:
        opened = False
    if opened:
        out("BROWSER_OPENED=1")
    else:
        out("BROWSER_OPEN_FAILED=1")
        out("OPEN_THIS_URL_MANUALLY:")
        out(auth_url)

    out("WAITING_FOR_LOGIN=1 timeout_s=" + str(LOGIN_TIMEOUT_S))
    captured = DONE.wait(LOGIN_TIMEOUT_S)

    try:
        server.shutdown()
    except Exception:
        pass
    try:
        server.server_close()
    except Exception:
        pass

    if not captured:
        fail("LOGIN_TIMEOUT",
             "no callback within " + str(LOGIN_TIMEOUT_S) + "s")

    if RESULT["error"]:
        fail("CALLBACK_REJECTED", str(RESULT["error"]))

    auth_code = RESULT["auth_code"] or ""
    if not auth_code:
        fail("AUTH_CODE_MISSING")

    returned_state = RESULT["state"] or ""
    if returned_state and returned_state != state:
        fail("STATE_MISMATCH")

    out("AUTH_CODE_CAPTURED=1")

    try:
        session.set_token(auth_code)
        response = session.generate_token()
    except Exception as exc:
        fail("TOKEN_EXCHANGE_EXCEPTION", str(exc))

    if not isinstance(response, dict):
        fail("TOKEN_EXCHANGE_BAD_RESPONSE", str(type(response)))
    if response.get("s") != "ok":
        fail("TOKEN_EXCHANGE_REJECTED",
             "s=" + str(response.get("s")) + " code=" + str(response.get("code"))
             + " message=" + str(response.get("message")))

    access_token = str(response.get("access_token", "") or "").strip()
    if not access_token:
        fail("ACCESS_TOKEN_EMPTY")

    try:
        with open(token_sink, "w", encoding="utf-8", newline="") as fh:
            fh.write(access_token)
            fh.flush()
            os.fsync(fh.fileno())
    except OSError as exc:
        fail("TOKEN_SINK_WRITE_FAILED", str(exc))

    try:
        written = os.path.getsize(token_sink)
    except OSError as exc:
        fail("TOKEN_SINK_VERIFY_FAILED", str(exc))
    if written != len(access_token.encode("utf-8")):
        fail("TOKEN_SINK_SIZE_MISMATCH", str(written))

    out("TOKEN_EXCHANGE=OK")
    out("TOKEN_LENGTH=" + str(len(access_token)))
    out("FYERS_LOGIN_OK=1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())