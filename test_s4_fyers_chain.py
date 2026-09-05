"""
S4 TEST A — OFFLINE deterministic normalization tests (NO NETWORK).

Drives FyersChainAdapter through an injected transport backed by the REAL
captured FYERS response (fixtures/s4_fyers_chain_sensex_raw.json), then
asserts the S4 acceptance gate items.

Run:
  python test_s4_fyers_chain.py
"""
from __future__ import annotations

import asyncio
import copy
import importlib.util
import json
import pathlib
import sys
import types
from datetime import date
from decimal import Decimal

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def _stub_fyers_ws_if_missing() -> None:
    """TEST-ONLY shim.

    Dhan.py imports `fyers_apiv3.FyersWebsocket.data_ws` purely for the LIVE
    websocket feed. That SDK pins an aiohttp build that cannot compile on this
    interpreter. Offline normalization tests never touch the websocket, so we
    register a placeholder module *in this test process only*. Dhan.py itself
    is NOT modified, and nothing here affects runtime behavior.
    """
    if importlib.util.find_spec("fyers_apiv3") is not None:
        return
    pkg = types.ModuleType("fyers_apiv3")
    pkg.__path__ = []  # mark as package
    ws_pkg = types.ModuleType("fyers_apiv3.FyersWebsocket")
    ws_pkg.__path__ = []
    data_ws = types.ModuleType("fyers_apiv3.FyersWebsocket.data_ws")

    class _UnavailableFyersSocket:  # pragma: no cover - never used offline
        def __init__(self, *a, **k):
            raise RuntimeError("fyers_apiv3 unavailable in offline test process")

    data_ws.FyersDataSocket = _UnavailableFyersSocket
    ws_pkg.data_ws = data_ws
    pkg.FyersWebsocket = ws_pkg
    sys.modules["fyers_apiv3"] = pkg
    sys.modules["fyers_apiv3.FyersWebsocket"] = ws_pkg
    sys.modules["fyers_apiv3.FyersWebsocket.data_ws"] = data_ws
    print("FYERS_SDK_STUBBED_FOR_OFFLINE_TEST=1")


_stub_fyers_ws_if_missing()

from fyers_chain_adapter import (  # noqa: E402
    FyersChainAdapter,
    derive_strike_step,
    parse_expiry_rows,
)

FIXTURE = ROOT / "fixtures" / "s4_fyers_chain_sensex_raw.json"

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(f"{name}={'PASS' if ok else 'FAIL'}" + (f"  {detail}" if detail else ""))


def load_fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def make_adapter(payload: dict, symbol_map=None) -> FyersChainAdapter:
    calls = {"n": 0}

    def transport(symbol: str, params: dict) -> dict:
        calls["n"] += 1
        transport.last_symbol = symbol      # type: ignore[attr-defined]
        transport.last_params = params      # type: ignore[attr-defined]
        return copy.deepcopy(payload)

    transport.calls = calls                 # type: ignore[attr-defined]
    ad = FyersChainAdapter(
        symbol_map=symbol_map or {"SENSEX": "BSE:SENSEX-INDEX"},
        logger=None,
        min_interval_s=0.0,
        app_id="TEST-100",
        access_token="TEST-TOKEN",
        transport=transport,
    )
    ad._t = transport                       # type: ignore[attr-defined]
    return ad


