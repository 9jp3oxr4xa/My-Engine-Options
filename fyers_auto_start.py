from __future__ import annotations

import ctypes
import hashlib
import json
import os
import secrets
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
import winreg
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, NoReturn

from fyers_apiv3 import fyersModel


# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------

APP_ID = os.environ.get("FYERS_APP_ID", "").strip()
SECRET_ID = os.environ.get("FYERS_SECRET_ID", "").strip()
FYERS_PIN = os.environ.get("FYERS_PIN", "").strip()  # optional; enables refresh path

REDIRECT_URI = "https://trade.fyers.in/api-login/redirect-uri/index.html"
CALLBACK_HOST = "127.0.0.1"
CALLBACK_PORT = 8765
CALLBACK_PATH = "/callback"
CALLBACK_TIMEOUT_S = 300

REFRESH_URL = "https://api-t1.fyers.in/api/v3/validate-refresh-token"
REFRESH_NETWORK_RETRIES = 2          # bounded retries, network errors only
VALIDATION_PROBE_SYMBOL = "NSE:SBIN-EQ"

# Paths are resolved relative to THIS file so the launcher works from any
# working directory / machine (plug-and-play requirement).
_HERE = Path(__file__).resolve().parent
ACCESS_TOKEN_FILE = _HERE / "fyers_access_token.txt"
REFRESH_TOKEN_FILE = _HERE / "fyers_refresh_token.txt"
DHAN_SCRIPT = _HERE / "Dhan.py"


def _resolve_python_exe() -> str:
    """Interpreter that will run Dhan.py.

    Order: explicit override -> this interpreter -> known install locations.
    Never hard-codes a machine-specific path.
    """
    override = os.environ.get("DHAN_PYTHON_EXE", "").strip()
    if override and Path(override).is_file():
        return override
    if sys.executable and Path(sys.executable).is_file():
        return sys.executable
    for candidate in (
        r"C:\Python314\python.exe",
        r"C:\Program Files\Python311\python.exe",
    ):
        if Path(candidate).is_file():
            return candidate
    return ""


PYTHON_EXE = _resolve_python_exe()

EXPECTED_STATE = secrets.token_urlsafe(24)

AUTH_RESULT: dict[str, Any] = {"auth_code": None, "state": None, "error": None}
AUTH_EVENT = threading.Event()


def fail(message: str) -> NoReturn:
    print(message)
    raise SystemExit(1)


if not APP_ID:
    fail("FYERS_APP_ID_MISSING")
if not SECRET_ID:
    fail("FYERS_SECRET_ID_MISSING")
if not DHAN_SCRIPT.exists():
    fail("DHAN_PY_MISSING")
if not PYTHON_EXE or not Path(PYTHON_EXE).exists():
    fail("PYTHON_INTERPRETER_MISSING")


# ----------------------------------------------------------------------
# Persistence helpers
# ----------------------------------------------------------------------

def load_token_file(path: Path) -> str:
    try:
        if path.is_file():
            return path.read_text(encoding="utf-8").strip()
    except OSError:
        pass
    return ""


def save_token_atomic(path: Path, token: str) -> None:
    abs_path = os.path.abspath(str(path))
    tmp = abs_path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(token)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, abs_path)
    if not os.path.isfile(abs_path) or os.path.getsize(abs_path) <= 0:
        raise OSError("TOKEN_FILE_VERIFY_FAILED")


def persist_user_env(name: str, value: str) -> None:
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE
    ) as key:
        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)

    HWND_BROADCAST = 0xFFFF
    WM_SETTINGCHANGE = 0x001A
    SMTO_ABORTIFHUNG = 0x0002
    ctypes.windll.user32.SendMessageTimeoutW(
        HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment",
        SMTO_ABORTIFHUNG, 5000, None,
    )


# ----------------------------------------------------------------------
# Access-token validation (fail-closed probe)
# ----------------------------------------------------------------------

