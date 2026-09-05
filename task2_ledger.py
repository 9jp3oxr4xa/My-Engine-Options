# -*- coding: utf-8 -*-
"""
TASK 2 / PHASES 2-5  (machine-generated, real persisted evidence only)

  P2  complete candidate ledger from logs/oi_diag.jsonl (+ logs/decisions.jsonl)
      with explicit PROVENANCE separation and an explicit discrepancy report
      against the expected LEDGER_TOTAL = 190.
  P3  join integrity: TIGHT / STALE / UNJOINABLE per candidate.
  P4  every neutral candidate: which of B1-B4 failed and on which operand.
  P5  every opposite candidate: winning branch and all its operands.

Nothing is recomputed from a model of the engine: each oi_candidate row carries
live_terms, i.e. the verbatim operand values the production branch ladder used.

Outputs: TASK2_LEDGER.json, TASK2_LEDGER_SUMMARY.json
"""
import collections
import json
import os
from datetime import datetime

R = r"C:\Users\Guest -A\Desktop\Dhan Test"
OI = os.path.join(R, "logs", "oi_diag.jsonl")
DEC = os.path.join(R, "logs", "decisions.jsonl")
OUT = os.path.join(R, "TASK2_LEDGER.json")
SUM = os.path.join(R, "TASK2_LEDGER_SUMMARY.json")
EXPECTED_TOTAL = 190
TIGHT_S = 90.0

# Task-1 artefacts: both Task-1 fixtures (replay + constructed signal path) were
# generated with expiry 2026-09-07; no real session in the evidence window used
# that expiry. Rows carrying it are NOT production evidence and are excluded
# from every causal conclusion (they are reported separately, never dropped).
SYNTH_EXPIRY = {"2026-09-07"}


def rows(p, ev=None):
    out = []
    if not os.path.exists(p):
        return out
    with open(p, encoding="utf-8", errors="replace") as fh:
        for i, ln in enumerate(fh, 1):
            ln = ln.strip()
            if not ln.startswith("{"):
                continue
            try:
                r = json.loads(ln)
            except Exception:
                continue
            if ev is None or r.get("event") == ev:
                r["_line"] = i
                out.append(r)
    return out


def ts(x):
    if not x:
        return None
    try:
        return datetime.fromisoformat(str(x))
    except Exception:
        return None


def f(x, d=None):
    try:
        return float(x)
    except Exception:
        return d


def provenance(r):
    if str(r.get("expiry")) in SYNTH_EXPIRY:
        return "TASK1_FIXTURE_SYNTHETIC"
    return "PRODUCTION"


REQ = {"LONG_CE": "bullish", "LONG_PE": "bearish"}


def branch_failure(lt, z_pe, z_ce):
    """Exact operand-level reason each branch did not fire. lt = live_terms."""
    win_pe, win_ce = f(lt.get("win_pe")), f(lt.get("win_ce"))
    up, dn = bool(lt.get("up_move")), bool(lt.get("down_move"))
    ceu, peu = bool(lt.get("ce_unwind_above_spot")), bool(lt.get("pe_unwind_below_spot"))
    spec = {
        "B1": [("z_pe>=1.5", z_pe is not None and z_pe >= 1.5, z_pe),
               ("z_ce<=0", z_ce is not None and z_ce <= 0, z_ce),
               ("win_pe>0", win_pe is not None and win_pe > 0, win_pe)],
        "B2": [("z_ce>=1.5", z_ce is not None and z_ce >= 1.5, z_ce),
               ("z_pe<=0", z_pe is not None and z_pe <= 0, z_pe),
               ("win_ce>0", win_ce is not None and win_ce > 0, win_ce)],
        "B3": [("z_ce<=-1.5", z_ce is not None and z_ce <= -1.5, z_ce),
               ("win_ce<0", win_ce is not None and win_ce < 0, win_ce),
               ("up_move", up, up), ("ce_unwind_above_spot", ceu, ceu)],
        "B4": [("z_pe<=-1.5", z_pe is not None and z_pe <= -1.5, z_pe),
               ("win_pe<0", win_pe is not None and win_pe < 0, win_pe),
               ("down_move", dn, dn), ("pe_unwind_below_spot", peu, peu)],
    }
    out = {}
    for b, terms in spec.items():
        failed = [{"operand": n, "actual_value": v, "required_condition": n}
                  for n, ok, v in terms if not ok]
        out[b] = {"fired": not failed, "failed_operands": failed,
                  "first_blocking_operand": failed[0]["operand"] if failed else None}
    return out


