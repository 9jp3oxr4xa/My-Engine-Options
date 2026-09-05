# -*- coding: utf-8 -*-
"""TASK 2 / P4-P5 operand probe over the reconciled 190-row ledger."""
import collections
import json
import os
import statistics as st

R = r"C:\Users\Guest -A\Desktop\Dhan Test"
L = json.load(open(os.path.join(R, "TASK2_LEDGER.json"), encoding="utf-8"))["ledger"]

opp = [r for r in L if r["semantic_directional_oi"] == "false"]
ev = [r for r in L if r["stage"] == "evaluated"]
warm = [r for r in L if r["stage"] == "informative_obs_lt_11"]
nolt = [r for r in L if r["stage"] is None]
print("ledger %d | opposites %d | evaluated %d | warmup %d | no_live_terms %d"
      % (len(L), len(opp), len(ev), len(warm), len(nolt)))

print("--- 25 OPPOSITES (all B3_bullish_ce_unwinding on LONG_PE) ---")
print("dates          ", dict(collections.Counter(r["candidate_ts"][:10] for r in opp)))
print("z_ce min/max   ", min(r["z_ce"] for r in opp), max(r["z_ce"] for r in opp))
print("z_pe min/max   ", min(r["z_pe"] for r in opp), max(r["z_pe"] for r in opp))
print("win_ce<0 all   ", all(r["win_ce"] < 0 for r in opp))
print("up_move all    ", all(r["up_move"] for r in opp),
      "| ce_unwind_above_spot all", all(r["ce_unwind_above_spot"] for r in opp))
print("B4 also true   ", sum(1 for r in opp if r["B4"]["fired"]))
print("B4 blockers    ", dict(collections.Counter(
    r["B4"]["first_blocking_operand"] for r in opp)))
for o in opp[:3]:
    print("  %s %s spot=%s atm=%s basket=%s" % (o["candidate_id"], o["candidate_ts"],
          o["spot"], o["atm"], o["basket_used_by_engine"]))
    print("     z_ce=%.3f win_ce=%s | z_pe=%.3f win_pe=%s | spot %s -> %s"
          % (o["z_ce"], o["win_ce"], o["z_pe"], o["win_pe"],
             o["spot_window_start"], o["spot_now"]))
    print("     per_strike_window_delta", json.dumps(o["per_strike_window_delta"]))

print("--- B4 blocked by win_pe>=0 although z_pe<=-1.5 ---")
c = [r for r in ev if r["z_pe"] is not None and r["z_pe"] <= -1.5
     and (r["win_pe"] or 0) >= 0]
print("count", len(c))
for r in c[:4]:
    print("   %s z_pe=%.3f win_pe=%s mu_pe=%s sd_pe=%s lookback=%s"
          % (r["candidate_id"], r["z_pe"], r["win_pe"], r["mu_pe"], r["sd_pe"],
             r["lookback_used"]))

print("--- evaluated neutrals: distance from thresholds ---")
n = [r for r in ev if r["semantic_directional_oi"] == "neutral"]
if n:
    print("n=%d  |z_pe| med %.3f max %.3f | |z_ce| med %.3f max %.3f"
          % (len(n), st.median(abs(r["z_pe"]) for r in n),
             max(abs(r["z_pe"]) for r in n), st.median(abs(r["z_ce"]) for r in n),
             max(abs(r["z_ce"]) for r in n)))
    print("direction mix", dict(collections.Counter(r["direction"] for r in n)))
    print("z_ce==0 exactly", sum(1 for r in n if r["z_ce"] == 0),
          "| z_pe==0 exactly", sum(1 for r in n if r["z_pe"] == 0))
    print("sd_ce==0", sum(1 for r in n if float(r["sd_ce"] or 0) == 0),
          "| sd_pe==0", sum(1 for r in n if float(r["sd_pe"] or 0) == 0))
    print("basket sizes", dict(collections.Counter(
        len(r["basket_used_by_engine"] or []) for r in n)))
    print("atm_vs_spot: atm>spot %d, atm==spot %d, atm<spot %d" % (
        sum(1 for r in n if float(r["atm"]) > float(r["spot"])),
        sum(1 for r in n if float(r["atm"]) == float(r["spot"])),
        sum(1 for r in n if float(r["atm"]) < float(r["spot"]))))

print("--- warmup rows (ladder never reached) ---")
print("dates", dict(collections.Counter(r["candidate_ts"][:10] for r in warm)))
print("informative_obs", dict(collections.Counter(r["informative_obs"] for r in warm)))
print("snapshots_len", dict(collections.Counter(r["snapshots_len"] for r in warm)))
print("duplicates_dropped", dict(collections.Counter(
    r["duplicates_dropped"] for r in warm)))

print("--- rows without live_terms (pre-instrumentation) ---")
print("dates", dict(collections.Counter(r["candidate_ts"][:10] for r in nolt)))
print("branch", dict(collections.Counter(r["branch"] for r in nolt)))
print("top-level z present", sum(1 for r in nolt if r["z_pe"] is not None),
      "| win present", sum(1 for r in nolt if r["win_pe"] is not None))
print("verdicts", dict(collections.Counter(r["verdict_engine"] for r in nolt)))
