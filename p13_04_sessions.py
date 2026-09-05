# -*- coding: utf-8 -*-
"""
TASK 2 / PHASE 13X - STEP 4: HISTORICAL SESSIONS + WINDOW INPUTS  (READ ONLY)

The locator found per-decision telemetry that carries the two window inputs
directly:  ~\\Dhan Test\\logs\\decisions.jsonl  (phase= and regime_strength,
2026-08-21 .. 2026-09-07)  plus metrics.json counter files across many project
generations and oi_diag streams.

This step, for EVERY available day:
  * parses every decisions*.jsonl completely -> phase / regime_strength / ts
  * parses every metrics*.json  -> cycles / skip_window / other counters + mtime
  * parses every engine*.log    -> start/stop, config events, health, restarts
  * harvests literal configuration values for holidays / timezone /
    evaluation_interval_s wherever they appear in any evidence file
Nothing is inferred; every value is tagged with its source path.

Emits 03_HISTORICAL_SESSION_INDEX.json, 07_RUNTIME_STATE_SEP02.json,
      _sessions_state.json
"""
import json
import os
import re
import time
from collections import Counter, defaultdict

DESK = r"C:\Users\Guest -A\Desktop"
PROJ = os.path.join(DESK, "Dhan Test")
PKG = os.path.join(PROJ, "TASK2_PHASE13_FABLE_PACKAGE")
TS_RE = re.compile(r"20\d\d-\d\d-\d\dT\d\d:\d\d:\d\d")
HOL_RE = re.compile(r"holidays\W{0,4}(\[[^\]]{0,400}\])", re.I)
HOL_YAML = re.compile(r"holidays\s*:\s*\n((?:\s*-\s*[^\n]+\n){1,40})", re.I)
TZ_RE = re.compile(r"timezone\W{0,4}[\"']?([A-Za-z_/+\-0-9]{3,32})[\"']?")
EVI_RE = re.compile(r"evaluation_interval_s\W{0,4}([0-9.]{1,6})")


def load_inventory():
    return json.load(open(os.path.join(PKG, "01_MASTER_INVENTORY.json"),
                          encoding="utf-8"))["files"]


def read_text(p, limit=None):
    with open(p, "rb") as fh:
        raw = fh.read() if limit is None else fh.read(limit)
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", "replace")
    return raw.decode("utf-8", "replace")


def iter_json_lines(p):
    with open(p, "rb") as fh:
        head = fh.read(2)
    enc = "utf-16" if head in (b"\xff\xfe", b"\xfe\xff") else "utf-8"
    with open(p, "r", encoding=enc, errors="replace") as fh:
        for i, line in enumerate(fh, 1):
            line = line.strip()
            if not line or line[0] != "{":
                continue
            try:
                yield i, json.loads(line)
            except ValueError:
                continue


