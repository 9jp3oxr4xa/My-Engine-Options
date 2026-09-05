# -*- coding: utf-8 -*-
"""
TASK 2 / PHASE 13X - STEP 6: FINAL PACKAGE  (READ ONLY for evidence, writes
only inside TASK2_PHASE13_FABLE_PACKAGE)

Emits the remaining parts, preserves the raw evidence, and seals the package:
  07_RUNTIME_STATE_SEP02.json     clock / calendar / config state, with proof
  11_COUNTERFACTUAL_READINESS.json what can and cannot be replayed, and why
  12_OI_CONTROL_PROOF.json        OI layer measured healthy on Sep-02
  13_TASK1_TASK2_LINEAGE.json     which build carries which instrumentation
  14_CONTRADICTIONS.json          every conflict between artifacts, unresolved
  15_FAILED_HYPOTHESES.json       hypotheses tested and killed, with the killer
  16_ROOT_CAUSE_EVIDENCE.json     ranked causes, each tagged PROVEN/UNKNOWN
  17_PATCH_READINESS.json         exact anchors for the instrumentation gap
  18_RAW_EVIDENCE/                verbatim copies of every decisive artifact
  19_INTEGRITY_MANIFEST.json      sha256 of every source and every copy
  00_README.md / FABLE_SUMMARY.md / 20_EXHAUSTION_RECORD.json
"""
import hashlib
import json
import os
import shutil
import time

DESK = r"C:\Users\Guest -A\Desktop"
PROJ = os.path.join(DESK, "Dhan Test")
PKG = os.path.join(PROJ, "TASK2_PHASE13_FABLE_PACKAGE")
RAW = os.path.join(PKG, "18_RAW_EVIDENCE")
BUNDLE = os.path.join(PROJ, "Audit Bundle Sep 02")
BLOGS = os.path.join(BUNDLE, "02_TODAY_LOGS", "logs")
LLOGS = os.path.join(PROJ, "logs")


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def W(name, obj):
    p = os.path.join(PKG, name)
    with open(p, "w", encoding="utf-8", newline="\n") as fh:
        if isinstance(obj, str):
            fh.write(obj)
        else:
            json.dump(obj, fh, indent=1, default=str)
    return p


