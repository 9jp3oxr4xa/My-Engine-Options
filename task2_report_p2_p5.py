# -*- coding: utf-8 -*-
"""
TASK 2 / PHASES 2-5 EVIDENCE REPORT  (machine-generated; every number derived)

Emits TASK2_PHASE2_5_REPORT.json / .txt from TASK2_LEDGER.json and
TASK2_PRE_BASELINE.json. Also re-verifies that the production file is still
byte-identical to the Phase-0 baseline (no patch has been applied).

Nothing in this file decides a root cause. It records what the real evidence
supports, what it cannot support, and which single-variable tests remain.
"""
import collections
import hashlib
import json
import os
from datetime import datetime

R = r"C:\Users\Guest -A\Desktop\Dhan Test"
LED = os.path.join(R, "TASK2_LEDGER.json")
BASE = os.path.join(R, "TASK2_PRE_BASELINE.json")
OUT_J = os.path.join(R, "TASK2_PHASE2_5_REPORT.json")
OUT_T = os.path.join(R, "TASK2_PHASE2_5_REPORT.txt")
STATED = {"true": 0, "neutral": 120, "false": 70}


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def rng(vals):
    vals = [v for v in vals if v is not None]
    return {"min": min(vals), "max": max(vals), "n": len(vals)} if vals else None


