import os
import time
from fyers_apiv3.FyersWebsocket import data_ws

app_id = os.environ["FYERS_APP_ID"]
token = os.environ["FYERS_ACCESS_TOKEN"]

def on_connect():
    print("FYERS_SDK_CONNECTED")
    try:
        ws.subscribe(
            symbols=["NSE:NIFTY50-INDEX"],
            data_type="SymbolUpdate"
        )
        print("FYERS_SUBSCRIBE_SENT")
    except Exception as e:
        print("SUBSCRIBE_ERROR=", type(e).__name__, str(e))

def on_message(message):
    print("FYERS_MESSAGE_RECEIVED=", repr(message)[:1500])

def on_error(message):
    print("FYERS_ERROR=", repr(message)[:2000])

def on_close(message):
    print("FYERS_CLOSE=", repr(message)[:2000])

ws = data_ws.FyersDataSocket(
    access_token=f"{app_id}:{token}",
    log_path="",
    litemode=False,
    write_to_file=False,
    on_connect=on_connect,
    on_message=on_message,
    on_error=on_error,
    on_close=on_close,
)

print("FYERS_SDK_CONNECTING")
ws.connect()

time.sleep(30)

try:
    ws.close()
except Exception:
    pass

print("FYERS_SDK_PROBE_DONE")
