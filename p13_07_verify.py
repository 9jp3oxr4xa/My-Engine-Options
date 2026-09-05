# -*- coding: utf-8 -*-
"""
TASK 2 / PHASE 13X - STEP 7: PACKAGE VERIFICATION  (READ ONLY)

Independently re-hashes every artifact and every preserved copy against
19_INTEGRITY_MANIFEST.json, then checks that each required part exists and that
the report's load-bearing numbers are actually present in the artifacts.
Fails loudly; prints nothing but counts and defects.
"""
import hashlib
import json
import os

PKG = os.path.join(r"C:\Users\Guest -A\Desktop\Dhan Test",
                   "TASK2_PHASE13_FABLE_PACKAGE")
REQUIRED = ["00_README.md", "FABLE_SUMMARY.md", "01_MASTER_INVENTORY.json",
            "02_SOURCE_LINEAGE.json", "03_HISTORICAL_SESSION_INDEX.json",
            "03_RUNTIME_EVIDENCE_LOCATOR.json", "04_WINDOW_PREDICATE.json",
            "05_WINDOW_CONTROL_FLOW.txt", "06_WINDOW_DEPENDENCY_GRAPH.json",
            "07_RUNTIME_STATE_SEP02.json",
            "08_SEP02_COMPLETE_CYCLE_LEDGER.json",
            "09_FAILED_RETURN_PATHS.json", "10_HISTORICAL_COMPARISON.json",
            "11_COUNTERFACTUAL_READINESS.json", "12_OI_CONTROL_PROOF.json",
            "13_TASK1_TASK2_LINEAGE.json", "14_CONTRADICTIONS.json",
            "15_FAILED_HYPOTHESES.json", "16_ROOT_CAUSE_EVIDENCE.json",
            "17_PATCH_READINESS.json", "19_INTEGRITY_MANIFEST.json",
            "20_EXHAUSTION_RECORD.json"]


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main():
    man = json.load(open(os.path.join(PKG, "19_INTEGRITY_MANIFEST.json"),
                         encoding="utf-8"))
    defects = []
    for name in REQUIRED:
        if not os.path.exists(os.path.join(PKG, name)):
            defects.append("MISSING PART %s" % name)

    ok = 0
    for a in man["artifacts"]:
        p = os.path.join(PKG, a["file"])
        if not os.path.exists(p):
            defects.append("manifest entry vanished: %s" % a["file"])
            continue
        if sha256(p) != a["sha256"]:
            defects.append("hash mismatch: %s" % a["file"])
        else:
            ok += 1

    copies_ok = 0
    for c in man["raw_evidence_copies"]:
        if not os.path.exists(c["copy"]):
            defects.append("copy missing: %s" % c["copy"])
            continue
        if sha256(c["copy"]) != c["sha256"]:
            defects.append("copy differs from source: %s" % c["copy"])
            continue
        if os.path.exists(c["source"]) and sha256(c["source"]) != c["sha256"]:
            defects.append("source changed since capture: %s" % c["source"])
            continue
        copies_ok += 1

    # load-bearing numbers must exist in the artifacts, not just in prose
    led = json.load(open(os.path.join(PKG,
                                      "08_SEP02_COMPLETE_CYCLE_LEDGER.json"),
                         encoding="utf-8"))
    checks = {
        "oi_polls_659": led["observed_session_span_from_oi"]["polls"] == 659,
        "span_19728s": led["observed_session_span_from_oi"]["span_seconds"]
        == 19728,
        "cycles_957": led["counters_epoch"]["cycles"] == 957,
        "skip_window_957": led["counters_epoch"]["skip_window"] == 957,
        "zero_sep02_oi_candidates": led["oi_candidates_on_sep02"] == 0,
        "per_cycle_records_absent": led["per_cycle_records_exist"] is False,
        "feed_resubscribes_6": led["engine_log_event_counts"]
        .get("fyers_resubscribe_after_drop") == 6,
        "health_degraded_7": led["engine_log_event_counts"]
        .get("health_degraded") == 7,
    }
    for k, v in checks.items():
        if not v:
            defects.append("claim not backed by artifact: %s" % k)

    print("artifacts_verified=%d/%d raw_copies_verified=%d/%d"
          % (ok, len(man["artifacts"]), copies_ok,
             len(man["raw_evidence_copies"])))
    print("required_parts=%d/%d claim_checks_passed=%d/%d"
          % (len(REQUIRED) - sum(1 for d in defects if d.startswith("MISSING")),
             len(REQUIRED), sum(1 for v in checks.values() if v), len(checks)))
    print("VERDICT=%s defects=%d" % ("PASS" if not defects else "FAIL",
                                     len(defects)))
    for d in defects[:20]:
        print("  ! %s" % d)
    return 1 if defects else 0


if __name__ == "__main__":
    raise SystemExit(main())