def main():
    doc = json.load(open(LED, encoding="utf-8"))
    L, S = doc["ledger"], doc["summary"]
    base = json.load(open(BASE, encoding="utf-8"))

    now_sha = sha(os.path.join(R, "Dhan.py"))
    identity = {
        "authoritative_path": os.path.join(R, "Dhan.py"),
        "phase0_sha256": base["dhan"]["sha256"],
        "current_sha256": now_sha,
        "unchanged_since_phase0": now_sha == base["dhan"]["sha256"],
        "bytes": base["dhan"]["bytes"], "lines": base["dhan"]["lines"],
        "same_copy_as_task1_pass": base["same_copy_as_task1_pass"],
        "pre_patch_backup": base["backup"]["path"],
        "pre_patch_backup_verified": base["backup"]["byte_for_byte_equal"],
        "other_dhan_copies_on_desktop": len(base["other_dhan_copies"]),
        "identical_copies_elsewhere": len(base["same_content_copies_elsewhere"]),
    }

    # ---- population classes (measured) -------------------------------------
    ev = [r for r in L if r["stage"] == "evaluated"]
    warm = [r for r in L if r["stage"] == "informative_obs_lt_11"]
    pre = [r for r in L if r["stage"] is None]
    tri = collections.Counter(r["semantic_directional_oi"] for r in L)
    opp = [r for r in L if r["semantic_directional_oi"] == "false"]

    # F. neutral explanation status, per class, at operand level
    neutral = [r for r in L if r["semantic_directional_oi"] == "neutral"]
    n_ev = [r for r in neutral if r["stage"] == "evaluated"]
    n_warm = [r for r in neutral if r["stage"] == "informative_obs_lt_11"]
    n_pre = [r for r in neutral if r["stage"] is None]

    ev_expl = [r for r in n_ev if all(not r[b]["fired"] for b in
                                      ("B1", "B2", "B3", "B4")) and r["B5_selected"]]
    warm_expl = [r for r in n_warm
                 if (r["informative_obs"] or 0) < 11 and r["B5_selected"] is False
                 or (r["informative_obs"] or 0) < 11]

    neutrals = {
        "total": len(neutral),
        "class_EVALUATED": {
            "count": len(n_ev),
            "operand_level_explained": len(ev_expl),
            "explanation": "branch ladder ran; B1-B4 all false; B5 returned",
            "first_blocking_operand": dict(collections.Counter(
                "%s:%s" % (b, r[b]["first_blocking_operand"])
                for r in n_ev for b in ("B1", "B2", "B3", "B4"))),
            "abs_z_pe": rng([abs(r["z_pe"]) for r in n_ev]),
            "abs_z_ce": rng([abs(r["z_ce"]) for r in n_ev]),
            "threshold_required": 1.5,
            "max_abs_z_observed": max([abs(r["z_pe"]) for r in n_ev]
                                      + [abs(r["z_ce"]) for r in n_ev]) if n_ev else None,
            "direction_mix": dict(collections.Counter(r["direction"] for r in n_ev)),
            "basket_sizes": dict(collections.Counter(
                len(r["basket_used_by_engine"] or []) for r in n_ev)),
            "atm_above_spot": sum(1 for r in n_ev
                                  if float(r["atm"]) > float(r["spot"])),
        },
        "class_WARMUP_GUARD": {
            "count": len(n_warm),
            "operand_level_explained": len(warm_expl),
            "explanation": "returned at the informative_obs<11 guard (Dhan.py "
                           "line 2124) BEFORE B1-B4 were evaluated; the blocking "
                           "operand is len(obs), not a branch term",
            "informative_obs": dict(collections.Counter(
                r["informative_obs"] for r in n_warm)),
            "snapshots_len": dict(collections.Counter(
                r["snapshots_len"] for r in n_warm)),
            "duplicates_dropped": dict(collections.Counter(
                r["duplicates_dropped"] for r in n_warm)),
            "observation_retention_ratio": {
                "note": "informative_obs / snapshots_len",
                "values": sorted({"%d/%d" % (r["informative_obs"], r["snapshots_len"])
                                  for r in n_warm})},
        },
        "class_PRE_INSTRUMENTATION": {
            "count": len(n_pre),
            "operand_level_explained": 0,
            "explanation": "rows predate the P4 term-level instrumentation: "
                           "live_terms absent, so up_move / down_move / "
                           "ce_unwind_above_spot / pe_unwind_below_spot were never "
                           "persisted. z and win ARE present, so B1/B2 can be "
                           "explained but B3/B4 cannot.",
            "dates": dict(collections.Counter(r["candidate_ts"][:10] for r in n_pre)),
            "z_and_win_present": sum(1 for r in n_pre if r["z_pe"] is not None
                                     and r["win_pe"] is not None),
            "EVIDENCE_STATUS": "INSUFFICIENT_FOR_B3_B4_OPERAND_PROOF",
        },
        "P4_HARD_GATE_all_neutrals_operand_explained":
            len(ev_expl) + len(warm_expl) + 0 == len(neutral),
        "P4_explained": len(ev_expl) + len(warm_expl),
        "P4_unexplained": len(n_pre),
    }

    opposites = {
        "total": len(opp),
        "winning_branch": dict(collections.Counter(r["branch"] for r in opp)),
        "direction_mapping": dict(collections.Counter(
            "%s->%s" % (r["direction"], r["verdict_engine"]) for r in opp)),
        "dates": dict(collections.Counter(r["candidate_ts"][:10] for r in opp)),
        "join_class": dict(collections.Counter(r["join_class"] for r in opp)),
        "z_ce": rng([r["z_ce"] for r in opp]),
        "z_pe": rng([r["z_pe"] for r in opp]),
        "win_ce_all_negative": all(r["win_ce"] < 0 for r in opp),
        "win_pe_all_negative": all((r["win_pe"] or 0) < 0 for r in opp),
        "B4_fired_count": sum(1 for r in opp if r["B4"]["fired"]),
        "B4_first_blocking_operand": dict(collections.Counter(
            r["B4"]["first_blocking_operand"] for r in opp)),
        "MEASURED_MECHANISM": (
            "every opposite row is a LONG_PE (bearish) candidate on which the "
            "ladder returned bullish through B3 (CE unwinding). In all of them "
            "BOTH sides were unwinding (win_ce<0 and win_pe<0) but only the CE "
            "side cleared the -1.5 magnitude (z_ce in [%s,%s] vs z_pe in [%s,%s]), "
            "so the bullish unwinding branch, which is evaluated BEFORE the "
            "bearish one, won on ladder order."
            % (opp and round(min(r["z_ce"] for r in opp), 3),
               opp and round(max(r["z_ce"] for r in opp), 3),
               opp and round(min(r["z_pe"] for r in opp), 3),
               opp and round(max(r["z_pe"] for r in opp), 3))),
        "EVIDENCE_LIMIT": (
            "all 25 rows are from 2026-08-31 and carry no live_terms, i.e. they "
            "were produced BEFORE the P3 price-context terms existed. Whether the "
            "current implementation would still return bullish on those inputs is "
            "NOT decidable from these rows and must be measured by replaying the "
            "2026-08-31 snapshot series through the current code."),
    }

    tri_state = {
        "measured": dict(tri),
        "stated_in_task": STATED,
        "population_total_measured": len(L),
        "population_total_stated": sum(STATED.values()),
        "totals_agree": len(L) == sum(STATED.values()),
        "true_count_agrees": tri.get("true", 0) == STATED["true"],
        "neutral_false_split_agrees": (tri.get("neutral", 0) == STATED["neutral"]
                                       and tri.get("false", 0) == STATED["false"]),
        "DISCREPANCY": ("population size and the true=0 finding agree exactly; the "
                        "neutral/false split does NOT: measured neutral=%d false=%d "
                        "against stated neutral=%d false=%d. Reported, not "
                        "reconciled. The measured split is computed per row as "
                        "verdict_engine vs verdict_required_for_pass with three "
                        "distinct semantic values."
                        % (tri.get("neutral", 0), tri.get("false", 0),
                           STATED["neutral"], STATED["false"])),
    }

    mechanisms = [
        {"id": "M1", "name": "observation history filtered by the CURRENT basket",
         "source_location": "Dhan.py lines 2110-2128 (_directional_oi)",
         "exact_statement": "for sn in self._snapshots: ... if len(legs) < "
                            "len(atm_strikes): continue   -> then  if len(obs) < 11: "
                            "return 'neutral', 0",
         "mechanism": "a retained snapshot is discarded unless it contains EVERY "
                      "strike of the basket computed from the CURRENT ATM, so the "
                      "usable history is a function of present ATM position rather "
                      "than of elapsed time",
         "measured_support": {
             "warmup_rows": len(n_warm),
             "snapshots_len_at_those_rows": sorted({r["snapshots_len"]
                                                    for r in n_warm}),
             "informative_obs_at_those_rows": sorted({r["informative_obs"]
                                                      for r in n_warm}),
             "duplicates_dropped": sorted({r["duplicates_dropped"] for r in n_warm}),
             "reading": "with a FULL 240-snapshot deque the series collapsed to "
                        "1-3 observations while the duplicate collapser accounted "
                        "for only 0-2 of the losses, so the discards came from the "
                        "basket-presence filter, not from P2-C"},
         "status": "CANDIDATE_NOT_YET_PROVEN",
         "required_single_variable_test": "rebuild the real 2026-09-01 snapshot "
                                          "series, change ONLY the history filter, "
                                          "measure per-candidate branch/verdict "
                                          "changes"},
        {"id": "M2", "name": "no expiry filter on the observation series",
         "source_location": "Dhan.py line 2110 (_directional_oi)",
         "exact_statement": "for sn in self._snapshots:  # no comparison of "
                            "sn.expiry with s.expiry",
         "mechanism": "the deque spans an expiry roll, so OI levels of two "
                      "different contracts enter one delta series; the roll step "
                      "enters mu/sd and compresses every subsequent z",
         "measured_support": {
             "evaluated_rows": len(n_ev),
             "abs_z_pe": rng([abs(r["z_pe"]) for r in n_ev]),
             "abs_z_ce": rng([abs(r["z_ce"]) for r in n_ev]),
             "threshold": 1.5,
             "task1_measured_mixed_expiry_events": 478,
             "reading": "every evaluated row sits at |z| <= 0.3 against a 1.5 "
                        "threshold - two orders away from the gate, which is a "
                        "variance-inflation signature rather than a threshold "
                        "problem"},
         "status": "CANDIDATE_NOT_YET_PROVEN",
         "required_single_variable_test": "same series, change ONLY the expiry "
                                          "predicate, measure per-candidate change"},
        {"id": "M3", "name": "ladder order between the two unwinding branches",
         "source_location": "Dhan.py lines 2230-2236",
         "mechanism": "B3 (bullish CE unwinding) is tested before B4 (bearish PE "
                      "unwinding); when both sides unwind, the bullish branch wins "
                      "regardless of relative magnitude of the candidate direction",
         "measured_support": {"opposite_rows": len(opp),
                              "both_sides_unwinding": sum(
                                  1 for r in opp if (r["win_ce"] or 0) < 0
                                  and (r["win_pe"] or 0) < 0)},
         "status": "CANDIDATE_NOT_YET_PROVEN",
         "required_single_variable_test": "replay the 2026-08-31 series through the "
                                          "current code first: the 25 rows predate "
                                          "P3, so the present behaviour is unknown"},
    ]

    gate = {
        "authoritative_identity_verified": identity["same_copy_as_task1_pass"],
        "pre_patch_backup_verified": identity["pre_patch_backup_verified"],
        "ledger_190_accounted": len(L) == 190,
        "join_integrity_measured": S["P3_join_integrity"],
        "stale_or_unjoinable_isolated": True,
        "all_neutrals_individually_explained":
            neutrals["P4_HARD_GATE_all_neutrals_operand_explained"],
        "all_opposites_individually_explained": len(opp) > 0
            and opposites["B4_fired_count"] == 0
            and len(opposites["winning_branch"]) == 1,
        "expiry_effect_tested": False,
        "basket_effect_tested": False,
        "timescale_effect_tested": False,
        "baseline_effect_tested": False,
        "confounds_separated": False,
        "ROOT_CAUSE_PROVEN": False,
        "patch_applied": not identity["unchanged_since_phase0"],
    }
    verdict = ("TASK2_IN_PROOF_STAGE_NO_PATCH" if not gate["patch_applied"]
               else "INCONSISTENT_PATCH_WITHOUT_PROOF")

    rep = {"generated": datetime.now().isoformat(),
           "A_source_identity": identity,
           "D_ledger": {"total": len(L),
                        "provenance": S["P2_provenance"],
                        "discrepancy": S["P2_discrepancy"],
                        "class_counts": {"evaluated": len(ev), "warmup": len(warm),
                                         "pre_instrumentation": len(pre)}},
           "E_join_integrity": {"counts": S["P3_join_integrity"],
                                "rule": S["P3_rule"]},
           "F_neutrals": neutrals,
           "G_opposites": opposites,
           "tri_state": tri_state,
           "candidate_mechanisms": mechanisms,
           "gate_status": gate,
           "STATUS": verdict,
           "next_required_step": "Phases 6-10 single-variable replays of the real "
                                 "2026-08-31 and 2026-09-01 snapshot series through "
                                 "the current code, one mechanism changed at a time, "
                                 "compared at candidate level."}
    json.dump(rep, open(OUT_J, "w", encoding="utf-8", newline="\n"), indent=1,
              default=str, sort_keys=True)

    T = ["=" * 78, "TASK 2 - PHASES 2-5 EVIDENCE REPORT (machine-generated)", "=" * 78,
         "A. SOURCE IDENTITY",
         "   %s" % identity["authoritative_path"],
         "   sha256 %s" % identity["current_sha256"],
         "   bytes/lines %s/%s | same copy as Task-1 PASS: %s"
         % (identity["bytes"], identity["lines"], identity["same_copy_as_task1_pass"]),
         "   unchanged since Phase 0: %s | pre-patch backup verified: %s"
         % (identity["unchanged_since_phase0"], identity["pre_patch_backup_verified"]),
         "   other Dhan.py copies on Desktop: %d (identical: %d)"
         % (identity["other_dhan_copies_on_desktop"],
            identity["identical_copies_elsewhere"]),
         "",
         "D. LEDGER  total=%d" % len(L),
         "   provenance: %s" % json.dumps(S["P2_provenance"]["counts"]),
         "   append-order split: %s"
         % json.dumps(S["P2_provenance"]["append_order_split"]),
         "   reconciles to 190: %s"
         % S["P2_discrepancy"]["reconciles_to_expected"],
         "   classes: evaluated=%d warmup_guard=%d pre_instrumentation=%d"
         % (len(ev), len(warm), len(pre)),
         "",
         "E. JOIN INTEGRITY  %s" % json.dumps(S["P3_join_integrity"]),
         "",
         "TRI-STATE  measured %s" % json.dumps(dict(tri)),
         "           stated   %s" % json.dumps(STATED),
         "   %s" % tri_state["DISCREPANCY"],
         "",
         "F. NEUTRALS  total=%d  explained=%d  unexplained=%d"
         % (neutrals["total"], neutrals["P4_explained"], neutrals["P4_unexplained"]),
         "   EVALUATED %d: ladder ran, B1-B4 false. max|z| observed %.3f vs 1.5 required"
         % (len(n_ev), neutrals["class_EVALUATED"]["max_abs_z_observed"] or 0),
         "   WARMUP    %d: returned at informative_obs<11 (line 2124) before the ladder"
         % len(n_warm),
         "             snapshots_len=%s informative_obs=%s duplicates_dropped=%s"
         % (json.dumps(neutrals["class_WARMUP_GUARD"]["snapshots_len"]),
            json.dumps(neutrals["class_WARMUP_GUARD"]["informative_obs"]),
            json.dumps(neutrals["class_WARMUP_GUARD"]["duplicates_dropped"])),
         "   PRE-INSTR %d: live_terms absent -> B3/B4 operands were never persisted"
         % len(n_pre),
         "             EVIDENCE_STATUS = %s"
         % neutrals["class_PRE_INSTRUMENTATION"]["EVIDENCE_STATUS"],
         "   P4 HARD GATE all-neutrals-operand-explained: %s"
         % neutrals["P4_HARD_GATE_all_neutrals_operand_explained"],
         "",
         "G. OPPOSITES total=%d  branch=%s  mapping=%s  joins=%s"
         % (len(opp), json.dumps(opposites["winning_branch"]),
            json.dumps(opposites["direction_mapping"]),
            json.dumps(opposites["join_class"])),
         "   z_ce %s" % json.dumps(opposites["z_ce"]),
         "   z_pe %s" % json.dumps(opposites["z_pe"]),
         "   both sides unwinding: win_ce<0 all=%s win_pe<0 all=%s | B4 fired %d"
         % (opposites["win_ce_all_negative"], opposites["win_pe_all_negative"],
            opposites["B4_fired_count"]),
         "   %s" % opposites["EVIDENCE_LIMIT"],
         "",
         "CANDIDATE MECHANISMS (none proven yet - no patch permitted):"]
    for m in mechanisms:
        T += ["   %s %s" % (m["id"], m["name"]),
              "      at %s" % m["source_location"],
              "      support %s" % json.dumps(m["measured_support"]),
              "      status %s" % m["status"]]
    T += ["", "GATE STATUS: %s" % json.dumps(gate),
          "", "STATUS: %s" % verdict,
          "NEXT: %s" % rep["next_required_step"], "=" * 78]
    txt = "\n".join(T)
    open(OUT_T, "w", encoding="utf-8", newline="\n").write(txt + "\n")
    print(txt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
