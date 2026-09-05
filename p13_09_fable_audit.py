# -*- coding: utf-8 -*-
"""
NUCLEAR OPUS 5 - TASK 2 FINAL EVIDENCE DISTILLATION
master corpus (139 MB, base64) -> ONE readable audit file <= 9,000,000 bytes

Input  : TASK2_PHASE13_FABLE_PACKAGE_COMPLETE.txt   (read only, never written)
Output : TASK2_FABLE_FINAL_AUDIT.txt                (plain UTF-8, no base64)

Everything emitted is decoded out of the master corpus and sha-verified on the
way in. Nothing is paraphrased where a raw record exists. Unrecoverable facts
are emitted as MISSING_FACT records, never as guesses.
"""
import ast
import base64
import hashlib
import io
import json
import os
import re
import time
from collections import Counter, defaultdict

PROJ = r"C:\Users\Guest -A\Desktop\Dhan Test"
CORPUS = os.path.join(PROJ, "TASK2_PHASE13_FABLE_PACKAGE_COMPLETE.txt")
OUT = os.path.join(PROJ, "TASK2_FABLE_FINAL_AUDIT.txt")
SIDE = OUT + ".verification.json"
P12 = os.path.join(PROJ, "TASK2_PHASE12_FINAL_REPORT.md")
HARD = 9_500_000
TARGET = 9_000_000
SRC_BUDGET = 2_600_000

LIVE = r"18_RAW_EVIDENCE\sep02_live_source\Dhan.py"
ELOG = r"18_RAW_EVIDENCE\sep02_bundle_logs\engine.log"
OIDIAG = r"18_RAW_EVIDENCE\sep02_bundle_logs\oi_diag.jsonl"
SEPMET = r"18_RAW_EVIDENCE\sep02_bundle_logs\metrics.json"
DEC = r"18_RAW_EVIDENCE\local_logs\decisions.jsonl"

CATS = [
    ("FEED_FYERS", 1, r"fyers|websock|ws_|on_message|on_error|on_close|"
                      r"resubscrib|subscrib|reconnect|_connect"),
    ("TICK_PATH", 1, r"tick|ingest|on_quote|on_ltp"),
    ("BAR_BUILD", 1, r"bar|candle|ohlc|five|_5m"),
    ("UNDERLYING_STATE", 1, r"underlying|spot|snapshot|state_update|"
                            r"update_state|warmup|bootstrap"),
    ("WINDOW_GATE", 0, r"signal_window_open|^phase$|is_trading_day|"
                       r"market_open|session|holiday|calendar"),
    ("CYCLE_EVAL", 0, r"_evaluate|_cycle|_run_cycle|_loop$"),
    ("STRUCTURE", 1, r"structure|swing|bos|choch|regime|trend"),
    ("CANDIDATE", 1, r"candidate|confluence|score|trigger|ledger|direction"),
    ("HEALTH", 1, r"health|degrad|stale|watchdog|supervis|monitor|freshness"),
    ("OI", 2, r"\boi\b|oi_|open_interest|chain|atm|expiry"),
    ("DECISION_LOG", 1, r"decision|metrics|telegram|alert|emit|inc\b"),
]


def sha(b):
    return hashlib.sha256(b).hexdigest()


class Corpus(object):
    def __init__(self, path):
        self.fh = open(path, "rb")
        head = self.fh.read(4_000_000)
        m = re.search(rb"BEGIN_MASTER_MANIFEST\n(.*?)END_MASTER_MANIFEST",
                      head, re.S)
        if not m:
            raise SystemExit("corpus manifest not found")
        self.files = {}
        for blk in m.group(1).split(b"\n\n"):
            d = dict(re.findall(rb"^([A-Z0-9_]+)=(.*)$", blk, re.M))
            if b"RELATIVE_PATH" not in d:
                continue
            rel = d[b"RELATIVE_PATH"].decode("utf-8")
            self.files[rel] = {
                "id": int(d[b"FILE_ID"]), "rel": rel,
                "size": int(d[b"ORIGINAL_BYTE_LENGTH"]),
                "sha256": d[b"SHA256"].decode(),
                "type": d[b"TYPE"].decode(),
                "enc": d[b"TEXT_ENCODING_DETECTED"].decode(),
                "begin": int(d[b"BASE64_PAYLOAD_BEGIN_OFFSET"]),
                "end": int(d[b"BASE64_PAYLOAD_END_OFFSET"])}
        self.header = head[:m.start()]

    def mtime(self, rel):
        e = self.files[rel]
        self.fh.seek(max(0, e["begin"] - 600))
        pre = self.fh.read(600)
        m = re.search(rb"SOURCE_MTIME=([0-9T:\-]+)", pre)
        return m.group(1).decode() if m else "UNKNOWN"

    def get(self, rel):
        e = self.files[rel]
        self.fh.seek(e["begin"])
        raw = self.fh.read(e["end"] - e["begin"])
        data = base64.b64decode(raw.replace(b"\n", b""), validate=True)
        if len(data) != e["size"] or sha(data) != e["sha256"]:
            raise SystemExit("corpus integrity failure on %s" % rel)
        return data

    def text(self, rel):
        b = self.get(rel)
        for enc in ("utf-8-sig", "utf-16", "utf-8"):
            try:
                return b.decode(enc)
            except UnicodeDecodeError:
                continue
        return b.decode("utf-8", "replace")


def jrows(txt):
    for i, line in enumerate(txt.splitlines(), 1):
        s = line.strip()
        if s.startswith("{"):
            try:
                yield i, s, json.loads(s)
            except ValueError:
                continue


