"""
DETERMINISTIC SIGNAL-PATH ACCEPTANCE TEST (NO NETWORK, NO ORDERS).

Proves the FULL pipeline can emit a paper signal using the engine's REAL
production config thresholds:

    5M BARS -> STRUCTURE -> REGIME -> FRESH TRIGGER -> DIRECTION
    -> CANDIDATE -> CONFLUENCE -> CONFIDENCE -> RISK -> SIGNAL MANAGER
    -> PAPER SIGNAL (Telegram payload)

RULES OBSERVED
  * config/config.yaml thresholds are used AS-IS. NOTHING is relaxed.
  * Only the market-data FIXTURE is synthetic. Every engine component,
    threshold, gate and score is the real production one.
  * Where an early fixture failed, the FIXTURE was corrected -- never the
    strategy. Specifically the fixture had to supply:
      - a real HH/HL swing sequence with RISING ADX  (else regime=UNKNOWN)
      - EVOLVING open interest                       (else directional OI z=0)
      - RISING cumulative option volume              (else AVWAP-O has no weight)
      - a realistic PCR (not a 4.0 extreme)
      - a genuine break-and-retest                   (RETEST_OK = 12/20 struct)
  * Also verifies FIX-EV: structure events survive a snapshot round-trip.
"""
from __future__ import annotations

import asyncio
import math
import pathlib
import sys
import tempfile
from dataclasses import replace as dc_replace
from datetime import date, datetime, timedelta
from decimal import Decimal

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import warnings
warnings.filterwarnings("ignore")

import yaml  # noqa: E402
import Dhan  # noqa: E402

R: list[tuple[str, bool, str]] = []


def ck(name: str, ok: bool, detail: str = "") -> None:
    R.append((name, bool(ok), detail))
    print(f"{name}={'PASS' if ok else 'FAIL'}" + (f"  {detail}" if detail else ""))


def build_engine(logdir: str):
    """Real production config + real instruments. No threshold changes."""
    cfg_raw = yaml.safe_load(
        (ROOT / "config" / "config.yaml").read_text(encoding="utf-8-sig"))
    inst_raw = yaml.safe_load(
        (ROOT / "config" / "instruments.yaml").read_text(encoding="utf-8-sig"))
    cfg_raw["logging"]["dir"] = logdir
    cfg = Dhan.load_config(cfg_raw)
    instruments = Dhan.Instruments.load(inst_raw)
    logger = Dhan.setup_logging("INFO", True, logdir)
    clock = Dhan.FixedClock(datetime(2026, 8, 20, 9, 15, tzinfo=Dhan.IST))
    eng = Dhan._build_engine(cfg, instruments, clock, logger, Dhan.Metrics(),
                             live=False, use_nse_chain=True)
    return eng, cfg, clock


# Tick number at which genuine sustained put-writing begins. Set by main()
# once the bar plan is known. Before this point the chain only CHURNS, which
# is what a quiet tape looks like and which the engine correctly reads as
# "neutral". The engine's directional-OI z-score measures ACCELERATION of
# delta-OI against the session's own delta distribution, so a flat or
# perfectly-linear OI ramp can never produce a verdict -- only a real burst
# after a period of churn can. No engine threshold is touched.
OI_REGIME: dict[str, int | None] = {"burst_from": None}

# A real NSE option chain lists a FIXED strike ladder for the whole session.
# The fixture must do the same. An earlier version emitted a ladder that slid
# with spot (spot +/- 6 strikes), so on a trending tape a strike would simply
# APPEAR mid-session: its OI series jumped from absent to ~3,000,000 in one
# snapshot. That fake jump (a) poisoned the mean/stdev the engine's z-score is
# measured against, (b) flipped z_ce positive, and (c) left the strike out of
# the 09:16 session baseline, so session-delta OI was structurally 0 and the
# engine's session-confirmation could never be satisfied. The engine was right
# to return "neutral" on that tape. Fixed ladder = continuous OI series.
GRID_LO = 23_500
GRID_HI = 25_700


