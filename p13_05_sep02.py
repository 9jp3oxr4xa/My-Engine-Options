# -*- coding: utf-8 -*-
"""
TASK 2 / PHASE 13X - STEP 5: WINDOW PREDICATE + SEP-02 LEDGER + CROSS-DAY
(READ ONLY)

Step 4 produced a result that changes the whole question:

  metrics.json                       cycles  skip_window   ticks  bars5m
  2026-08-21 before-24-Aug copy          13           13       1       -
  2026-08-24 Aug-25 copy                 50            0     182       1
  2026-08-25 28-Aug-Raw copy           1972         1024    4135      16
  2026-08-26 audit_bundle              3896         1572       -      52
  2026-08-28 Aug-30-old copy           3624         3624     173       7
  2026-08-31 Aug-31 copy               1521         1521     208       5
  2026-09-01 local logs                 519          519     213       4
  2026-09-02 audit bundle               957          957     162       4

skip_window == cycles is therefore NOT a Sep-02 signature; it also holds on
08-28, 08-31 and 09-01 - and on 08-31/09-01 decisions.jsonl proves the engine
did reach candidate scoring, which is only reachable AFTER the window gate.
That is a hard contradiction and it is what this step measures.

Produces, from the proven live source and from raw records only:
  04_WINDOW_PREDICATE.json         exact predicate, callers, clause ladder
  05_WINDOW_CONTROL_FLOW.txt       literal source, evaluation order preserved
  06_WINDOW_DEPENDENCY_GRAPH.json  every operand traced to its producer
  08_SEP02_COMPLETE_CYCLE_LEDGER.json  every Sep-02 runtime record found
  09_FAILED_RETURN_PATHS.json      per-clause reachability over the real span
  10_HISTORICAL_COMPARISON.json    metrics vs decisions vs OI, per day
"""
import ast
import json
import os
import re
import time
from collections import Counter, defaultdict

DESK = r"C:\Users\Guest -A\Desktop"
PROJ = os.path.join(DESK, "Dhan Test")
PKG = os.path.join(PROJ, "TASK2_PHASE13_FABLE_PACKAGE")
BUNDLE = os.path.join(PROJ, "Audit Bundle Sep 02")
LIVE = os.path.join(BUNDLE, "01_SOURCE", "Dhan.py")
BLOGS = os.path.join(BUNDLE, "02_TODAY_LOGS", "logs")
LLOGS = os.path.join(PROJ, "logs")
TS_RE = re.compile(r"20\d\d-\d\d-\d\dT\d\d:\d\d:\d\d")
WANT_FN = ("signal_window_open", "phase", "is_trading_day", "_evaluate_inner",
           "_evaluate", "_run_cycle", "_cycle_loop")


def read(p, limit=None):
    with open(p, "rb") as fh:
        raw = fh.read() if limit is None else fh.read(limit)
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", "replace")
    if raw[:3] == b"\xef\xbb\xbf":
        return raw[3:].decode("utf-8", "replace")
    return raw.decode("utf-8", "replace")


def jl(p):
    for i, line in enumerate(read(p).splitlines(), 1):
        s = line.strip()
        if s.startswith("{"):
            try:
                yield i, json.loads(s)
            except ValueError:
                continue


# ---------------------------------------------------------------- window model
def window_model(src):
    tree = ast.parse(src)
    lines = src.splitlines()
    fns, calls, phases = {}, [], None
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and \
                n.name in WANT_FN:
            fns.setdefault(n.name, []).append(
                {"span": [n.lineno, n.end_lineno],
                 "source": [lines[i - 1] for i in range(n.lineno,
                                                        n.end_lineno + 1)]})
        if isinstance(n, ast.Call):
            f = n.func
            name = getattr(f, "attr", getattr(f, "id", None))
            if name in ("signal_window_open", "is_trading_day", "phase"):
                calls.append({"callee": name, "line": n.lineno,
                              "source": lines[n.lineno - 1].strip(),
                              "args": [ast.unparse(a) for a in n.args]})
        if isinstance(n, ast.Assign) and any(
                getattr(t, "id", "") == "PHASES" for t in n.targets):
            phases = {"line": n.lineno, "source": ast.unparse(n)}
    # clause ladder of signal_window_open, in real evaluation order
    ladder = []
    swo = [x for x in ast.walk(tree)
           if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef))
           and x.name == "signal_window_open"][0]
    for st in ast.walk(swo):
        if isinstance(st, ast.If):
            ladder.append({"line": st.lineno,
                           "test": ast.unparse(st.test),
                           "body": [ast.unparse(b) for b in st.body],
                           "short_circuit_ops": [type(o).__name__ for o in
                                                 ast.walk(st.test)
                                                 if isinstance(o, ast.BoolOp)]})
    ladder.sort(key=lambda d: d["line"])
    returns = [{"line": r.lineno, "value": ast.unparse(r.value) if r.value
                else None}
               for r in ast.walk(swo) if isinstance(r, ast.Return)]
    returns.sort(key=lambda d: d["line"])
    return fns, calls, phases, ladder, returns