def tier_of(rel, typ):
    r = rel.lower()
    if r.endswith(("sep02_live_source\\dhan.py", "sep02_bundle_logs\\engine.log",
                   "sep02_bundle_logs\\metrics.json",
                   "sep02_bundle_logs\\oi_diag.jsonl")) or \
            r.endswith("08_sep02_complete_cycle_ledger.json") or \
            r.endswith("local_logs\\decisions.jsonl"):
        return 0, "load-bearing Sep-02 causal evidence or live source"
    if re.search(r"0[4567]_|09_|10_|1[2-7]_|20_", rel) and typ == "JSON":
        return 1, "direct analytical artifact over raw evidence"
    if "metrics_generations" in r or "decisions_generations" in r:
        return 2, "historical control (per-day counters / scored candidates)"
    if "source_generations" in r:
        return 2, "lineage control (predicate byte-comparison population)"
    if r.endswith("config.yaml"):
        return 1, "config literal evidence (holidays / timezone / interval)"
    if r.endswith(("01_master_inventory.json", "02_source_lineage.json",
                   "_discovery_state.json", "_lineage_state.json",
                   "_runtime_state.json")):
        return 3, "inventory / intermediate state, claims covered elsewhere"
    if r.endswith(("oi_live.log", "local_logs\\oi_diag.jsonl",
                   "local_logs\\engine.log", "local_logs\\metrics.json")):
        return 2, "non-Sep02 runtime stream, control value only"
    return 3, "contextual"


def extract_functions(src, path_sha, budget):
    tree = ast.parse(src)
    lines = src.splitlines()
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for ch in node.body:
            if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)):
                found.append(("%s.%s" % (node.name, ch.name), ch.name, ch))
    for ch in tree.body:
        if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)):
            found.append((ch.name, ch.name, ch))
    picked, seen = [], set()
    for cat, prio, pat in CATS:
        rx = re.compile(pat, re.I)
        for qual, name, node in found:
            if (qual, node.lineno) in seen:
                continue
            if rx.search(name) or rx.search(qual):
                seen.add((qual, node.lineno))
                picked.append({"cat": cat, "prio": prio, "qual": qual,
                               "start": node.lineno, "end": node.end_lineno,
                               "src": "\n".join(lines[node.lineno - 1:
                                                      node.end_lineno])})
    picked.sort(key=lambda d: (d["prio"], d["cat"], d["start"]))
    out, used, dropped = [], 0, []
    for p in picked:
        n = len(p["src"].encode("utf-8")) + 220
        if used + n > budget:
            dropped.append(p)
            continue
        used += n
        out.append(p)
    return out, dropped, used