def access_token_is_valid(access_token: str) -> bool:
    """Probe with a market-data call: guaranteed permitted for a
    Data-Only app and answers correctly in and out of market hours.
    Any non-ok result is treated as unusable (fail-closed)."""
    try:
        client = fyersModel.FyersModel(
            client_id=APP_ID,
            token=access_token,
            is_async=False,
            log_path="",
        )
        response = client.quotes({"symbols": VALIDATION_PROBE_SYMBOL})
    except Exception:
        return False
    return isinstance(response, dict) and response.get("s") == "ok"


# ----------------------------------------------------------------------
# Refresh-token flow (supported FYERS mechanism: requires PIN)
# ----------------------------------------------------------------------

def refresh_access_token(refresh_token: str) -> str:
    """Returns a new access token, or '' if refresh failed or is
    unsupported for this app/configuration."""
    if not FYERS_PIN:
        print("FYERS_PIN_MISSING")
        print("REFRESH_UNSUPPORTED_FOR_THIS_CONFIGURATION")
        return ""

    app_id_hash = hashlib.sha256(
        f"{APP_ID}:{SECRET_ID}".encode("utf-8")
    ).hexdigest()

    payload = json.dumps({
        "grant_type": "refresh_token",
        "appIdHash": app_id_hash,
        "refresh_token": refresh_token,
        "pin": FYERS_PIN,
    }).encode("utf-8")

    for attempt in range(1, REFRESH_NETWORK_RETRIES + 1):
        try:
            request = urllib.request.Request(
                REFRESH_URL,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=30) as raw:
                response = json.loads(raw.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # Explicit server rejection: do not retry, do not loop.
            print(f"TOKEN_REFRESH_HTTP_STATUS={exc.code}")
            print("REFRESH_UNSUPPORTED_FOR_THIS_CONFIGURATION")
            return ""
        except Exception:
            print(f"TOKEN_REFRESH_NETWORK_ERROR_ATTEMPT={attempt}")
            continue

        if not isinstance(response, dict):
            print("TOKEN_REFRESH=FAIL")
            return ""

        if response.get("s") != "ok":
            # Explicit rejection by FYERS for this app/use-case.
            print("TOKEN_REFRESH_RESPONSE_STATUS=", response.get("s"))
            print("TOKEN_REFRESH_RESPONSE_CODE=", response.get("code"))
            print("REFRESH_UNSUPPORTED_FOR_THIS_CONFIGURATION")
            return ""

        new_access = str(response.get("access_token", "")).strip()
        if not new_access:
            print("TOKEN_REFRESH=FAIL")
            return ""

        # Some responses may rotate the refresh token; persist if present.
        new_refresh = str(response.get("refresh_token", "")).strip()
        if new_refresh:
            try:
                save_token_atomic(REFRESH_TOKEN_FILE, new_refresh)
                print("REFRESH_TOKEN_SAVED=PASS")
            except Exception:
                print("REFRESH_TOKEN_SAVE_FAILED")

        return new_access

    print("TOKEN_REFRESH=FAIL")
    return ""


# ----------------------------------------------------------------------
# Browser authentication flow (proven baseline, unchanged behavior)
# ----------------------------------------------------------------------

class CallbackHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path != CALLBACK_PATH:
            body = b"NOT_FOUND"
            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        qs = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)

        status = (qs.get("s", [""])[0] or "").strip().lower()
        auth_code = (qs.get("auth_code", [""])[0] or "").strip()
        callback_state = (qs.get("state", [""])[0] or "").strip()
        error_value = (qs.get("error", [""])[0] or "").strip()
        error_code = (qs.get("error_code", [""])[0] or "").strip()
        error_message = (qs.get("message", [""])[0] or "").strip()

        explicit_error = ""
        if error_value:
            explicit_error = "CALLBACK_ERROR"
        elif error_code:
            explicit_error = "CALLBACK_ERROR_CODE"
        elif status and status != "ok":
            explicit_error = "CALLBACK_STATUS_NOT_OK"
        elif error_message and not auth_code:
            explicit_error = "CALLBACK_MESSAGE_ERROR"

        if explicit_error:
            AUTH_RESULT["error"] = explicit_error
        elif not auth_code:
            AUTH_RESULT["error"] = "AUTH_CODE_MISSING"
        elif EXPECTED_STATE and callback_state != EXPECTED_STATE:
            AUTH_RESULT["error"] = "STATE_MISMATCH"
        else:
            AUTH_RESULT["auth_code"] = auth_code
            AUTH_RESULT["state"] = callback_state

        if AUTH_RESULT["auth_code"]:
            body = (
                b"<html><body style='font-family:Arial;text-align:center;"
                b"margin-top:80px'><h1>FYERS LOGIN SUCCESS</h1>"
                b"<p>You may close this browser tab.</p></body></html>"
            )
        else:
            body = (
                b"<html><body style='font-family:Arial;text-align:center;"
                b"margin-top:80px'><h1>FYERS LOGIN FAILED</h1>"
                b"<p>Return to the PowerShell window.</p></body></html>"
            )

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

        AUTH_EVENT.set()


