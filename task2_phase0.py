# -*- coding: utf-8 -*-
"""
TASK 2 / PHASE 0 - AUTHORITATIVE FILE IDENTITY  (machine-generated)

Proves that the file about to be analysed/patched is exactly
    C:\\Users\\Guest -A\\Desktop\\Dhan Test\\Dhan.py
and that it is the same copy the Task-1 PASS run measured. Creates and verifies
Dhan.py.TASK2_PRE.bak and writes TASK2_PRE_BASELINE.json.

No production file is modified by this script.
"""
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime

AUTH_DIR = r"C:\Users\Guest -A\Desktop\Dhan Test"
R = os.path.dirname(os.path.abspath(__file__))
P = os.path.join(AUTH_DIR, "Dhan.py")
BAK = P + ".TASK2_PRE.bak"
OUT = os.path.join(AUTH_DIR, "TASK2_PRE_BASELINE.json")


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for blk in iter(lambda: fh.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def ident(p):
    if not os.path.exists(p):
        return {"path": p, "exists": False}
    with open(p, "rb") as fh:
        b = fh.read()
    return {"path": p, "exists": True, "sha256": hashlib.sha256(b).hexdigest(),
            "bytes": len(b), "lines": b.count(b"\n") + (0 if b.endswith(b"\n") else 1),
            "mtime": datetime.fromtimestamp(os.path.getmtime(p)).isoformat()}


def jsonl_info(p):
    if not os.path.exists(p):
        return {"path": p, "exists": False}
    n, first, last, bad = 0, None, None, 0
    with open(p, encoding="utf-8", errors="replace") as fh:
        for ln in fh:
            ln = ln.strip()
            if not ln:
                continue
            n += 1
            if not ln.startswith("{"):
                bad += 1
                continue
            try:
                r = json.loads(ln)
            except Exception:
                bad += 1
                continue
            t = r.get("ts") or r.get("timestamp") or r.get("chain_ts")
            if first is None:
                first = t
            last = t
    return {"path": p, "exists": True, "bytes": os.path.getsize(p), "lines": n,
            "unparsable": bad, "first_ts": first, "last_ts": last,
            "sha256": sha(p)}


def main():
    rep = {"phase": 0, "generated": datetime.now().isoformat(),
           "authoritative_dir": AUTH_DIR,
           "script_dir": R,
           "script_dir_is_authoritative": os.path.normcase(R) == os.path.normcase(AUTH_DIR)}

    rep["dhan"] = ident(P)
    if not rep["dhan"]["exists"]:
        rep["IDENTITY"] = "AMBIGUOUS_MISSING_FILE"
        json.dump(rep, open(OUT, "w", encoding="utf-8"), indent=1)
        print("STOP: authoritative Dhan.py not found")
        return 2

    # every other copy of Dhan.py on the Desktop tree, to prove uniqueness of
    # the file under test (path rule: only the Guest -A copy may be used)
    others = []
    desk = os.path.dirname(AUTH_DIR)
    for root, dirs, files in os.walk(desk):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git", "node_modules")]
        for f in files:
            if f == "Dhan.py":
                fp = os.path.join(root, f)
                if os.path.normcase(fp) != os.path.normcase(P):
                    try:
                        others.append({"path": fp, "sha256": sha(fp),
                                       "bytes": os.path.getsize(fp)})
                    except Exception as e:
                        others.append({"path": fp, "error": str(e)})
    rep["other_dhan_copies"] = others
    rep["same_content_copies_elsewhere"] = [o for o in others
                                            if o.get("sha256") == rep["dhan"]["sha256"]]

    # tie the file to the Task-1 PASS evidence
    t1, t1v2 = {}, {}
    for name, key in (("TASK1C_FINAL_REPORT.json", "t1"),
                      ("TASK1C_FINAL_REPORT_V2.json", "t1v2")):
        p = os.path.join(AUTH_DIR, name)
        d = {"path": p, "exists": os.path.exists(p)}
        if d["exists"]:
            d["sha256"] = sha(p)
            j = json.load(open(p, encoding="utf-8"))
            d["final_verdict"] = j.get("final_verdict")
            d["recorded_dhan_sha256"] = (j.get("final_sha256")
                                         or j.get("reused", {}).get("final_sha256"))
            d["recorded_forensics_sha256"] = (j.get("forensics_sha256")
                                              or j.get("reused", {}).get("forensics_sha256"))
        (t1 if key == "t1" else t1v2).update(d)
    rep["task1_report"] = t1
    rep["task1_report_v2"] = t1v2
    rep["same_copy_as_task1_pass"] = bool(
        t1.get("recorded_dhan_sha256") == rep["dhan"]["sha256"]
        and t1v2.get("recorded_dhan_sha256") == rep["dhan"]["sha256"]
        and t1v2.get("final_verdict") == "PASS")

    rep["support_files"] = {n: ident(os.path.join(AUTH_DIR, n)) for n in
                            ("forensics.py", "task1c_signalpath.py", "task1c_final.py",
                             "task1c_report.py", "Dhan.py.PRE_FORENSICS.bak")}
    fsha = rep["support_files"]["forensics.py"].get("sha256")
    rep["forensics_matches_task1_record"] = (
        fsha == t1.get("recorded_forensics_sha256") ==
        t1v2.get("recorded_forensics_sha256"))

    # pre-patch backup
    if not os.path.exists(BAK) or sha(BAK) != rep["dhan"]["sha256"]:
        shutil.copy2(P, BAK)
    with open(P, "rb") as a, open(BAK, "rb") as b:
        rep["backup"] = {"path": BAK, "byte_for_byte_equal": a.read() == b.read(),
                         "sha256": sha(BAK)}

    # real production evidence inventory (no interpretation yet)
    rep["evidence_files"] = {
        "decisions_root": jsonl_info(os.path.join(AUTH_DIR, "decisions.jsonl")),
        "decisions_logs": jsonl_info(os.path.join(AUTH_DIR, "logs", "decisions.jsonl")),
        "oi_diag": jsonl_info(os.path.join(AUTH_DIR, "logs", "oi_diag.jsonl")),
        "trace": jsonl_info(os.path.join(AUTH_DIR, "logs",
                                         "signal_starvation_trace.jsonl")),
    }

    ok = (rep["dhan"]["exists"] and rep["script_dir_is_authoritative"]
          and rep["same_copy_as_task1_pass"] and rep["backup"]["byte_for_byte_equal"])
    rep["IDENTITY"] = "VERIFIED" if ok else "AMBIGUOUS"
    json.dump(rep, open(OUT, "w", encoding="utf-8", newline="\n"), indent=1,
              default=str, sort_keys=True)

    print("IDENTITY              :", rep["IDENTITY"])
    print("Dhan.py               :", rep["dhan"]["sha256"])
    print("  bytes/lines/mtime   :", rep["dhan"]["bytes"], rep["dhan"]["lines"],
          rep["dhan"]["mtime"])
    print("same copy as T1 PASS  :", rep["same_copy_as_task1_pass"],
          "| forensics matches:", rep["forensics_matches_task1_record"])
    print("other Dhan.py copies  :", len(others),
          "| identical elsewhere:", len(rep["same_content_copies_elsewhere"]))
    for o in others[:6]:
        print("   ", o.get("path"), str(o.get("sha256"))[:12])
    print("backup byte-equal     :", rep["backup"]["byte_for_byte_equal"], BAK)
    for k, v in rep["evidence_files"].items():
        print("evidence %-15s" % k, "exists=%s lines=%s first=%s last=%s"
              % (v.get("exists"), v.get("lines"), v.get("first_ts"), v.get("last_ts")))
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
