# -*- coding: utf-8 -*-
"""
TASK 1C STAGE-COMPLETION HARNESS  (LEVELS / RR / LIQUIDITY / VETO / FINAL / SIGNAL)

The real 2026-09-01 session never produced a signal, so the downstream half of
the DAG is never entered by the real-data replay and its ON/OFF equality cannot
be measured there. This harness drives the REAL production entrypoint
Engine.evaluate() -> Engine._evaluate_inner() with CONSTRUCTED (clearly labelled,
non-market) chain snapshots and bars that satisfy the real gate arithmetic, so
those stages actually execute.

Nothing is stubbed: ConfluenceEngine, ConfidenceScorer, LevelEngine, RiskGates,
SignalManager and TelegramAlerter formatting are the production objects, and no
threshold, weight or rule is modified. Scaffolding is limited to setting up
market STATE (bars, chain, regime, structure event), exactly as a fixture would.

Usage:  python task1c_signalpath.py OUT.json      (honours DHAN_FORENSICS)
"""
import json
import os
import sys

R = os.path.dirname(os.path.abspath(__file__))
os.chdir(R)
sys.path.insert(0, R)

import Dhan as D                                             # noqa: E402
from decimal import Decimal                                  # noqa: E402
from datetime import timedelta                               # noqa: E402

U = "NIFTY"
SPOT0 = Decimal("26000")


def _leg(ltp, oi, vol, iv=Decimal("15")):
    ltp = Decimal(ltp).quantize(Decimal("0.05"))
    return D.OptionLeg(ltp=ltp, bid=ltp - Decimal("0.50"), ask=ltp + Decimal("0.50"),
                       oi=int(oi), oi_prev=int(oi), volume=int(vol), iv=iv,
                       bid_qty=10000, ask_qty=10000, security_id="")


def chain(ts, spot, pe_oi, ce_oi, vol):
    strikes = []
    for i in range(-6, 7):
        k = spot + Decimal(50 * i)
        d = (spot - k) / Decimal(2)
        strikes.append(D.ChainStrike(
            strike=k,
            ce=_leg(Decimal(150) + d, ce_oi, vol),
            pe=_leg(Decimal(150) - d, pe_oi, vol)))
    return D.ChainSnapshot(underlying=U, expiry=ts.date() + timedelta(days=6),
                           spot=spot, ts=ts, strikes=strikes, atm_strike=spot)


