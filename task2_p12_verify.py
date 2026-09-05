# -*- coding: utf-8 -*-
"""
TASK 2 / PHASE 12 VERIFICATION  (READ ONLY)

Re-checks the one claim in the final report that was produced by the earlier
extractor before it was fixed: whether _directional_oi is really identical
between today's proven live source and the forensic copy. The first comparison
ran on a 2-line extraction (the multi-line def signature defeated the indent
walker), so it proved nothing. This uses ast spans.

Also confirms every Phase 12 artifact exists and is valid JSON.
"""
import ast
import difflib
import hashlib
import json
import os

PROJ = r"C:\Users\Guest -A\Desktop\Dhan Test"
LIVE = os.path.join(PROJ, "Audit Bundle Sep 02", "01_SOURCE", "Dhan.py")
FOREN = os.path.join(PROJ, "Dhan.py")
ART = ["TASK2_SOURCE_LINEAGE.json", "TASK2_EVIDENCE_RECONCILIATION.json",
       "TASK2_LIVE_SOURCE_DIRECTIONAL_OI.json", "TASK2_P12_Z_DEGENERACY.json",
       "TASK2_OI_RECONSTRUCTION_REPORT.json", "TASK2_COUNTERFACTUAL_LEDGER.json",
       "TASK2_P12_WINDOW_GATE.json", "TASK2_P12_SIGNAL_WINDOW.json"]


def span(path, name):
    src = open(path, encoding="utf-8", errors="replace").read()
    lines = src.splitlines()
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and \
                n.name == name:
            return (n.lineno, n.end_lineno,
                    lines[n.lineno - 1:n.end_lineno])
    return None, None, []


def main():
    out = {}
    for fn in ("_directional_oi", "signal_window_open", "_evaluate_inner",
               "is_trading_day"):
        a1, b1, t1 = span(LIVE, fn)
        a2, b2, t2 = span(FOREN, fn)
        norm1 = [x.rstrip() for x in t1]
        norm2 = [x.rstrip() for x in t2]
        same = norm1 == norm2
        h1 = hashlib.sha256("\n".join(norm1).encode()).hexdigest()[:16]
        h2 = hashlib.sha256("\n".join(norm2).encode()).hexdigest()[:16]
        d = [] if same else [l for l in difflib.unified_diff(
            norm2, norm1, "forensic", "live", n=0, lineterm="")][:40]
        out[fn] = {"live_span": [a1, b1], "live_lines": len(t1), "live_sha16": h1,
                   "forensic_span": [a2, b2], "forensic_lines": len(t2),
                   "forensic_sha16": h2, "identical": same, "diff": d}
        print("%-20s live=%s(%d) foren=%s(%d) identical=%s"
              % (fn, [a1, b1], len(t1), [a2, b2], len(t2), same))
        for line in d:
            print("    %s" % line[:150])

    print("\n== ARTIFACTS ==")
    arts = {}
    for a in ART:
        p = os.path.join(PROJ, a)
        if not os.path.exists(p):
            print(" MISSING %s" % a)
            arts[a] = "MISSING"
            continue
        try:
            json.load(open(p, encoding="utf-8"))
            ok = "valid_json"
        except Exception as e:
            ok = "INVALID: %s" % e
        arts[a] = {"bytes": os.path.getsize(p), "status": ok}
        print(" %-46s %8d  %s" % (a, os.path.getsize(p), ok))
    md = os.path.join(PROJ, "TASK2_PHASE12_FINAL_REPORT.md")
    print(" %-46s %8d  %s" % (os.path.basename(md), os.path.getsize(md),
                              "present" if os.path.exists(md) else "MISSING"))

    json.dump({"function_identity": out, "artifacts": arts},
              open(os.path.join(PROJ, "TASK2_P12_VERIFICATION.json"), "w",
                   encoding="utf-8", newline="\n"), indent=1, default=str)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
