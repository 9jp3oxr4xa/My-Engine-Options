import os
import time
from fyers_apiv3.FyersWebsocket import data_ws

token = os.environ["FYERS_ACCESS_TOKEN"]
app_id = "X53PITZA3A-100"

messages = []
errors = []

def on_connect():
    print("FYERS_CONNECT=PASS")
    fyers.subscribe(
        symbols=["NSE:NIFTY50-INDEX"],
        data_type="SymbolUpdate"
    )
    print("FYERS_SUBSCRIBE=PASS")

def on_message(message):
    messages.append(message)
    print("FYERS_MESSAGE=", message)

def on_error(message):
    errors.append(message)
    print("FYERS_ERROR=", message)

def on_close(message):
    print("FYERS_CLOSE=", message)

fyers = data_ws.FyersDataSocket(
    access_token=f"{app_id}:{token}",
    log_path="",
    litemode=False,
    write_to_file=False,
    reconnect=True,
    on_connect=on_connect,
    on_message=on_message,
    on_error=on_error,
    on_close=on_close,
)

print("FYERS_SOCKET_START=PASS")
fyers.connect()

time.sleep(20)

print("\n=== FYERS NIFTY RESULT ===")
print("MESSAGES=", len(messages))
print("ERRORS=", len(errors))

if messages:
    print("LAST_MESSAGE=", messages[-1])

fyers.close()
print("FYERS_SOCKET_TEST=DONE")
