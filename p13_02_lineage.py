# -*- coding: utf-8 -*-
"""
TASK 2 / PHASE 13X - STEP 2: SOURCE LINEAGE  (READ ONLY)

Discovery found Dhan.py generations preserved by VS Code Local History
(AppData\\Roaming\\Code\\User\\History\\*). Those carry timestamps, so the
yesterday-baseline can be identified by evidence instead of by filename.

For every engine-source variant on the machine:
  sha256 / size / mtime / VS Code History timestamp + original resource
  ast span + per-function sha of the window-critical functions
  presence of forensic (_FX / forensics) and TASK1 / TASK2 markers
Then groups variants by window-predicate identity and diffs each generation
against today's proven live source.

Emits 02_SOURCE_LINEAGE.json  +  _lineage_state.json
"""
import ast
import difflib
import hashlib
import json
import os
import time
import urllib.parse as up

DESK = r"C:\Users\Guest -A\Desktop"
PROJ = os.path.join(DESK, "Dhan Test")
PKG = os.path.join(PROJ, "TASK2_PHASE13_FABLE_PACKAGE")
HIST = r"C:\Users\Guest -A\AppData\Roaming\Code\User\History"
LIVE = os.path.join(PROJ, "Audit Bundle Sep 02", "01_SOURCE", "Dhan.py")
FUNCS = ["signal_window_open", "phase", "is_trading_day", "_evaluate_inner",
         "_directional_oi", "_parse_config", "load_config", "_evaluate"]
MARKERS = {"_FX": "_FX.", "forensics_import": "import forensics",
           "TASK1": "TASK1", "TASK2": "TASK2",
           "SIGNAL_WINDOW_CLOSED": "SIGNAL_WINDOW_CLOSED",
           "oi_sentinel": "oi_sentinel", "oi_diag": "oi_diag"}


def sha(b):
    return hashlib.sha256(b).hexdigest()


def read(p):
    with open(p, "rb") as fh:
        raw = fh.read()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw, raw.decode("utf-16", "replace")
    if raw[:3] == b"\xef\xbb\xbf":
        return raw, raw[3:].decode("utf-8", "replace")
    return raw, raw.decode("utf-8", "replace")


def fn_map(src):
    out = {}
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError) as e:
        # keep the container shape uniform so callers never see a bare string
        return {"__parse_error__": [{"span": None, "lines": 0, "sha16": None,
                                     "text": [], "error": str(e)}]}
    lines = src.splitlines()
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and \
                n.name in FUNCS:
            body = [l.rstrip() for l in lines[n.lineno - 1:n.end_lineno]]
            out.setdefault(n.name, []).append(
                {"span": [n.lineno, n.end_lineno], "lines": len(body),
                 "sha16": sha("\n".join(body).encode())[:16], "text": body})
    return out


def history_index():
    """filename -> (timestamp_iso, original resource path)"""
    idx = {}
    if not os.path.isdir(HIST):
        return idx
    for d in os.listdir(HIST):
        ej = os.path.join(HIST, d, "entries.json")
        if not os.path.exists(ej):
            continue
        try:
            j = json.load(open(ej, encoding="utf-8"))
        except Exception:
            continue
        res = up.unquote(j.get("resource", "")).replace("file:///", "")
        for e in j.get("entries", []):
            ts = e.get("timestamp", 0) / 1000.0
            idx[os.path.normcase(os.path.join(HIST, d, e.get("id", "")))] = (
                time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts)), res,
                e.get("timestamp", 0))
    return idx


