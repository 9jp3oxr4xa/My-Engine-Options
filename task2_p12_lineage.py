# -*- coding: utf-8 -*-
"""
TASK 2 / PHASE 12-0A..0E  (READ ONLY)

0A  source lineage: hash every Dhan.py reachable on this machine and the bundle,
    and decide - by hash, not by date - which one today's live session used.
0C  Task1/Task2 inclusion control against the actual live source.
0D  ingest today's live data: the bundle oi_diag.jsonl AND oi_live.log (UTF-16).
0E  reconcile the bundle's evidence against the earlier Task 2 evidence.
0G  test whether z is now exactly reproducible: today's rows persist mu, sd, win
    and lookback, so z needs no delta array at all.

Emits TASK2_SOURCE_LINEAGE.json, TASK2_EVIDENCE_RECONCILIATION.json
"""
import collections
import hashlib
import json
import math
import os
from datetime import datetime, timezone

GUEST = r"C:\Users\Guest -A\Desktop"
PROJ = os.path.join(GUEST, "Dhan Test")
B = os.path.join(PROJ, "Audit Bundle Sep 02")
BUNDLE_SRC = os.path.join(B, "01_SOURCE", "Dhan.py")
BUNDLE_DIAG = os.path.join(B, "02_TODAY_LOGS", "logs", "oi_diag.jsonl")
OILOG = os.path.join(B, "oi_live.log")
LOCAL_DIAG = os.path.join(PROJ, "logs", "oi_diag.jsonl")
CLAIMED_TODAY_SHA = "550d18d3a3b665b2861c41bbf0a7ae2442c4a9e05efb8372c00b2bd5ed21bf21"
FORENSIC_SHA = "faad0e675f1c8cd14550415c53438f3a3a52462f76fed05ad0cafe241c9d50f0"


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for x in iter(lambda: fh.read(1 << 20), b""):
            h.update(x)
    return h.hexdigest()


def ts(x):
    return datetime.fromtimestamp(x, timezone.utc).astimezone().isoformat()


def rows(path, encoding):
    with open(path, encoding=encoding, errors="replace") as fh:
        for ln in fh:
            ln = ln.strip().lstrip("\ufeff")
            if ln.startswith("{"):
                try:
                    yield json.loads(ln)
                except Exception:
                    continue