def browser_authenticate() -> dict[str, str] | None:
    """
    Interactive FYERS authentication for the registered hosted redirect URI.

    The FYERS app is registered with:
        https://trade.fyers.in/api-login/redirect-uri/index.html

    Therefore we must NOT wait for the old localhost callback server.
    We open the auth URL, let FYERS redirect the browser, then accept the
    full redirected URL and extract auth_code + state locally.
    """
    AUTH_RESULT["auth_code"] = None
    AUTH_RESULT["state"] = None
    AUTH_RESULT["error"] = None
    AUTH_EVENT.clear()

    print("HOSTED_REDIRECT_MODE=PASS")
    print(f"REDIRECT_URI={REDIRECT_URI}")

    try:
        session = fyersModel.SessionModel(
            client_id=APP_ID,
            secret_key=SECRET_ID,
            redirect_uri=REDIRECT_URI,
            response_type="code",
            grant_type="authorization_code",
            state=EXPECTED_STATE,
        )
        auth_url = session.generate_authcode()
    except Exception:
        print("FYERS_AUTH_URL_GENERATION_FAILED")
        return None

    print("AUTH_URL_GENERATED=PASS")
    print("Opening FYERS login...")

    try:
        webbrowser.open(auth_url, new=1)
    except Exception:
        print("BROWSER_OPEN_FAILED")
        print(auth_url)

    print("")
    print("Complete FYERS login + 2FA in the browser.")
    print("After FYERS redirects to the registered hosted page,")
    print("paste the FULL redirected URL below.")
    print("The URL must contain auth_code= and state=.")
    print("")

    redirected = input("REDIRECT URL = ").strip()

    if not redirected:
        print("REDIRECT_URL_EMPTY")
        return None

    try:
        parsed = urllib.parse.urlparse(redirected)
        qs = urllib.parse.parse_qs(parsed.query)
    except Exception:
        print("REDIRECT_URL_PARSE_FAILED")
        return None

    auth_code = (qs.get("auth_code", [""])[0] or "").strip()
    callback_state = (qs.get("state", [""])[0] or "").strip()

    # Allow pasting a raw auth_code as a fallback, while still preferring
    # the full redirected URL.
    if not auth_code and "://" not in redirected and len(redirected) > 20:
        auth_code = redirected.strip()

    if not auth_code:
        print("AUTH_CODE_MISSING")
        return None

    if callback_state and EXPECTED_STATE and callback_state != EXPECTED_STATE:
        print("STATE_MISMATCH")
        return None

    AUTH_RESULT["auth_code"] = auth_code
    AUTH_RESULT["state"] = callback_state

    print("AUTH_CODE_CAPTURED=PASS")

    try:
        session.set_token(auth_code)
        response = session.generate_token()
    except Exception:
        print("FYERS_TOKEN_EXCHANGE_FAILED")
        return None

    print("TOKEN_RESPONSE_STATUS=", response.get("s"))
    print("HAS_ACCESS_TOKEN=", bool(response.get("access_token")))
    print("HAS_REFRESH_TOKEN=", bool(response.get("refresh_token")))

    if response.get("s") != "ok":
        print("FYERS_TOKEN_EXCHANGE_FAILED")
        return None

    access_token = str(response.get("access_token", "")).strip()
    refresh_token = str(response.get("refresh_token", "")).strip()

    if not access_token:
        print("FYERS_ACCESS_TOKEN_MISSING")
        return None

    print("TOKEN_EXCHANGE=PASS")

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
    }

