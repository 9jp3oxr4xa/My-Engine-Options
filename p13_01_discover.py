# -*- coding: utf-8 -*-
"""
TASK 2 / PHASE 13X - STEP 1: EVIDENCE DISCOVERY  (READ ONLY)

Recursively enumerates every candidate evidence file under the authorised roots,
hashes it, records which forensic content terms it contains and which session
dates it mentions. Nothing is copied or modified in this step.

Emits (into the Fable package dir):
  01_MASTER_INVENTORY.json
  _discovery_state.json   (working state for later steps)
"""
import hashlib
import json
import os
import re
import time

DESK = r"C:\Users\Guest -A\Desktop"
PROJ = os.path.join(DESK, "Dhan Test")
BUNDLE = os.path.join(PROJ, "Audit Bundle Sep 02")
PKG = os.path.join(PROJ, "TASK2_PHASE13_FABLE_PACKAGE")
APPDATA_CODE = os.path.join(r"C:\Users\Guest -A\AppData\Roaming", "Code")

ROOTS = [PROJ, DESK, APPDATA_CODE]
EXTS = {".log", ".txt", ".json", ".jsonl", ".csv", ".ndjson", ".trace", ".out",
        ".err", ".md", ".py", ".ps1", ".yaml", ".yml", ".ini", ".cfg", ".toml"}
SKIP_DIR = re.compile(r"(\\|/)(\.git|node_modules|__pycache__|\.venv|venv|"
                      r"site-packages|CachedData|Cache|CachedExtensions|"
                      r"GPUCache|Code Cache|blob_storage|logs\\exthost|"
                      r"TASK2_PHASE13_FABLE_PACKAGE)($|\\|/)", re.I)
TERMS = ["signal_window_open", "SIGNAL_WINDOW_CLOSED", "skip_window",
         "signal_window", "window", "candidate", "structure", "poll", "cycle",
         "session", "holiday", "holidays", "calendar", "timezone",
         "engine.holidays", "timestamp", "market date", "session start",
         "session end", "directional_oi", "z_ce", "z_pe", "basket", "atm",
         "expiry", "fyers", "nse", "engine", "health", "restart",
         "task1", "task2", "regime_strength", "SessionPhase", "is_trading_day",
         "evaluation_interval", "_FX", "oi_diag", "metrics", "snapshot"]
STRONG = {"signal_window_open", "SIGNAL_WINDOW_CLOSED", "skip_window",
          "engine.holidays", "holidays", "is_trading_day", "SessionPhase",
          "evaluation_interval", "regime_strength", "_FX", "timezone"}
DATE_RE = re.compile(r"20\d\d-\d\d-\d\d")
SCAN_BYTES = 1 << 20  # 1 MiB head scan for terms/dates
BIG = 40 << 20


def sha256(p):
    h = hashlib.sha256()
    try:
        with open(p, "rb") as fh:
            for b in iter(lambda: fh.read(1 << 20), b""):
                h.update(b)
    except OSError as e:
        return "ERROR:%s" % e
    return h.hexdigest()


