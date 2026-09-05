"""
S4 REGRESSION — routing / isolation / NIFTY-unchanged (NO NETWORK).

Verifies the post-S4 Dhan.py wiring:
  * NIFTY still routes to the existing NSEChainAdapter.
  * SENSEX routes to FyersChainAdapter and NEVER to NIFTY/NSE.
  * Unconfigured underlyings fail closed via _chain_adapter_for.
  * Per-underlying state remains isolated.
  * S4 code path is inert while SENSEX is absent from engine.underlyings.
  * No live-order surface was introduced.

Run:
  python test_s4_routing.py
"""
from __future__ import annotations

import asyncio
import importlib.util
import pathlib
import sys
import tempfile
import types
from decimal import Decimal

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def _stub_fyers_ws_if_missing() -> None:
    if importlib.util.find_spec("fyers_apiv3") is not None:
        return
    pkg = types.ModuleType("fyers_apiv3")
    pkg.__path__ = []
    ws = types.ModuleType("fyers_apiv3.FyersWebsocket")
    ws.__path__ = []
    dws = types.ModuleType("fyers_apiv3.FyersWebsocket.data_ws")

    class _Unavailable:
        def __init__(self, *a, **k):
            raise RuntimeError("fyers_apiv3 unavailable")

    dws.FyersDataSocket = _Unavailable
    ws.data_ws = dws
    pkg.FyersWebsocket = ws
    sys.modules["fyers_apiv3"] = pkg
    sys.modules["fyers_apiv3.FyersWebsocket"] = ws
    sys.modules["fyers_apiv3.FyersWebsocket.data_ws"] = dws


_stub_fyers_ws_if_missing()

import Dhan  # noqa: E402
from fyers_chain_adapter import FyersChainAdapter  # noqa: E402
from nse_chain_adapter import NSEChainAdapter  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(f"{name}={'PASS' if ok else 'FAIL'}" + (f"  {detail}" if detail else ""))


def base_cfg(underlyings: list[str], logdir: str) -> dict:
    return {
        "engine": {"underlyings": underlyings, "evaluation_interval_s": 5,
                   "timezone": "Asia/Kolkata", "holidays": []},
        "feeds": {"ws_reconnect_max_s": 30, "chain_poll_interval_s": 5,
                  "stale_tick_s": 10, "stale_chain_s": 30},
        "signals": {"confidence_threshold": 70, "min_categories_passed": 3,
                    "cooldown_minutes_per_underlying": 10,
                    "max_signals_per_day_per_underlying": 5,
                    "min_reward_risk": 1.5},
        "risk": {"max_spread_pct_of_premium": 5, "min_option_volume_5m": 100,
                 "min_top_depth_lots": 2, "news_blackout": []},
        "structure": {"swing_left_bars": 2, "swing_right_bars": 2,
                      "sweep_max_close_back_bars": 3},
        "regime": {"adx_period": 14, "atr_period": 14,
                   "compression_bb_pct_rank": 20},
        "options": {"atm_band_strikes": 3, "oi_delta_lookback_snapshots": 3,
                    "pcr_bands": {"bearish_below": 0.8, "bullish_above": 1.2}},
        "telegram": {"chat_id_env": "TG_CHAT_ID", "send_rejections_digest": False},
        "logging": {"level": "INFO", "json": True, "dir": logdir},
    }


def instruments_for(names: list[str]) -> "Dhan.Instruments":
    spec = {}
    if "NIFTY" in names:
        spec["NIFTY"] = {"security_id": "13", "exchange_segment": "NSE_FNO",
                         "lot_size": 65, "strike_step": 50, "tick_size": 0.05,
                         "fyers_symbol": "NSE:NIFTY50-INDEX"}
    if "SENSEX" in names:
        spec["SENSEX"] = {"security_id": "51", "exchange_segment": "BSE_FNO",
                          "lot_size": 20, "strike_step": 100, "tick_size": 0.05,
                          "fyers_symbol": "BSE:SENSEX-INDEX"}
    return Dhan.Instruments.load({"instruments": spec})


def build(underlyings: list[str]):
    logdir = tempfile.mkdtemp()
    cfg = Dhan.load_config(base_cfg(underlyings, logdir))
    instr = instruments_for(underlyings)
    logger = Dhan.setup_logging("INFO", True, logdir)
    return Dhan._build_engine(cfg, instr, Dhan.Clock(), logger,
                              Dhan.Metrics(), live=False, use_nse_chain=True)