def main():
    files = load_inventory()
    dec_files, met_files, eng_files = [], [], []
    for f in files:
        b = os.path.basename(f["path"]).lower()
        if "TASK2_PHASE13_FABLE_PACKAGE" in f["path"]:
            continue
        if b.startswith("decisions") and f["ext"] in (".jsonl", ".ndjson"):
            dec_files.append(f)
        elif b.startswith("metrics") and f["ext"] == ".json":
            met_files.append(f)
        elif b.startswith("engine") and f["ext"] in (".log", ".txt"):
            eng_files.append(f)

    # ---------- decisions: the only per-cycle carrier of phase+strength -------
    dec_days = defaultdict(lambda: {"records": 0, "phases": Counter(),
                                    "strength": [], "ts_min": None,
                                    "ts_max": None, "keys": Counter(),
                                    "window_fields": Counter(),
                                    "sources": Counter()})
    dec_keys_global = Counter()
    sample = None
    for f in dec_files:
        for ln, rec in iter_json_lines(f["path"]):
            ts = str(rec.get("ts") or rec.get("timestamp") or
                     rec.get("time") or "")
            m = TS_RE.search(ts) or TS_RE.search(json.dumps(rec)[:400])
            day = m.group(0)[:10] if m else "UNKNOWN"
            d = dec_days[day]
            d["records"] += 1
            d["sources"][f["path"]] += 1
            for k in rec:
                d["keys"][k] += 1
                dec_keys_global[k] += 1
            ph = rec.get("phase") or rec.get("session_phase")
            if ph is not None:
                d["phases"][str(ph)] += 1
            rs = rec.get("regime_strength", rec.get("strength_0_100"))
            if isinstance(rs, (int, float)):
                d["strength"].append(rs)
            for wk in ("window_open", "signal_window_open", "skip_window",
                       "window", "reason", "stage", "verdict", "gate"):
                if wk in rec:
                    d["window_fields"][wk] += 1
            if m:
                t = m.group(0)
                d["ts_min"] = t if not d["ts_min"] else min(d["ts_min"], t)
                d["ts_max"] = t if not d["ts_max"] else max(d["ts_max"], t)
            if sample is None:
                sample = {"file": f["path"], "line": ln, "record": rec}

    dec_summary = {}
    for day, d in sorted(dec_days.items()):
        s = sorted(d["strength"])
        dec_summary[day] = {
            "records": d["records"], "ts_min": d["ts_min"],
            "ts_max": d["ts_max"], "phases": dict(d["phases"]),
            "strength_n": len(s),
            "strength_min": s[0] if s else None,
            "strength_med": s[len(s) // 2] if s else None,
            "strength_max": s[-1] if s else None,
            "strength_ge_70": sum(1 for x in s if x >= 70),
            "window_fields": dict(d["window_fields"]),
            "record_keys": dict(d["keys"]),
            "sources": dict(d["sources"])}

    # ---------- metrics counters across every generation ---------------------
    metrics = []
    for f in met_files:
        try:
            j = json.loads(read_text(f["path"]))
        except Exception as e:
            metrics.append({"path": f["path"], "error": str(e)})
            continue
        metrics.append({"path": f["path"], "mtime": f["mtime"],
                        "size": f["size"], "counters": j})

    # ---------- engine logs: session boundaries + config/health events -------
    eng = []
    for f in eng_files:
        txt = read_text(f["path"])
        ts = TS_RE.findall(txt)
        evs = Counter(re.findall(r'"event"\s*:\s*"([a-z_]+)"', txt))
        eng.append({"path": f["path"], "size": f["size"], "mtime": f["mtime"],
                    "lines": txt.count("\n"),
                    "ts_min": min(ts) if ts else None,
                    "ts_max": max(ts) if ts else None,
                    "days": sorted({t[:10] for t in ts}),
                    "events": dict(evs.most_common(25))})

    # ---------- literal configuration values anywhere in the corpus ----------
    cfg_hits = {"holidays": [], "timezone": Counter(),
                "evaluation_interval_s": Counter()}
    for f in files:
        if f["ext"] not in (".json", ".yaml", ".yml", ".txt", ".log", ".md",
                            ".jsonl", ".py", ".ini", ".cfg", ".toml"):
            continue
        if f["size"] > (20 << 20) or "TASK2_PHASE13_FABLE_PACKAGE" in f["path"]:
            continue
        terms = f.get("terms", {})
        if not any(k in terms for k in ("holidays", "timezone",
                                        "evaluation_interval")):
            continue
        try:
            txt = read_text(f["path"], 4 << 20)
        except OSError:
            continue
        for m in HOL_RE.finditer(txt):
            cfg_hits["holidays"].append({"value": m.group(1)[:400],
                                         "source": f["path"],
                                         "kind": "inline_list"})
        for m in HOL_YAML.finditer(txt):
            cfg_hits["holidays"].append({"value": " ".join(
                m.group(1).split())[:400], "source": f["path"],
                "kind": "yaml_block"})
        for m in TZ_RE.finditer(txt):
            cfg_hits["timezone"][m.group(1)] += 1
        for m in EVI_RE.finditer(txt):
            cfg_hits["evaluation_interval_s"][m.group(1)] += 1

    hol_distinct = {}
    for h in cfg_hits["holidays"]:
        hol_distinct.setdefault(h["value"], []).append(h["source"])

    out = {"generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "decisions_files": [f["path"] for f in dec_files],
           "metrics_files": len(met_files), "engine_log_files": len(eng_files),
           "decisions_record_keys_global": dict(dec_keys_global),
           "decisions_sample_record": sample,
           "per_day_decisions": dec_summary,
           "metrics_counters": metrics,
           "engine_logs": eng,
           "config_values_found": {
               "holidays_distinct": {k: sorted(set(v))
                                     for k, v in hol_distinct.items()},
               "timezone_counts": dict(cfg_hits["timezone"].most_common(20)),
               "evaluation_interval_s_counts":
                   dict(cfg_hits["evaluation_interval_s"].most_common(20))}}
    json.dump(out, open(os.path.join(PKG, "03_HISTORICAL_SESSION_INDEX.json"),
                        "w", encoding="utf-8", newline="\n"), indent=1,
              default=str)

    print("decisions_files=%d metrics_files=%d engine_logs=%d"
          % (len(dec_files), len(met_files), len(eng_files)))
    print("decisions keys=%s" % json.dumps(dict(dec_keys_global.most_common(14))))
    if sample:
        print("sample[%s:%d]=%s" % (os.path.basename(sample["file"]),
                                    sample["line"],
                                    json.dumps(sample["record"])[:520]))
    print("\nDAY        REC  TSMIN..TSMAX          STRENGTH(min/med/max,>=70)  PHASES")
    for day, d in sorted(dec_summary.items()):
        print(" %s %5d %s..%s %s/%s/%s,%d %s"
              % (day, d["records"], (d["ts_min"] or "-")[11:19],
                 (d["ts_max"] or "-")[11:19], d["strength_min"],
                 d["strength_med"], d["strength_max"], d["strength_ge_70"],
                 json.dumps(d["phases"])[:60]))
    print("\n== METRICS COUNTER FILES (path | mtime | counters) ==")
    for m in sorted(metrics, key=lambda x: x.get("mtime", "")):
        if "counters" in m:
            print(" %-58s %s %s" % (m["path"].replace(DESK, "~")[-58:],
                                    m["mtime"],
                                    json.dumps(m["counters"])[:150]))
    print("\n== HOLIDAY LITERALS FOUND (%d distinct) ==" % len(hol_distinct))
    for k, v in list(hol_distinct.items())[:12]:
        print(" %s\n     <- %d source(s), e.g. %s"
              % (k[:200], len(v), v[0].replace(DESK, "~")[:80]))
    print("\ntimezone=%s\neval_interval=%s"
          % (json.dumps(dict(cfg_hits["timezone"].most_common(8))),
             json.dumps(dict(cfg_hits["evaluation_interval_s"].most_common(8)))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