def decode(b):
    if b[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return b.decode("utf-16", "replace"), "utf-16"
    if b[:3] == b"\xef\xbb\xbf":
        return b[3:].decode("utf-8", "replace"), "utf-8-sig"
    return b.decode("utf-8", "replace"), "utf-8"


def main():
    os.makedirs(PKG, exist_ok=True)
    t0 = time.time()
    seen = set()
    files = []
    searched_roots = []
    skipped = {"ext": 0, "dir": 0, "error": 0}

    for root in ROOTS:
        if not os.path.isdir(root):
            searched_roots.append({"root": root, "exists": False})
            continue
        n_here = 0
        for dirpath, dirnames, filenames in os.walk(root):
            if SKIP_DIR.search(dirpath):
                dirnames[:] = []
                skipped["dir"] += 1
                continue
            dirnames[:] = [d for d in dirnames
                           if not SKIP_DIR.search(os.path.join(dirpath, d))]
            for fn in filenames:
                p = os.path.join(dirpath, fn)
                ext = os.path.splitext(fn)[1].lower()
                if ext not in EXTS:
                    skipped["ext"] += 1
                    continue
                try:
                    key = os.path.normcase(os.path.abspath(p))
                    if key in seen:
                        continue
                    seen.add(key)
                    st = os.stat(p)
                except OSError:
                    skipped["error"] += 1
                    continue
                rec = {"path": p, "ext": ext, "size": st.st_size,
                       "mtime": time.strftime("%Y-%m-%dT%H:%M:%S",
                                              time.localtime(st.st_mtime)),
                       "ctime": time.strftime("%Y-%m-%dT%H:%M:%S",
                                              time.localtime(st.st_ctime)),
                       "in_bundle": os.path.normcase(BUNDLE)
                                    in os.path.normcase(p),
                       "sha256": sha256(p) if st.st_size <= BIG else "SKIPPED_BIG",
                       "encoding": None, "terms": {}, "dates": [],
                       "lines_head": None}
                try:
                    with open(p, "rb") as fh:
                        head = fh.read(SCAN_BYTES)
                    txt, enc = decode(head)
                    rec["encoding"] = enc
                    low = txt.lower()
                    for t in TERMS:
                        c = low.count(t.lower())
                        if c:
                            rec["terms"][t] = c
                    rec["dates"] = sorted(set(DATE_RE.findall(txt)))
                    rec["lines_head"] = txt.count("\n")
                except OSError:
                    skipped["error"] += 1
                rec["relevant"] = bool(rec["terms"])
                rec["strong"] = sorted(set(rec["terms"]) & STRONG)
                files.append(rec)
                n_here += 1
        searched_roots.append({"root": root, "exists": True, "files": n_here})

    rel = [f for f in files if f["relevant"]]
    dates = {}
    for f in rel:
        for d in f["dates"]:
            dates.setdefault(d, []).append(f["path"])
    by_ext = {}
    for f in rel:
        by_ext[f["ext"]] = by_ext.get(f["ext"], 0) + 1
    strong_files = sorted([f for f in rel if f["strong"]],
                         key=lambda f: (-len(f["strong"]), -f["size"]))

    inv = {"generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "roots_searched": searched_roots,
           "extensions_searched": sorted(EXTS),
           "content_terms_searched": TERMS,
           "skip_rules": SKIP_DIR.pattern,
           "counts": {"files_indexed": len(files), "relevant": len(rel),
                      "skipped_by_extension": skipped["ext"],
                      "skipped_dirs": skipped["dir"],
                      "errors": skipped["error"],
                      "elapsed_s": round(time.time() - t0, 1)},
           "relevant_by_extension": by_ext,
           "session_dates_mentioned": {d: len(v) for d, v in sorted(dates.items())},
           "files": files}
    json.dump(inv, open(os.path.join(PKG, "01_MASTER_INVENTORY.json"), "w",
                        encoding="utf-8", newline="\n"), indent=1, default=str)
    json.dump({"relevant_paths": [f["path"] for f in rel],
               "strong_paths": [f["path"] for f in strong_files],
               "dates": {d: sorted(set(v)) for d, v in dates.items()}},
              open(os.path.join(PKG, "_discovery_state.json"), "w",
                   encoding="utf-8", newline="\n"), indent=1, default=str)

    print("indexed=%d relevant=%d elapsed=%.1fs"
          % (len(files), len(rel), time.time() - t0))
    print("by_ext=%s" % json.dumps(by_ext))
    print("dates_mentioned=%s"
          % json.dumps({d: len(v) for d, v in sorted(dates.items())}))
    print("\n-- files carrying STRONG window/config terms (top 40) --")
    for f in strong_files[:40]:
        print(" %9d %-13s %s" % (f["size"], ",".join(f["strong"])[:12],
                                 f["path"].replace(DESK, "~")[:118]))
    print("\n-- largest relevant data files (top 15) --")
    for f in sorted(rel, key=lambda x: -x["size"])[:15]:
        print(" %10d %s" % (f["size"], f["path"].replace(DESK, "~")[:118]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