def chain_for(spot: float, ts: datetime, expiry: date, tick_no: int,
              atm_step: int = 50) -> "Dhan.ChainSnapshot":

    """Liquid NIFTY-like chain with EVOLVING OI and RISING cumulative volume.

    Bullish option structure: puts being written at/near ATM (PE OI rising),
    calls being unwound (CE OI falling). PCR kept in a realistic band.
    """
    base = int(round(spot / atm_step) * atm_step)
    strikes = []
    for k in range(GRID_LO, GRID_HI, atm_step):

        moneyness = k - spot
        ce_prem = max(30.0, 150.0 - moneyness * 0.45)
        pe_prem = max(30.0, 150.0 + moneyness * 0.45)
        near_atm = abs(k - base) <= atm_step          # ATM and ATM+/-1

        # Bullish option structure with a REALISTIC PCR *and* realistic OI
        # DYNAMICS. The engine scores directional OI as an ACCELERATION:
        #     z = (window_sum - mean*lookback) / (stdev * sqrt(lookback))
        # measured against the session's own distribution of per-snapshot
        # deltas. A flat chain gives z=0, and so does a perfectly linear
        # ramp (zero stdev) -- neither is what a real tape looks like.
        # So the fixture CHURNS near-ATM OI for most of the session, then
        # delivers a genuine sustained put-writing BURST near the trigger:
        # PE OI builds at/near ATM while CE OI unwinds (resistance
        # dissolving). Totals stay bounded so PCR remains in a sane band.
        # NO ENGINE THRESHOLD IS TOUCHED -- only the fixture's OI behaviour.
        def _oi_pair(tno: int) -> tuple[int, int]:
            """(pe_oi, ce_oi) for a near-ATM strike at snapshot `tno`."""
            churn = 45_000 if tno % 2 == 0 else 0
            pe = 3_000_000 + churn
            ce = 3_000_000 + (0 if tno % 2 == 0 else 45_000)
            b = OI_REGIME["burst_from"]
            if b is not None and tno >= b:
                steps = tno - b + 1
                pe += 220_000 * steps          # put writing accelerates
                ce -= 110_000 * steps          # calls unwind
            return pe, max(60_000, ce)

        if near_atm:
            pe_oi, ce_oi = _oi_pair(tick_no)
            prev_pe, prev_ce = _oi_pair(max(1, tick_no - 1))
        else:
            pe_oi = ce_oi = 3_000_000          # wings inert -> PCR stays sane
            prev_pe = prev_ce = 3_000_000
        prev_pe = max(1, prev_pe)
        prev_ce = max(1, prev_ce)
        vol = 120_000 + 9_000 * tick_no               # cumulative, rising


        def leg(prem: float, oi: int, oi_prev: int) -> "Dhan.OptionLeg":
            p = Decimal(str(round(prem, 2)))
            return Dhan.OptionLeg(
                ltp=p,
                bid=p - Decimal("0.25"),           # tight book -> SPREAD ok
                ask=p + Decimal("0.25"),
                oi=int(oi), oi_prev=int(oi_prev),
                volume=int(vol),
                iv=Decimal("12.5"),
                bid_qty=20_000, ask_qty=20_000,    # deep book -> LIQUIDITY ok
                security_id=f"NFO{k}",
                delta=None,
            )

        strikes.append(Dhan.ChainStrike(
            strike=Decimal(k),
            ce=leg(ce_prem, ce_oi, prev_ce),
            pe=leg(pe_prem, pe_oi, prev_pe),
        ))
    return Dhan.ChainSnapshot(
        underlying="NIFTY", expiry=expiry, spot=Decimal(str(round(spot, 2))),
        ts=ts, strikes=strikes, atm_strike=Decimal(base))


