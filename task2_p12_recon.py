# -*- coding: utf-8 -*-
"""
TASK 2 / PHASE 12E-12G + 12M/12N  (READ ONLY)

Exact reconstruction of today's OI decision from persisted evidence, then
candidate-level attribution.

Reconstructed per poll, using ONLY persisted operands:
  z      = (win - mu*lookback) / (sd*sqrt(lookback))          [source line 2099]
  win    = sum over basket strikes of per_strike_delta/avg_oi  [2075-2083]
  b1..b4 = the exact conjunctions at source lines 2123-2128
  verdict= the ladder at 2153-2170
and compared against the engine's own persisted branch/verdict.

Also: cohort analysis of today's runtime (engine logs + metrics) and of the 120
candidates, with per-candidate blocking-operand attribution.

Emits TASK2_OI_RECONSTRUCTION_REPORT.json/.txt, TASK2_COUNTERFACTUAL_LEDGER.json
"""
import collections
import json
import math
import os
from decimal import Decimal

PROJ = r"C:\Users\Guest -A\Desktop\Dhan Test"
B = os.path.join(PROJ, "Audit Bundle Sep 02")
DIAG = os.path.join(B, "02_TODAY_LOGS", "logs", "oi_diag.jsonl")
LOGS = [os.path.join(B, "02_TODAY_LOGS", "logs", "engine.log"),
        os.path.join(B, "02_TODAY_LOGS", "logs", "engine-live-current.txt")]
MET = os.path.join(B, "02_TODAY_LOGS", "logs", "metrics.json")
TH = Decimal("1.5")


def f(x, d=None):
    try:
        return float(x)
    except Exception:
        return d