def main():
    inv = json.load(open(os.path.join(PKG, "01_MASTER_INVENTORY.json"),
                         encoding="utf-8"))
    hidx = history_index()
    live_raw, live_src = read(LIVE)
    live_sha = sha(live_raw)
    live_fns = fn_map(live_src)

    cands = [f["path"] for f in inv["files"]
             if f["ext"] == ".py" and f["size"] > 100000
             and "signal_window_open" in f.get("terms", {})
             or (f["ext"] == ".py" and f["size"] > 100000
                 and "SessionPhase" in f.get("terms", {}))]
    variants = []
    for p in sorted(set(cands)):
        try:
            raw, src = read(p)
        except OSError:
            continue
        if "class SessionCalendar" not in src:
            continue
        st = os.stat(p)
        h = hidx.get(os.path.normcase(os.path.abspath(p)))
        fns = fn_map(src)
        v = {"path": p, "size": st.st_size, "sha256": sha(raw),
             "mtime": time.strftime("%Y-%m-%dT%H:%M:%S",
                                    time.localtime(st.st_mtime)),
             "history_timestamp": h[0] if h else None,
             "history_resource": h[1] if h else None,
             "history_epoch_ms": h[2] if h else None,
             "lines": src.count("\n") + 1,
             "markers": {k: src.count(v2) for k, v2 in MARKERS.items()},
             "functions": {k: [{kk: vv for kk, vv in d.items() if kk != "text"}
                               for d in lst] for k, lst in fns.items()},
             "is_today_live_source": sha(raw) == live_sha}
        # window predicate identity + diff vs live
        wl = live_fns.get("signal_window_open", [{}])[0].get("sha16")
        wv = fns.get("signal_window_open", [{}])[0].get("sha16")
        v["window_sha16"] = wv
        v["window_identical_to_live"] = (wv == wl)
        if not v["window_identical_to_live"] and \
                fns.get("signal_window_open") and live_fns.get("signal_window_open"):
            v["window_diff_vs_live"] = list(difflib.unified_diff(
                fns["signal_window_open"][0]["text"],
                live_fns["signal_window_open"][0]["text"],
                "variant", "live", n=1, lineterm=""))
        for f in FUNCS:
            a = fns.get(f, [{}])[0].get("sha16")
            b = live_fns.get(f, [{}])[0].get("sha16")
            v.setdefault("fn_identical_to_live", {})[f] = (a == b) if (a and b) \
                else ("MISSING_IN_VARIANT" if not a else "MISSING_IN_LIVE")
        variants.append(v)

    by_sha = {}
    for v in variants:
        by_sha.setdefault(v["sha256"], []).append(v["path"])
    ordered = sorted(variants, key=lambda v: (v["history_epoch_ms"] or 0,
                                              v["mtime"]))
    out = {"generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "today_live_source": {"path": LIVE, "sha256": live_sha,
                                 "size": os.path.getsize(LIVE)},
           "vscode_history_entries_indexed": len(hidx),
           "variant_count": len(variants),
           "distinct_sha256": len(by_sha),
           "duplicate_groups": {k: v for k, v in by_sha.items() if len(v) > 1},
           "window_predicate_groups": {},
           "variants_chronological": ordered,
           "live_functions": {k: [{"span": d["span"], "lines": d["lines"],
                                   "sha16": d["sha16"]} for d in lst]
                              for k, lst in live_fns.items()}}
    for v in variants:
        out["window_predicate_groups"].setdefault(str(v["window_sha16"]),
                                                  []).append(v["path"])
    json.dump(out, open(os.path.join(PKG, "02_SOURCE_LINEAGE.json"), "w",
                        encoding="utf-8", newline="\n"), indent=1, default=str)
    json.dump({"variants": [{"path": v["path"], "sha256": v["sha256"],
                             "size": v["size"], "ts": v["history_timestamp"]
                             or v["mtime"], "live": v["is_today_live_source"],
                             "window_sha16": v["window_sha16"]}
                            for v in ordered]},
              open(os.path.join(PKG, "_lineage_state.json"), "w",
                   encoding="utf-8", newline="\n"), indent=1, default=str)

    print("live_sha=%s" % live_sha[:16])
    print("variants=%d distinct_sha=%d history_entries=%d"
          % (len(variants), len(by_sha), len(hidx)))
    print("window_predicate_groups=%d -> %s"
          % (len(out["window_predicate_groups"]),
             json.dumps({k[:8]: len(v) for k, v
                         in out["window_predicate_groups"].items()})))
    print("\n TS/MTIME            SIZE   SHA8     WIN8     FX T1 T2 LIVE PATH")
    for v in ordered:
        print(" %-19s %7d %s %s %2d %2d %2d %s %s"
              % (v["history_timestamp"] or v["mtime"], v["size"],
                 v["sha256"][:8], str(v["window_sha16"])[:8],
                 v["markers"]["_FX"], v["markers"]["TASK1"],
                 v["markers"]["TASK2"],
                 "YES " if v["is_today_live_source"] else "    ",
                 v["path"].replace(DESK, "~").replace(HIST, "$H")[:60]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
