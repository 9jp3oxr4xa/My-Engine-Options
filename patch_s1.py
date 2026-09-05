import os, sys

PATH = "Dhan.py"
with open(PATH, "r", encoding="utf-8", newline="") as fh:
    src = fh.read()

if "symbol_map" in src:
    print("ABORT_ALREADY_PATCHED")
    sys.exit(2)

eol = "\r\n" if "\r\n" in src else "\n"
def N(s):
    return s.replace("\r\n", "\n").replace("\n", eol)

EDITS = []

EDITS.append(("R1_INSTRUMENT_FIELD", '''class Instrument:
    name: str
    security_id: str
    exchange_segment: str
    lot_size: int
    strike_step: Decimal
    tick_size: Decimal''', '''class Instrument:
    name: str
    security_id: str
    exchange_segment: str
    lot_size: int
    strike_step: Decimal
    tick_size: Decimal
    fyers_symbol: Optional[str] = None''', 1))

EDITS.append(("R2_LOADER_ALLOWED_KEYS",
'''                spec, ["security_id", "exchange_segment", "lot_size", "strike_step", "tick_size"],''',
'''                spec, ["security_id", "exchange_segment", "lot_size", "strike_step", "tick_size", "fyers_symbol"],''', 1))

EDITS.append(("R3_LOADER_FIELD",
'''                tick_size=_d(_require(spec, "tick_size", f"instruments.{name}")),
            ))''',
'''                tick_size=_d(_require(spec, "tick_size", f"instruments.{name}")),
                fyers_symbol=(str(spec["fyers_symbol"]) if spec.get("fyers_symbol") is not None else None),
            ))''', 1))

EDITS.append(("R4_FEED_INIT",
'''    def __init__(self, access_token: str, app_id: str, logger: logging.Logger,
                 metrics: Metrics, clock: Clock, on_tick: Callable[[Tick], None]) -> None:
        self.access_token = access_token''',
'''    def __init__(self, access_token: str, app_id: str, logger: logging.Logger,
                 metrics: Metrics, clock: Clock, on_tick: Callable[[Tick], None],
                 symbol_map: Dict[str, Tuple[str, str, Decimal]]) -> None:
        self.symbol_map: Dict[str, Tuple[str, str, Decimal]] = dict(symbol_map)
        self.access_token = access_token''', 1))

EDITS.append(("R5_ON_CONNECT",
'''    def _on_connect(self) -> None:
        try:
            self._socket.subscribe(
                symbols=["NSE:NIFTY50-INDEX"],
                data_type="SymbolUpdate"
            )
            log_event(self.logger, logging.INFO, "fyers_subscribed",
                      symbol="NSE:NIFTY50-INDEX")''',
'''    def _on_connect(self) -> None:
        try:
            self._socket.subscribe(
                symbols=sorted(self.symbol_map.keys()),
                data_type="SymbolUpdate"
            )
            log_event(self.logger, logging.INFO, "fyers_subscribed",
                      symbols=",".join(sorted(self.symbol_map.keys())))''', 1))

EDITS.append(("R6_ON_MESSAGE_ROUTE",
'''        if message.get("symbol") != "NSE:NIFTY50-INDEX":
            return''',
'''        _entry = self.symbol_map.get(message.get("symbol"))
        if _entry is None:
            return''', 1))

EDITS.append(("R7_TICK_BUILD",
'''            tick = Tick(
                security_id="13",
                ts=ts,
                ltp=quantize_tick(_d(ltp), Decimal("0.05")),''',
'''            tick = Tick(
                security_id=_entry[1],
                ts=ts,
                ltp=quantize_tick(_d(ltp), _entry[2]),''', 1))

EDITS.append(("R8_RESUBSCRIBE",
'''        """Compatibility with the existing Engine WS interface.
        FYERS underlying subscription is fixed to NIFTY50-INDEX.
        """
        if self._stopped or self._socket is None:
            return
        try:
            self._socket.unsubscribe_all()
        except Exception:
            pass
        try:
            self._socket.subscribe(
                symbols=["NSE:NIFTY50-INDEX"],
                data_type="SymbolUpdate"
            )
            self.metrics.inc("ws_resubscribes")
            log_event(self.logger, logging.INFO, "fyers_resubscribed",
                      symbol="NSE:NIFTY50-INDEX")''',
'''        """Compatibility with the existing Engine WS interface.
        FYERS underlying subscriptions are driven by the symbol map.
        """
        if self._stopped or self._socket is None:
            return
        try:
            self._socket.unsubscribe_all()
        except Exception:
            pass
        try:
            self._socket.subscribe(
                symbols=sorted(self.symbol_map.keys()),
                data_type="SymbolUpdate"
            )
            self.metrics.inc("ws_resubscribes")
            log_event(self.logger, logging.INFO, "fyers_resubscribed",
                      symbols=",".join(sorted(self.symbol_map.keys())))''', 1))

EDITS.append(("R9_BUILD_ENGINE",
'''        fyers_ws = FyersWsFeed(
            fyers_token, fyers_app_id, logger, metrics, clock, engine.on_tick
        )''',
'''        symbol_map: Dict[str, Tuple[str, str, Decimal]] = {}
        for u in cfg.engine.underlyings:
            _inst = instruments.by_name[u]
            _fsym = _inst.fyers_symbol
            if _fsym is None and u == "NIFTY":
                _fsym = "NSE:NIFTY50-INDEX"
            if _fsym is None:
                raise FatalConfigError(
                    f"instruments.{u}.fyers_symbol is required for live mode")
            symbol_map[_fsym] = (u, _inst.security_id, _inst.tick_size)
        fyers_ws = FyersWsFeed(
            fyers_token, fyers_app_id, logger, metrics, clock, engine.on_tick,
            symbol_map
        )''', 1))

failed = False
for name, old, new, exp in EDITS:
    c = src.count(N(old))
    print(f"{name}: count={c} expected={exp}")
    if c != exp:
        failed = True
if failed:
    print("S1_PATCH=ANCHOR_ABORT_NO_CHANGES_WRITTEN")
    sys.exit(2)

for name, old, new, exp in EDITS:
    src = src.replace(N(old), N(new))

post_sym = src.count("NSE:NIFTY50-INDEX")
post_sid = src.count('security_id="13"')
print(f"POST: NIFTY_SYMBOL={post_sym} (expect 2) SECURITY_ID_13={post_sid} (expect 0)")
if post_sym != 2 or post_sid != 0:
    print("S1_PATCH=POSTCHECK_ABORT_NO_CHANGES_WRITTEN")
    sys.exit(3)

tmp = PATH + ".s1tmp"
with open(tmp, "w", encoding="utf-8", newline="") as fh:
    fh.write(src)
os.replace(tmp, PATH)
print("S1_PATCH=APPLIED")