def main():
    t0 = time.time()
    C = Corpus(CORPUS)
    corpus_sha, corpus_n = None, os.path.getsize(CORPUS)
    h = hashlib.sha256()
    with open(CORPUS, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 22), b""):
            h.update(b)
    corpus_sha = h.hexdigest()

    W = io.StringIO()
    A = W.write

    def sec(n, title):
        A("\n" + "=" * 78 + "\n[%s] %s\n" % (n, title) + "=" * 78 + "\n")

    # ---------------------------------------------------------------- inputs
    live_src = C.text(LIVE)
    live_meta = C.files[LIVE]
    elog_txt = C.text(ELOG)
    sep_met_raw = C.text(SEPMET)
    sep_met = json.loads(sep_met_raw)
    oi_txt = C.text(OIDIAG)
    dec_txt = C.text(DEC)

    # ------------------------------------------------------------ [1] dossier
    A("FABLE 5 ROOT-CAUSE DOSSIER - TASK 2 / SEP-02 ZERO-SIGNAL SESSION\n")
    A("GENERATED_AT=%s\n" % time.strftime("%Y-%m-%dT%H:%M:%S"))
    A("DISTILLED_FROM=%s\n" % CORPUS)
    A("SOURCE_CORPUS_BYTES=%d\nSOURCE_CORPUS_SHA256=%s\n"
      % (corpus_n, corpus_sha))
    A("SOURCE_CORPUS_FILE_COUNT=%d\n" % len(C.files))
    A("ENCODING=UTF-8 PLAIN TEXT (no base64; every record below is literal)\n")
    A("EVIDENCE_STATUS_VOCABULARY=OBSERVED|RECOVERED|DERIVED|UNKNOWN\n")
    A("""
MISSION
 Determine why 2026-09-02 produced zero trading signals, fix the causal
 boundary with the smallest safe change, and prove it with regression
 controls. This file is the complete evidence base; no further collection
 round is required.

CURRENT STATUS
 The prior theory ("the signal window was closed all session", inferred from
 skip_window == cycles == 957) is REFUTED as a session-wide claim. The
 leading hypothesis is upstream market-data starvation, which is supported by
 several independent observations but is NOT yet proven end to end, because
 the live build records no per-cycle window state and no bar-level records.

PROVEN FACTS (each carries a CLAIM_ID in section [16])
 1 The Sep-02 process ran continuously 10:00:59 -> 15:29:47 (659 OI polls,
   ~30 s cadence). Clock advance is OBSERVED.
 2 The FYERS feed failed repeatedly that session: 5 fyers_error,
   6 fyers_resubscribe_after_drop, 7 health_degraded / 7 health_recovered.
 3 The Sep-02 counter epoch shows ticks_ingested=162 and bars_5m=4.
 4 decisions.jsonl contains ZERO rows dated 2026-09-02, against 150 rows on
   08-31 and 204 rows on 09-01.
 5 oi_diag contains ZERO oi_candidate rows on 2026-09-02: nothing upstream
   ever presented a candidate to the OI layer.
 6 skip_window == cycles also occurs on 08-28, 08-31 and 09-01, and on 08-31
   / 09-01 scored candidates exist. A 100% skip_window ratio therefore cannot
   mean the session was blocked at the window gate.
 7 metrics.json carries no epoch boundaries, is overwritten by the last
   process to run, and the Sep-02 copy was written 86 minutes after close.
 8 The window predicate is byte-identical across the overwhelming majority of
   477 engine copies and unchanged since 2026-08-17.

CURRENT ROOT-CAUSE HYPOTHESIS
 FEED_STARVATION_UPSTREAM_OF_CANDIDATE: FYERS drops starved the tick stream,
 which starved 5-minute bar construction, which left the structure layer
 without the swing series needed to emit a candidate; with no candidate, no
 OI check, no scoring, no decision row, no alert.

EVIDENCE SUPPORTING IT
 facts 2,3,4,5 above, plus the historical contrast in section [9]: the two
 comparison days with scored candidates carried materially different tick and
 bar counts in their own counter epochs.

EVIDENCE AGAINST IT / STILL OPEN
 The arrow "bars_5m=4 -> structure produced no swing -> no candidate" is
 INFERRED from source structure, not observed: no bar records and no
 structure-state records exist for Sep-02. The counter epoch that reports
 ticks=162 / bars=4 has unknown boundaries, so those two numbers cannot yet
 be pinned to the session window with certainty. Both gaps are recorded as
 MISSING_FACT entries in section [17], with the exact instrumentation that
 would close them.

UNKNOWN / UNPROVEN ELEMENTS
 per-cycle window result on Sep-02; regime_strength series on Sep-02;
 resolved engine.holidays for the Sep-02 process; metrics epoch boundaries;
 bar-level records for Sep-02.

EXACT SOURCE LOCATIONS  -> sections [3], [8], [14]
EXACT PATCH READINESS   -> section [14]
REQUIRED VALIDATION     -> section [15]
""")

    # -------------------------------------------------------- [2] lineage
    sec("2", "SOURCE LINEAGE / WHICH BUILD RAN")
    A("LIVE_SOURCE_RELATIVE_PATH=%s\n" % LIVE)
    A("LIVE_SOURCE_SHA256=%s\nLIVE_SOURCE_BYTES=%d\nLIVE_SOURCE_MTIME=%s\n"
      % (live_meta["sha256"], live_meta["size"], C.mtime(LIVE)))
    A("LIVE_SOURCE_LINES=%d\n" % len(live_src.splitlines()))
    A("PROVENANCE=copied verbatim from 'Audit Bundle Sep 02\\01_SOURCE\\"
      "Dhan.py', the build captured for the 2026-09-02 session\n")
    lin = json.loads(C.text("13_TASK1_TASK2_LINEAGE.json"))
    A("\nWINDOW_PREDICATE_VARIANT_GROUPS (byte-distinct forms across all "
      "engine copies found on the machine):\n")
    A(json.dumps(lin.get("window_predicate_groups"), indent=1) + "\n")
    A("VARIANT_COUNT=%s DISTINCT_FILE_SHA256=%s\n"
      % (lin.get("variant_count"), lin.get("distinct_sha256")))
    A("INSTRUMENTATION_SPLIT=%s\n"
      % json.dumps(lin.get("instrumentation_split"), indent=1))
    gens = sorted(r for r in C.files if "source_generations" in r)
    A("\nENGINE_SOURCE_GENERATIONS_PRESERVED=%d (timestamp_sha8_name)\n"
      % len(gens))
    for r in gens:
        A("GEN %s BYTES=%d SHA256=%s\n" % (os.path.basename(r),
                                           C.files[r]["size"],
                                           C.files[r]["sha256"]))

    # ------------------------------------------------ [3] load-bearing source
    sec("3", "LOAD-BEARING PRODUCTION SOURCE (complete functions, verbatim)")
    fns, dropped, used = extract_functions(live_src, live_meta["sha256"],
                                           SRC_BUDGET)
    A("SOURCE_FILE=%s\nSOURCE_SHA256=%s\nFUNCTIONS_INCLUDED=%d\n"
      "FUNCTIONS_DEFERRED=%d BYTES_USED=%d\n"
      % (LIVE, live_meta["sha256"], len(fns), len(dropped), used))
    A("RULE=每 function is emitted whole; no truncation, no paraphrase.\n"
      .replace("每", "each "))
    for p in fns:
        A("\n-- BEGIN_FUNCTION\nCATEGORY=%s\nSOURCE_FILE=%s\nSHA256=%s\n"
          "FUNCTION=%s\nLINE_START=%d\nLINE_END=%d\nCOMPLETE_SOURCE_TEXT:\n"
          % (p["cat"], LIVE, live_meta["sha256"], p["qual"], p["start"],
             p["end"]))
        A(p["src"] + "\n-- END_FUNCTION\n")
    if dropped:
        A("\nDEFERRED_FUNCTIONS (not emitted for budget; locate by line range "
          "in the recorded SHA256 build):\n")
        for p in dropped:
            A("DEFERRED CATEGORY=%s FUNCTION=%s LINES=%d-%d\n"
              % (p["cat"], p["qual"], p["start"], p["end"]))

    # ---------------------------------------------------- [4] feed timeline
    sec("4", "SEP-02 FEED TIMELINE (every engine.log record, verbatim)")
    A("SOURCE_FILE=%s\nSOURCE_SHA256=%s\nBYTES=%d\nRECORD_COUNT=%d\n"
      "EVIDENCE_STATUS=OBSERVED\n"
      % (ELOG, C.files[ELOG]["sha256"], C.files[ELOG]["size"],
         len([l for l in elog_txt.splitlines() if l.strip()])))
    ev = Counter()
    for line in elog_txt.splitlines():
        s = line.strip()
        if not s:
            continue
        m = re.search(r'"event"\s*:\s*"([^"]+)"', s)
        if m:
            ev[m.group(1)] += 1
    A("EVENT_HISTOGRAM=%s\n\n" % json.dumps(dict(ev.most_common())))
    for i, line in enumerate(elog_txt.splitlines(), 1):
        if line.strip():
            A("ELOG:%03d| %s\n" % (i, line.rstrip()))
    A("\nCAUSAL_SIGNIFICANCE: fyers_error and fyers_resubscribe_after_drop "
      "mark feed loss; health_degraded / health_recovered mark the engine's "
      "own view of feed usability; the degrade branch in production requires "
      "market_open, so their presence also proves phase() was not CLOSED at "
      "those timestamps.\n")

    # -------------------------------------------------------- [5] bar evidence
    sec("5", "SEP-02 BAR / TICK EVIDENCE")
    A("SOURCE_FILE=%s\nSOURCE_SHA256=%s\nFILE_MTIME=%s\nRAW_CONTENT:\n%s\n"
      % (SEPMET, C.files[SEPMET]["sha256"], C.mtime(SEPMET),
         sep_met_raw.strip()))
    A("\nTICKS_INGESTED=%s  EVIDENCE_STATUS=OBSERVED (counter, epoch unknown)\n"
      % sep_met["counters"].get("ticks_ingested"))
    A("BARS_5M=%s  EVIDENCE_STATUS=OBSERVED (counter, epoch unknown)\n"
      % sep_met["counters"].get("bars_5m"))
    A("PER_BAR_RECORDS=NONE  EVIDENCE_STATUS=UNKNOWN\n")
    A("MISSING_5M_INTERVALS=NOT_DETERMINABLE - the live build emits no bar "
      "record, only a counter; a 09:15-15:30 session contains 75 five-minute "
      "intervals, and only the count 4 is recorded, so which 4 closed cannot "
      "be recovered. See MISSING_FACT MF-002 in section [17].\n")
    A("TICK_GAP_BOUNDARIES=NOT_DETERMINABLE from surviving records; the "
      "closest available proxy is the OI poll cadence in section [6], which "
      "measures process liveness rather than tick arrival.\n")

    # ---------------------------------------------------- [6] pipeline evidence
    sec("6", "SEP-02 PIPELINE EVIDENCE (OI polls = process liveness control)")
    polls, cands = [], []
    for ln, raw, rec in jrows(oi_txt):
        ts = str(rec.get("ts", ""))
        if not ts.startswith("2026-09-02"):
            continue
        if rec.get("type") == "oi_candidate":
            cands.append((ln, raw, rec))
        else:
            polls.append((ln, raw, rec))
    A("SOURCE_FILE=%s\nSOURCE_SHA256=%s\nSEP02_POLL_ROWS=%d\n"
      "SEP02_OI_CANDIDATE_ROWS=%d\nEVIDENCE_STATUS=OBSERVED\n"
      % (OIDIAG, C.files[OIDIAG]["sha256"], len(polls), len(cands)))
    if polls:
        A("FIRST_POLL_TS=%s\nLAST_POLL_TS=%s\n"
          % (polls[0][2]["ts"], polls[-1][2]["ts"]))
        A("\nVERBATIM_FIRST_3:\n")
        for _, raw, _ in polls[:3]:
            A(raw + "\n")
        A("VERBATIM_LAST_3:\n")
        for _, raw, _ in polls[-3:]:
            A(raw + "\n")
        A("\nCOMPACT_POLL_LEDGER ts|underlying|spot|atm|z_ce|z_pe|verdict|"
          "informative_obs\n")
        for _, _, r in polls:
            A("%s|%s|%s|%s|%s|%s|%s|%s\n"
              % (r.get("ts"), r.get("underlying"), r.get("spot"),
                 r.get("atm"), r.get("z_ce"), r.get("z_pe"),
                 r.get("verdict"), r.get("informative_obs")))
    A("\nCAUSAL_SIGNIFICANCE: the OI stage ran to completion all session, so "
      "no downstream OI theory can explain zero signals; and because the OI "
      "check is only invoked for an existing candidate, zero oi_candidate "
      "rows is positive evidence that no candidate was ever formed.\n")

    # ------------------------------------------------------- [7] cycle ledger
    sec("7", "SEP-02 957-CYCLE LEDGER")
    led = json.loads(C.text("08_SEP02_COMPLETE_CYCLE_LEDGER.json"))
    cyc = sep_met["counters"].get("cycles")
    skw = sep_met["counters"].get("skip_window")
    A("CYCLES_COUNTED=%s\nSKIP_WINDOW_COUNTED=%s\n"
      "PER_CYCLE_RECORDS_EXIST=%s\nWHY=%s\n"
      % (cyc, skw, led["per_cycle_records_exist"],
         led["why_no_per_cycle_records"]))
    A("CYCLE_BUDGET_ARITHMETIC=%s\n"
      % json.dumps(led["cycle_budget_arithmetic"]))
    A("\nLEDGER_ROWS: the population is emitted in full so its shape is "
      "explicit. Every per-cycle operand is UNKNOWN because the production "
      "build increments a bare counter and emits no record. No value is "
      "invented.\n")
    A("cycle_id|timestamp|window_result|caller|return_path|candidate_reached|"
      "downstream_stage|operands|evidence_status\n")
    for i in range(1, (cyc or 0) + 1):
        A("%d|UNKNOWN|UNKNOWN|Engine._evaluate_inner|UNKNOWN|FALSE|"
          "NONE_RECORDED|UNKNOWN|UNKNOWN\n" % i)
    A("\nDERIVED_LIVENESS_GRID: the only OBSERVED per-iteration timestamps "
      "for Sep-02 are the %d OI polls in section [6]; they bound process "
      "liveness to %s..%s but are a different loop from the evaluate cycle, "
      "so they are DERIVED context, not cycle records.\n"
      % (len(polls), polls[0][2]["ts"] if polls else "-",
         polls[-1][2]["ts"] if polls else "-"))

    # ------------------------------------------------------- [8] window source
    sec("8", "SIGNAL-WINDOW SOURCE EVIDENCE")
    A(C.text("05_WINDOW_CONTROL_FLOW.txt"))
    wp = json.loads(C.text("04_WINDOW_PREDICATE.json"))
    A("\nCLAUSE_LADDER_IN_EVALUATION_ORDER=%s\n"
      % json.dumps(wp["clause_ladder_in_evaluation_order"], indent=1))
    A("RETURNS_IN_SOURCE_ORDER=%s\n"
      % json.dumps(wp["returns_in_source_order"]))
    A("OPERAND_DEPENDENCY_GRAPH=%s\n"
      % json.dumps(json.loads(C.text("06_WINDOW_DEPENDENCY_GRAPH.json")),
                   indent=1))
    A("CLAUSE_REACHABILITY_OVER_THE_REAL_SESSION_SPAN=%s\n"
      % json.dumps(json.loads(C.text("09_FAILED_RETURN_PATHS.json")),
                   indent=1))

    # -------------------------------------------------- [9] historical controls
    sec("9", "HISTORICAL WINDOW CONTROLS (why skip_window=100% is misleading)")
    comp = json.loads(C.text("10_HISTORICAL_COMPARISON.json"))
    A("PER_DAY_TABLE=%s\n" % json.dumps(comp["per_day"], indent=1))
    A("KEY_OBSERVATION=%s\n" % comp["key_observation"])
    A("\nMETRICS_GENERATIONS (every preserved counter file, verbatim):\n")
    for r in sorted(x for x in C.files if "metrics_generations" in x):
        A("\nMETRICS_FILE=%s\nSHA256=%s\nSOURCE_MTIME=%s\nCONTENT=%s\n"
          % (os.path.basename(r), C.files[r]["sha256"], C.mtime(r),
             C.text(r).strip()))
    per_day = defaultdict(list)
    for ln, raw, rec in jrows(dec_txt):
        ts = str(rec.get("ts", ""))
        if len(ts) >= 10:
            per_day[ts[:10]].append((ln, raw, rec))
    A("\nSCORED_CANDIDATE_ROWS_BY_DAY (source=%s sha256=%s):\n"
      % (DEC, C.files[DEC]["sha256"]))
    for day in sorted(per_day):
        rows = per_day[day]
        A("DAY=%s ROWS=%d TS_MIN=%s TS_MAX=%s\n"
          % (day, len(rows), rows[0][2].get("ts"), rows[-1][2].get("ts")))
    A("\nCOMPACT_DECISION_LEDGER ts|type|stage|direction|score|underlying|"
      "reasons\n")
    for day in sorted(per_day):
        for _, _, r in per_day[day]:
            A("%s|%s|%s|%s|%s|%s|%s\n"
              % (r.get("ts"), r.get("type"), r.get("stage"),
                 r.get("direction"), r.get("score"), r.get("underlying"),
                 (";".join(r.get("reasons") or [])
                  if isinstance(r.get("reasons"), list)
                  else r.get("reasons"))))
    A("\nVERBATIM_PROOF_RECORDS (2 per control day, complete with ledger):\n")
    for day in ("2026-08-28", "2026-08-31", "2026-09-01"):
        for _, raw, _ in per_day.get(day, [])[:2]:
            A("DAY=%s RAW=%s\n" % (day, raw))
    A("\nCONTRADICTION_TO_CARRY_FORWARD=%s\n"
      % json.dumps(json.loads(C.text("14_CONTRADICTIONS.json")), indent=1))

    # ----------------------------------------------------------- [10] OI control
    sec("10", "OI DOWNSTREAM CONTROL")
    A(json.dumps(json.loads(C.text("12_OI_CONTROL_PROOF.json")), indent=1)
      + "\n")
    if os.path.exists(P12):
        raw12 = open(P12, "rb").read()
        A("\nPHASE_12_RECONSTRUCTION_PROOF\nSOURCE_FILE=%s\nSHA256=%s\n"
          "NOTE=this report lives beside the package, not inside it; it is "
          "quoted here so the OI reconstruction result travels with the "
          "dossier\n" % (P12, sha(raw12)))
        txt12 = raw12.decode("utf-8", "replace")
        keep = [l for l in txt12.splitlines()
                if re.search(r"1,?384|mismatch|BULLISH|BEARISH|\bB[1-4]\b|"
                             r"win_pe|win_ce|lookback_used|z_pe|z_ce|parity|"
                             r"PASS|FAIL", l)]
        for l in keep[:120]:
            A("P12| %s\n" % l.rstrip())
    A("\nPURPOSE=prevent re-opening eliminated OI theories: the OI branch "
      "logic was reconstructed exactly, and on Sep-02 the poller was healthy "
      "while zero candidates reached it.\n")

    # ------------------------------------------------- [11] rejected hypotheses
    sec("11", "REJECTED HYPOTHESES (decisive evidence only)")
    A(json.dumps(json.loads(C.text("15_FAILED_HYPOTHESES.json")), indent=1)
      + "\n")
    A("\nRUNTIME_STATE_BASIS_FOR_THE_REJECTIONS=%s\n"
      % json.dumps(json.loads(C.text("07_RUNTIME_STATE_SEP02.json")),
                   indent=1))
    cfg = [r for r in C.files if r.endswith("config.yaml")]
    for r in cfg:
        A("\nCONFIG_FILE=%s\nSHA256=%s\nCONTENT:\n%s\n"
          % (r, C.files[r]["sha256"], C.text(r)))

    # ---------------------------------------------------------- [12] matrix
    sec("12", "CAUSAL MATRIX")
    A("CAUSE|PROOF_FOR|PROOF_AGAINST|CRITICAL_RUNTIME_STATE|"
      "CAUSAL_LINK_PROVEN|CAUSAL_LINK_UNPROVEN|STATUS\n")
    for row in [
        ("FEED_STARVATION_UPSTREAM_OF_CANDIDATE",
         "5 fyers_error + 6 resubscribe + 7 degrade pairs (OBSERVED); "
         "ticks=162 bars_5m=4 (OBSERVED); 0 decision rows; 0 oi_candidate rows",
         "epoch boundaries of the tick/bar counters unknown; no bar records",
         "tick arrival series, bar close series",
         "feed loss -> engine self-declared degraded; no candidate reached OI",
         "bars=4 -> structure produced no swing (inferred from source only)",
         "LEADING, NOT PROVEN"),
        ("WINDOW_GATE_CLOSED_ALL_SESSION",
         "skip_window == cycles == 957",
         "same ratio on 08-28/08-31/09-01 where 150/204 scored candidates "
         "exist; predicate returns True 09:45-11:30 and 13:30-14:45",
         "per-cycle phase and regime_strength",
         "none", "entire chain", "REFUTED as session-wide claim"),
        ("METRICS_EPOCH_ARTIFACT",
         "no epoch fields; written 16:58:24; 957 cycles over a 19,728 s "
         "session implies 20.6 s/cycle against a configured 5 s interval",
         "none found", "process start/stop times",
         "counter file cannot be read as a session record", "-",
         "PROVEN (measurement defect)"),
        ("ENGINE_HOLIDAY", "-",
         "no holiday literal anywhere in the corpus contains 2026-09-02; "
         "2026-09-02 is a Wednesday", "engine.holidays", "-", "-",
         "ELIMINATED"),
        ("TIMEZONE", "-",
         "predicate normalises with now.astimezone(IST); only Asia/Kolkata "
         "and IST literals exist", "process TZ", "-", "-", "ELIMINATED"),
        ("FROZEN_CLOCK", "-",
         "659 monotonic OI polls 10:00:59-15:29:47", "clock", "-", "-",
         "ELIMINATED"),
        ("PREDICATE_REGRESSION", "-",
         "3 byte-distinct predicate forms across 477 engine copies; live form "
         "unchanged since 2026-08-17", "source bytes", "-", "-", "ELIMINATED"),
        ("OI_HISTORY_STARVATION", "-",
         "Phase 12 reconstructed 1,384 polls with 0 mismatches; Sep-02 poller "
         "healthy with 659 polls", "OI baseline windows", "-", "-",
         "ELIMINATED"),
        ("TELEGRAM_OR_ALERT_FAILURE", "-",
         "no candidate existed to alert; telegram_sent absent from the Sep-02 "
         "counters", "alerter queue", "-", "-", "NOT SUPPORTED"),
    ]:
        A("|".join(row) + "\n")

    # ------------------------------------------------------- [13] root timeline
    sec("13", "ROOT-CAUSE TIMELINE (only arrows the evidence supports)")
    A("TIME|EVENT|STATE|DOWNSTREAM_EFFECT|EVIDENCE_STATUS\n")
    first = next((l for l in elog_txt.splitlines() if l.strip()), "")
    A("%s|engine.log first record|process start|-|OBSERVED\n"
      % (re.search(r"20\d\d-\d\d-\d\dT\d\d:\d\d:\d\d", first).group(0)
         if re.search(r"20\d\d-\d\d-\d\dT\d\d:\d\d:\d\d", first) else
         "UNKNOWN"))
    for line in elog_txt.splitlines():
        m = re.search(r"20\d\d-\d\d-\d\dT\d\d:\d\d:\d\d", line)
        e = re.search(r'"event"\s*:\s*"([^"]+)"', line)
        if m and e and e.group(1) in (
                "fyers_error", "fyers_resubscribe_after_drop",
                "health_degraded", "health_recovered", "fyers_subscribed",
                "fyers_history_bootstrap", "cold_bootstrap_skipped",
                "snapshot_restored", "rvol_baseline_salvaged",
                "data_api_historical_skipped"):
            A("%s|%s|feed/health transition|see section [4]|OBSERVED\n"
              % (m.group(0), e.group(1)))
    if polls:
        A("%s|first OI poll|process live|OI stage running|OBSERVED\n"
          % polls[0][2]["ts"])
        A("%s|last OI poll|process live|OI stage running|OBSERVED\n"
          % polls[-1][2]["ts"])
    A("%s|metrics.json written|counters flushed|epoch boundaries unrecorded|"
      "OBSERVED\n" % C.mtime(SEPMET))
    A("SESSION_END|no decision row, no oi_candidate row, no alert|zero "
      "signals|user-visible outcome|OBSERVED\n")
    A("\nARROWS_NOT_YET_PROVEN: bars_5m=4 -> structure emitted no swing -> no "
      "candidate. Source reading in section [3] shows the structure stage "
      "consumes closed 5-minute bars, but no Sep-02 structure record exists "
      "to observe the transition.\n")

    # ----------------------------------------------------------- [14] patch
    sec("14", "PATCH READINESS (verified against the recorded source)")
    A(json.dumps(json.loads(C.text("17_PATCH_READINESS.json")), indent=1)
      + "\n")
    A("\nSOURCE_VERIFICATION_OF_PATCH_ANCHORS (line numbers recomputed from "
      "the live build sha256=%s):\n" % live_meta["sha256"])
    for pat, label in ((r"skip_window", "skip_window increment site"),
                       (r"metrics\.json|def .*metrics|_write_metrics|"
                        r"dump_metrics", "metrics writer"),
                       (r"skip_warmup|skip_degraded|skip_stale",
                        "sibling skip counters"),
                       (r"ticks_ingested|bars_5m", "feed progress counters"),
                       (r"signal_window_open", "window predicate + callers")):
        rx = re.compile(pat)
        for i, line in enumerate(live_src.splitlines(), 1):
            if rx.search(line):
                A("ANCHOR|%s|LINE=%d|%s\n" % (label, i, line.strip()))
    A("\nAUTHORIZATION=NOT AUTHORIZED for a behavioural change. The proven "
      "defects are observability defects (no per-cycle window record, no "
      "epoch stamping) plus a reliability gap (silent feed starvation). The "
      "behavioural root cause is not yet proven, so the minimal change "
      "boundary is instrumentation plus alerting only.\n")
    A("MINIMAL_CHANGE_BOUNDARY=three additive edits: (1) emit a record at the "
      "skip_window site carrying ts/phase/regime_strength/is_trading_day/"
      "clause; (2) stamp epoch_start_ts, epoch_end_ts, session_date, pid into "
      "metrics.json and roll per session date; (3) raise an alert when "
      "ticks_ingested or bars_5m fall below a session-progress floor.\n")
    A("SIDE_EFFECT_RISKS=(1) log volume at 5 s cadence -> gate to one record "
      "per state change plus a periodic heartbeat; (2) metrics file rename "
      "may break any external reader of logs/metrics.json -> keep the same "
      "path and add fields; (3) an alert path must not run inside the "
      "evaluate loop's critical section.\n")

    # ------------------------------------------------------ [15] regression
    sec("15", "REGRESSION AND NEGATIVE CONTROLS REQUIRED")
    for i, t in enumerate([
        "replay a healthy day (08-31 or 09-01) and assert scored candidates "
        "still appear with identical direction/score to decisions.jsonl - "
        "the instrumentation must not change behaviour",
        "assert the window predicate output is unchanged for a synthetic "
        "grid across all six phases plus both boundary minutes of each",
        "negative control: force a feed drop in a sandbox and assert the new "
        "starvation alert fires and the new skip record shows the true phase",
        "assert metrics.json now carries epoch_start_ts/epoch_end_ts/"
        "session_date and that two runs on one date do not overwrite each "
        "other's counters",
        "assert skip_window + skip_warmup + skip_degraded + skip_stale + "
        "evaluated == cycles for a full session (conservation check that the "
        "Sep-02 data could not satisfy)",
        "assert 2026-09-02 remains a trading day under the resolved calendar "
        "and that the resolved config is now dumped at startup",
        "OI parity: re-run the Phase 12 reconstruction and require 0 "
        "mismatches over the same 1,384 polls",
    ], 1):
        A("RC-%02d %s\n" % (i, t))

    # --------------------------------------------------- [16] claim->proof map
    sec("16", "EVIDENCE INDEX / CLAIM -> PROOF MAP")
    claims = [
        ("FEED-001", "the FYERS feed dropped and was resubscribed repeatedly "
                     "on 2026-09-02", ELOG, C.files[ELOG]["sha256"],
         "records tagged fyers_error / fyers_resubscribe_after_drop",
         "section [4] verbatim log", "engine's own feed events"),
        ("FEED-002", "the engine declared itself degraded 7 times and "
                     "recovered 7 times", ELOG, C.files[ELOG]["sha256"],
         "health_degraded / health_recovered records", "section [4]",
         "degrade branch requires market_open, so phase() was live"),
        ("TICK-001", "ticks_ingested=162 in the Sep-02 counter epoch", SEPMET,
         C.files[SEPMET]["sha256"], "counters.ticks_ingested",
         "section [5] raw file", "orders of magnitude below healthy days"),
        ("BAR-001", "bars_5m=4 in the Sep-02 counter epoch", SEPMET,
         C.files[SEPMET]["sha256"], "counters.bars_5m", "section [5]",
         "a 5-minute structure series cannot form from 4 bars"),
        ("CAND-001", "zero decision rows exist for 2026-09-02", DEC,
         C.files[DEC]["sha256"], "no row with ts prefix 2026-09-02",
         "section [9] per-day table", "candidate stage never produced output"),
        ("CAND-002", "zero oi_candidate rows exist for 2026-09-02", OIDIAG,
         C.files[OIDIAG]["sha256"], "type==oi_candidate count 0",
         "section [6]", "the OI check is only invoked for a candidate"),
        ("OI-001", "the OI poller ran all session at ~30 s cadence", OIDIAG,
         C.files[OIDIAG]["sha256"], "659 rows 10:00:59..15:29:47",
         "section [6]", "eliminates OI availability as the cause"),
        ("WIN-001", "skip_window == cycles == 957 on Sep-02", SEPMET,
         C.files[SEPMET]["sha256"], "counters.skip_window and counters.cycles",
         "section [7]", "the number that motivated the refuted theory"),
        ("WIN-002", "the same 100% ratio occurs on days with scored "
                    "candidates", "10_HISTORICAL_COMPARISON.json",
         C.files["10_HISTORICAL_COMPARISON.json"]["sha256"],
         "per_day 08-28 / 08-31 / 09-01", "section [9]",
         "refutes the session-wide reading of skip_window"),
        ("WIN-003", "the window predicate is unchanged since 2026-08-17",
         "13_TASK1_TASK2_LINEAGE.json",
         C.files["13_TASK1_TASK2_LINEAGE.json"]["sha256"],
         "window_predicate_groups", "section [2]",
         "eliminates a code regression"),
        ("MET-001", "metrics.json has no epoch boundaries and was written "
                    "86 minutes after close", SEPMET,
         C.files[SEPMET]["sha256"], "file content plus SOURCE_MTIME",
         "sections [5] and [13]", "counters cannot be scoped to the session"),
        ("SRC-001", "the exact build that ran is recorded byte for byte",
         LIVE, live_meta["sha256"], "whole file",
         "sections [2] and [3]", "all source claims are checkable"),
    ]
    for cid, claim, src, s, rec, where, why in claims:
        A("\nCLAIM_ID=%s\nCLAIM=%s\nSOURCE_FILE=%s\nSOURCE_SHA256=%s\n"
          "SOURCE_LINE_OR_RECORD=%s\nEXACT_EVIDENCE=%s\nWHY_DECISIVE=%s\n"
          % (cid, claim, src, s, rec, where, why))

    # ------------------------------------------------------- [17] integrity
    sec("17", "MISSING FACTS, TIER MAP, INTEGRITY AND SIZE")
    for mf, req, searched, why in [
        ("per-cycle window result for 2026-09-02",
         "decides whether the window gate ever closed during the session",
         "live source skip site; engine.log; metrics.json; decisions.jsonl; "
         "oi_diag; every preserved metrics generation",
         "the production build increments a bare counter and emits no record; "
         "the sentinel exists only in the forensic build, which did not run"),
        ("per-bar records for 2026-09-02",
         "closes the arrow bars_5m=4 -> no structure -> no candidate",
         "engine.log; metrics.json; both oi streams; decisions.jsonl",
         "only an aggregate bars_5m counter is written"),
        ("resolved engine config for the Sep-02 process",
         "pins engine.holidays and evaluation_interval_s for that run",
         "every config.yaml and every source default in the corpus",
         "the engine never dumps its effective config; bounded instead by all "
         "holiday literals found, none of which contains 2026-09-02"),
        ("regime_strength series for 2026-09-02",
         "decides the MIDDAY clause of the window predicate",
         "decisions.jsonl (0 Sep-02 rows); engine.log; oi_diag",
         "emitted only alongside a scored candidate, and none existed"),
        ("metrics epoch boundaries",
         "scopes ticks=162 / bars=4 / cycles=957 to a time range",
         "the file itself and all 11 preserved generations",
         "the writer stamps no timestamps and overwrites in place"),
    ]:
        A("\nMISSING_FACT=%s\nWHY_REQUIRED=%s\nALL_SEARCHED_SOURCES=%s\n"
          "WHY_UNRECOVERABLE=%s\n" % (mf, req, searched, why))
    A("\nTIER_MAP (every file in the master corpus, ranked):\n")
    A("TIER|BYTES|SHA256|RELATIVE_PATH|REASON\n")
    tiers = Counter()
    for rel in sorted(C.files):
        t, why = tier_of(rel, C.files[rel]["type"])
        tiers[t] += 1
        A("%d|%d|%s|%s|%s\n" % (t, C.files[rel]["size"],
                                C.files[rel]["sha256"][:16], rel, why))
    A("TIER_COUNTS=%s\n" % json.dumps({("TIER_%d" % k): v
                                       for k, v in sorted(tiers.items())}))
    A("\nQUESTION_COVERAGE (Part 2 A-O):\n")
    for q, ans in [
        ("A exact Dhan.py that ran", "section [2], sha256 recorded"),
        ("B controlling predicate", "sections [3] and [8], verbatim"),
        ("C FYERS feed on Sep-02", "section [4], all 40 records"),
        ("D ticks", "section [5], counter only - epoch UNKNOWN"),
        ("E 5m bars", "section [5], counter only - no bar records (MF-002)"),
        ("F underlying state", "section [3] source; no Sep-02 state record"),
        ("G structure / candidate reachability",
         "sections [6] and [9]: zero candidates on Sep-02, hundreds on the "
         "control days"),
        ("H OI downstream", "sections [6] and [10]"),
        ("I why skip_window misleads", "sections [7] and [9]"),
        ("J historical days that settle it", "section [9]: 08-28/08-31/09-01"),
        ("K causal chain", "section [13], with the unproven arrow named"),
        ("L rejected explanations", "sections [11] and [12]"),
        ("M where to patch", "section [14], anchors recomputed from source"),
        ("N smallest safe patch", "section [14], instrumentation only"),
        ("O regression controls", "section [15]"),
    ]:
        A("Q=%s -> %s\n" % (q, ans))
    A("\nDATA_SUFFICIENT_FOR_FABLE=YES for: identifying the causal boundary "
      "candidates, refuting the window theory, eliminating five competing "
      "mechanisms, and specifying the minimal safe instrumentation patch and "
      "its regression suite. NO for: proving the bar->structure->candidate "
      "arrow from Sep-02 records alone, which is impossible from any "
      "surviving artifact and is recorded as MISSING_FACT rather than "
      "glossed over.\n")
    A("Dhan.py_MODIFIED=FALSE\nSOURCE_CORPUS_MODIFIED=FALSE\n")

    body = W.getvalue()
    tail_tmpl = ("\n" + "=" * 78 + "\nFINAL INTEGRITY\n" + "=" * 78 +
                 "\nCONTENT_PREFIX_BYTES=%012d\nCONTENT_PREFIX_SHA256=%s\n"
                 "FINAL_FILE_SIZE_BYTES=%012d\n"
                 "FINAL_FILE_SHA256=NOT_SELF_REFERENTIAL_SEE_SIDECAR "
                 "(a file cannot contain its own digest; "
                 "CONTENT_PREFIX_SHA256 above covers every byte before this "
                 "block and the whole-file digest is in %s)\n"
                 "SIZE_LIMIT_TARGET=%d\nSIZE_LIMIT_HARD=%d\n"
                 "END_FABLE_FINAL_AUDIT\n")
    bb = body.encode("utf-8")
    tail_len = len((tail_tmpl % (len(bb), "0" * 64, 0,
                                 os.path.basename(SIDE), TARGET, HARD))
                   .encode("utf-8"))
    total = len(bb) + tail_len
    if total > HARD:
        print("EXPORT_STATUS=FAIL size %d exceeds hard limit" % total)
        return 1
    tail = tail_tmpl % (len(bb), sha(bb), total, os.path.basename(SIDE),
                        TARGET, HARD)
    with open(OUT, "wb") as fh:
        fh.write(bb)
        fh.write(tail.encode("utf-8"))
    final_n = os.path.getsize(OUT)
    final_sha = sha(open(OUT, "rb").read())

    ok = (final_n == total and final_n <= HARD)
    json.dump({"final_file": OUT, "final_size_bytes": final_n,
               "final_sha256": final_sha, "prefix_sha256": sha(bb),
               "target": TARGET, "hard_limit": HARD,
               "within_target": final_n <= TARGET,
               "source_corpus": CORPUS, "source_corpus_sha256": corpus_sha,
               "source_corpus_bytes": corpus_n,
               "corpus_files_read": len(C.files),
               "functions_included": len(fns),
               "functions_deferred": len(dropped),
               "sep02_cycle_rows": cyc, "sep02_feed_records": sum(ev.values()),
               "sep02_oi_polls": len(polls),
               "decision_rows_emitted": sum(len(v) for v in per_day.values()),
               "tier_counts": {("TIER_%d" % k): v
                               for k, v in sorted(tiers.items())},
               "size_check_ok": ok,
               "elapsed_s": round(time.time() - t0, 1)},
              open(SIDE, "w", encoding="utf-8", newline="\n"), indent=1)

    print("FINAL_FILE=%s" % OUT)
    print("FINAL_SIZE_BYTES=%d" % final_n)
    print("FINAL_SHA256=%s" % final_sha)
    print("SOURCE_CORPUS_READ=%s (%d bytes, %d files, sha256=%s)"
          % (os.path.basename(CORPUS), corpus_n, len(C.files), corpus_sha[:16]))
    print("LOAD_BEARING_SOURCE_FUNCTIONS=%d (deferred=%d)"
          % (len(fns), len(dropped)))
    print("SEP02_CYCLES_INCLUDED=%s" % cyc)
    print("SEP02_FEED_EVENTS_INCLUDED=%d" % sum(ev.values()))
    print("SEP02_OI_POLLS_INCLUDED=%d" % len(polls))
    print("DECISION_ROWS_INCLUDED=%d" % sum(len(v) for v in per_day.values()))
    print("TIER_COUNTS=%s" % json.dumps({("T%d" % k): v
                                         for k, v in sorted(tiers.items())}))
    print("WITHIN_TARGET=%s HARD_OK=%s" % (final_n <= TARGET, final_n <= HARD))
    print("elapsed=%.1fs" % (time.time() - t0))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
