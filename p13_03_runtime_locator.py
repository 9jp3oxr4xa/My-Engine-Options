# -*- coding: utf-8 -*-
"""
TASK 2 / PHASE 13X - STEP 3: RUNTIME-EVIDENCE LOCATOR  (READ ONLY)

Lineage step 2 proved the window predicate is byte-stable across 420 of the 477
engine-source variants, so the Sep-02 closure must come from an INPUT, not from
the predicate. This step finds every runtime/telemetry artifact on the machine
that can carry those inputs, scanning each file COMPLETELY (not just its head).

Markers hunted (runtime evidence, not source text):
  window / cycle telemetry .... SIGNAL_WINDOW_CLOSED, skip_window, signal_window
  calendar+config ............. holidays, timezone, evaluation_interval, PRE_OPEN
  phase/regime ................ SessionPhase names, regime_strength, phase=
  session boundaries .......... engine_start/stop, metrics counters
Every hit is recorded with its count and the file's observed date span.

Emits 03_RUNTIME_EVIDENCE_LOCATOR.json + _runtime_state.json
"""
import json
import os
import re
import time

DESK = r"C:\Users\Guest -A\Desktop"
PROJ = os.path.join(DESK, "Dhan Test")
PKG = os.path.join(PROJ, "TASK2_PHASE13_FABLE_PACKAGE")
DATA_EXT = {".log", ".jsonl", ".json", ".csv", ".ndjson", ".txt", ".out", ".err",
            ".trace"}
NAME_HINT = re.compile(r"(log|metric|oi_|state|snapshot|cycle|fx|forensic|"
                       r"engine|diag|window|session|candidate|signal|config|"
                       r"holiday|task1|task2)", re.I)
MARKERS = {
    "SIGNAL_WINDOW_CLOSED": "SIGNAL_WINDOW_CLOSED",
    "skip_window": "skip_window",
    "signal_window": "signal_window",
    "window_open": "window_open",
    "holidays": "holidays",
    "timezone": "timezone",
    "evaluation_interval": "evaluation_interval",
    "regime_strength": "regime_strength",
    "PRE_OPEN": "PRE_OPEN",
    "MIDDAY": "MIDDAY",
    "phase_eq": "phase=",
    "phase_key": '"phase"',
    "cycles": '"cycles"',
    "engine_start": "engine_start",
    "engine_stop": "engine_stop",
    "oi_candidate": "oi_candidate",
    "oi_snapshot": "oi_snapshot",
    "TRIGGER": "TRIGGER",
    "CANDIDATE": "CANDIDATE",
    "is_trading_day": "is_trading_day",
    "trading_day": "trading_day",
    "market_closed": "market_closed",
    "skip_warmup": "skip_warmup",
    "rejections_by_reason": "rejections_by_reason",
}
DATE_RE = re.compile(r"20\d\d-\d\d-\d\d")
CHUNK = 1 << 22


def scan(path):
    """complete streaming scan; returns marker counts, date set, bytes, lines"""
    counts = {k: 0 for k in MARKERS}
    dates = {}
    nbytes = nlines = 0
    tail = ""
    try:
        with open(path, "rb") as fh:
            first = fh.read(2)
            fh.seek(0)
            enc = "utf-16" if first in (b"\xff\xfe", b"\xfe\xff") else "utf-8"
            while True:
                raw = fh.read(CHUNK)
                if not raw:
                    break
                nbytes += len(raw)
                txt = tail + raw.decode(enc, "replace")
                nlines += txt.count("\n")
                for k, m in MARKERS.items():
                    counts[k] += txt.count(m)
                for d in DATE_RE.findall(txt):
                    dates[d] = dates.get(d, 0) + 1
                tail = txt[-64:]
    except OSError as e:
        return None, None, str(e), 0
    return counts, dates, None, (nbytes, nlines)