def main():
    rows = []
    with open(DIAG, encoding="utf-8", errors="replace") as fh:
        for ln in fh:
            ln = ln.strip()
            if ln.startswith("{"):
                try:
                    rows.append(json.loads(ln))
                except Exception:
                    pass

    # ---------------- 12E/12F exact reconstruction ------------------------
    m = collections.Counter()
    detail = []
    for r in rows:
        lt = r.get("live_terms")
        if not isinstance(lt, dict) or lt.get("lookback_used") is None:
            continue
        lb = int(lt["lookback_used"])
        avg, psd = lt.get("avg_oi"), lt.get("per_strike_window_delta")
        rec = {}
        # win from per-strike raw state
        if isinstance(avg, dict) and isinstance(psd, dict):
            rec["win_ce"] = sum(psd[k] / avg[k] for k in psd
                                if k.endswith("|CE") and avg.get(k))
            rec["win_pe"] = sum(psd[k] / avg[k] for k in psd
                                if k.endswith("|PE") and avg.get(k))
            m["win_ce_mismatch"] += int(abs(rec["win_ce"]
                                            - f(lt["win_ce"], 0)) > 1e-9)
            m["win_pe_mismatch"] += int(abs(rec["win_pe"]
                                            - f(lt["win_pe"], 0)) > 1e-9)
        # z from persisted scalars
        zz = {}
        for side in ("pe", "ce"):
            mu, sd, win = (f(lt["mu_%s" % side]), f(lt["sd_%s" % side]),
                           f(lt["win_%s" % side]))
            zz[side] = (Decimal(0) if sd <= 0 else
                        Decimal(repr((win - mu * lb) / (sd * (lb ** 0.5)))))
            eng = f(lt["z_%s" % side])
            m["z_%s_mismatch" % side] += int(abs(float(zz[side]) - eng) > 1e-9)
        # branch conjunctions, exactly as at 2123-2128
        wp, wc = f(lt["win_pe"], 0), f(lt["win_ce"], 0)
        b1 = bool(zz["pe"] >= TH and zz["ce"] <= 0 and wp > 0)
        b2 = bool(zz["ce"] >= TH and zz["pe"] <= 0 and wc > 0)
        b3 = bool(zz["ce"] <= -TH and wc < 0 and lt.get("up_move")
                  and lt.get("ce_unwind_above_spot"))
        b4 = bool(zz["pe"] <= -TH and wp < 0 and lt.get("down_move")
                  and lt.get("pe_unwind_below_spot"))
        for k, v in (("B1", b1), ("B2", b2), ("B3", b3), ("B4", b4)):
            m["%s_mismatch" % k] += int(bool(lt.get(k)) != v)
        branch = ("B1_bullish_pe_writing" if b1 else
                  "B2_bearish_ce_writing" if b2 else
                  "B3_bullish_ce_unwinding" if b3 else
                  "B4_bearish_pe_unwinding" if b4 else "B5_fallthrough_neutral")
        verdict = ("bullish" if b1 or b3 else "bearish" if b2 or b4 else "neutral")
        m["branch_mismatch"] += int(branch != lt.get("branch"))
        m["verdict_mismatch"] += int(verdict != r.get("verdict_engine"))
        m["polls_tested"] += 1
        if branch != lt.get("branch") and len(detail) < 5:
            detail.append({"ts": r.get("ts"), "engine": lt.get("branch"),
                           "reconstructed": branch, "z_pe": str(zz["pe"]),
                           "z_ce": str(zz["ce"]), "win_pe": wp, "win_ce": wc})

    mism = sum(v for k, v in m.items() if k.endswith("_mismatch"))

    # ---------------- 12G/12M candidates ---------------------------------
    cands = [r for r in rows if r.get("event") == "oi_candidate"]
    cdates = collections.Counter(str(c.get("ts"))[:10] for c in cands)
    chas_lt = sum(1 for c in cands if isinstance(c.get("live_terms"), dict))
    cschema = collections.Counter(
        ("live_terms" if isinstance(c.get("live_terms"), dict) else
         "sess_style" if c.get("sess_pe") is not None else "unknown")
        for c in cands)
    ledger, block = [], collections.Counter()
    for c in cands:
        need = "bearish" if c.get("candidate_direction") == "LONG_PE" else "bullish"
        lt = c.get("live_terms") if isinstance(c.get("live_terms"), dict) else None
        src = lt or c
        zp, zc = f(src.get("z_pe")), f(src.get("z_ce"))
        wp = f(src.get("win_pe"), f(c.get("sess_pe")))
        wc = f(src.get("win_ce"), f(c.get("sess_ce")))
        fails = []
        if need == "bearish":
            if zc is None or zc < 1.5:
                fails.append("B2:z_ce<1.5")
            if zp is not None and zp > 0:
                fails.append("B2:z_pe>0")
            if wc is not None and wc <= 0:
                fails.append("B2:win_ce<=0")
            if zp is None or zp > -1.5:
                fails.append("B4:z_pe>-1.5")
            if wp is not None and wp >= 0:
                fails.append("B4:win_pe>=0")
            if lt is not None and not lt.get("down_move"):
                fails.append("B4:no_down_move")
            if lt is not None and not lt.get("pe_unwind_below_spot"):
                fails.append("B4:no_pe_unwind_below_spot")
        for x in fails:
            block[x] += 1
        ledger.append({"candidate_ts": c.get("candidate_ts"), "ts": c.get("ts"),
                       "direction": c.get("candidate_direction"),
                       "required_verdict": need,
                       "production_verdict": c.get("verdict_engine"),
                       "would_pass": c.get("directional_oi_would_pass"),
                       "branch": c.get("branch"),
                       "schema": "live_terms" if lt else "sess_style",
                       "z_pe": zp, "z_ce": zc, "win_pe": wp, "win_ce": wc,
                       "informative_obs": (lt or {}).get("informative_obs"),
                       "snapshots_len": c.get("snapshots_len"),
                       "blocking_operands": fails,
                       "counterfactual_A_admission": "NOT_COMPUTABLE",
                       "counterfactual_B_basket": "NOT_COMPUTABLE",
                       "counterfactual_C_expiry": "NOT_COMPUTABLE"})

    # non-candidate polls that DID reach bearish - negative control context
    bear = sum(1 for r in rows if r.get("verdict_engine") == "bearish")
    bull = sum(1 for r in rows if r.get("verdict_engine") == "bullish")

    # ---------------- today's runtime -------------------------------------
    met = json.load(open(MET, encoding="utf-8")) if os.path.exists(MET) else {}
    loglines = []
    for p in LOGS:
        if not os.path.exists(p):
            continue
        t = open(p, encoding="utf-8", errors="replace").read().splitlines()
        keep = [x for x in t if any(k in x.lower() for k in
                                    ("skip", "window", "candidate", "signal",
                                     "error", "warn", "start", "shutdown",
                                     "expiry", "reject"))]
        loglines.append({"file": os.path.basename(p), "lines": len(t),
                         "kept": len(keep), "sample": keep[:14] + keep[-6:]})

    rep = {"polls_tested": m["polls_tested"],
           "mismatches": {k: v for k, v in sorted(m.items())
                          if k.endswith("_mismatch")},
           "RECONSTRUCTION_MISMATCHES": mism,
           "RECONSTRUCTION_EXACT": mism == 0,
           "mismatch_examples": detail,
           "candidates": {"count": len(cands), "dates": dict(cdates),
                          "with_live_terms": chas_lt,
                          "schema_mix": dict(cschema),
                          "blocking_operand_frequency": dict(block)},
           "population_verdicts": {"bearish": bear, "bullish": bull,
                                   "rows": len(rows)},
           "today_runtime": {"metrics": met, "logs": loglines},
           "counterfactuals": {
               "A_per_strike_admission": "NOT_RUN",
               "B_symmetric_basket": "NOT_RUN",
               "C_expiry_predicate": "NOT_RUN",
               "reason": "each requires per-snapshot state that is not persisted: "
                         "A needs every retained snapshot's full strike list, B "
                         "needs OI for strikes outside the basket, C needs a "
                         "per-snapshot expiry tag. The bundle persists only the "
                         "three ATM legs per poll plus basket aggregates."}}
    json.dump(rep, open(os.path.join(PROJ, "TASK2_OI_RECONSTRUCTION_REPORT.json"),
                        "w", encoding="utf-8", newline="\n"), indent=1,
              default=str, sort_keys=True)
    json.dump({"generated_from": DIAG, "candidate_ledger": ledger},
              open(os.path.join(PROJ, "TASK2_COUNTERFACTUAL_LEDGER.json"), "w",
                   encoding="utf-8", newline="\n"), indent=1, default=str)

    print("== 12F EXACT RECONSTRUCTION GATE ==")
    print("polls_tested=%d" % m["polls_tested"])
    print("mismatches=%s" % json.dumps(rep["mismatches"]))
    print("RECONSTRUCTION_MISMATCHES=%d EXACT=%s" % (mism, mism == 0))
    for d in detail:
        print("  example: %s" % json.dumps(d))
    print("\n== 12G/12M CANDIDATES ==")
    print("count=%d dates=%s with_live_terms=%d schema=%s"
          % (len(cands), json.dumps(dict(cdates)), chas_lt,
             json.dumps(dict(cschema))))
    print("blocking operands=%s" % json.dumps(dict(block)))
    print("population verdicts: bearish=%d bullish=%d of %d rows"
          % (bear, bull, len(rows)))
    print("\n== TODAY'S RUNTIME ==")
    print("metrics=%s" % json.dumps(met))
    for l in loglines:
        print(" %s lines=%d kept=%d" % (l["file"], l["lines"], l["kept"]))
        for s in l["sample"]:
            print("   %s" % s[:170])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