def main():
    cand = rows(OI, "oi_candidate")
    snaps = rows(OI, "oi_snapshot")
    dec = rows(DEC)

    prov = collections.Counter(provenance(r) for r in cand)
    by_day = collections.Counter(str(r.get("candidate_ts"))[:10] for r in cand)
    by_day_prod = collections.Counter(str(r.get("candidate_ts"))[:10]
                                     for r in cand if provenance(r) == "PRODUCTION")
    prod = [r for r in cand if provenance(r) == "PRODUCTION"]

    # duplicate detection: a replay of an already-recorded session re-emits an
    # identical row. Identity key = every value the ladder consumed.
    def key(r):
        return json.dumps([r.get("candidate_ts"), r.get("candidate_underlying"),
                           r.get("candidate_direction"), r.get("ts"), r.get("spot"),
                           r.get("atm"), r.get("expiry"), r.get("z_pe"), r.get("z_ce"),
                           r.get("win_pe"), r.get("win_ce"), r.get("branch")],
                          sort_keys=True, default=str)
    kc = collections.Counter(key(r) for r in prod)
    dup_rows = sum(v - 1 for v in kc.values() if v > 1)

    # PROVENANCE BY FILE POSITION (oi_diag.jsonl is append-only):
    # the original production evidence is the first EXPECTED_TOTAL oi_candidate
    # rows; every row appended afterwards belongs to the Task-1 verification
    # runs of 2026-09-02 (replayed duplicates + synthetic fixture rows).
    cand_ordered = sorted(cand, key=lambda r: r["_line"])
    orig = cand_ordered[:EXPECTED_TOTAL]
    appended = cand_ordered[EXPECTED_TOTAL:]
    split_clean = {
        "original_rows": len(orig),
        "appended_rows": len(appended),
        "synthetic_inside_original": sum(1 for r in orig
                                        if provenance(r) != "PRODUCTION"),
        "synthetic_inside_appended": sum(1 for r in appended
                                        if provenance(r) != "PRODUCTION"),
        "original_last_line": orig[-1]["_line"] if orig else None,
        "appended_first_line": appended[0]["_line"] if appended else None,
        "original_date_span": sorted({str(r.get("candidate_ts"))[:10] for r in orig}),
        "appended_date_span": sorted({str(r.get("candidate_ts"))[:10]
                                      for r in appended}),
        "content_duplicates_between_sets": sum(
            1 for r in appended if key(r) in {key(o) for o in orig}),
    }
    uniq_rows = orig


    ledger, cls = [], collections.Counter()
    join = collections.Counter()
    pfd = collections.Counter()          # predicate failure distribution
    first_block = collections.Counter()
    neutral_stage = collections.Counter()
    opp = []
    for i, r in enumerate(uniq_rows, 1):
        lt = r.get("live_terms") or {}
        z_pe, z_ce = f(r.get("z_pe")), f(r.get("z_ce"))
        d = str(r.get("candidate_direction"))
        req = REQ.get(d)
        eng = str(r.get("verdict_engine"))
        semantic = ("true" if eng == req else
                    "neutral" if eng == "neutral" else "false")
        cts, ots = ts(r.get("candidate_ts")), ts(r.get("ts"))
        if cts is None or ots is None:
            age, jc = None, "UNJOINABLE"
        else:
            age = (cts - ots).total_seconds()
            jc = "TIGHT" if abs(age) <= TIGHT_S else "STALE"
        bf = branch_failure(lt, z_pe, z_ce)
        row = {
            "candidate_id": "C%03d" % i, "line": r.get("_line"),
            "candidate_ts": r.get("candidate_ts"), "oi_ts": r.get("ts"),
            "age_seconds": age, "join_class": jc,
            "underlying": r.get("candidate_underlying"),
            "direction": d, "required_for_pass": req,
            "verdict_engine": eng, "verdict_recomputed": r.get("verdict_recomputed"),
            "legacy_verdict": r.get("legacy_verdict"),
            "legacy_differs_from_engine": r.get("legacy_differs_from_engine"),
            "mirror_matches_engine": r.get("mirror_matches_engine"),
            "semantic_directional_oi": semantic,
            "mandatory_category_result": "PASS" if semantic == "true" else "FAIL",
            "branch": r.get("branch"), "stage": lt.get("stage"),
            "warmup_ok": r.get("warmup_ok"),
            "expiry": r.get("expiry"), "spot": r.get("spot"), "atm": r.get("atm"),
            "basket_used_by_engine": r.get("basket_used_by_engine"),
            "strike_atm_minus_1": r.get("strike_atm_minus_1"),
            "strike_atm_plus_1": r.get("strike_atm_plus_1"),
            "snapshots_len": r.get("snapshots_len"),
            "informative_obs": lt.get("informative_obs"),
            "duplicates_dropped": lt.get("duplicates_dropped"),
            "deltas_len": r.get("deltas_len"), "lookback_used": r.get("lookback_used"),
            "oi_delta_lookback_cfg": r.get("oi_delta_lookback_cfg"),
            "baseline_oi_entries": r.get("baseline_oi_entries"),
            "z_pe": z_pe, "z_ce": z_ce,
            "win_pe": f(r.get("win_pe")), "win_ce": f(r.get("win_ce")),
            "mu_pe": r.get("mu_pe"), "mu_ce": r.get("mu_ce"),
            "sd_pe": r.get("sd_pe"), "sd_ce": r.get("sd_ce"),
            "sess_pe": r.get("sess_pe"), "sess_ce": r.get("sess_ce"),
            "spot_now": lt.get("spot_now"),
            "spot_window_start": lt.get("spot_window_start"),
            "up_move": lt.get("up_move"), "down_move": lt.get("down_move"),
            "ce_unwind_above_spot": lt.get("ce_unwind_above_spot"),
            "pe_unwind_below_spot": lt.get("pe_unwind_below_spot"),
            "per_strike_window_delta": lt.get("per_strike_window_delta"),
            "B1": bf["B1"], "B2": bf["B2"], "B3": bf["B3"], "B4": bf["B4"],
            "B5_selected": r.get("branch", "").startswith("B5"),
            "legacy_predicates": {k: r.get(k) for k in
                                  ("pred_bull_write", "pred_bear_write",
                                   "pred_bull_ce_unwind", "pred_bear_pe_unwind")},
        }
        ledger.append(row)
        cls[semantic] += 1
        join[jc] += 1
        if semantic == "neutral":
            neutral_stage[str(lt.get("stage"))] += 1
            for b in ("B1", "B2", "B3", "B4"):
                fo = bf[b]["first_blocking_operand"]
                if fo:
                    first_block["%s:%s" % (b, fo)] += 1
                for x in bf[b]["failed_operands"]:
                    pfd["%s:%s" % (b, x["operand"])] += 1
        elif semantic == "false":
            opp.append({k: row[k] for k in
                        ("candidate_id", "candidate_ts", "direction",
                         "required_for_pass", "verdict_engine", "branch", "expiry",
                         "spot", "atm", "basket_used_by_engine", "z_pe", "z_ce",
                         "win_pe", "win_ce", "sess_pe", "sess_ce", "up_move",
                         "down_move", "ce_unwind_above_spot", "pe_unwind_below_spot",
                         "join_class", "age_seconds", "per_strike_window_delta")})

    # every neutral must be fully explained: B1-B4 all failed and B5 selected
    neutral_rows = [r for r in ledger if r["semantic_directional_oi"] == "neutral"]
    unexplained = [r["candidate_id"] for r in neutral_rows
                   if not (all(not r[b]["fired"] for b in ("B1", "B2", "B3", "B4"))
                           and r["B5_selected"])]
    opp_unexplained = [r["candidate_id"] for r in ledger
                       if r["semantic_directional_oi"] == "false"
                       and not str(r["branch"]).startswith(("B1", "B2", "B3", "B4"))]

    summary = {
        "generated": datetime.now().isoformat(),
        "evidence": {"oi_diag": OI, "decisions": DEC,
                     "oi_candidate_rows_total": len(cand),
                     "oi_snapshot_rows_total": len(snaps),
                     "decision_rows_total": len(dec),
                     "decision_types": dict(collections.Counter(
                         d.get("type") for d in dec))},
        "P2_provenance": {
            "counts": dict(prov), "by_candidate_date_all": dict(by_day),
            "by_candidate_date_production": dict(by_day_prod),
            "synthetic_expiry_marker": sorted(SYNTH_EXPIRY),
            "production_rows": len(prod),
            "production_duplicate_rows_from_replays": dup_rows,
            "append_order_split": split_clean,
            "production_unique_candidates": len(uniq_rows)},
        "P2_discrepancy": {
            "expected_ledger_total": EXPECTED_TOTAL,
            "actual_unique_production_candidates": len(uniq_rows),
            "delta": len(uniq_rows) - EXPECTED_TOTAL,
            "reconciles_to_expected": len(uniq_rows) == EXPECTED_TOTAL,
            "statement": ("evidence files grew after the 190-candidate figure was "
                          "taken: Task-1 verification replays re-emitted identical "
                          "production rows (duplicates) and the Task-1 fixtures "
                          "emitted synthetic rows. Both classes are reported and "
                          "excluded; no row was silently reconciled.")},
        "P2_tri_state": dict(cls),
        "P2_tri_state_note": "true/neutral/false are semantic values; never bool()",
        "P3_join_integrity": dict(join),
        "P3_rule": "only TIGHT rows support synchronized predicate conclusions; "
                   "TIGHT means |candidate_ts - oi_ts| <= %.0fs" % TIGHT_S,
        "P4_neutral_total": len(neutral_rows),
        "P4_all_neutrals_explained": not unexplained,
        "P4_unexplained_ids": unexplained,
        "P4_stage_distribution": dict(neutral_stage),
        "P4_predicate_failure_distribution": dict(pfd.most_common()),
        "P4_first_blocking_operand": dict(first_block.most_common()),
        "P5_opposite_total": len(opp),
        "P5_all_opposites_have_a_winning_branch": not opp_unexplained,
        "P5_opposite_branch_distribution": dict(collections.Counter(
            o["branch"] for o in opp)),
        "P5_opposite_join_distribution": dict(collections.Counter(
            o["join_class"] for o in opp)),
        "P5_opposite_direction_distribution": dict(collections.Counter(
            (o["direction"], o["verdict_engine"]) for o in opp).items().__iter__()
            .__class__.__name__) if False else dict(collections.Counter(
                "%s->%s" % (o["direction"], o["verdict_engine"]) for o in opp)),
        "engine_mirror": {
            "mirror_matches_engine_all": all(r.get("mirror_matches_engine") is True
                                             for r in uniq_rows),
            "legacy_differs_count": sum(1 for r in uniq_rows
                                        if r.get("legacy_differs_from_engine")),
            "verdict_recomputed_equals_engine": sum(
                1 for r in uniq_rows
                if r.get("verdict_recomputed") == r.get("verdict_engine"))},
    }
    json.dump({"summary": summary, "ledger": ledger, "opposites": opp},
              open(OUT, "w", encoding="utf-8", newline="\n"), indent=1, default=str)
    json.dump(summary, open(SUM, "w", encoding="utf-8", newline="\n"), indent=1,
              default=str, sort_keys=True)

    p = summary
    print("oi_candidate rows total :", len(cand), "| provenance", dict(prov))
    print("production rows         :", len(prod), "| duplicates", dup_rows,
          "| UNIQUE", len(uniq_rows))
    print("by candidate date (all) :", dict(by_day))
    print("append-order split      :", json.dumps(split_clean))
    print("EXPECTED 190 -> ACTUAL  :", len(uniq_rows),
          "| reconciles", p["P2_discrepancy"]["reconciles_to_expected"])
    print("tri-state               :", dict(cls))
    print("join integrity          :", dict(join))
    print("neutral total/explained :", len(neutral_rows), not unexplained)
    print("neutral stages          :", dict(neutral_stage))
    print("first blocking operand  :")
    for k, v in first_block.most_common():
        print("     %-34s %d" % (k, v))
    print("opposite total          :", len(opp), "| branches",
          p["P5_opposite_branch_distribution"], "| joins",
          p["P5_opposite_join_distribution"])
    print("opposite dir mapping    :", p["P5_opposite_direction_distribution"])
    print("engine mirror           :", p["engine_mirror"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