def main(out_path):
    cfg = D.load_config(D._load_yaml(os.path.join("config", "config.yaml")))
    inst = D.Instruments.load(D._load_yaml(os.path.join("config", "instruments.yaml")))
    logger = D.setup_logging("ERROR", True, cfg.logging.dir)
    metrics = D.Metrics()
    t0 = D.datetime(2026, 9, 1, 9, 15, tzinfo=D.IST)
    clock = D.FixedClock(t0)
    eng = D._build_engine(cfg, inst, clock, logger, metrics, live=False)
    st = eng.store.get(U)

    # ---- 1. constructed trending 1m series: HH/HL so ADX rises -------------
    px = SPOT0 - Decimal(300)
    agg = eng.aggregators[U]
    for i in range(45):
        leg_up = (i % 5) != 4
        step = Decimal(14) if leg_up else Decimal("-6")
        o = px
        c = px + step
        hi = max(o, c) + Decimal(3)
        lo = min(o, c) - Decimal(3)
        ts = t0 + timedelta(minutes=i)
        bar = D.Bar(ts_open=ts, open=o, high=hi, low=lo, close=c,
                    volume=100000 + i * 500, tick_count=60)
        st.last_atm_option_volume = 120000 + i * 700       # feeds rvol + avwap
        st.last_atm_option_volume_suspect = False
        eng.store.apply_index_bar(U, bar, D.SessionPhase.MORNING, agg)
        px = c
    spot = st.bars_1m[-1].close

    # ---- 2. constructed chain history: PE writing, CE flat -----------------
    ct = t0 + timedelta(minutes=21)
    pe, ce = 100000, 100000
    for i in range(26):
        pe += 120 if i < 15 else 6000                    # last-10 window spike
        pe += (i % 3)                                    # non-zero variance
        snap = chain(ct + timedelta(seconds=30 * i), spot, pe, ce,
                     60000 + i * 25000)
        eng.store.apply_chain(snap)
    view = st.last_options_view

    # ---- 3. clock into the signal window; freshness satisfied -------------
    now = st.last_chain.ts + timedelta(seconds=20)
    clock.set(now)
    eng.store.last_tick_ts = now
    eng._warmup_bars_remaining[U] = 0

    # ---- 4. state scaffolding for a trend-continuation trigger ------------
    st.regime._state = D.RegimeState(D.Regime.TREND_UP, now - timedelta(minutes=20), 80)
    st.structure._bias = "BULLISH"
    # Trigger 15 pts under spot: premium risk = beta(0.5) * 15 = 7.5, while the
    # nearest qualifying clustered target sits ~47 pts above spot, so the REAL
    # LevelEngine arithmetic yields R:R above cfg.signals.min_reward_risk and
    # the RR / LIQUIDITY / VETO / FINAL / SIGNAL stages are entered. No
    # threshold is altered; only the constructed geometry.
    trig_level = (spot - Decimal(15)).quantize(Decimal("0.05"))
    ref = D.Swing(D.SwingKind.LOW, trig_level, now - timedelta(minutes=10), 30, True)
    ev = D.StructureEvent(D.StructureKind.RETEST_OK, trig_level,
                          now - timedelta(seconds=30), ref)
    st.structure._events.append(ev)

    # ---- 5. THE REAL PRODUCTION CYCLE ------------------------------------
    dec_path = os.path.join(cfg.logging.dir, "decisions.jsonl")
    d0 = os.path.getsize(dec_path) if os.path.exists(dec_path) else 0
    sent = []
    _orig = eng.alerter.enqueue
    eng.alerter.enqueue = lambda m: (sent.append((m.kind, m.text)), _orig(m))[0]
    eng.evaluate(U)
    rows = []
    if os.path.exists(dec_path):
        with open(dec_path, encoding="utf-8", errors="replace") as fh:
            fh.seek(d0)
            for ln in fh:
                if ln.strip().startswith("{"):
                    r = json.loads(ln)
                    r.pop("ts", None)                    # wall-clock only
                    rows.append(r)

    # what the pipeline decided, and what it would have alerted
    sig = [t for k, t in sent if k == "SIGNAL"]
    out = {
        "forensics": os.environ.get("DHAN_FORENSICS", "0"),
        "spot": str(spot), "atm": str(view.atm_strike),
        "directional_oi": view.directional_oi, "z": str(view.directional_z),
        "oi_branch": st.options._last_terms.get("branch"),
        "liquidity_atm_ce": view.liquidity_scores.get("%s|CE" % view.atm_strike),
        "volume_5m_atm_ce": view.volume_5m.get("%s|CE" % view.atm_strike),
        "counters": dict(sorted(metrics.counters.items())),
        "rejections_by_reason": dict(sorted(metrics.rejections_by_reason.items())),
        "decision_rows": rows,
        "signal_messages": [s.replace("\u20b9", "Rs") for s in sig],
        "signal_count": len(sig),
    }
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, indent=1, default=str, sort_keys=True)
    print(json.dumps({k: out[k] for k in
                      ("forensics", "directional_oi", "z", "oi_branch",
                       "liquidity_atm_ce", "volume_5m_atm_ce", "counters",
                       "rejections_by_reason", "signal_count")},
                     default=str, sort_keys=True))
    for r in rows:
        print("DECISION", r.get("type"), r.get("stage"), r.get("reasons"),
              r.get("score"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "_sp.json"))