def main():
    inv = json.load(open(os.path.join(PKG, "01_MASTER_INVENTORY.json"),
                         encoding="utf-8"))
    todo = []
    for f in inv["files"]:
        if f["ext"] not in DATA_EXT:
            continue
        p = f["path"]
        if "TASK2_PHASE13_FABLE_PACKAGE" in p:
            continue
        if not (NAME_HINT.search(os.path.basename(p))
                or NAME_HINT.search(os.path.dirname(p))):
            continue
        if f["size"] > (300 << 20) or f["size"] == 0:
            continue
        todo.append(f)

    hits = []
    t0 = time.time()
    for f in todo:
        c, d, err, sz = scan(f["path"])
        if err:
            continue
        if not any(c.values()):
            continue
        hits.append({"path": f["path"], "size": f["size"], "ext": f["ext"],
                     "mtime": f["mtime"], "sha256": f.get("sha256"),
                     "bytes_scanned": sz[0], "lines": sz[1],
                     "markers": {k: v for k, v in c.items() if v},
                     "dates": dict(sorted(d.items())),
                     "date_min": min(d) if d else None,
                     "date_max": max(d) if d else None})

    # which files carry the decisive window telemetry
    decisive = [h for h in hits
                if h["markers"].get("SIGNAL_WINDOW_CLOSED")
                or h["markers"].get("skip_window")
                or h["markers"].get("signal_window")
                or h["markers"].get("holidays")]
    sep02 = [h for h in hits if "2026-09-02" in h["dates"]]
    days = {}
    for h in hits:
        for d, n in h["dates"].items():
            days.setdefault(d, {"files": 0, "mentions": 0})
            days[d]["files"] += 1
            days[d]["mentions"] += n

    out = {"generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "files_considered": len(todo), "files_with_hits": len(hits),
           "scan_seconds": round(time.time() - t0, 1),
           "markers_searched": MARKERS,
           "name_hint_regex": NAME_HINT.pattern,
           "days_present": dict(sorted(days.items())),
           "decisive_window_evidence_files": [h["path"] for h in decisive],
           "files_mentioning_2026_09_02": [h["path"] for h in sep02],
           "hits": hits}
    json.dump(out, open(os.path.join(PKG, "03_RUNTIME_EVIDENCE_LOCATOR.json"),
                        "w", encoding="utf-8", newline="\n"), indent=1,
              default=str)
    json.dump({"decisive": [h["path"] for h in decisive],
               "sep02_files": [h["path"] for h in sep02],
               "all_hit_paths": [h["path"] for h in hits]},
              open(os.path.join(PKG, "_runtime_state.json"), "w",
                   encoding="utf-8", newline="\n"), indent=1, default=str)

    print("considered=%d hits=%d scan=%.1fs" % (len(todo), len(hits),
                                                time.time() - t0))
    print("days_present=%s" % json.dumps(
        {d: v["files"] for d, v in sorted(days.items()) if d >= "2026-08-01"}))
    print("\n== FILES WITH WINDOW / HOLIDAY TELEMETRY (%d) ==" % len(decisive))
    for h in sorted(decisive, key=lambda x: -x["size"]):
        m = h["markers"]
        print(" %9d %-11s SWC=%d skipw=%d sigw=%d hol=%d tz=%d  %s"
              % (h["size"], (h["date_min"] or "-")[:11],
                 m.get("SIGNAL_WINDOW_CLOSED", 0), m.get("skip_window", 0),
                 m.get("signal_window", 0), m.get("holidays", 0),
                 m.get("timezone", 0), h["path"].replace(DESK, "~")[:70]))
    print("\n== TOP RUNTIME FILES BY MARKER RICHNESS ==")
    for h in sorted(hits, key=lambda x: -sum(x["markers"].values()))[:18]:
        print(" %9d %s..%s  %s\n     %s"
              % (h["size"], h["date_min"], h["date_max"],
                 h["path"].replace(DESK, "~")[:78],
                 json.dumps({k: v for k, v in sorted(
                     h["markers"].items(), key=lambda kv: -kv[1])[:8]})))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
