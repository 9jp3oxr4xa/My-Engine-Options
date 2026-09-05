import os, sys

PATH = "Dhan.py"
with open(PATH, "r", encoding="utf-8", newline="") as fh:
    src = fh.read()

if "def fetch_day(symbol" in src:
    print("ABORT_ALREADY_PATCHED")
    sys.exit(2)

eol = "\r\n" if "\r\n" in src else "\n"
def N(s):
    return s.replace("\r\n", "\n").replace("\n", eol)

EDITS = []

EDITS.append(("E1_SIGNATURE",
'''        u = self.cfg.engine.underlyings[0]
        today = self.clock.now().date()

        def fetch_day(day: date) -> List[List[Any]]:''',
'''        today = self.clock.now().date()

        def fetch_day(symbol: str, day: date) -> List[List[Any]]:''', 1))

EDITS.append(("E2_SYMBOL_PARAM",
'''                    "symbol": "NSE:NIFTY50-INDEX",''',
'''                    "symbol": symbol,''', 1))

EDITS.append(("E3_ROW_TO_BAR_TICK",
'''        def row_to_bar(row: List[Any]) -> Optional[Bar]:
            if len(row) < 6:
                return None
            epoch, o, h, l, c, v = row[:6]
            ts = datetime.fromtimestamp(
                int(epoch), tz=ZoneInfo("UTC")
            ).astimezone(IST).replace(second=0, microsecond=0)
            return Bar(
                ts_open=ts,
                open=quantize_tick(_d(o), Decimal("0.05")),
                high=quantize_tick(_d(h), Decimal("0.05")),
                low=quantize_tick(_d(l), Decimal("0.05")),
                close=quantize_tick(_d(c), Decimal("0.05")),
                volume=int(v or 0),
                tick_count=0,
                volume_suspect=True,
            )''',
'''        def row_to_bar(row: List[Any], tick: Decimal) -> Optional[Bar]:
            if len(row) < 6:
                return None
            epoch, o, h, l, c, v = row[:6]
            ts = datetime.fromtimestamp(
                int(epoch), tz=ZoneInfo("UTC")
            ).astimezone(IST).replace(second=0, microsecond=0)
            return Bar(
                ts_open=ts,
                open=quantize_tick(_d(o), tick),
                high=quantize_tick(_d(h), tick),
                low=quantize_tick(_d(l), tick),
                close=quantize_tick(_d(c), tick),
                volume=int(v or 0),
                tick_count=0,
                volume_suspect=True,
            )''', 1))

