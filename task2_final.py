# -*- coding: utf-8 -*-
"""
TASK 2 / PHASE 11  ROOT-CAUSE GATE  (machine-generated from the phase artifacts)

Consumes TASK2_PRE_BASELINE.json, TASK2_LEDGER_SUMMARY.json, TASK2_P6_P10.json
and TASK2_P7B.json. Decides the gate; does not modify Dhan.py.

Emits TASK2_FINAL_REPORT.json / .txt
"""
import hashlib
import json
import os
from datetime import datetime

R = r"C:\Users\Guest -A\Desktop\Dhan Test"


def load(n):
    p = os.path.join(R, n)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main():
    base, led = load("TASK2_PRE_BASELINE.json"), load("TASK2_LEDGER_SUMMARY.json")
    a, b = load("TASK2_P6_P10.json"), load("TASK2_P7B.json")
    p7, p8, p9 = (a.get("P7_M1_history_admission", {}),
                  a.get("P8_M2_expiry_composition", {}),
                  a.get("P9_M3_ladder_order", {}))
    sel = b.get("SELECTION_candidate_vs_population", {})
    P, C = sel.get("population", {}), sel.get("candidate_times", {})
    v0a, v0b = a.get("V0_control", {}), b.get("V0_repair", {})

    now = sha(os.path.join(R, "Dhan.py"))
    unchanged = now == base.get("dhan", {}).get("sha256")

    findings = [
        {"id": "F1", "claim": "the candidate population is fully accounted for",
         "measured": {"ledger": led.get("P2_provenance", {}).get(
             "append_order_split"), "tri_state": led.get("P2_tri_state"),
             "joins": led.get("P3_join_integrity")},
         "status": "MEASURED"},
        {"id": "F2", "claim": "stale joins are not a cause",
         "measured": led.get("P3_join_integrity"), "status": "MEASURED_NON_CAUSE"},
        {"id": "F3", "claim": "M1 as first formulated (history admission is a "
                              "function of how recently the basket changed) is false",
         "measured": {"obs_p50_by_recency_bucket_is_flat":
                      {k: v.get("obs_p50") for k, v in list(
                          p7.get("obs_by_since_basket_change", {}).items())[:8]},
                      "obs_equals_recency_plus_1":
                      p7.get("obs_equals_since_change_plus_1"),
                      "of_polls": p7.get("polls_measured")},
         "status": "REFUTED_BY_MEASUREMENT"},
        {"id": "F4", "claim": "the basket-presence filter discards a large, "
                              "measurable share of retained history at every poll",
         "measured": {"rejected_by_basket_filter": p7.get(
             "rejected_by_basket_filter"), "snapshots_len": p7.get("snapshots_len"),
             "informative_obs": p7.get("informative_obs"),
             "arithmetic": "rejected = snapshots_len - duplicates_dropped - "
                           "informative_obs, all three engine-recorded"},
         "status": "MEASURED"},
        {"id": "F5", "claim": "candidate-time polls are not drawn from the "
                              "population distribution: at candidate moments the "
                              "history is almost entirely discarded",
         "measured": {
             "candidates_joined": sel.get("candidates_joined"),
             "candidates_unjoined": sel.get("candidates_unjoined"),
             "informative_obs_p50": {"population": (P.get("obs") or {}).get("p50"),
                                     "candidate_times": (C.get("obs") or {}).get("p50")},
             "rejected_p50": {"population": (P.get("rejected") or {}).get("p50"),
                              "candidate_times": (C.get("rejected") or {}).get("p50")},
             "obs_lt_11_share": {"population": P.get("obs_lt_11_share"),
                                 "candidate_times": C.get("obs_lt_11_share")},
             "ladder_ran_share": {"population": P.get("ladder_ran_share"),
                                  "candidate_times": C.get("ladder_ran_share")},
             "max_abs_z_p50_when_evaluated": {
                 "population": (P.get("max_abs_z_when_evaluated") or {}).get("p50"),
                 "candidate_times": (C.get("max_abs_z_when_evaluated") or {}).get("p50")},
             "atm_span_strikes_mean": {"population": (P.get("atm_span_strikes")
                                                      or {}).get("mean"),
                                       "candidate_times": (C.get("atm_span_strikes")
                                                           or {}).get("mean")},
             "chance_of_zero_agreement_in_190":
                 sel.get("chance_of_zero_agreement_in_190")},
         "status": "MEASURED"},
        {"id": "F6", "claim": "ATM travel raises rejection and lowers admission "
                              "monotonically, but by itself is far too weak to "
                              "produce what candidate times show",
         "measured": {k: {"polls": v.get("polls"),
                          "obs_p50": (v.get("obs") or {}).get("p50"),
                          "rejected_p50": (v.get("rejected") or {}).get("p50"),
                          "obs_lt_11_share": v.get("obs_lt_11_share")}
                      for k, v in b.get("M1_prime_atm_displacement", {}).items()},
         "status": "MEASURED_PARTIAL_EFFECT"},
        {"id": "F7", "claim": "expiry mixing inflates z instead of suppressing it, "
                              "and produces no non-neutral verdict at all",
         "measured": {"share_of_polls_with_mixed_window": p8.get("share_mixed"),
                      "abs_z_mixed": p8.get("abs_z_mixed"),
                      "abs_z_homogeneous": p8.get("abs_z_homogeneous"),
                      "non_neutral_in_mixed_cells": 0,
                      "reading": "both legs jump together at a roll, so the "
                                 "mutual-exclusion operands (z_ce<=0 for B1, "
                                 "z_pe<=0 for B2) block every branch"},
         "status": "MEASURED_SECONDARY"},
        {"id": "F8", "claim": "B3 and B4 never fire together, so ladder order did "
                              "not decide any poll in the instrumented window",
         "measured": {"B3_only": p9.get("B3_only"), "B4_only": p9.get("B4_only"),
                      "B3_and_B4": p9.get("B3_and_B4"),
                      "evaluated_polls": p9.get("evaluated_polls"),
                      "note": "the 25 opposite candidates are all pre-P3 rows, so "
                              "M3 remains untested against current code"},
         "status": "REFUTED_FOR_CURRENT_CODE"},
        {"id": "F9", "claim": "the persisted evidence cannot support any "
                              "recomputation of z, so no counterfactual can be "
                              "computed from the logs",
         "measured": {"v0_sampled_rows": v0a.get("checked"),
                      "v0_sampled_exact": v0a.get("exact_model"),
                      "v0_max_abs_err": v0a.get("max_abs_err"),
                      "rows_with_truncated_delta_arrays": v0b.get("truncated_rows"),
                      "rows_that_looked_complete": v0b.get("complete_rows"),
                      "exact_on_those": v0b.get("matched"),
                      "reason": "oi_diag records a truncated tail of the delta "
                                "series (~25 values) while the engine computes "
                                "mu/sd over the whole informative series (median "
                                "62 values); the full series and the full chain "
                                "strike list were never persisted"},
         "status": "EVIDENCE_INSUFFICIENT"},
    ]

    root_cause = {
        "statement": (
            "In OptionsIntel._directional_oi the statistical history is admitted "
            "per snapshot only if that snapshot contains EVERY strike of the "
            "basket derived from the CURRENT ATM (Dhan.py 2110-2116: "
            "`if len(legs) < len(atm_strikes): continue`). Admission is therefore "
            "a function of where price is NOW rather than of elapsed time. The "
            "provider's strike window travels with spot, so a directional move - "
            "which is the precondition for a structure candidate - removes the "
            "current basket from the older snapshots and deletes the history "
            "exactly when a candidate needs it."),
        "predicted_consequence": (
            "at candidate moments the retained deque is full but almost entirely "
            "discarded, informative_obs falls below the 11 required at line 2124 "
            "and the function returns neutral before B1-B4 are evaluated; where it "
            "survives, the window is too short for |z| to approach 1.5"),
        "observed_consequence": {
            "informative_obs_p50_at_candidate_times": (C.get("obs") or {}).get("p50"),
            "rejected_p50_at_candidate_times": (C.get("rejected") or {}).get("p50"),
            "share_below_the_11_guard": C.get("obs_lt_11_share"),
            "ladder_ran_share": C.get("ladder_ran_share"),
            "max_abs_z_p50_when_it_did_run": (C.get("max_abs_z_when_evaluated")
                                              or {}).get("p50"),
            "threshold_required": 1.5,
            "population_comparison": {
                "informative_obs_p50": (P.get("obs") or {}).get("p50"),
                "rejected_p50": (P.get("rejected") or {}).get("p50"),
                "share_below_the_11_guard": P.get("obs_lt_11_share"),
                "ladder_ran_share": P.get("ladder_ran_share")}},
        "affected_population": "all 190 ledger candidates; 139 of 190 by the guard "
                               "(73.16 percent of candidate-time polls) and the "
                               "remainder by window shortness",
        "why_not_proven": (
            "a root cause is only proven here by a single-variable counterfactual "
            "that changes the admission rule and nothing else, and that requires "
            "either the full per-poll chain strike lists or the full delta series. "
            "Neither was persisted (F9), and the V0 control failed, so no "
            "recomputation from the logs is admissible."),
        "status": "IDENTIFIED_WITH_STRONG_MEASURED_SUPPORT_NOT_COUNTERFACTUALLY_PROVEN",
    }

    proof_procedure = [
        "1. add observability only (no decision-core change): persist per poll the "
        "full informative series length, the full pe_d/ce_d arrays, the chain's "
        "complete strike list, and the per-snapshot basket-presence outcome",
        "2. run one session, or replay one recorded session, so the arrays are "
        "complete; re-run the V0 control until recomputed z matches persisted z "
        "exactly on every row",
        "3. counterfactual A: admit history per strike independently (a strike's "
        "series is used wherever that strike exists) changing nothing else; "
        "measure informative_obs, ladder_ran, |z| and verdicts per candidate",
        "4. counterfactual B: keep admission as is, widen the basket to a "
        "moneyness-symmetric set, changing nothing else",
        "5. counterfactual C: add the expiry predicate to the observation loop, "
        "changing nothing else",
        "6. accept as PRIMARY only the single change that moves the affected "
        "candidates, and only if the other two do not reproduce the effect",
    ]

    gate = {
        "authoritative_source_verified": base.get("same_copy_as_task1_pass"),
        "pre_patch_backup_verified": base.get("backup", {}).get(
            "byte_for_byte_equal"),
        "dhan_py_unchanged": unchanged,
        "ledger_complete": led.get("P2_discrepancy", {}).get(
            "reconciles_to_expected"),
        "joins_measured": bool(led.get("P3_join_integrity")),
        "all_neutrals_operand_explained": False,
        "all_opposites_have_a_winning_branch": led.get(
            "P5_all_opposites_have_a_winning_branch"),
        "v0_control_passed": bool(v0a.get("exact_model")),
        "expiry_effect_tested": True,
        "history_admission_effect_tested": True,
        "ladder_order_effect_tested": True,
        "counterfactual_permitted": bool(v0a.get("exact_model")),
        "ROOT_CAUSE_PROVEN": False,
        "PATCH_APPLIED": not unchanged,
        "VERDICT": "TASK2_FAIL_CLOSED_NO_PATCH",
    }

    rep = {"generated": datetime.now().isoformat(),
           "source": {"path": os.path.join(R, "Dhan.py"), "sha256": now,
                      "unchanged_since_phase0": unchanged},
           "findings": findings, "root_cause": root_cause,
           "proof_procedure_to_close_the_gate": proof_procedure,
           "gate": gate}
    json.dump(rep, open(os.path.join(R, "TASK2_FINAL_REPORT.json"), "w",
                        encoding="utf-8", newline="\n"), indent=1, default=str,
              sort_keys=True)

    T = ["=" * 78, "TASK 2 - FINAL REPORT (PHASES 0-11)", "=" * 78,
         "SOURCE  %s" % os.path.join(R, "Dhan.py"),
         "        sha256 %s  unchanged since Phase 0: %s" % (now, unchanged), ""]
    for f in findings:
        T += ["%s [%s] %s" % (f["id"], f["status"], f["claim"]),
              "     %s" % json.dumps(f["measured"], default=str)]
    T += ["", "ROOT CAUSE (%s)" % root_cause["status"], "  " + root_cause["statement"],
          "  predicted: " + root_cause["predicted_consequence"],
          "  observed:  " + json.dumps(root_cause["observed_consequence"]),
          "  affected:  " + root_cause["affected_population"],
          "  not proven because: " + root_cause["why_not_proven"], "",
          "PROOF PROCEDURE TO CLOSE THE GATE"]
    T += ["  " + s for s in proof_procedure]
    T += ["", "GATE %s" % json.dumps(gate), "", "VERDICT: %s" % gate["VERDICT"],
          "No change was made to Dhan.py: a root cause that is not "
          "counterfactually proven does not authorise a patch.", "=" * 78]
    txt = "\n".join(T)
    open(os.path.join(R, "TASK2_FINAL_REPORT.txt"), "w", encoding="utf-8",
         newline="\n").write(txt + "\n")
    print(txt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
