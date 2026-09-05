# -*- coding: utf-8 -*-
"""
TASK 2 / PHASE 12L  (READ ONLY)

metrics.json for today's session says cycles=957 and skip_window=957, i.e. every
cycle was skipped. This locates the predicate that increments skip_window in
today's PROVEN live source and measures what the OI layer was doing meanwhile.

Emits TASK2_P12_WINDOW_GATE.json
"""
import ast
import collections
import json
import os
import re

PROJ = r"C:\Users\Guest -A\Desktop\Dhan Test"
B = os.path.join(PROJ, "Audit Bundle Sep 02")
LIVE = os.path.join(B, "01_SOURCE", "Dhan.py")
DIAG = os.path.join(B, "02_TODAY_LOGS", "logs", "oi_diag.jsonl")
CUR = os.path.join(B, "02_TODAY_LOGS", "logs", "engine-live-current.txt")
PAT = re.compile(r"skip_window|_in_session|in_window|session_window|"
                 r"SESSION_(START|END)|market_open|market_close|"
                 r"square_off|no_new_entries|entry_cutoff|WINDOW")


def owner(tree, line):
    best = None
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if n.lineno <= line <= (n.end_lineno or n.lineno):
                if best is None or n.lineno > best.lineno:
                    best = n
    return best.name if best else "<module>"


def main():
    src = open(LIVE, encoding="utf-8", errors="replace").read()
    lines = src.splitlines()
    tree = ast.parse(src)
    hits = []
    for i, ln in enumerate(lines, 1):
        if PAT.search(ln):
            hits.append({"line": i, "func": owner(tree, i), "text": ln.rstrip()})

    print("== WINDOW-GATE SITES IN TODAY'S PROVEN LIVE SOURCE ==")
    for h in hits:
        print("%5d| %-28s %s" % (h["line"], h["func"], h["text"].strip()[:120]))

    # context around the skip_window increment
    ctx = []
    for h in hits:
        if "skip_window" in h["text"]:
            a, b = max(1, h["line"] - 18), min(len(lines), h["line"] + 4)
            ctx.append({"anchor": h["line"], "func": h["func"],
                        "text": ["%d| %s" % (n, lines[n - 1].rstrip())
                                 for n in range(a, b + 1)]})
    print("\n== CONTEXT AROUND skip_window ==")
    for c in ctx:
        print("-- %s (anchor %d)" % (c["func"], c["anchor"]))
        for t in c["text"]:
            print("   %s" % t[:150])

    # what the OI layer did on 09-02 while every cycle was skipped
    d = collections.Counter()
    br = collections.Counter()
    vd = collections.Counter()
    obs = []
    first = last = None
    with open(DIAG, encoding="utf-8", errors="replace") as fh:
        for ln in fh:
            ln = ln.strip()
            if not ln.startswith("{"):
                continue
            try:
                r = json.loads(ln)
            except Exception:
                continue
            day = str(r.get("ts"))[:10]
            d[day] += 1
            if day != "2026-09-02":
                continue
            br[str(r.get("branch"))] += 1
            vd[str(r.get("verdict_engine"))] += 1
            lt = r.get("live_terms")
            if isinstance(lt, dict) and lt.get("informative_obs") is not None:
                obs.append(lt["informative_obs"])
            first = first or r.get("ts")
            last = r.get("ts")
    ov = sorted(obs)
    print("\n== 09-02 OI ACTIVITY WHILE cycles==skip_window==957 ==")
    print("rows_by_date=%s" % json.dumps(dict(d)))
    print("09-02 first=%s last=%s" % (first, last))
    print("09-02 branches=%s" % json.dumps(dict(br)))
    print("09-02 verdicts=%s" % json.dumps(dict(vd)))
    print("09-02 informative_obs n=%d p50=%s max=%s"
          % (len(ov), ov[len(ov) // 2] if ov else None, ov[-1] if ov else None))
    print("09-02 oi_candidate rows=%d" % br.get("None", 0))

    tail = open(CUR, encoding="utf-8", errors="replace").read().splitlines()
    print("\n== engine-live-current.txt (first 6 / last 8 of %d lines) ==" % len(tail))
    for t in tail[:6] + ["..."] + tail[-8:]:
        print("   %s" % t[:170])

    json.dump({"window_gate_sites": hits, "skip_window_context": ctx,
               "oi_rows_by_date": dict(d),
               "sep02": {"first_ts": first, "last_ts": last,
                         "branches": dict(br), "verdicts": dict(vd),
                         "informative_obs_n": len(ov),
                         "informative_obs_p50": (ov[len(ov) // 2] if ov else None)},
               "engine_live_current_tail": tail[-12:]},
              open(os.path.join(PROJ, "TASK2_P12_WINDOW_GATE.json"), "w",
                   encoding="utf-8", newline="\n"), indent=1, default=str)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