EDITS.append(("E4_PER_UNDERLYING_LOOP",
'''        inst = self.instruments.by_name[u]
        _keep_volume = self.store.get(u).volume
        self.store.states[u] = UnderlyingState(
            u, self.cfg, inst.tick_size, self.clock
        )
        st = self.store.get(u)
        st.volume = _keep_volume

        # Previous sessions: seed slow indicators only.
        prior = []
        for back in range(1, 6):
            for row in fetch_day(today - timedelta(days=back)):
                b = row_to_bar(row)
                if b is not None:
                    prior.append(b)
            if len(prior) >= 200:
                break

        prior.sort(key=lambda b: b.ts_open)
        if prior:
            _pd_date = prior[-1].ts_open.date()
            _pd_bars = [b for b in prior if b.ts_open.date() == _pd_date]
            st.structure.set_prev_day(
                max(b.high for b in _pd_bars),
                min(b.low for b in _pd_bars),
                _pd_bars[-1].close,
            )
        pa = BarAggregator5m()
        for b in prior:
            b5 = pa.on_bar_1m(b)
            if b5 is not None:
                st.atr_5m.update(b5)
                st.adx.update(b5)
                st.bb.update(b5)
                st.ema20.update(b5)

        # Today: rebuild actual session state on the live aggregator (continuity).
        self.aggregators[u] = BarAggregator5m()
        ta = self.aggregators[u]
        current_minute = self.clock.now().replace(second=0, microsecond=0)
        today_count = 0
        for row in fetch_day(today):
            b = row_to_bar(row)
            if b is None or b.ts_open >= current_minute:
                continue
            self.store.apply_index_bar(
                u, b, self.calendar.phase(b.ts_open), ta
            )
            today_count += 1

        self._maybe_set_opening_range(u)
        self._warmup_bars_remaining[u] = 0

        log_event(
            self.logger, logging.INFO, "fyers_history_bootstrap",
            underlying=u, prior_1m=len(prior), today_1m=today_count,
            state_1m=len(st.bars_1m), state_5m=len(st.bars_5m),
            atr_5m=str(st.atr_5m.value), adx=str(st.adx.value),
            ema20=str(st.ema20.value)
        )''',
'''        for u in self.cfg.engine.underlyings:
            inst = self.instruments.by_name[u]
            _fsym = inst.fyers_symbol
            if _fsym is None and u == "NIFTY":
                _fsym = "NSE:NIFTY50-INDEX"
            if _fsym is None:
                raise FatalConfigError(
                    f"instruments.{u}.fyers_symbol is required for history bootstrap")
            _keep_volume = self.store.get(u).volume
            self.store.states[u] = UnderlyingState(
                u, self.cfg, inst.tick_size, self.clock
            )
            st = self.store.get(u)
            st.volume = _keep_volume

            # Previous sessions: seed slow indicators only.
            prior = []
            for back in range(1, 6):
                for row in fetch_day(_fsym, today - timedelta(days=back)):
                    b = row_to_bar(row, inst.tick_size)
                    if b is not None:
                        prior.append(b)
                if len(prior) >= 200:
                    break

            prior.sort(key=lambda b: b.ts_open)
            if prior:
                _pd_date = prior[-1].ts_open.date()
                _pd_bars = [b for b in prior if b.ts_open.date() == _pd_date]
                st.structure.set_prev_day(
                    max(b.high for b in _pd_bars),
                    min(b.low for b in _pd_bars),
                    _pd_bars[-1].close,
                )
            pa = BarAggregator5m()
            for b in prior:
                b5 = pa.on_bar_1m(b)
                if b5 is not None:
                    st.atr_5m.update(b5)
                    st.adx.update(b5)
                    st.bb.update(b5)
                    st.ema20.update(b5)

            # Today: rebuild actual session state on the live aggregator (continuity).
            self.aggregators[u] = BarAggregator5m()
            ta = self.aggregators[u]
            current_minute = self.clock.now().replace(second=0, microsecond=0)
            today_count = 0
            for row in fetch_day(_fsym, today):
                b = row_to_bar(row, inst.tick_size)
                if b is None or b.ts_open >= current_minute:
                    continue
                self.store.apply_index_bar(
                    u, b, self.calendar.phase(b.ts_open), ta
                )
                today_count += 1

            self._maybe_set_opening_range(u)
            self._warmup_bars_remaining[u] = 0

            log_event(
                self.logger, logging.INFO, "fyers_history_bootstrap",
                underlying=u, fyers_symbol=_fsym,
                prior_1m=len(prior), today_1m=today_count,
                state_1m=len(st.bars_1m), state_5m=len(st.bars_5m),
                atr_5m=str(st.atr_5m.value), adx=str(st.adx.value),
                ema20=str(st.ema20.value)
            )''', 1))

failed = False
for name, old, new, exp in EDITS:
    c = src.count(N(old))
    print(f"{name}: count={c} expected={exp}")
    if c != exp:
        failed = True
if failed:
    print("S2_PATCH=ANCHOR_ABORT_NO_CHANGES_WRITTEN")
    sys.exit(2)

for name, old, new, exp in EDITS:
    src = src.replace(N(old), N(new))

p_zero = src.count("underlyings[0]")
p_sym  = src.count("NSE:NIFTY50-INDEX")
p_fd   = src.count("def fetch_day(symbol: str, day: date)")
p_rtb  = src.count("row_to_bar(row, inst.tick_size)")
p_url  = src.count("api-t1.fyers.in/data/history")
print(f"POST: UNDERLYINGS_ZERO={p_zero} (expect 0) NIFTY_SYMBOL={p_sym} (expect 2) "
      f"FETCH_DAY_NEW={p_fd} (expect 1) ROW_TO_BAR_TICK={p_rtb} (expect 2) URL_INTACT={p_url} (expect 1)")
if p_zero != 0 or p_sym != 2 or p_fd != 1 or p_rtb != 2 or p_url != 1:
    print("S2_PATCH=POSTCHECK_ABORT_NO_CHANGES_WRITTEN")
    sys.exit(3)

tmp = PATH + ".s2tmp"
with open(tmp, "w", encoding="utf-8", newline="") as fh:
    fh.write(src)
os.replace(tmp, PATH)
print("S2_PATCH=APPLIED")