def finalize_and_start(access_token: str, refresh_token: str = "") -> int:
    try:
        save_token_atomic(ACCESS_TOKEN_FILE, access_token)
    except Exception:
        print("TOKEN_SAVE_FAILED")
        return 1
    print("TOKEN_SAVED=PASS")

    if refresh_token:
        try:
            save_token_atomic(REFRESH_TOKEN_FILE, refresh_token)
            print("REFRESH_TOKEN_SAVED=PASS")
        except Exception:
            # Refresh token is an optimization, not a launch requirement.
            print("REFRESH_TOKEN_SAVE_FAILED")

    try:
        persist_user_env("FYERS_ACCESS_TOKEN", access_token)
    except Exception:
        print("TOKEN_PERSISTENCE_FAILED")
        return 1

    os.environ["FYERS_ACCESS_TOKEN"] = access_token
    print("TOKEN_PERSISTED=PASS")

    for var in ("FYERS_APP_ID", "FYERS_ACCESS_TOKEN", "TG_BOT_TOKEN", "TG_CHAT_ID"):
        if not os.environ.get(var):
            print(f"{var}_MISSING_AT_DHAN_START")
            return 1

    print("STARTING_DHAN=PASS")

    try:
        completed = subprocess.run(
            [PYTHON_EXE, "-u", str(DHAN_SCRIPT)],
            env=os.environ.copy(),
            check=False,
        )
    except KeyboardInterrupt:
        return 130
    except Exception:
        print("DHAN_START_FAILED")
        return 1

    return int(completed.returncode)


# ----------------------------------------------------------------------
# Lifecycle entry point
# ----------------------------------------------------------------------

def main() -> int:
    print("=== FYERS TOKEN LIFECYCLE ===")

    stored_access = load_token_file(ACCESS_TOKEN_FILE)
    stored_refresh = load_token_file(REFRESH_TOKEN_FILE)

    # --- Path 1: stored access token still valid -----------------------
    if stored_access:
        if access_token_is_valid(stored_access):
            print("ACCESS_TOKEN=VALID")
            return finalize_and_start(stored_access)
        print("ACCESS_TOKEN=EXPIRED")
    else:
        print("ACCESS_TOKEN=ABSENT")

    # --- Path 2: supported refresh --------------------------------------
    if stored_refresh:
        new_access = refresh_access_token(stored_refresh)
        if new_access:
            if access_token_is_valid(new_access):
                print("TOKEN_REFRESH=PASS")
                return finalize_and_start(new_access)
            # Fail-closed: refreshed token that does not validate
            # is never handed to Dhan.py.
            print("TOKEN_REFRESH=FAIL_VALIDATION")
    else:
        print("REFRESH_TOKEN=ABSENT")

    # --- Path 3: automatic browser fallback -----------------------------
    print("AUTH_FALLBACK=BROWSER")
    tokens = browser_authenticate()
    if tokens is None:
        print("AUTHENTICATION_FAILED_FAIL_CLOSED")
        return 1

    return finalize_and_start(tokens["access_token"], tokens["refresh_token"])


if __name__ == "__main__":
    raise SystemExit(main())