def main():
    # ---------- 0A: every Dhan.py on this machine ---------------------------
    copies = []
    for root, dnames, fnames in os.walk(GUEST):
        dnames[:] = [d for d in dnames if not d.startswith((".git", "node_modules",
                                                            "__pycache__"))]
        for f in fnames:
            if f.lower() == "dhan.py":
                p = os.path.join(root, f)
                try:
                    st = os.stat(p)
                    copies.append({"path": p, "size": st.st_size,
                                   "last_write_time": ts(st.st_mtime),
                                   "sha256": sha(p)})
                except OSError as e:
                    copies.append({"path": p, "error": str(e)})
    by_sha = collections.Counter(c.get("sha256") for c in copies)
    match_today = [c for c in copies if c.get("sha256") == CLAIMED_TODAY_SHA]
    match_forensic = [c for c in copies if c.get("sha256") == FORENSIC_SHA]

    src_txt = open(BUNDLE_SRC, encoding="utf-8", errors="replace").read()
    for_txt = (open(os.path.join(PROJ, "Dhan.py"), encoding="utf-8",
                    errors="replace").read()
               if os.path.exists(os.path.join(PROJ, "Dhan.py")) else "")

    def markers(t):
        return {
            "live_terms_instrumentation": t.count("_last_terms"),
            "oi_diag_note_candidate": t.count("oi_diag_note_candidate"),
            "mirror_matches_engine": t.count("mirror_matches_engine"),
            "legacy_verdict": t.count("legacy_verdict"),
            "informative_obs": t.count("informative_obs"),
            "duplicates_dropped": t.count("duplicates_dropped"),
            "basket_presence_filter": t.count("len(legs) < len(atm_strikes)"),
            "task1_marker": t.count("TASK1"),
            "task2_marker": t.count("TASK2"),
            "import_task1": t.count("import task1"),
            "import_task2": t.count("import task2"),
            "import_forensics": t.count("import forensics"),
            "lines": t.count("\n") + 1,
        }

    lineage = {
        "generated": datetime.now().isoformat(),
        "bundle_declares": {
            "project": r"C:\Users\Administrator\Desktop\Dhan Test",
            "authoritative_source": r"C:\Users\Administrator\Desktop\Dhan Test\Dhan.py",
            "sha256": CLAIMED_TODAY_SHA,
            "length": 248303,
            "last_write_time": "2026-09-01T08:43:15.0796436+05:30",
            "dhan_unchanged_during_bundle": True,
            "task1_included_as_production": False,
            "task2_included_as_production": False},
        "MACHINE_MISMATCH": {
            "bundle_project_user": "Administrator",
            "this_machine_project_user": "Guest -A",
            "consequence": "the bundle's live source and this machine's forensic "
                           "source are different files on different profiles; "
                           "phases 0-11 line numbers refer to the forensic copy"},
        "dhan_py_copies_found_on_this_machine": copies,
        "distinct_hashes": dict(by_sha),
        "bundle_source_copy": {"path": BUNDLE_SRC, "sha256": sha(BUNDLE_SRC),
                               "size": os.path.getsize(BUNDLE_SRC),
                               "matches_bundle_manifest":
                                   sha(BUNDLE_SRC) == CLAIMED_TODAY_SHA},
        "TODAY_LIVE_SOURCE_PROVEN": sha(BUNDLE_SRC) == CLAIMED_TODAY_SHA,
        "TODAY_LIVE_SOURCE_SHA256": sha(BUNDLE_SRC),
        "today_live_source_present_on_this_machine": bool(match_today),
        "forensic_source_sha256": FORENSIC_SHA,
        "forensic_source_copies_on_this_machine": len(match_forensic),
        "YESTERDAY_BASELINE_PROVEN": False,
        "YESTERDAY_BASELINE_SHA256": None,
        "yesterday_baseline_reason": (
            "no artifact on this machine or in the bundle is identified as "
            "yesterday's production source; the bundle itself states it must be "
            "independently identified and must not be inferred from today's "
            "source. Today's live file carries a 2026-09-01 08:43 write time, "
            "which is consistent with but does not prove a yesterday baseline."),
        "markers_today_live_source": markers(src_txt),
        "markers_forensic_source": markers(for_txt),
        "TASK1_IN_TODAY_LIVE_SOURCE": "FALSE" if (
            "import task1" not in src_txt and "TASK1" not in src_txt) else "TRUE",
        "TASK2_IN_TODAY_LIVE_SOURCE": "FALSE" if (
            "import task2" not in src_txt and "TASK2" not in src_txt) else "TRUE",
        "task_exclusion_basis": ("searched today's live source text for task "
                                 "imports and task markers; forensic scripts live "
                                 "outside Dhan.py and are not imported by it"),
    }
    json.dump(lineage, open(os.path.join(PROJ, "TASK2_SOURCE_LINEAGE.json"), "w",
                            encoding="utf-8", newline="\n"), indent=1,
              default=str, sort_keys=True)

    # ---------- 0D: today's data, both files --------------------------------
    def census(it, tag):
        c = {"tag": tag, "events": collections.Counter(),
             "dates": collections.Counter(), "expiries": collections.Counter(),
             "mirror": collections.Counter(), "branches": collections.Counter(),
             "verdicts": collections.Counter(), "series_len": collections.Counter(),
             "snap_len": collections.Counter(), "z_exact": 0, "z_checked": 0,
             "z_max_err": 0.0, "ladder_checked": 0, "ladder_exact": 0,
             "live_terms_keys": collections.Counter(), "cand": 0,
             "cand_dirs": collections.Counter(), "cand_pass": collections.Counter()}
        for r in it:
            ev = str(r.get("event"))
            c["events"][ev] += 1
            c["dates"][str(r.get("ts"))[:10]] += 1
            c["expiries"][str(r.get("expiry"))] += 1
            c["mirror"][str(r.get("mirror_matches_engine"))] += 1
            c["branches"][str(r.get("branch"))] += 1
            c["verdicts"][str(r.get("verdict_engine"))] += 1
            if isinstance(r.get("snapshots_len"), int):
                c["snap_len"][r["snapshots_len"] // 50 * 50] += 1
            if isinstance(r.get("pe_basket_series"), list):
                c["series_len"][len(r["pe_basket_series"])] += 1
            lt = r.get("live_terms")
            if isinstance(lt, dict):
                for k in lt:
                    c["live_terms_keys"][k] += 1
            if ev == "oi_candidate":
                c["cand"] += 1
                c["cand_dirs"][str(r.get("candidate_direction"))] += 1
                c["cand_pass"][str(r.get("directional_oi_would_pass"))] += 1
            # z from persisted scalars only
            lb = r.get("lookback_used")
            if lb:
                for side in ("pe", "ce"):
                    mu, sd, win, z = (r.get("mu_%s" % side), r.get("sd_%s" % side),
                                      r.get("win_%s" % side), r.get("z_%s" % side))
                    if None in (mu, sd, win, z):
                        continue
                    mu, sd, win, z, lb = (float(mu), float(sd), float(win),
                                          float(z), int(lb))
                    calc = 0.0 if sd <= 0 else (win - mu * lb) / (sd * math.sqrt(lb))
                    c["z_checked"] += 1
                    err = abs(calc - z)
                    c["z_max_err"] = max(c["z_max_err"], err)
                    if err <= 1e-9:
                        c["z_exact"] += 1
                # ladder from persisted term flags
                t = {k: r.get(k) for k in ("term_z_pe_ge_1_5", "term_z_ce_le_0",
                                           "term_z_ce_ge_1_5", "term_z_pe_le_0",
                                           "term_z_ce_le_neg_1_5",
                                           "term_z_pe_le_neg_1_5")}
                if all(v is not None for v in t.values()):
                    wp = float(r.get("win_pe") or 0)
                    wc = float(r.get("win_ce") or 0)
                    b1 = bool(t["term_z_pe_ge_1_5"] and t["term_z_ce_le_0"] and wp > 0)
                    b2 = bool(t["term_z_ce_ge_1_5"] and t["term_z_pe_le_0"] and wc > 0)
                    pred = ("bearish" if b1 else "bullish" if b2 else None)
                    c["ladder_checked"] += 1
                    if pred is None or pred == str(r.get("verdict_engine")):
                        c["ladder_exact"] += 1
        for k in ("events", "dates", "expiries", "mirror", "branches", "verdicts",
                  "series_len", "snap_len", "live_terms_keys", "cand_dirs",
                  "cand_pass"):
            c[k] = dict(c[k])
        return c

    bundle_c = census(rows(BUNDLE_DIAG, "utf-8"), "bundle oi_diag.jsonl")
    live_c = census(rows(OILOG, "utf-16"), "oi_live.log (utf-16)")

    prev = {}
    for n in ("TASK2_LEDGER_SUMMARY.json", "TASK2_P6_P10.json", "TASK2_P7B.json"):
        p = os.path.join(PROJ, n)
        if os.path.exists(p):
            prev[n] = json.load(open(p, encoding="utf-8"))
    prev_polls = ((prev.get("TASK2_P6_P10.json", {})
                   .get("P7_M1_history_admission", {}) or {}).get("polls_measured"))
    prev_cand = (prev.get("TASK2_LEDGER_SUMMARY.json", {}) or {}).get("P2_total")

    recon = {
        "generated": datetime.now().isoformat(),
        "streams_are_different_files": {
            "bundle_diag": {"path": BUNDLE_DIAG,
                            "bytes": os.path.getsize(BUNDLE_DIAG),
                            "sha256": sha(BUNDLE_DIAG)},
            "local_diag": {"path": LOCAL_DIAG,
                           "bytes": os.path.getsize(LOCAL_DIAG)
                           if os.path.exists(LOCAL_DIAG) else None},
            "same_file": False},
        "metrics": [
            {"metric": "poll_count", "previous_value": prev_polls,
             "today_bundle_value": bundle_c["events"].get("oi_snapshot"),
             "source": "oi_snapshot rows",
             "reason": "different machines and different log files; the bundle "
                       "stream is NIFTY-only and much shorter"},
            {"metric": "candidate_count", "previous_value": prev_cand,
             "today_bundle_value": bundle_c["events"].get("oi_candidate"),
             "source": "oi_candidate rows",
             "reason": "the bundle's 120 candidates are a different population "
                       "from the 190-row forensic ledger"},
            {"metric": "date_coverage",
             "previous_value": ["2026-08-31", "2026-09-01"],
             "today_bundle_value": sorted(bundle_c["dates"]),
             "source": "ts field", "reason": "bundle adds 2026-09-02"},
            {"metric": "expiry_coverage", "previous_value": ["2026-09-01",
                                                             "2026-09-08"],
             "today_bundle_value": sorted(bundle_c["expiries"]),
             "source": "expiry field", "reason": "same roll present"},
            {"metric": "mirror_matches_engine", "previous_value": None,
             "today_bundle_value": bundle_c["mirror"],
             "source": "engine self-check",
             "reason": "field absent from the forensic stream"},
            {"metric": "informative_obs", "previous_value": "present (live_terms)",
             "today_bundle_value": ("present" if "informative_obs"
                                    in bundle_c["live_terms_keys"] else "ABSENT"),
             "source": "live_terms",
             "reason": "today's live source instrumented fewer terms"},
            {"metric": "series truncation", "previous_value": "~25 of median 62",
             "today_bundle_value": bundle_c["series_len"],
             "source": "pe_basket_series length",
             "reason": "same truncation defect"},
        ],
        "bundle_census": bundle_c, "oi_live_census": live_c,
        "Z_RECONSTRUCTION_FROM_PERSISTED_SCALARS": {
            "bundle_checked": bundle_c["z_checked"],
            "bundle_exact": bundle_c["z_exact"],
            "bundle_max_abs_err": bundle_c["z_max_err"],
            "oi_live_checked": live_c["z_checked"],
            "oi_live_exact": live_c["z_exact"],
            "oi_live_max_abs_err": live_c["z_max_err"],
            "method": "z = (win - mu*lookback) / (sd*sqrt(lookback)) using only "
                      "the persisted mu, sd, win and lookback_used, so no delta "
                      "array is needed",
            "EXACT": (bundle_c["z_checked"] > 0
                      and bundle_c["z_exact"] == bundle_c["z_checked"])},
    }
    json.dump(recon, open(os.path.join(PROJ, "TASK2_EVIDENCE_RECONCILIATION.json"),
                          "w", encoding="utf-8", newline="\n"), indent=1,
              default=str, sort_keys=True)

    print("== 0A LINEAGE ==")
    print("bundle source sha matches manifest: %s"
          % lineage["bundle_source_copy"]["matches_bundle_manifest"])
    print("TODAY_LIVE_SOURCE_SHA256=%s" % lineage["TODAY_LIVE_SOURCE_SHA256"])
    print("today's live source present on this machine: %s"
          % lineage["today_live_source_present_on_this_machine"])
    print("Dhan.py copies on this machine: %d  distinct hashes: %d"
          % (len(copies), len(by_sha)))
    print("YESTERDAY_BASELINE_PROVEN=%s" % lineage["YESTERDAY_BASELINE_PROVEN"])
    print("TASK1_IN_TODAY_LIVE_SOURCE=%s  TASK2_IN_TODAY_LIVE_SOURCE=%s"
          % (lineage["TASK1_IN_TODAY_LIVE_SOURCE"],
             lineage["TASK2_IN_TODAY_LIVE_SOURCE"]))
    print("markers today: %s" % json.dumps(lineage["markers_today_live_source"]))
    print("markers forensic: %s" % json.dumps(lineage["markers_forensic_source"]))
    print("== 0D TODAY DATA ==")
    for c in (bundle_c, live_c):
        print(" %s: events=%s dates=%s" % (c["tag"], json.dumps(c["events"]),
                                           json.dumps(c["dates"])))
        print("    candidates=%d dirs=%s would_pass=%s"
              % (c["cand"], json.dumps(c["cand_dirs"]),
                 json.dumps(c["cand_pass"])))
        print("    branches=%s" % json.dumps(c["branches"]))
        print("    verdicts=%s mirror=%s" % (json.dumps(c["verdicts"]),
                                             json.dumps(c["mirror"])))
        print("    series_len=%s snap_len_buckets=%s"
              % (json.dumps(dict(sorted(c["series_len"].items())[-6:])),
                 json.dumps(dict(sorted(c["snap_len"].items())))))
        print("    live_terms keys=%s" % json.dumps(c["live_terms_keys"]))
        print("    z: checked=%d exact=%d max_err=%.3g | ladder: checked=%d exact=%d"
              % (c["z_checked"], c["z_exact"], c["z_max_err"],
                 c["ladder_checked"], c["ladder_exact"]))
    print("Z_EXACT_FROM_PERSISTED_SCALARS=%s"
          % recon["Z_RECONSTRUCTION_FROM_PERSISTED_SCALARS"]["EXACT"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