async def main() -> int:
    # ---------- CONTROL: NIFTY-only (current production config) ----------
    eng = build(["NIFTY"])
    check("NIFTY_PROVIDER", "NIFTY" in eng.chain_adapters)
    check("NIFTY_PROVIDER_IS_CURRENT_NSE",
          isinstance(eng.chain_adapters["NIFTY"], NSEChainAdapter),
          type(eng.chain_adapters["NIFTY"]).__name__)
    check("NIFTY_PROVIDER_UNCHANGED",
          eng.chain_adapters["NIFTY"] is eng.nse_chain,
          "same object as pre-S4 nse_chain")
    check("S4_INERT_WHEN_SENSEX_ABSENT",
          "SENSEX" not in eng.chain_adapters,
          "no SENSEX adapter created for NIFTY-only config")

    try:
        eng._chain_adapter_for("SENSEX")
        check("SENSEX_UNCONFIGURED_FAILS_CLOSED", False, "returned an adapter!")
    except Exception as exc:
        check("SENSEX_UNCONFIGURED_FAILS_CLOSED",
              type(exc).__name__ == "FatalConfigError", type(exc).__name__)

    # ---------- DUAL: NIFTY + SENSEX (S5 preview; config NOT changed) -----
    eng2 = build(["NIFTY", "SENSEX"])
    check("S3_NIFTY_STILL_NSE",
          isinstance(eng2.chain_adapters.get("NIFTY"), NSEChainAdapter),
          type(eng2.chain_adapters.get("NIFTY")).__name__)
    check("S4_SENSEX_PROVIDER_WIRED",
          isinstance(eng2.chain_adapters.get("SENSEX"), FyersChainAdapter),
          type(eng2.chain_adapters.get("SENSEX")).__name__)
    check("SENSEX_DOES_NOT_FALLBACK_TO_NIFTY",
          eng2.chain_adapters["SENSEX"] is not eng2.chain_adapters["NIFTY"],
          "distinct adapter objects")
    check("SENSEX_ADAPTER_SYMBOL_MAP",
          eng2.chain_adapters["SENSEX"].symbol_map == {"SENSEX": "BSE:SENSEX-INDEX"},
          str(eng2.chain_adapters["SENSEX"].symbol_map))
    check("SENSEX_ADAPTER_REFUSES_NIFTY_SYMBOL",
          "NIFTY" not in eng2.chain_adapters["SENSEX"].symbol_map)

    # adapter routing helper resolves each independently
    check("CHAIN_ADAPTER_FOR_NIFTY",
          eng2._chain_adapter_for("NIFTY") is eng2.chain_adapters["NIFTY"])
    check("CHAIN_ADAPTER_FOR_SENSEX",
          eng2._chain_adapter_for("SENSEX") is eng2.chain_adapters["SENSEX"])

    # ---------- state isolation ----------
    n_state = eng2.store.get("NIFTY")
    s_state = eng2.store.get("SENSEX")
    check("STATE_ISOLATION", n_state is not s_state)
    n_state.bars_1m.append(
        Dhan.Bar(ts_open=Dhan.datetime.now(Dhan.IST), open=Decimal(1),
                 high=Decimal(2), low=Decimal(1), close=Decimal(2),
                 volume=1, tick_count=1))
    check("STATE_NO_CROSS_CONTAMINATION",
          len(n_state.bars_1m) == 1 and len(s_state.bars_1m) == 0,
          f"nifty={len(n_state.bars_1m)} sensex={len(s_state.bars_1m)}")
    check("SCRIP_MAP_ISOLATED",
          eng2.scrip_map["NIFTY"] == 13 and eng2.scrip_map["SENSEX"] == 51,
          str(eng2.scrip_map))
    check("TICK_SIZE_PER_UNDERLYING",
          n_state.tick_size == Decimal("0.05")
          and s_state.tick_size == Decimal("0.05"))

    # ---------- SENSEX provider failure must not affect NIFTY -------------
    async def boom(*a, **k):
        raise Dhan.TransientInfraError("simulated SENSEX provider outage")

    eng2.chain_adapters["SENSEX"].option_chain = boom  # type: ignore[assignment]
    eng2.expiries["SENSEX"] = Dhan.date(2026, 8, 27)
    try:
        await eng2._poll_chain("SENSEX")
        check("SENSEX_OUTAGE_RAISES_PER_UNDERLYING", False, "no error raised")
    except Dhan.TransientInfraError:
        check("SENSEX_OUTAGE_RAISES_PER_UNDERLYING", True,
              "caught by chain_poll_task per-underlying handler")
    except Exception as exc:
        check("SENSEX_OUTAGE_RAISES_PER_UNDERLYING", False, type(exc).__name__)

    check("NIFTY_ADAPTER_SURVIVES_SENSEX_OUTAGE",
          isinstance(eng2.chain_adapters.get("NIFTY"), NSEChainAdapter))

    # ---------- production config must still be NIFTY-only ----------------
    import yaml
    live_cfg = yaml.safe_load(
        (ROOT / "config" / "config.yaml").read_text(encoding="utf-8"))
    check("NIFTY_CONFIG",
          live_cfg["engine"]["underlyings"] == ["NIFTY"],
          str(live_cfg["engine"]["underlyings"]))
    check("SENSEX_NOT_ACTIVATED_IN_PROD",
          "SENSEX" not in live_cfg["engine"]["underlyings"])

    # ---------- paper-safety: no order surface ----------------------------
    adapter_src = (ROOT / "fyers_chain_adapter.py").read_text(encoding="utf-8")
    forbidden = [t for t in ("/orders", "/positions/convert", "place_order",
                             "modify_order", "cancel_order", "exit_position")
                 if t in adapter_src]
    check("NO_LIVE_ORDER_SURFACE", not forbidden, str(forbidden))
    check("ADAPTER_READ_ONLY_GET",
          'method="GET"' in adapter_src and "urlopen" in adapter_src)

    # ---------- credential hygiene ----------------------------------------
    leaks = [t for t in ("print(token", "print(app_id", "log_event(self.logger, logging.INFO, \"token")
             if t in adapter_src]
    check("NO_CREDENTIAL_LOGGING", not leaks, str(leaks))

    failed = [n for n, ok, _ in RESULTS if not ok]
    print("\n===== S4 ROUTING REGRESSION SUMMARY =====")
    print(f"TOTAL={len(RESULTS)} PASSED={len(RESULTS) - len(failed)} "
          f"FAILED={len(failed)}")
    if failed:
        print("FAILED_ITEMS=" + ",".join(failed))
    print("S4_ROUTING_REGRESSION=" + ("PASS" if not failed else "FAIL"))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