def feed_minute(eng, clock, st, ts: datetime, px: float, expiry: date,
                tick_no: int, hi_off: float = 6.0, lo_off: float = 6.0,
                close_off: float = 2.0) -> None:
    clock.set(ts)
    eng.store.apply_chain(chain_for(px, ts, expiry, tick_no))
    eng.store.last_tick_ts = ts
    o = Decimal(str(round(px, 2)))
    c = o + Decimal(str(close_off))
    st.latest_tick = Dhan.Tick(security_id="13", ts=ts, ltp=c, ltq=1,
                               volume_cum=tick_no * 500, oi=0, bid=c, ask=c,
                               bid_qty=1, ask_qty=1)
    eng._on_bar_1m("NIFTY", Dhan.Bar(
        ts_open=ts, open=o,
        high=o + Decimal(str(hi_off)), low=o - Decimal(str(lo_off)),
        close=c, volume=1200, tick_count=12))


async def main() -> int:
    logdir = tempfile.mkdtemp()
    eng, cfg, clock = build_engine(logdir)

    ck("REAL_CONFIG_THRESHOLDS",
       cfg.signals.confidence_threshold == 70,
       f"confidence>={cfg.signals.confidence_threshold} "
       f"min_cats={cfg.signals.min_categories_passed} "
       f"min_rr={cfg.signals.min_reward_risk} "
       f"max_spread={cfg.risk.max_spread_pct_of_premium} "
       f"min_depth_lots={cfg.risk.min_top_depth_lots}")

    captured: list[Dhan.OutboundMessage] = []
    eng.alerter.enqueue = lambda m: captured.append(m)  # type: ignore[assignment]

    expiry = date(2026, 8, 27)
    eng.expiries["NIFTY"] = expiry
    eng._active_expiry["NIFTY"] = expiry
    st = eng.store.get("NIFTY")

    # ---------- FIXTURE PHASE 1: real HH/HL uptrend + rising ADX ----------
    levels_5m: list[float] = []
    for i in range(44):
        levels_5m.append(24000.0 + 22.0 * i + 70.0 * math.sin(2 * math.pi * i / 8.0))
    for _ in range(8):                      # closing impulse -> fresh BOS
        levels_5m.append(levels_5m[-1] + 55.0)

    # Put-writing burst starts 8 snapshots before the trigger, i.e. inside the
    # engine's own oi_delta_lookback window but AFTER a long stretch of churn.
    # This is what a real pre-breakout tape looks like, and it is what makes
    # the engine's z-score meaningful rather than degenerate.
    total_ticks = len(levels_5m) * 5 + 6
    OI_REGIME["burst_from"] = total_ticks - 8

    t = datetime(2026, 8, 20, 9, 15, tzinfo=Dhan.IST)

    n = 0
    for bi, level in enumerate(levels_5m):
        prev = levels_5m[bi - 1] if bi > 0 else level
        for j in range(5):
            n += 1
            px = prev + (level - prev) * ((j + 1) / 5.0)
            feed_minute(eng, clock, st, t, px, expiry, n)
            t += timedelta(minutes=1)

    ck("STAGE_5M_BARS", len(st.bars_5m) >= 20, f"bars_5m={len(st.bars_5m)}")
    ck("STAGE_STRUCTURE_SWINGS", len(st.structure.swings) >= 4,
       f"swings={len(st.structure.swings)} bias={st.structure.bias}")
    ck("STAGE_REGIME",
       st.regime.state.regime in (Dhan.Regime.TREND_UP, Dhan.Regime.TREND_DOWN,
                                  Dhan.Regime.EXPANSION),
       f"regime={st.regime.state.regime.value} "
       f"strength={st.regime.state.strength_0_100} "
       f"adx={str(st.adx.value)[:6]} rising={st.adx.rising}")

    # Options intelligence must be READABLE, internally consistent, AND must
    # produce a real directional verdict from the tape. The fixture supplies a
    # genuine put-writing burst after a churn phase on a fixed strike ladder,
    # so the engine's own z-score must clear its own 1.5 bar and call this
    # bullish. Asserting the verdict here means a regression that silently
    # neuters directional OI cannot hide behind a still-passing signal.
    ov = st.last_options_view
    v5_keys = len(getattr(ov, "volume_5m", {}) or {})
    ck("STAGE_OPTIONS_INTEL",
       ov is not None and ov.atm_strike > 0 and v5_keys > 0
       and ov.pcr > 0 and len(ov.liquidity_scores) > 0
       and ov.directional_oi == "bullish"
       and float(ov.directional_z) >= 1.5,

       f"oi={ov.directional_oi} z={round(float(ov.directional_z), 2)} "
       f"pcr={round(float(ov.pcr), 2)}({ov.pcr_signal}) atm={ov.atm_strike} "
       f"vol5m_keys={v5_keys} liq_keys={len(ov.liquidity_scores)}")

    # ---------- FIXTURE PHASE 2: genuine break-and-retest -----------------
    pend = list(st.structure._pending_bos)
    ck("STAGE_PENDING_BOS", len(pend) > 0,
       f"pending={[(p['kind'].value, str(p['level'])) for p in pend]}")

    if pend:
        lvl = float(pend[-1]["level"])
        atr5 = float(st.atr_5m.value or 0)
        # pull back so the 1m LOW touches the broken level, then close strong
        # (engine requires: |low-level| <= 0.25*ATR5, close>open, close in top third)
        # Six minutes at the retest level also lets the chain's ATM
        # re-centre onto that strike, so strike selection, OI evidence and
        # volume_5m all refer to the SAME contract.
        for _step in range(6):
            n += 1
            feed_minute(eng, clock, st, t, lvl + 4.0, expiry, n,
                        hi_off=14.0, lo_off=4.0, close_off=12.0)
            t += timedelta(minutes=1)
        ck("STAGE_RETEST_GEOMETRY", atr5 > 0,
           f"bos_level={lvl:.2f} atr5={atr5:.2f} tol={0.25 * atr5:.2f}")

    evs = st.structure.events
    kinds = [e.kind.value for e in evs]
    ck("STAGE_STRUCTURE_EVENTS", len(evs) >= 1, f"events={kinds[-6:]}")
    ck("STAGE_RETEST_OK_PRODUCED", "RETEST_OK" in kinds,
       "break-and-retest is the spec's preferred trigger (12/20 structure)")

    # ---------- FIX-EV: events survive a snapshot round-trip ---------------
    persisted = st.structure.state()
    ck("FIXEV_EVENTS_PERSISTED", "events" in persisted,
       f"persisted_events={len(persisted.get('events', []))}")
    probe = Dhan.StructureEngine(2, 2, 3)
    probe.restore(persisted)
    ck("FIXEV_EVENTS_RESTORED",
       len(probe.events) == len(evs) and len(probe.events) > 0,
       f"before={len(evs)} after={len(probe.events)}")
    ck("FIXEV_EMITTED_LATCH_RESTORED", len(probe._emitted) > 0,
       f"latch={len(probe._emitted)} (blocks duplicate signals)")

    # ---------- fresh trigger + direction (real scanner) ------------------
    target = next((e for e in reversed(evs)
                   if e.kind == Dhan.StructureKind.RETEST_OK), evs[-1])
    clock.set(target.ts + timedelta(seconds=30))       # inside 180 s window
    cand = eng._scan_trigger("NIFTY", st)
    ck("STAGE_FRESH_TRIGGER", cand is not None,
       f"trigger={cand.trigger.kind.value if cand else None}")

    if cand is None:
        ages = [(e.kind.value, round((clock.now() - e.ts).total_seconds(), 1))
                for e in evs[-5:]]
        ck("SIGNAL_PATH_COMPLETE", False, f"no candidate; ages={ages}")
    else:
        ck("STAGE_DIRECTION", cand.direction is not None,
           f"direction={cand.direction.value}")

        sel = eng._select_strike("NIFTY", cand.direction)
        ck("STAGE_STRIKE_SELECTION", sel is not None, f"selected={sel}")

        m = Dhan.build_market_view(
            eng.store, "NIFTY", eng.calendar, clock,
            cand.trigger.level, cand.direction,
            sel[0] if sel else None, sel[1] if sel else None)

        ledger = eng.confluence.evaluate(cand, m)
        scored = dc_replace(eng.scorer.score(ledger), candidate=cand)
        cats: dict[str, float] = {}
        for e in ledger:
            cats[e.category] = cats.get(e.category, 0.0) + e.contribution
        ck("STAGE_CONFLUENCE", len(ledger) > 0,
           " ".join(f"{k}={v:.0f}/{Dhan.CATEGORY_MAX[k]:.0f}"
                    for k, v in cats.items()))
        # Full production admission rule, asserted in its entirety:
        #   score >= threshold, min-categories met, both MANDATORY categories
        #   (Structure and Options/OI) clearing 60% of max, and < 2
        #   contradictions. Nothing is excused. Earlier this fixture could not
        #   satisfy mandatory_ok because its sliding strike ladder destroyed
        #   OI continuity; with a fixed ladder the tape earns Options/OI 20/20
        #   on the engine's own arithmetic.
        ck("STAGE_CONFIDENCE_THRESHOLD",
           scored.score >= cfg.signals.confidence_threshold
           and scored.min_categories_ok and scored.mandatory_ok
           and scored.contradictions < 2,

           f"score={scored.score}/{cfg.signals.confidence_threshold} "
           f"band={scored.band} cats={scored.categories_passed}"
           f">={cfg.signals.min_categories_passed} "
           f"mandatory_ok={scored.mandatory_ok} contra={scored.contradictions}")

        result = eng.levels.compute(scored, m)
        is_sig = isinstance(result, Dhan.Signal)
        ck("STAGE_LEVELS", is_sig,
           (f"entry={result.option_entry} stop={result.option_stop} "
            f"t1={result.targets[0]} rr={result.reward_risk}")
           if is_sig else f"rejected={result.reason_codes}")

        if is_sig:
            m2 = dc_replace(m, reward_risk=result.reward_risk)
            gate = eng.gates.validate(scored, m2)
            if not gate.passed:
                leg = next((s.ce if m.selected_leg == "CE" else s.pe)
                           for s in m.chain.strikes
                           if s.strike == m.selected_strike)
                mid = (leg.bid + leg.ask) / Decimal(2)
                lot = eng.instruments.by_name["NIFTY"].lot_size
                diag = (f"liq={m.options_view.liquidity_scores.get(f'{m.selected_strike}|{m.selected_leg}')} "
                        f"depth_lots={min(leg.bid_qty, leg.ask_qty) / lot:.1f} "
                        f"vol={leg.volume} "
                        f"spread%={float((leg.ask - leg.bid) / mid * 100):.3f} "
                        f"regime={m.regime.regime.value} rr={result.reward_risk} "
                        f"iv_spike={m.iv_spike}")
            else:
                diag = ""
            ck("STAGE_RISK_GATES", gate.passed,
               f"reasons={gate.reason_codes} {diag}".strip())

            if gate.passed:
                accepted = eng.signals.submit(result)
                ck("STAGE_SIGNAL_MANAGER", accepted, f"id={result.id}")
                if accepted:
                    msg = Dhan.format_signal_message(result)
                    eng.alerter.enqueue(Dhan.OutboundMessage("SIGNAL", msg))
                    eng._record_signal(result, scored)
                    ck("STAGE_PAPER_SIGNAL",
                       any(x.kind == "SIGNAL" for x in captured),
                       msg.split("\n")[0])
                    dj = pathlib.Path(logdir) / "decisions.jsonl"
                    ck("AUDIT_TRAIL_WRITTEN",
                       dj.is_file() and dj.stat().st_size > 0,
                       f"decisions.jsonl={dj.stat().st_size if dj.is_file() else 0}B")
                    ck("DEDUP_STILL_ENFORCED",
                       eng.signals.submit(result) is False,
                       "duplicate submit rejected")
                    ck("SIGNAL_PATH_COMPLETE", True,
                       "trigger->candidate->confluence->confidence->risk->signal")

    failed = [n2 for n2, ok, _ in R if not ok]
    print("\n===== DETERMINISTIC SIGNAL PATH SUMMARY =====")
    print(f"TOTAL={len(R)} PASSED={len(R)-len(failed)} FAILED={len(failed)}")
    if failed:
        print("FAILED_ITEMS=" + ",".join(failed))
    print("NIFTY_SIGNAL_PATH=" + ("PASS" if not failed else "FAIL"))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
