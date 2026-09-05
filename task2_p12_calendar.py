# -*- coding: utf-8 -*-
"""
TASK 2 / PHASE 12L-2  (READ ONLY)

Today every cycle returned at line 5004:
    if not self.calendar.signal_window_open(now, regime_strength): skip_window
This extracts signal_window_open and everything it depends on from today's
PROVEN live source, so the closed-window condition can be read off directly.

Emits TASK2_P12_SIGNAL_WINDOW.json
"""
import ast
import json
import os
import re

PROJ = r"C:\Users\Guest -A\Desktop\Dhan Test"
LIVE = os.path.join(PROJ, "Audit Bundle Sep 02", "01_SOURCE", "Dhan.py")
WANT = ["signal_window_open", "_phase", "phase_at", "session_phase",
        "SessionPhase", "SIGNAL_WINDOW", "LATE_SESSION", "strength"]


def main():
    src = open(LIVE, encoding="utf-8", errors="replace").read()
    lines = src.splitlines()
    tree = ast.parse(src)

    out = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and \
                node.name in ("signal_window_open", "phase", "phase_at",
                              "_phase_for", "session_phase"):
            a, b = node.lineno, node.end_lineno
            out[node.name] = {"span": [a, b],
                              "text": ["%d| %s" % (n, lines[n - 1].rstrip())
                                       for n in range(a, min(b, a + 70) + 1)]}
    for name, d in out.items():
        print("== %s lines %s ==" % (name, d["span"]))
        for t in d["text"]:
            print("  %s" % t[:160])

    print("\n== SESSION / WINDOW CONSTANTS ==")
    consts = []
    pat = re.compile(r"(time\(\s*\d+|SessionPhase|SIGNAL_WINDOW|"
                     r"signal_window|strength_min|MIN_STRENGTH|"
                     r"regime_strength|no_new|cutoff|9,\s*1[0-9]|1[0-5],\s*\d+)")
    for i, ln in enumerate(lines, 1):
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        if pat.search(s) and ("=" in s or "class " in s or "return" in s
                              or "if " in s):
            consts.append((i, s))
    for i, s in consts[:60]:
        print("%5d| %s" % (i, s[:150]))

    json.dump({"functions": out, "constants": consts[:120]},
              open(os.path.join(PROJ, "TASK2_P12_SIGNAL_WINDOW.json"), "w",
                   encoding="utf-8", newline="\n"), indent=1, default=str)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