def main():
    src = read(LIVE)
    fns, calls, phases, ladder, returns = window_model(src)

    # ---- operand dependency graph (traced to producer, from source only) ----
    dep = {
        "now": {"expression": "now.astimezone(IST)",
                "producer": "argument passed by Engine._evaluate_inner",
                "call_site": [c for c in calls
                              if c["callee"] == "signal_window_open"],
                "upstream": "clock.now() -> see 07_RUNTIME_STATE_SEP02.json",
                "class": "clock"},
        "regime_strength": {"expression": "regime_strength >= 70 (MIDDAY only)",
                            "producer": "st.regime.state.strength_0_100",
                            "class": "runtime state",
                            "affects_clauses": ["MIDDAY"]},
        "self.holidays": {"expression": "d not in self.holidays",
                          "producer": "SessionCalendar(cfg.engine.holidays)",
                          "class": "configuration",
                          "affects_clauses": ["ALL (via is_trading_day)"]},
        "d.weekday()": {"expression": "d.weekday() >= 5",
                        "producer": "calendar date of now",
                        "class": "clock/derived"},
        "PHASES": {"expression": "start <= t < end", "producer": "class literal",
                   "class": "literal", "source": phases},
    }

    # -------------------------------- Sep-02 raw runtime records --------------
    sep = {"engine_log_events": [], "oi_polls": [], "oi_candidates": [],
           "other_files": []}
    elog = os.path.join(BLOGS, "engine.log")
    if os.path.exists(elog):
        for i, line in enumerate(read(elog).splitlines(), 1):
            s = line.strip()
            if not s:
                continue
            rec = None
            if s.startswith("{"):
                try:
                    rec = json.loads(s)
                except ValueError:
                    rec = None
            ts = (TS_RE.search(s).group(0) if TS_RE.search(s) else None)
            sep["engine_log_events"].append(
                {"line": i, "ts": ts, "raw": s[:400],
                 "event": (rec or {}).get("event"),
                 "level": (rec or {}).get("level"),
                 "fields": {k: v for k, v in (rec or {}).items()
                            if k not in ("event", "level", "ts")}})
    oi = os.path.join(BLOGS, "oi_diag.jsonl")
    if os.path.exists(oi):
        for ln, rec in jl(oi):
            ts = str(rec.get("ts", ""))
            if not ts.startswith("2026-09-02"):
                continue
            row = {"line": ln, "ts": ts, "type": rec.get("type"),
                   "underlying": rec.get("underlying"),
                   "spot": rec.get("spot"), "atm": rec.get("atm"),
                   "verdict": rec.get("verdict"),
                   "informative_obs": rec.get("informative_obs"),
                   "z_ce": rec.get("z_ce"), "z_pe": rec.get("z_pe")}
            if rec.get("type") == "oi_candidate":
                row["direction"] = rec.get("direction")
                sep["oi_candidates"].append(row)
            else:
                sep["oi_polls"].append(row)

    poll_ts = [r["ts"] for r in sep["oi_polls"]]
    gaps = []
    for a, b in zip(poll_ts, poll_ts[1:]):
        try:
            ta = time.mktime(time.strptime(a[:19], "%Y-%m-%dT%H:%M:%S"))
            tb = time.mktime(time.strptime(b[:19], "%Y-%m-%dT%H:%M:%S"))
            gaps.append(int(tb - ta))
        except ValueError:
            pass
    gapc = Counter(gaps)

    met = json.loads(read(os.path.join(BLOGS, "metrics.json")))
    span_s = None
    if poll_ts:
        span_s = int(time.mktime(time.strptime(poll_ts[-1][:19],
                                              "%Y-%m-%dT%H:%M:%S"))
                     - time.mktime(time.strptime(poll_ts[0][:19],
                                                 "%Y-%m-%dT%H:%M:%S")))
    cycles = met["counters"].get("cycles")
    ledger = {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "per_cycle_records_exist": False,
        "why_no_per_cycle_records":
            "the live source increments a bare counter at Dhan.py:5005 "
            "(metrics.inc('skip_window')) and emits no record; the "
            "SIGNAL_WINDOW_CLOSED sentinel that would emit one exists only in "
            "the forensic build (see 13_TASK1_TASK2_LINEAGE.json)",
        "counters_epoch": {"file": os.path.join(BLOGS, "metrics.json"),
                           "file_mtime": time.strftime(
                               "%Y-%m-%dT%H:%M:%S", time.localtime(
                                   os.path.getmtime(os.path.join(
                                       BLOGS, "metrics.json")))),
                           "counters": met["counters"],
                           "rejections_by_reason": met.get(
                               "rejections_by_reason"),
                           "cycles": cycles,
                           "skip_window": met["counters"].get("skip_window")},
        "observed_session_span_from_oi": {
            "first_poll": poll_ts[0] if poll_ts else None,
            "last_poll": poll_ts[-1] if poll_ts else None,
            "span_seconds": span_s, "polls": len(poll_ts),
            "poll_gap_histogram_top": dict(gapc.most_common(8))},
        "cycle_budget_arithmetic": {
            "cycles_counted": cycles,
            "session_span_seconds": span_s,
            "implied_seconds_per_cycle": (round(span_s / cycles, 2)
                                          if cycles and span_s else None),
            "config_evaluation_interval_s_evidence":
                "5 (config.yaml literal, see 03_HISTORICAL_SESSION_INDEX.json)",
            "cycles_expected_if_5s": (int(span_s / 5) if span_s else None),
            "interpretation_status": "OBSERVED counters vs OBSERVED span; the "
                                     "epoch boundaries of metrics.json are "
                                     "UNKNOWN (no timestamps in the file)"},
        "engine_log_event_counts": dict(Counter(
            e["event"] for e in sep["engine_log_events"] if e["event"])),
        "engine_log_first_ts": next((e["ts"] for e in sep["engine_log_events"]
                                     if e["ts"]), None),
        "engine_log_last_ts": next((e["ts"] for e in
                                    reversed(sep["engine_log_events"])
                                    if e["ts"]), None),
        "oi_candidates_on_sep02": len(sep["oi_candidates"]),
        "records": sep}
    json.dump(ledger, open(os.path.join(
        PKG, "08_SEP02_COMPLETE_CYCLE_LEDGER.json"), "w", encoding="utf-8",
        newline="\n"), indent=1, default=str)

    # ------------------------------- clause reachability ---------------------
    reach = {"session_span": [poll_ts[0] if poll_ts else None,
                              poll_ts[-1] if poll_ts else None],
             "clauses": [
                 {"clause": "is_trading_day False -> return False",
                  "source_line": 597,
                  "requires": "weekday>=5 or date in engine.holidays",
                  "sep02_weekday": "Wednesday (weekday()==2)",
                  "status_on_sep02": "UNKNOWN - engine.holidays runtime value "
                                     "not recoverable; see PART 9 record",
                  "counter_evidence": "health_degraded requires market_open "
                                      "(live line 4400) and market_open is "
                                      "False when phase is CLOSED (4382); "
                                      "engine.log records health_degraded on "
                                      "2026-09-02, so phase() was not CLOSED "
                                      "at those timestamps, which is only "
                                      "possible if is_trading_day was True"},
                 {"clause": "phase PRE_OPEN/CLOSED -> return False",
                  "source_line": 611,
                  "requires": "t < 09:00 or t >= 15:30 or non-trading day",
                  "status_on_sep02": "TRUE for any cycle outside 09:00-15:30; "
                                     "the OI stream proves the process was "
                                     "alive 10:00:59-15:29:47 and metrics.json "
                                     "was written 16:58:24, so post-close "
                                     "cycles certainly existed"},
                 {"clause": "OPENING and t < 09:21 -> False",
                  "source_line": 602, "requires": "09:15 <= t < 09:21",
                  "status_on_sep02": "UNREACHABLE for the observed span "
                                     "(first evidence 10:00:59)"},
                 {"clause": "MORNING -> True", "source_line": 604,
                  "requires": "09:45 <= t < 11:30",
                  "status_on_sep02": "would return TRUE for 10:00:59-11:30 - "
                                     "contradicts skip_window == cycles if the "
                                     "counter epoch covered the session"},
                 {"clause": "MIDDAY -> regime_strength >= 70",
                  "source_line": 608, "requires": "11:30 <= t < 13:30",
                  "status_on_sep02": "regime_strength UNKNOWN for Sep-02 (no "
                                     "record); with 4 five-minute bars a "
                                     "strength >= 70 is not established"},
                 {"clause": "AFTERNOON -> True", "source_line": 606,
                  "requires": "13:30 <= t < 14:45",
                  "status_on_sep02": "would return TRUE - same contradiction"},
                 {"clause": "CLOSING -> t < 15:00", "source_line": 610,
                  "requires": "14:45 <= t < 15:30",
                  "status_on_sep02": "TRUE until 15:00, False 15:00-15:30"}]}
    json.dump(reach, open(os.path.join(PKG, "09_FAILED_RETURN_PATHS.json"), "w",
                          encoding="utf-8", newline="\n"), indent=1,
              default=str)

    # ------------------------------- cross-day comparison --------------------
    hist = json.load(open(os.path.join(PKG, "03_HISTORICAL_SESSION_INDEX.json"),
                          encoding="utf-8"))
    per_day = defaultdict(dict)
    for m in hist["metrics_counters"]:
        if "counters" not in m:
            continue
        day = m["mtime"][:10]
        c = m["counters"].get("counters", m["counters"])
        per_day[day].setdefault("metrics", []).append(
            {"file": m["path"], "mtime": m["mtime"], "cycles": c.get("cycles"),
             "skip_window": c.get("skip_window"),
             "skip_warmup": c.get("skip_warmup"),
             "skip_degraded": c.get("skip_degraded"),
             "skip_stale": c.get("skip_stale"),
             "bars_5m": c.get("bars_5m"), "ticks": c.get("ticks_ingested"),
             "structure_events": c.get("structure_events"),
             "telegram_sent": c.get("telegram_sent"),
             "fyers_reconnects": c.get("fyers_reconnects"),
             "pct_skipped": (round(100.0 * c.get("skip_window", 0)
                                   / c["cycles"], 1) if c.get("cycles")
                             else None)})
    for day, d in hist["per_day_decisions"].items():
        per_day[day]["decisions"] = {"records": d["records"],
                                     "ts_min": d["ts_min"],
                                     "ts_max": d["ts_max"],
                                     "stages": d.get("window_fields")}
    # OI rows per day from both streams
    for stream in (os.path.join(BLOGS, "oi_diag.jsonl"),
                   os.path.join(LLOGS, "oi_diag.jsonl")):
        if not os.path.exists(stream):
            continue
        cnt = Counter()
        cand = Counter()
        for _, rec in jl(stream):
            ts = str(rec.get("ts", ""))[:10]
            if not ts.startswith("2026"):
                continue
            cnt[ts] += 1
            if rec.get("type") == "oi_candidate":
                cand[ts] += 1
        for day in cnt:
            per_day[day].setdefault("oi_streams", []).append(
                {"stream": stream, "rows": cnt[day], "candidates": cand[day]})

    comp = {"generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "per_day": {k: per_day[k] for k in sorted(per_day)},
            "key_observation":
                "skip_window == cycles occurs on 2026-08-28, 08-31, 09-01 and "
                "09-02. On 08-31 and 09-01 decisions.jsonl contains scored "
                "candidates, which are only reachable downstream of the window "
                "gate; therefore a 100% skip_window counter does NOT prove the "
                "window was closed for the whole session on those days, and by "
                "the same reasoning it does not prove it for 09-02.",
            "sep02_distinguishing_facts":
                ["decisions.jsonl contains 0 records for 2026-09-02 "
                 "(08-31: 150, 09-01: 204)",
                 "ticks_ingested 162 and bars_5m 4 in the Sep-02 counter epoch",
                 "6 fyers_reconnects and repeated lost-connection warnings in "
                 "engine.log on 09-02",
                 "OI poller healthy all session (659 rows, 58 bearish / 49 "
                 "bullish verdicts) - so the OI layer is not the constraint"]}
    json.dump(comp, open(os.path.join(PKG, "10_HISTORICAL_COMPARISON.json"),
                         "w", encoding="utf-8", newline="\n"), indent=1,
              default=str)

    # ------------------------------- window artifacts ------------------------
    json.dump({"generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
               "source": {"path": LIVE},
               "functions": fns, "callers": calls, "PHASES": phases,
               "clause_ladder_in_evaluation_order": ladder,
               "returns_in_source_order": returns},
              open(os.path.join(PKG, "04_WINDOW_PREDICATE.json"), "w",
                   encoding="utf-8", newline="\n"), indent=1, default=str)
    with open(os.path.join(PKG, "05_WINDOW_CONTROL_FLOW.txt"), "w",
              encoding="utf-8", newline="\n") as fh:
        fh.write("EXACT PRODUCTION CONTROL FLOW - copied verbatim from\n%s\n"
                 "(no paraphrase, evaluation order preserved)\n\n" % LIVE)
        for name in ("signal_window_open", "phase", "is_trading_day",
                     "_evaluate_inner"):
            for d in fns.get(name, []):
                fh.write("=" * 70 + "\n%s  lines %d-%d\n" % (name, d["span"][0],
                                                             d["span"][1])
                         + "=" * 70 + "\n")
                for i, l in enumerate(d["source"], d["span"][0]):
                    fh.write("%5d| %s\n" % (i, l))
                fh.write("\n")
        fh.write("=" * 70 + "\nCALL SITES\n" + "=" * 70 + "\n")
        for c in calls:
            fh.write("%5d| %-18s %s\n" % (c["line"], c["callee"], c["source"]))
    json.dump({"generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
               "operands": dep,
               "note": "every operand traced to literal / clock / config / "
                       "runtime state; no operand value invented"},
              open(os.path.join(PKG, "06_WINDOW_DEPENDENCY_GRAPH.json"), "w",
                   encoding="utf-8", newline="\n"), indent=1, default=str)

    print("window fns=%s ladder=%d returns=%d callers=%d"
          % (list(fns), len(ladder), len(returns), len(calls)))
    print("sep02: engine_log_lines=%d oi_polls=%d oi_candidates=%d span=%ss"
          % (len(sep["engine_log_events"]), len(sep["oi_polls"]),
             len(sep["oi_candidates"]), span_s))
    print("sep02 poll gaps top=%s" % json.dumps(dict(gapc.most_common(6))))
    print("cycles=%s implied_s_per_cycle=%s expected_if_5s=%s"
          % (cycles, ledger["cycle_budget_arithmetic"]
             ["implied_seconds_per_cycle"],
             ledger["cycle_budget_arithmetic"]["cycles_expected_if_5s"]))
    print("engine.log events=%s" % json.dumps(
        ledger["engine_log_event_counts"]))
    print("\nDAY        CYC  SKIPW  %%SKIP TICKS BARS DEC  OIROWS OICAND")
    for day in sorted(per_day):
        m = (per_day[day].get("metrics") or [{}])[0]
        d = per_day[day].get("decisions") or {}
        o = per_day[day].get("oi_streams") or []
        print(" %s %5s %6s %6s %5s %4s %4s %6s %6s"
              % (day, m.get("cycles"), m.get("skip_window"),
                 m.get("pct_skipped"), m.get("ticks"), m.get("bars_5m"),
                 d.get("records"), sum(x["rows"] for x in o) or None,
                 sum(x["candidates"] for x in o) or None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
