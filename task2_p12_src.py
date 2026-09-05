# -*- coding: utf-8 -*-
"""
TASK 2 / PHASE 12-0B + 12A  (READ ONLY)

Anchors the analysis to TODAY'S PROVEN LIVE SOURCE (bundle 01_SOURCE\\Dhan.py,
sha 550d18d3...) instead of the forensic copy used in phases 0-11.

1. extracts _directional_oi from today's live source and from the forensic copy
2. compares them line by line and classifies every difference
3. prints only the decision-relevant lines (predicates, thresholds, exits)
4. dumps the live_terms / candidate record shapes actually present today

Emits TASK2_LIVE_SOURCE_DIRECTIONAL_OI.json
"""
import difflib
import json
import os
import re

PROJ = r"C:\Users\Guest -A\Desktop\Dhan Test"
B = os.path.join(PROJ, "Audit Bundle Sep 02")
LIVE = os.path.join(B, "01_SOURCE", "Dhan.py")
FOREN = os.path.join(PROJ, "Dhan.py")
DIAG = os.path.join(B, "02_TODAY_LOGS", "logs", "oi_diag.jsonl")
TOKENS = re.compile(
    r"(def |return |continue|break|if |elif |else:|_MIN_|threshold|1\.5|0\.5|"
    r"lookback|informative|duplicates|len\(legs\)|atm_strikes|avg_oi|sd_|mu_|"
    r"z_ce|z_pe|win_ce|win_pe|B1|B2|B3|B4|B5|bullish|bearish|neutral|expiry|"
    r"snapshots|basket|per_strike|spot)")


def fn_lines(path, name="_directional_oi"):
    src = open(path, encoding="utf-8", errors="replace").read().splitlines()
    start = None
    for i, ln in enumerate(src):
        if re.match(r"\s*def %s\b" % name, ln):
            start = i
            indent = len(ln) - len(ln.lstrip())
            break
    if start is None:
        return None, []
    out = [(start + 1, src[start])]
    for j in range(start + 1, len(src)):
        ln = src[j]
        if ln.strip() and (len(ln) - len(ln.lstrip())) <= indent and \
                not ln.lstrip().startswith("#"):
            break
        out.append((j + 1, ln))
    return start + 1, out


def main():
    ls, live = fn_lines(LIVE)
    fs, foren = fn_lines(FOREN)
    lt = [x[1] for x in live]
    ft = [x[1] for x in foren]
    sm = difflib.SequenceMatcher(None, lt, ft)
    diffs = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        diffs.append({"tag": tag,
                      "live_lines": [live[k][0] for k in range(i1, i2)],
                      "live_text": [lt[k] for k in range(i1, i2)],
                      "forensic_lines": [foren[k][0] for k in range(j1, j2)],
                      "forensic_text": [ft[k] for k in range(j1, j2)]})

    def classify(d):
        blob = " ".join(d["live_text"] + d["forensic_text"])
        if re.search(r"oi_diag|_last_terms|diag|log|note_candidate|jsonl", blob):
            return "DIAGNOSTIC_ONLY", "only touches diagnostic emission"
        if re.search(r"len\(legs\)|atm_strikes|lookback|1\.5|avg_oi|sd|mu|"
                     r"z_ce|z_pe|verdict|expiry|basket", blob):
            return "FUNCTIONAL", "touches a decision operand or predicate"
        return "UNCERTAIN", "no decisive marker"

    for d in diffs:
        d["classification"], d["reason"] = classify(d)

    rep = {"live_source": {"path": LIVE, "func_first_line": ls,
                           "func_line_count": len(live)},
           "forensic_source": {"path": FOREN, "func_first_line": fs,
                               "func_line_count": len(foren)},
           "identical": lt == ft,
           "similarity": round(sm.ratio(), 6),
           "difference_blocks": diffs,
           "difference_classification_counts": {},
           "live_function_text": ["%d|%s" % (n, t) for n, t in live]}
    cc = {}
    for d in diffs:
        cc[d["classification"]] = cc.get(d["classification"], 0) + 1
    rep["difference_classification_counts"] = cc
    json.dump(rep, open(os.path.join(PROJ,
                                     "TASK2_LIVE_SOURCE_DIRECTIONAL_OI.json"),
                        "w", encoding="utf-8", newline="\n"), indent=1,
              default=str)

    print("== _directional_oi IN TODAY'S PROVEN LIVE SOURCE ==")
    print("live: first_line=%s lines=%d | forensic: first_line=%s lines=%d"
          % (ls, len(live), fs, len(foren)))
    print("identical=%s similarity=%.6f diff_blocks=%d classes=%s"
          % (rep["identical"], sm.ratio(), len(diffs), json.dumps(cc)))
    print("-- decision-relevant lines of TODAY'S live source --")
    for n, t in live:
        s = t.rstrip()
        if s.strip() and TOKENS.search(s):
            print("%5d| %s" % (n, s[:150]))
    print("-- difference blocks (live vs forensic) --")
    for d in diffs[:12]:
        print(" [%s/%s] live%s: %s" % (d["tag"], d["classification"],
                                       d["live_lines"],
                                       [x.strip()[:90] for x in d["live_text"]]))
        print("            foren%s: %s" % (d["forensic_lines"],
                                           [x.strip()[:90]
                                            for x in d["forensic_text"]]))

    print("\n== RECORD SHAPES IN TODAY'S DATA ==")
    lt_row = cand = None
    with open(DIAG, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line.startswith("{"):
                continue
            r = json.loads(line)
            if lt_row is None and isinstance(r.get("live_terms"), dict) \
                    and r["live_terms"].get("B1") is not None:
                lt_row = r
            if cand is None and r.get("event") == "oi_candidate":
                cand = r
            if lt_row and cand:
                break
    if lt_row:
        print("live_terms sample (ts=%s branch=%s verdict=%s):"
              % (lt_row.get("ts"), lt_row.get("branch"),
                 lt_row.get("verdict_engine")))
        print(json.dumps(lt_row["live_terms"], default=str)[:2200])
    if cand:
        c = {k: v for k, v in cand.items()
             if k not in ("pe_basket_series", "ce_basket_series", "pe_deltas",
                          "ce_deltas", "live_terms")}
        print("candidate sample:")
        print(json.dumps(c, default=str)[:1600])
        if isinstance(cand.get("live_terms"), dict):
            print("candidate live_terms:")
            print(json.dumps(cand["live_terms"], default=str)[:1600])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