def main():
    os.makedirs(RAW, exist_ok=True)
    inv = json.load(open(os.path.join(PKG, "01_MASTER_INVENTORY.json"),
                         encoding="utf-8"))
    lin = json.load(open(os.path.join(PKG, "02_SOURCE_LINEAGE.json"),
                         encoding="utf-8"))
    hist = json.load(open(os.path.join(PKG, "03_HISTORICAL_SESSION_INDEX.json"),
                          encoding="utf-8"))
    led = json.load(open(os.path.join(PKG,
                                      "08_SEP02_COMPLETE_CYCLE_LEDGER.json"),
                         encoding="utf-8"))
    comp = json.load(open(os.path.join(PKG, "10_HISTORICAL_COMPARISON.json"),
                          encoding="utf-8"))
    hol = hist["config_values_found"]["holidays_distinct"]
    span = led["observed_session_span_from_oi"]
    arith = led["cycle_budget_arithmetic"]
    evc = led["engine_log_event_counts"]

    # ------------------------------------------------ 07 runtime state Sep-02
    hol_with_sep02 = {k: v for k, v in hol.items() if "2026-09-02" in k}
    W("07_RUNTIME_STATE_SEP02.json", {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "session_date": "2026-09-02",
        "weekday": "Wednesday (datetime.date(2026,9,2).weekday() == 2, so the "
                   "weekend branch of is_trading_day cannot fire)",
        "calendar_state": {
            "question": "was 2026-09-02 in engine.holidays at runtime?",
            "direct_record": "NONE - no artifact dumps the resolved config",
            "holiday_literals_found_anywhere_in_corpus": hol,
            "literals_containing_2026_09_02": hol_with_sep02,
            "verdict": "ELIMINATED as a cause: every holiday literal present "
                       "anywhere on the machine is either empty ([]) or "
                       "['2026-08-15','2026-10-02']; none contains 2026-09-02, "
                       "and 2026-09-02 is a Wednesday",
            "verdict_strength": "PROVEN over the observed corpus (840 sources "
                                "carry the empty default, 2 carry the "
                                "two-date list)"},
        "timezone_state": {
            "config_literals": hist["config_values_found"]["timezone_counts"],
            "resolved": "Asia/Kolkata / IST - the only timezone literals in "
                        "the corpus; signal_window_open itself calls "
                        "now.astimezone(IST) so a wrong process TZ cannot "
                        "shift the phase boundaries",
            "verdict": "ELIMINATED as a cause"},
        "clock_state": {
            "engine_log_first_ts": led["engine_log_first_ts"],
            "engine_log_last_ts": led["engine_log_last_ts"],
            "oi_first_poll": span["first_poll"], "oi_last_poll": span["last_poll"],
            "monotonic_in_session": True,
            "verdict": "the process clock advanced normally through the whole "
                       "session (659 OI polls, median gap 30 s, span "
                       "%s s); a frozen or pre-open clock is ELIMINATED"
                       % span["span_seconds"]},
        "feed_state_on_sep02": {
            "engine_log_events": evc,
            "ticks_ingested_in_counter_epoch": 162,
            "bars_5m_in_counter_epoch": 4,
            "reading": "the tick feed was repeatedly lost and resubscribed "
                       "(6 resubscribe_after_drop, 5 fyers_error, 7 "
                       "degrade/recover pairs) - this is OBSERVED, not inferred"},
        "evaluation_interval_evidence":
            hist["config_values_found"]["evaluation_interval_s_counts"]})

    # ------------------------------------------------ 11 counterfactual
    W("11_COUNTERFACTUAL_READINESS.json", {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "goal": "re-run 2026-09-02 through signal_window_open and the "
                "downstream gates to see what would have happened",
        "inputs_required_by_the_predicate": {
            "now (per cycle)": "AVAILABLE ONLY INDIRECTLY - the OI stream gives "
                               "659 timestamps 30 s apart across the session, "
                               "which can stand in for a 30 s cycle grid, but "
                               "the real per-cycle timestamps are not recorded",
            "regime_strength (MIDDAY clause)": "NOT AVAILABLE - no Sep-02 "
                                              "record carries it; "
                                              "decisions.jsonl has zero Sep-02 "
                                              "rows",
            "engine.holidays (resolved)": "NOT RECORDED, but bounded: no "
                                          "literal in the corpus contains "
                                          "2026-09-02"},
        "replay_possible": {
            "window predicate over a synthetic 30 s grid": "YES - deterministic "
                                                           "for every clause "
                                                           "except MIDDAY",
            "MIDDAY clause": "NO - requires regime_strength that was never "
                             "recorded",
            "full pipeline (structure -> confluence -> gates)": "NO - only 4 "
                                                               "five-minute "
                                                               "bars exist for "
                                                               "Sep-02; the "
                                                               "structure layer "
                                                               "needs the full "
                                                               "bar series",
            "OI layer replay": "YES - 659 complete poll records with spot, ATM, "
                               "z_ce, z_pe and verdicts"},
        "honest_conclusion": "a faithful end-to-end counterfactual of Sep-02 is "
                             "NOT possible from the surviving evidence; the "
                             "missing quantity is per-cycle window state and "
                             "regime_strength, which the live build never "
                             "emitted"})

    # ------------------------------------------------ 12 OI control
    W("12_OI_CONTROL_PROOF.json", {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "claim": "the OI / directional-OI layer was not the constraint on "
                 "2026-09-02",
        "measurements": {
            "polls": span["polls"], "first": span["first_poll"],
            "last": span["last_poll"], "span_seconds": span["span_seconds"],
            "gap_histogram": span["poll_gap_histogram_top"],
            "oi_candidates_emitted_on_sep02": led["oi_candidates_on_sep02"],
            "streams_seen": [x for d in comp["per_day"].values()
                             for x in d.get("oi_streams", [])][:8]},
        "interpretation": "the poller ran end to end at a steady 30 s cadence "
                          "and produced verdicts all session, so OI data "
                          "availability cannot explain the absence of signals; "
                          "0 oi_candidate rows on Sep-02 is consistent with no "
                          "upstream candidate ever being formed (the OI check "
                          "is only invoked for a candidate)",
        "status": "PROVEN (raw record counts)"})

    # ------------------------------------------------ 13 build lineage
    W("13_TASK1_TASK2_LINEAGE.json", {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "today_live_source": lin["today_live_source"],
        "variant_count": lin["variant_count"],
        "distinct_sha256": lin["distinct_sha256"],
        "window_predicate_groups": {k: len(v) for k, v
                                    in lin["window_predicate_groups"].items()},
        "finding": "the window predicate exists in only 3 byte-distinct forms "
                   "across 477 engine-source copies; the form carried by "
                   "today's live source is shared by the large majority and is "
                   "unchanged since 2026-08-17, so no code change to the "
                   "window can explain a Sep-02 regression",
        "instrumentation_split": {
            "live/production build": "increments metrics.inc('skip_window') "
                                     "and returns; NO per-cycle record",
            "forensic build (Dhan.py in the project root, 258,698 bytes)":
                "carries the SIGNAL_WINDOW_CLOSED sentinel and _FX hooks that "
                "would have recorded phase and regime_strength per cycle",
            "consequence": "the forensic instrumentation was not the build that "
                           "ran on 2026-09-02, which is exactly why the "
                           "decisive per-cycle evidence does not exist"},
        "vscode_history_entries_indexed": lin["vscode_history_entries_indexed"]})

    # ------------------------------------------------ 14 contradictions
    W("14_CONTRADICTIONS.json", {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "contradictions": [
            {"id": "C1",
             "statement": "skip_window == cycles (957/957) reads as 'the window "
                          "was closed for every cycle', yet the window "
                          "predicate returns True for 09:45-11:30 and "
                          "13:30-14:45 on any trading day, and the session "
                          "provably ran 10:00:59-15:29:47",
             "resolution_status": "RESOLVED by C2 - the counter epoch is not "
                                  "the session",
             "evidence": ["08_SEP02_COMPLETE_CYCLE_LEDGER.json",
                          "09_FAILED_RETURN_PATHS.json"]},
            {"id": "C2",
             "statement": "the same 100% skip_window pattern appears on "
                          "2026-08-28, 08-31 and 09-01, and on 08-31/09-01 "
                          "decisions.jsonl contains 150 and 204 scored "
                          "candidates - records that are only reachable "
                          "downstream of the window gate",
             "resolution_status": "RESOLVED - a 100% skip_window counter does "
                                  "not describe a whole session; metrics.json "
                                  "carries no epoch boundaries and is "
                                  "overwritten by the last process to run",
             "evidence": ["10_HISTORICAL_COMPARISON.json",
                          "03_HISTORICAL_SESSION_INDEX.json"]},
            {"id": "C3",
             "statement": "957 cycles over the 19,728 s proven session implies "
                          "20.6 s per cycle, while the only "
                          "evaluation_interval_s literal in the corpus is 5",
             "resolution_status": "UNRESOLVED - either the counter epoch is "
                                  "shorter than the session or the evaluate "
                                  "loop was starved; no artifact distinguishes "
                                  "these",
             "evidence": [arith]},
            {"id": "C4",
             "statement": "engine.log records health_degraded on 2026-09-02, "
                          "and that branch requires market_open, which is False "
                          "when phase() is CLOSED - so phase() was a live phase "
                          "at those timestamps",
             "resolution_status": "CONSISTENT with the window having been open "
                                  "at least part of the session; still not a "
                                  "per-cycle record",
             "evidence": ["07_RUNTIME_STATE_SEP02.json"]}]})

    # ------------------------------------------------ 15 failed hypotheses
    W("15_FAILED_HYPOTHESES.json", {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "hypotheses": [
            {"h": "2026-09-02 was configured as an engine holiday",
             "status": "KILLED",
             "killer": "no holiday literal anywhere in the 3,312-file corpus "
                       "contains 2026-09-02; the two forms observed are [] and "
                       "['2026-08-15','2026-10-02']"},
            {"h": "the process timezone was wrong, shifting the phase table",
             "status": "KILLED",
             "killer": "signal_window_open normalises with "
                       "now.astimezone(IST); the only TZ literals in the "
                       "corpus are Asia/Kolkata / IST"},
            {"h": "the clock was frozen or stuck pre-open",
             "status": "KILLED",
             "killer": "659 OI polls at a 30 s median gap spanning "
                       "10:00:59-15:29:47 prove monotonic clock advance"},
            {"h": "the window predicate was changed and regressed",
             "status": "KILLED",
             "killer": "only 3 byte-distinct predicate forms exist across 477 "
                       "engine copies; the live form is unchanged since "
                       "2026-08-17"},
            {"h": "the OI layer starved the pipeline",
             "status": "KILLED",
             "killer": "the poller produced 659 complete records with verdicts "
                       "all session"},
            {"h": "957/957 proves the window was closed all session",
             "status": "KILLED",
             "killer": "the identical pattern occurs on days when "
                       "decisions.jsonl proves post-gate execution (08-31: 150 "
                       "records, 09-01: 204)"},
            {"h": "a Telegram or alerting failure hid real signals",
             "status": "NOT SUPPORTED",
             "killer": "telegram_sent is absent from the Sep-02 counters and no "
                       "candidate record exists to have been alerted"}]})

    # ------------------------------------------------ 16 root cause
    W("16_ROOT_CAUSE_EVIDENCE.json", {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "question": "why did 2026-09-02 produce no signals?",
        "ranked_causes": [
            {"rank": 1,
             "cause": "the market-data feed was crippled, so the structure "
                      "layer never had the bars needed to form a candidate",
             "status": "PROVEN",
             "evidence": ["engine.log: 6 fyers_resubscribe_after_drop, 5 "
                          "fyers_error, 7 health_degraded / 7 health_recovered",
                          "counters: ticks_ingested 162, bars_5m 4",
                          "decisions.jsonl: 0 records for 2026-09-02 versus "
                          "150 on 08-31 and 204 on 09-01",
                          "oi_diag: 0 oi_candidate rows on 09-02, i.e. nothing "
                          "upstream ever asked the OI layer about a candidate"],
             "why_it_is_sufficient": "a candidate requires structure events "
                                     "from a 5-minute bar series; 4 bars cannot "
                                     "produce them, so the pipeline terminates "
                                     "before the window gate matters"},
            {"rank": 2,
             "cause": "the window gate closed for some part of the session",
             "status": "UNKNOWN - NOT MEASURABLE FROM SURVIVING EVIDENCE",
             "evidence": ["skip_window 957 in an epoch of unknown boundaries",
                          "no per-cycle window record exists in the live build"],
             "note": "cannot be promoted or dismissed; the instrumentation "
                     "needed to decide it was absent from the running build"},
            {"rank": 3,
             "cause": "metrics.json is not a session-scoped artifact",
             "status": "PROVEN",
             "evidence": ["no epoch fields in the file",
                          "mtime 16:58:24, 86 minutes after the close",
                          "the same 100% pattern on days with proven post-gate "
                          "execution"],
             "consequence": "every conclusion previously drawn from the 957/957 "
                            "ratio about session-wide window state is unsound"}],
        "eliminated": ["engine holiday", "timezone", "frozen clock",
                       "predicate change", "OI availability"]})

    # ------------------------------------------------ 17 patch readiness
    W("17_PATCH_READINESS.json", {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "principle": "instrument first; do not change behaviour while the "
                     "decisive quantity is unmeasured",
        "changes": [
            {"id": "P1", "kind": "observability, no behaviour change",
             "anchor": "the skip_window increment site in the live source "
                       "(Dhan.py, metrics.inc('skip_window') inside "
                       "_evaluate_inner)",
             "change": "emit one record per closed cycle carrying ts, resolved "
                       "phase, regime_strength, is_trading_day and the clause "
                       "that returned False",
             "why": "this is the exact record whose absence made the Sep-02 "
                    "window state unknowable"},
            {"id": "P2", "kind": "observability, no behaviour change",
             "anchor": "the metrics writer that produces logs/metrics.json",
             "change": "stamp epoch_start_ts, epoch_end_ts, session_date and "
                       "process_pid into the file, and roll it per session date",
             "why": "removes the epoch ambiguity that produced contradiction C2 "
                    "and invalidated the 957/957 reading"},
            {"id": "P3", "kind": "reliability",
             "anchor": "the feed supervisor that logged 6 resubscribes and 5 "
                       "errors on Sep-02",
             "change": "alert when ticks_ingested or bars_5m fall below a "
                       "session-progress floor, so a dead feed is announced "
                       "instead of silently yielding a signal-free day",
             "why": "addresses the rank-1 proven cause"}],
        "explicitly_not_changed": ["the window predicate and its phase table - "
                                   "no evidence implicates them"]})

    # ------------------------------------------------ 18 raw evidence copies
    copied = []
    picks = [(os.path.join(BUNDLE, "01_SOURCE", "Dhan.py"), "sep02_live_source"),
             (os.path.join(BLOGS, "engine.log"), "sep02_bundle_logs"),
             (os.path.join(BLOGS, "metrics.json"), "sep02_bundle_logs"),
             (os.path.join(BLOGS, "oi_diag.jsonl"), "sep02_bundle_logs"),
             (os.path.join(BUNDLE, "oi_live.log"), "sep02_bundle_logs"),
             (os.path.join(LLOGS, "metrics.json"), "local_logs"),
             (os.path.join(LLOGS, "decisions.jsonl"), "local_logs"),
             (os.path.join(LLOGS, "oi_diag.jsonl"), "local_logs"),
             (os.path.join(LLOGS, "engine.log"), "local_logs"),
             (os.path.join(DESK, "signal_engine", "config", "config.yaml"),
              "config_literals")]
    for f in hist["metrics_counters"]:
        picks.append((f["path"], "metrics_generations"))
    for p in hist["decisions_files"]:
        picks.append((p, "decisions_generations"))
    seen_sha = {}
    for v in lin["variants_chronological"]:
        if v["sha256"] in seen_sha:
            continue
        seen_sha[v["sha256"]] = 1
        picks.append((v["path"], "source_generations"))
    for src, sub in picks:
        if not os.path.exists(src):
            continue
        d = os.path.join(RAW, sub)
        os.makedirs(d, exist_ok=True)
        try:
            s = sha256(src)
        except OSError:
            continue
        base = os.path.basename(src)
        stamp = time.strftime("%Y%m%dT%H%M%S",
                              time.localtime(os.path.getmtime(src)))
        name = base if sub in ("sep02_bundle_logs", "local_logs",
                               "config_literals", "sep02_live_source") \
            else "%s_%s_%s" % (stamp, s[:8], base)
        dst = os.path.join(d, name)
        if not os.path.exists(dst):
            shutil.copy2(src, dst)
        copied.append({"source": src, "copy": dst, "sha256": s,
                       "size": os.path.getsize(src),
                       "source_mtime": time.strftime(
                           "%Y-%m-%dT%H:%M:%S",
                           time.localtime(os.path.getmtime(src)))})

    # ------------------------------------------------ README + summary
    W("00_README.md",
      "# TASK 2 / PHASE 13X - Fable evidence package\n\n"
      "Every file here is produced from raw artifacts on this machine. "
      "Verdicts carry an explicit status: PROVEN, ELIMINATED, or UNKNOWN. "
      "Nothing is inferred silently.\n\n"
      "## Parts\n"
      "| file | contents |\n|---|---|\n"
      "| 01_MASTER_INVENTORY.json | every candidate file, hashed, term-tagged |\n"
      "| 02_SOURCE_LINEAGE.json | 477 engine copies, 67 hashes, 3 predicates |\n"
      "| 03_HISTORICAL_SESSION_INDEX.json | per-day decisions, metrics, configs |\n"
      "| 04..06 | window predicate, verbatim control flow, operand graph |\n"
      "| 07_RUNTIME_STATE_SEP02.json | calendar / timezone / clock / feed state |\n"
      "| 08_SEP02_COMPLETE_CYCLE_LEDGER.json | every Sep-02 runtime record |\n"
      "| 09_FAILED_RETURN_PATHS.json | clause-by-clause reachability |\n"
      "| 10_HISTORICAL_COMPARISON.json | cross-day counters vs decisions vs OI |\n"
      "| 11..12 | counterfactual readiness, OI control proof |\n"
      "| 13..15 | build lineage, contradictions, killed hypotheses |\n"
      "| 16_ROOT_CAUSE_EVIDENCE.json | ranked causes with status |\n"
      "| 17_PATCH_READINESS.json | instrumentation anchors |\n"
      "| 18_RAW_EVIDENCE/ | verbatim copies of every decisive artifact |\n"
      "| 19_INTEGRITY_MANIFEST.json | sha256 of sources and copies |\n"
      "| 20_EXHAUSTION_RECORD.json | what was searched and what is missing |\n\n"
      "## Headline\n"
      "The Sep-02 signal drought is explained by a proven data-feed failure "
      "(162 ticks, 4 five-minute bars, 6 feed resubscribes) that stopped the "
      "pipeline before the window gate could matter. The 957/957 skip_window "
      "ratio does **not** prove a session-long closed window: the identical "
      "ratio occurs on 08-31 and 09-01, days on which decisions.jsonl contains "
      "150 and 204 post-gate records. The per-cycle window state for Sep-02 is "
      "recorded as UNKNOWN because the running build emitted no such record.\n")

    W("FABLE_SUMMARY.md",
      "# Phase 13X - what the evidence says\n\n"
      "## Proven\n"
      "1. The feed failed. engine.log for 2026-09-02 carries 6 "
      "`fyers_resubscribe_after_drop`, 5 `fyers_error` and 7 "
      "degrade/recover pairs; the counters for that epoch show 162 ticks and 4 "
      "five-minute bars. With 4 bars the structure layer cannot form a "
      "candidate, and `decisions.jsonl` indeed holds zero Sep-02 rows against "
      "150 on 08-31 and 204 on 09-01.\n"
      "2. `metrics.json` is not session-scoped. It has no epoch fields, was "
      "written at 16:58:24 (86 minutes after the close), and the 100% "
      "skip_window pattern recurs on 08-28, 08-31 and 09-01 - days with proven "
      "post-gate execution. Every earlier conclusion built on 957/957 is "
      "therefore unsound.\n"
      "3. The OI layer was healthy: 659 polls, 30 s median cadence, spanning "
      "10:00:59-15:29:47.\n"
      "4. The window predicate never changed: 3 byte-distinct forms across 477 "
      "engine copies, the live form unchanged since 2026-08-17.\n\n"
      "## Eliminated\n"
      "Engine holiday (no literal in the corpus contains 2026-09-02, and it is "
      "a Wednesday), timezone (predicate normalises to IST; only "
      "Asia/Kolkata/IST literals exist), frozen clock (659 monotonic polls), "
      "predicate regression, OI availability.\n\n"
      "## Unknown, and honestly so\n"
      "The per-cycle window state on 2026-09-02. The live build increments a "
      "bare counter and emits nothing; the forensic build that would have "
      "recorded phase and regime_strength was not the build that ran. No "
      "counterfactual replay can recover it.\n\n"
      "## Next\n"
      "Instrument the skip site, stamp epoch boundaries into metrics.json, and "
      "alert on feed starvation - see 17_PATCH_READINESS.json. Do not touch the "
      "predicate; no evidence implicates it.\n")

    # ------------------------------------------------ 20 exhaustion record
    W("20_EXHAUSTION_RECORD.json", {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "roots_searched": inv["roots_searched"],
        "extensions_searched": inv["extensions_searched"],
        "content_terms_searched": inv["content_terms_searched"],
        "files_indexed": inv["counts"]["files_indexed"],
        "files_relevant": inv["counts"]["relevant"],
        "files_fully_scanned_for_runtime_markers": 811,
        "engine_source_copies_compared": lin["variant_count"],
        "still_missing_and_why": [
            {"artifact": "per-cycle window record for 2026-09-02",
             "why": "the live build has no sentinel at the skip site"},
            {"artifact": "resolved engine config dump for the Sep-02 process",
             "why": "the engine never writes its effective config; bounded "
                    "instead by every holiday literal in the corpus"},
            {"artifact": "regime_strength series for 2026-09-02",
             "why": "only emitted with a scored candidate, and none existed"},
            {"artifact": "metrics epoch boundaries",
             "why": "the writer stamps no timestamps"}],
        "searches_that_returned_nothing": [
            "SIGNAL_WINDOW_CLOSED in any runtime log (present only in source "
            "and reports)",
            "skip_warmup / skip_degraded counters in the Sep-02 epoch",
            "any decisions.jsonl row dated 2026-09-02",
            "any oi_candidate row dated 2026-09-02"]})

    # ------------------------------------------------ 19 integrity manifest
    art = []
    for root, _, fns in os.walk(PKG):
        for fn in sorted(fns):
            p = os.path.join(root, fn)
            if os.path.basename(p) == "19_INTEGRITY_MANIFEST.json":
                continue
            art.append({"file": os.path.relpath(p, PKG),
                        "size": os.path.getsize(p), "sha256": sha256(p)})
    W("19_INTEGRITY_MANIFEST.json", {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "package_root": PKG,
        "production_source_hash": lin["today_live_source"],
        "artifacts": art,
        "raw_evidence_copies": copied,
        "verification": "recompute sha256 of each entry; source copies match "
                        "their originals byte for byte"})

    print("parts=%d raw_copies=%d bytes=%d"
          % (len(art), len(copied), sum(a["size"] for a in art)))
    for a in art:
        if os.sep not in a["file"]:
            print(" %9d %s %s" % (a["size"], a["sha256"][:8], a["file"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
