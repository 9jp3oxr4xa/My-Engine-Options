"""
S4 — FYERS option-chain adapter (SENSEX).

PURPOSE
    Provide SENSEX option-chain data to the EXISTING generic options pipeline
    by normalizing the FYERS /data/options-chain-v3 response into the engine's
    ChainSnapshot / ChainStrike / OptionLeg model.

SCOPE / SAFETY CONTRACT
    * DATA ONLY. Read-only HTTP GET. No order placement of any kind.
    * Serves ONLY the underlyings explicitly present in `symbol_map`.
      Any other underlying raises DataIntegrityError -> the engine's
      per-underlying routing fails closed. There is NO NIFTY fallback.
    * NEVER fabricates values. Fields absent from the provider are left at
      the engine model's documented defaults (see FIELD AVAILABILITY below).
    * Credentials are read from env/token-file and are never logged.
    * A failure here raises TransientInfraError / DataIntegrityError, which
      Engine.chain_poll_task already catches per-underlying; NIFTY is
      unaffected.

FIELD AVAILABILITY (verified against live FYERS response 2026-08-21)
    SUPPORTED             : strike, ltp, oi, oi_prev (prev_oi), volume,
                            security_id (fyToken), spot, expiry list
    SUPPORTED (greeks=1)  : iv  (data.optionsChain[].greeks.iv)
    UNAVAILABLE for BSE   : bid, ask  -> provider returns 0 for SENSEX on
                            /options-chain-v3, /quotes AND /depth. Passed
                            through as the provider's own 0, never invented.
    UNAVAILABLE (all)     : bid_qty, ask_qty -> field does not exist in this
                            endpoint. Left at OptionLeg default 0.

    CONSEQUENCE (intentional, not worked around): with bid/ask/qty absent the
    engine's LIQUIDITY and SPREAD gates cannot be satisfied for SENSEX, so
    SENSEX will fail closed at risk validation. That is the correct
    conservative behavior and is why SENSEX stays out of engine.underlyings
    until a depth-capable source exists (S5 decision, not S4).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import pathlib
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

FYERS_CHAIN_URL = "https://api-t1.fyers.in/data/options-chain-v3"

# FYERS' WAF rejects the default urllib User-Agent with HTTP 403 / code 1010.
_UA = "python-requests/2.31.0"

_APPID_RE = re.compile(r"\b[A-Z0-9]{6,14}-10\d\b")
_APPID_SOURCES = (
    "fyers_auth_manual.py",
    "fyers_auth_nuclear.py",
    "fyers_1m_5m_nuclear.py",
    "fyers_nifty_ws_nuclear.py",
)

# Default per-underlying FYERS spot symbols this adapter is allowed to serve.
DEFAULT_SYMBOL_MAP: Dict[str, str] = {"SENSEX": "BSE:SENSEX-INDEX"}


def _root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parent


def resolve_app_id() -> str:
    """Never logged. env first, then local project scripts."""
    env = os.environ.get("FYERS_APP_ID", "").strip()
    if env:
        return env
    for name in _APPID_SOURCES:
        p = _root() / name
        if not p.is_file():
            continue
        m = _APPID_RE.search(p.read_text(encoding="utf-8", errors="replace"))
        if m:
            return m.group(0)
    return ""


def resolve_access_token() -> str:
    """Never logged. env first, then fyers_access_token.txt."""
    env = os.environ.get("FYERS_ACCESS_TOKEN", "").strip()
    if env:
        return env
    p = _root() / "fyers_access_token.txt"
    if p.is_file():
        return p.read_text(encoding="utf-8").strip()
    return ""


def _errors():
    """Import engine error taxonomy lazily to avoid an import cycle."""
    from Dhan import DataIntegrityError, TransientInfraError
    return TransientInfraError, DataIntegrityError


def _num(value: Any) -> Optional[Decimal]:
    """Strict numeric coercion. Returns None when not a usable number."""
    if value is None or isinstance(value, bool):
        return None
    try:
        d = Decimal(str(value))
    except Exception:
        return None
    if d != d or d.is_infinite():  # NaN / Inf
        return None
    return d


def _int(value: Any) -> Optional[int]:
    d = _num(value)
    if d is None:
        return None
    try:
        return int(d)
    except Exception:
        return None


def parse_expiry_rows(rows: Any) -> List[Tuple[date, str, str]]:
    """data.expiryData -> [(date, epoch_str, flag)] sorted ascending.

    FYERS supplies {"date": "27-08-2026", "expiry": "<epoch>",
    "expiry_flag": "M"|"W"}. Rows that cannot be parsed are dropped.
    """
    out: List[Tuple[date, str, str]] = []
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not isinstance(row, dict):
            continue
        epoch = str(row.get("expiry", "")).strip()
        flag = str(row.get("expiry_flag", "")).strip()
        raw = str(row.get("date", "")).strip()
        parsed: Optional[date] = None
        if raw:
            for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d-%b-%Y"):
                try:
                    parsed = datetime.strptime(raw, fmt).date()
                    break
                except ValueError:
                    continue
        if parsed is None and epoch.isdigit():
            try:
                parsed = datetime.fromtimestamp(int(epoch), IST).date()
            except Exception:
                parsed = None
        if parsed is None:
            continue
        out.append((parsed, epoch, flag))
    out.sort(key=lambda t: t[0])
    return out


def derive_strike_step(strikes: List[Decimal]) -> Optional[Decimal]:
    """Modal positive difference across sorted unique strikes.

    Never guessed from tick size or lot size. Returns None when the grid is
    too thin to establish a step.
    """
    uniq = sorted(set(strikes))
    if len(uniq) < 3:
        return None
    diffs: Dict[Decimal, int] = {}
    for a, b in zip(uniq, uniq[1:]):
        gap = b - a
        if gap > 0:
            diffs[gap] = diffs.get(gap, 0) + 1
    if not diffs:
        return None
    best = max(diffs.items(), key=lambda kv: (kv[1], -kv[0]))
    return best[0]


class FyersChainAdapter:
    """FYERS option-chain source restricted to an explicit symbol map.

    Interface matches the engine's existing per-underlying chain adapter
    contract (see NSEChainAdapter): start / close / expiry_list / option_chain.
    """

    def __init__(
        self,
        symbol_map: Optional[Dict[str, str]] = None,
        logger: Optional[logging.Logger] = None,
        min_interval_s: float = 1.0,
        timeout_s: float = 20.0,
        strikecount: int = 10,
        app_id: Optional[str] = None,
        access_token: Optional[str] = None,
        transport: Optional[Any] = None,
    ) -> None:
        self.symbol_map = dict(symbol_map or DEFAULT_SYMBOL_MAP)
        self.logger = logger
        self.min_interval_s = float(min_interval_s)
        self.timeout_s = float(timeout_s)
        self.strikecount = int(strikecount)
        self._app_id = app_id
        self._token = access_token
        # Injectable for offline tests: transport(symbol, params) -> dict
        self._transport = transport
        self._last_call_mono: float = 0.0
        self._lock = asyncio.Lock()
        # underlying -> [(date, epoch, flag)]
        self._expiry_cache: Dict[str, List[Tuple[date, str, str]]] = {}

    # -- lifecycle ------------------------------------------------------

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None

    # -- internals ------------------------------------------------------

    def _log(self, level: int, event: str, **fields: Any) -> None:
        if self.logger is None:
            return
        try:
            from Dhan import log_event
            log_event(self.logger, level, event, **fields)
        except Exception:
            pass

    def _symbol_for(self, underlying: str) -> str:
        sym = self.symbol_map.get(underlying)
        if not sym:
            _, DataIntegrityError = _errors()
            raise DataIntegrityError(
                f"FyersChainAdapter is not configured for underlying "
                f"{underlying}; refusing to substitute another underlying")
        return sym

    def _credentials(self) -> Tuple[str, str]:
        app_id = self._app_id if self._app_id is not None else resolve_app_id()
        token = self._token if self._token is not None else resolve_access_token()
        if not app_id or not token:
            TransientInfraError, _ = _errors()
            raise TransientInfraError("FYERS credentials unavailable for chain fetch")
        return app_id, token

    def _http_get_json(self, symbol: str, params: Dict[str, Any]) -> Dict[str, Any]:
        TransientInfraError, DataIntegrityError = _errors()
        app_id, token = self._credentials()
        query = {"symbol": symbol, "strikecount": self.strikecount}
        query.update(params)
        url = f"{FYERS_CHAIN_URL}?{urllib.parse.urlencode(query)}"
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"{app_id}:{token}",
                "User-Agent": _UA,
                "Accept": "application/json",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as raw:
                body = raw.read()
        except urllib.error.HTTPError as exc:
            raise TransientInfraError(
                f"fyers chain http {exc.code} for {symbol}") from exc
        except Exception as exc:
            raise TransientInfraError(
                f"fyers chain transport error for {symbol}: "
                f"{type(exc).__name__}") from exc
        try:
            data = json.loads(body.decode("utf-8", "replace"))
        except Exception as exc:
            raise DataIntegrityError(
                f"fyers chain unparseable json for {symbol}") from exc
        if not isinstance(data, dict):
            raise DataIntegrityError(f"fyers chain non-object json for {symbol}")
        if data.get("s") != "ok":
            raise TransientInfraError(
                f"fyers chain status={data.get('s')} code={data.get('code')} "
                f"for {symbol}")
        return data

    async def _fetch(self, underlying: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Rate-limited single chain request. One request per call."""
        symbol = self._symbol_for(underlying)
        async with self._lock:
            wait = self.min_interval_s - (time.monotonic() - self._last_call_mono)
            if wait > 0:
                await asyncio.sleep(wait)
            if self._transport is not None:
                data = self._transport(symbol, dict(params))
                if asyncio.iscoroutine(data):
                    data = await data
            else:
                data = await asyncio.to_thread(self._http_get_json, symbol, params)
            self._last_call_mono = time.monotonic()
        if not isinstance(data, dict):
            _, DataIntegrityError = _errors()
            raise DataIntegrityError(f"fyers chain bad payload for {underlying}")
        return data

    # -- interface ------------------------------------------------------

    async def expiry_list(
        self,
        underlying_scrip: int,
        underlying_seg: str = "IDX_I",
        underlying: str = "SENSEX",
    ) -> List[date]:
        data = await self._fetch(underlying, {})
        rows = parse_expiry_rows((data.get("data") or {}).get("expiryData"))
        self._expiry_cache[underlying] = rows
        self._log(logging.INFO, "sensex_expiry_fetch",
                  underlying=underlying, count=len(rows),
                  nearest=(rows[0][0].isoformat() if rows else None))
        return [d for d, _e, _f in rows]

    async def option_chain(
        self,
        underlying: str,
        underlying_scrip: int,
        expiry: date,
        spot_hint: Decimal,
        underlying_seg: str = "IDX_I",
    ):
        TransientInfraError, DataIntegrityError = _errors()

        rows = self._expiry_cache.get(underlying) or []
        if not rows:
            rows = parse_expiry_rows(
                (await self._fetch(underlying, {})).get("data", {}).get("expiryData"))
            self._expiry_cache[underlying] = rows

        epoch = next((e for d, e, _f in rows if d == expiry), "")
        params: Dict[str, Any] = {"greeks": 1}
        if epoch:
            params["timestamp"] = epoch

        data = await self._fetch(underlying, params)
        snap = self._normalize(underlying, expiry, spot_hint, data)
        self._log(logging.INFO, "sensex_chain_normalized",
                  underlying=underlying, expiry=snap.expiry.isoformat(),
                  strikes=len(snap.strikes), atm=str(snap.atm_strike))
        return snap

    # -- normalization --------------------------------------------------

    def _normalize(self, underlying: str, expiry: date,
                   spot_hint: Decimal, data: Dict[str, Any]):
        """Provider payload -> engine ChainSnapshot. Fails closed."""
        from Dhan import ChainSnapshot, ChainStrike, OptionLeg
        _TransientInfraError, DataIntegrityError = _errors()

        payload = data.get("data") or {}
        rows = payload.get("optionsChain")
        if not isinstance(rows, list) or not rows:
            raise DataIntegrityError(
                f"fyers chain empty optionsChain for {underlying}")

        expected_symbol = self._symbol_for(underlying)

        # --- spot row: option_type empty AND strike_price sentinel (-1) ----
        spot: Optional[Decimal] = None
        for row in rows:
            if not isinstance(row, dict):
                continue
            otype = str(row.get("option_type", "")).strip().upper()
            strike_raw = _num(row.get("strike_price"))
            is_spot_row = (otype == "") and (strike_raw is None or strike_raw < 0)
            if not is_spot_row:
                continue
            if str(row.get("symbol", "")).strip() != expected_symbol:
                raise DataIntegrityError(
                    f"fyers chain underlying mismatch for {underlying}")
            spot = _num(row.get("ltp"))
            break

        if spot is None or spot <= 0:
            hint = _num(spot_hint)
            if hint is None or hint <= 0:
                raise DataIntegrityError(
                    f"fyers chain no usable spot for {underlying}")
            spot = hint

        # --- CE/PE rows -----------------------------------------------------
        legs: Dict[Decimal, Dict[str, Dict[str, Any]]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            otype = str(row.get("option_type", "")).strip().upper()
            if otype not in ("CE", "PE"):
                continue  # unknown types never silently become CE/PE
            strike = _num(row.get("strike_price"))
            if strike is None or strike <= 0:
                continue
            bucket = legs.setdefault(strike, {})
            if otype in bucket:
                # Deterministic duplicate handling: first row wins.
                continue
            bucket[otype] = row

        strikes = []
        for strike in sorted(legs):
            pair = legs[strike]
            ce_row, pe_row = pair.get("CE"), pair.get("PE")
            if ce_row is None or pe_row is None:
                continue  # incomplete pair is dropped, never half-filled
            ce = self._leg(OptionLeg, ce_row)
            pe = self._leg(OptionLeg, pe_row)
            if ce is None or pe is None:
                continue
            strikes.append(ChainStrike(strike=strike, ce=ce, pe=pe))

        if not strikes:
            raise DataIntegrityError(
                f"fyers chain no complete CE/PE pairs for {underlying}")

        step = derive_strike_step([s.strike for s in strikes])
        if step is None:
            self._log(logging.WARNING, "sensex_chain_strike_step_indeterminate",
                      underlying=underlying, strikes=len(strikes))
        else:
            gaps = {b.strike - a.strike for a, b in zip(strikes, strikes[1:])}
            if any(g % step != 0 for g in gaps):
                self._log(logging.WARNING, "sensex_chain_irregular_strike_grid",
                          underlying=underlying, step=str(step),
                          gaps=sorted(str(g) for g in gaps)[:6])

        atm = min(strikes, key=lambda s: abs(s.strike - spot)).strike

        return ChainSnapshot(
            underlying=underlying,
            expiry=expiry,
            spot=spot,
            ts=datetime.now(IST),
            strikes=strikes,
            atm_strike=atm,
        )

    @staticmethod
    def _leg(OptionLeg: Any, row: Dict[str, Any]):
        """One CE/PE row -> OptionLeg. Rejects negative/unusable values.

        bid/ask are passed through exactly as supplied (0 for BSE today).
        bid_qty/ask_qty are absent from this endpoint and therefore left at
        the model default of 0 -- never invented.
        """
        ltp = _num(row.get("ltp"))
        if ltp is None or ltp < 0:
            return None

        bid = _num(row.get("bid"))
        ask = _num(row.get("ask"))
        if bid is None or bid < 0:
            bid = Decimal(0)
        if ask is None or ask < 0:
            ask = Decimal(0)
        if bid > 0 and ask > 0 and bid > ask:
            return None  # crossed book is rejected, not silently reordered

        oi = _int(row.get("oi"))
        oi_prev = _int(row.get("prev_oi"))
        volume = _int(row.get("volume"))
        if oi is None or oi < 0:
            return None
        if volume is None or volume < 0:
            return None
        if oi_prev is None or oi_prev < 0:
            oi_prev = oi

        greeks = row.get("greeks")
        iv = _num(greeks.get("iv")) if isinstance(greeks, dict) else None
        if iv is None or iv < 0:
            iv = Decimal(0)

        token = row.get("fyToken")
        security_id = str(token).strip() if token is not None else ""

        return OptionLeg(
            ltp=ltp,
            bid=bid,
            ask=ask,
            oi=oi,
            oi_prev=oi_prev,
            volume=volume,
            iv=iv,
            bid_qty=0,   # UNAVAILABLE from this endpoint
            ask_qty=0,   # UNAVAILABLE from this endpoint
            security_id=security_id,
            delta=None,
        )