async def main() -> int:
    if not FIXTURE.is_file():
        print("FIXTURE_MISSING", FIXTURE.name)
        return 2
    payload = load_fixture()
    check("S4_FIXTURE_PRESENT", True, FIXTURE.name)

    # ---------- expiry parsing ----------
    rows = parse_expiry_rows(payload["data"]["expiryData"])
    check("FYERS_SENSEX_EXPIRY", len(rows) >= 2, f"count={len(rows)}")
    check("SENSEX_EXPIRY_SORTED",
          all(rows[i][0] <= rows[i + 1][0] for i in range(len(rows) - 1)),
          f"nearest={rows[0][0].isoformat()}")
    check("SENSEX_EXPIRY_EPOCH_PRESENT", all(r[1].isdigit() for r in rows))
    check("SENSEX_EXPIRY_NO_HARDCODE",
          rows[0][0] == date(2026, 8, 27),
          "derived from response, not constant")

    ad = make_adapter(payload)
    expiries = await ad.expiry_list(51, underlying="SENSEX")
    check("SENSEX_EXPIRY_LIST_INTERFACE",
          isinstance(expiries, list) and all(isinstance(e, date) for e in expiries),
          f"n={len(expiries)}")

    # ---------- chain normalization ----------
    snap = await ad.option_chain("SENSEX", 51, expiries[0], Decimal(0))
    check("SENSEX_CHAIN_NORMALIZATION", snap is not None)
    check("SENSEX_UNDERLYING_CORRECT", snap.underlying == "SENSEX", snap.underlying)
    check("SENSEX_EXPIRY_ON_SNAPSHOT", snap.expiry == expiries[0],
          snap.expiry.isoformat())
    check("SENSEX_SPOT", snap.spot > 0, f"spot={snap.spot}")
    check("SENSEX_SPOT_NOT_SENTINEL", snap.spot > Decimal(1000), f"spot={snap.spot}")
    check("SENSEX_STRIKES_NONEMPTY", len(snap.strikes) >= 10,
          f"strikes={len(snap.strikes)}")

    ce_ok = all(s.ce is not None for s in snap.strikes)
    pe_ok = all(s.pe is not None for s in snap.strikes)
    check("SENSEX_CE", ce_ok)
    check("SENSEX_PE", pe_ok)
    check("SENSEX_LTP", all(s.ce.ltp > 0 and s.pe.ltp > 0 for s in snap.strikes))
    check("SENSEX_OI", all(s.ce.oi >= 0 and s.pe.oi >= 0 for s in snap.strikes))
    check("SENSEX_VOLUME",
          all(s.ce.volume >= 0 and s.pe.volume >= 0 for s in snap.strikes))
    check("SENSEX_OI_PREV_PRESENT",
          any(s.ce.oi_prev != s.ce.oi for s in snap.strikes),
          "prev_oi differs from oi on >=1 leg")

    # ---------- ATM ----------
    expected_atm = min((s.strike for s in snap.strikes),
                       key=lambda k: abs(k - snap.spot))
    check("SENSEX_ATM", snap.atm_strike == expected_atm,
          f"atm={snap.atm_strike} spot={snap.spot}")
    check("SENSEX_ATM_IN_GRID",
          snap.atm_strike in {s.strike for s in snap.strikes})

    # ---------- strike grid ----------
    step = derive_strike_step([s.strike for s in snap.strikes])
    check("SENSEX_STRIKE_STEP", step == Decimal(100), f"derived_step={step}")
    check("SENSEX_STRIKE_GRID",
          all((b.strike - a.strike) == step
              for a, b in zip(snap.strikes, snap.strikes[1:])),
          "uniform grid")
    check("SENSEX_STRIKE_STEP_NOT_TICK", step != Decimal(5),
          "step derived from data, not option tick 5.0")

    # ---------- security id ----------
    ids = [s.ce.security_id for s in snap.strikes] + \
          [s.pe.security_id for s in snap.strikes]
    check("SENSEX_SECURITY_ID_HANDLING",
          all(i and i.isdigit() for i in ids) and len(set(ids)) == len(ids),
          f"fyToken unique n={len(set(ids))}")
    check("SENSEX_SECURITY_ID_NOT_INDEX_ID",
          all(i != "51" for i in ids),
          "index id 51 never reused as option id")

    # ---------- IV via greeks ----------
    check("SENSEX_IV_FROM_GREEKS",
          any(s.ce.iv > 0 for s in snap.strikes),
          f"atm_ce_iv={min(snap.strikes, key=lambda s: abs(s.strike - snap.spot)).ce.iv}")

    # ---------- documented unavailability (must NOT be fabricated) ----------
    check("SENSEX_BID_ASK_DOCUMENTED_UNAVAILABLE",
          all(s.ce.bid == 0 and s.ce.ask == 0 for s in snap.strikes),
          "BSE bid/ask absent -> passed through as 0, not invented")
    check("SENSEX_DEPTH_QTY_NOT_FABRICATED",
          all(s.ce.bid_qty == 0 and s.ce.ask_qty == 0 for s in snap.strikes),
          "bid_qty/ask_qty absent from endpoint")
    check("SENSEX_SPOT_NOT_USED_AS_PREMIUM",
          all(s.ce.ltp != snap.spot and s.pe.ltp != snap.spot
              for s in snap.strikes))

    # ---------- no-fallback / isolation ----------
    try:
        await ad.option_chain("NIFTY", 13, expiries[0], Decimal(0))
        check("SENSEX_NO_NIFTY_FALLBACK", False, "NIFTY was served!")
    except Exception as exc:
        check("SENSEX_NO_NIFTY_FALLBACK",
              type(exc).__name__ == "DataIntegrityError", type(exc).__name__)

    ad2 = make_adapter(payload, symbol_map={"SENSEX": "BSE:SENSEX-INDEX"})
    try:
        await ad2.expiry_list(13, underlying="BANKNIFTY")
        check("UNCONFIGURED_UNDERLYING_REJECTED", False, "served unknown underlying")
    except Exception as exc:
        check("UNCONFIGURED_UNDERLYING_REJECTED",
              type(exc).__name__ == "DataIntegrityError", type(exc).__name__)

    # ---------- rate limiting / request economy ----------
    n_before = ad._t.calls["n"]                      # type: ignore[attr-defined]
    await ad.option_chain("SENSEX", 51, expiries[0], Decimal(0))
    check("SENSEX_ONE_REQUEST_PER_CHAIN",
          ad._t.calls["n"] - n_before == 1,          # type: ignore[attr-defined]
          "expiry cache reused; no per-strike calls")
    check("SENSEX_EXPIRY_TIMESTAMP_SENT",
          str(ad._t.last_params.get("timestamp", "")) == rows[0][1],  # type: ignore[attr-defined]
          "explicit expiry epoch passed to provider")
    check("SENSEX_GREEKS_REQUESTED",
          ad._t.last_params.get("greeks") == 1)      # type: ignore[attr-defined]

    # ---------- fail-closed on malformed data ----------
    async def expect_fail(name: str, mutate) -> None:
        bad = copy.deepcopy(payload)
        mutate(bad)
        a = make_adapter(bad)
        try:
            await a.option_chain("SENSEX", 51, date(2026, 8, 27), Decimal(0))
            check(name, False, "accepted malformed data")
        except Exception as exc:
            check(name, type(exc).__name__ == "DataIntegrityError",
                  type(exc).__name__)

    await expect_fail("FAILCLOSED_EMPTY_CHAIN",
                      lambda d: d["data"].__setitem__("optionsChain", []))
    await expect_fail(
        "FAILCLOSED_WRONG_UNDERLYING",
        lambda d: [r.__setitem__("symbol", "NSE:NIFTY50-INDEX")
                   for r in d["data"]["optionsChain"]
                   if r.get("option_type") == ""])
    await expect_fail(
        "FAILCLOSED_NO_CE_PE",
        lambda d: d["data"].__setitem__(
            "optionsChain",
            [r for r in d["data"]["optionsChain"] if r.get("option_type") == ""]))

    # negative OI on every CE row -> all pairs dropped -> fail closed
    await expect_fail(
        "FAILCLOSED_NEGATIVE_OI",
        lambda d: [r.__setitem__("oi", -5) for r in d["data"]["optionsChain"]
                   if r.get("option_type") == "CE"])

    # crossed book (bid > ask) on every CE row -> pairs dropped
    await expect_fail(
        "FAILCLOSED_CROSSED_BOOK",
        lambda d: [(r.__setitem__("bid", 100), r.__setitem__("ask", 10))
                   for r in d["data"]["optionsChain"]
                   if r.get("option_type") == "CE"])

    # duplicate strike rows must be handled deterministically (first wins)
    dup = copy.deepcopy(payload)
    ce_rows = [r for r in dup["data"]["optionsChain"] if r.get("option_type") == "CE"]
    clone = copy.deepcopy(ce_rows[0])
    clone["ltp"] = 999999
    dup["data"]["optionsChain"].append(clone)
    ad3 = make_adapter(dup)
    snap3 = await ad3.option_chain("SENSEX", 51, date(2026, 8, 27), Decimal(0))
    target = next(s for s in snap3.strikes
                  if s.strike == Decimal(str(ce_rows[0]["strike_price"])))
    check("DUPLICATE_STRIKE_DETERMINISTIC",
          target.ce.ltp == Decimal(str(ce_rows[0]["ltp"])),
          "first row wins")

    # spot fallback to hint when spot row unusable
    nospot = copy.deepcopy(payload)
    for r in nospot["data"]["optionsChain"]:
        if r.get("option_type") == "":
            r["ltp"] = 0
    ad4 = make_adapter(nospot)
    snap4 = await ad4.option_chain("SENSEX", 51, date(2026, 8, 27), Decimal("77000"))
    check("SPOT_HINT_FALLBACK", snap4.spot == Decimal("77000"),
          f"spot={snap4.spot}")

    ad5 = make_adapter(nospot)
    try:
        await ad5.option_chain("SENSEX", 51, date(2026, 8, 27), Decimal(0))
        check("FAILCLOSED_NO_SPOT_NO_HINT", False, "accepted zero spot")
    except Exception as exc:
        check("FAILCLOSED_NO_SPOT_NO_HINT",
              type(exc).__name__ == "DataIntegrityError", type(exc).__name__)

    # ---------- engine model compatibility ----------
    from Dhan import ChainSnapshot, ChainStrike, OptionLeg
    check("ENGINE_MODEL_TYPES",
          isinstance(snap, ChainSnapshot)
          and isinstance(snap.strikes[0], ChainStrike)
          and isinstance(snap.strikes[0].ce, OptionLeg))
    check("SNAPSHOT_TS_TZ_AWARE", snap.ts.tzinfo is not None,
          str(snap.ts.tzinfo))
    check("SNAPSHOT_TS_IS_IST",
          str(snap.ts.utcoffset()) == "5:30:00", str(snap.ts.utcoffset()))

    # ---------- consumed by real OptionsIntel (generic layer) ----------
    from Dhan import OptionsIntel
    oi = OptionsIntel(3, 3, Decimal("0.8"), Decimal("1.2"))
    view = oi.on_snapshot(snap)
    check("OPTIONSINTEL_ACCEPTS_SENSEX", view is not None,
          f"atm={view.atm_strike} pcr={round(float(view.pcr), 3)}")
    check("OPTIONSINTEL_ATM_MATCHES_GRID",
          view.atm_strike in {s.strike for s in snap.strikes})
    check("OPTIONSINTEL_LIQ_SCORES_BUILT",
          len(view.liquidity_scores) > 0, f"n={len(view.liquidity_scores)}")

    total = len(RESULTS)
    failed = [n for n, ok, _ in RESULTS if not ok]
    print("\n===== S4 TEST A SUMMARY =====")
    print(f"TOTAL={total} PASSED={total - len(failed)} FAILED={len(failed)}")
    if failed:
        print("FAILED_ITEMS=" + ",".join(failed))
    print("S4_OFFLINE_NORMALIZATION=" + ("PASS" if not failed else "FAIL"))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
