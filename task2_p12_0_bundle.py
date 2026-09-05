# -*- coding: utf-8 -*-
"""
TASK 2 / PHASE 12-0  AUDIT BUNDLE FORENSIC INGESTION   (READ ONLY)

Enumerates, hashes and classifies every file in the Sep 02 audit bundle.
Nothing inside the bundle is opened for writing, moved, renamed or extracted.
Outputs are written OUTSIDE the bundle.

Emits TASK2_AUDIT_BUNDLE_INVENTORY.json / .txt
"""
import hashlib
import json
import os
import zipfile
from datetime import datetime, timezone

BUNDLE = r"C:\Users\Guest -A\Desktop\Dhan Test\Audit Bundle Sep 02"
OUTDIR = r"C:\Users\Guest -A\Desktop\Dhan Test"
TEXT_EXT = {".json", ".jsonl", ".txt", ".log", ".py", ".csv", ".md", ".yaml",
            ".yml", ".ini", ".cfg", ".ndjson", ""}
HEAD = 8192


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for blk in iter(lambda: fh.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def ts(x):
    return datetime.fromtimestamp(x, timezone.utc).astimezone().isoformat()


def peek(p, n=HEAD):
    try:
        with open(p, "rb") as fh:
            return fh.read(n).decode("utf-8", "replace")
    except Exception:
        return ""


def classify(rel, ext, head, mtime_iso):
    """Content first, filename only as a tiebreaker. Never filename alone."""
    h = head
    hl = h.lower()
    reasons = []

    is_manifest = False
    if ext in (".txt", ".json", "") and h:
        lines = [x for x in h.splitlines() if x.strip()][:40]
        hexish = sum(1 for x in lines if len(x.split()) >= 2
                     and len(x.split()[0]) == 64
                     and all(c in "0123456789abcdefABCDEF" for c in x.split()[0]))
        if lines and hexish >= max(3, len(lines) // 2):
            is_manifest = True
            reasons.append("majority of lines are <sha256> <name>")
    if is_manifest:
        return "HASH_MANIFEST", reasons

    if ext == ".py":
        if ("class OptionsIntel" in h or "_directional_oi" in h
                or "DhanFeed" in h or "class SignalEngine" in h):
            reasons.append("engine source markers present in head")
            return "SOURCE_CODE", reasons
        if "TASK1" in h or "task1" in rel.lower():
            reasons.append("task1 forensic runner")
            return "TASK1_FORENSIC", reasons
        if "TASK2" in h or "task2" in rel.lower():
            reasons.append("task2 forensic runner")
            return "TASK2_FORENSIC", reasons
        reasons.append("python file without engine or task markers")
        return "UNKNOWN", reasons

    if '"event"' in h and ("oi_snapshot" in h or "oi_candidate" in h):
        reasons.append("oi diagnostic event records")
        return "TODAY_DIAGNOSTIC_EVIDENCE", reasons
    if "TASK1_" in h or "TASK1 " in h:
        reasons.append("task1 report content")
        return "TASK1_FORENSIC", reasons
    if "TASK2_" in h or "TASK2 " in h:
        reasons.append("task2 report content")
        return "TASK2_FORENSIC", reasons
    if any(k in hl for k in ("candidate", "signal", "decision", "structure",
                             "confluence", "gate")) and ext in (".jsonl", ".json"):
        reasons.append("engine decision/candidate records")
        return "TODAY_RUNTIME_EVIDENCE", reasons
    if ext == ".log" or (ext == ".txt" and any(
            k in hl for k in ("info", "warning", "error", "engine", "startup"))):
        reasons.append("runtime log text")
        return "TODAY_RUNTIME_EVIDENCE", reasons
    if ext in (".json",) and any(k in hl for k in ("python", "platform",
                                                   "version", "os", "cwd")):
        reasons.append("environment/system metadata")
        return "SYSTEM_METADATA", reasons
    reasons.append("no decisive content marker")
    return "UNKNOWN", reasons


def main():
    rep = {"generated": datetime.now().isoformat(), "bundle": BUNDLE,
           "bundle_exists": os.path.isdir(BUNDLE)}
    if not rep["bundle_exists"]:
        rep["FAIL_CLOSED"] = "AUDIT_BUNDLE_NOT_FOUND"
        json.dump(rep, open(os.path.join(OUTDIR,
                                         "TASK2_AUDIT_BUNDLE_INVENTORY.json"),
                            "w", encoding="utf-8"), indent=1)
        print("AUDIT_BUNDLE_FOUND=FALSE")
        return 1

    files, dirs = [], []
    for root, dnames, fnames in os.walk(BUNDLE):
        for d in dnames:
            dirs.append(os.path.relpath(os.path.join(root, d), BUNDLE))
        for f in fnames:
            ap = os.path.join(root, f)
            try:
                stt = os.stat(ap)
            except OSError as e:
                files.append({"relative_path": os.path.relpath(ap, BUNDLE),
                              "absolute_path": ap, "error": str(e)})
                continue
            ext = os.path.splitext(f)[1].lower()
            head = peek(ap) if ext in TEXT_EXT else ""
            cls, why = classify(os.path.relpath(ap, BUNDLE), ext, head,
                                ts(stt.st_mtime))
            rec = {"relative_path": os.path.relpath(ap, BUNDLE),
                   "absolute_path": ap, "size": stt.st_size,
                   "creation_time": ts(stt.st_ctime),
                   "last_write_time": ts(stt.st_mtime),
                   "sha256": sha256(ap), "extension": ext,
                   "classification": cls, "classification_reason": why}
            if ext in (".zip",):
                try:
                    with zipfile.ZipFile(ap) as z:
                        rec["zip_entries"] = [
                            {"name": i.filename, "size": i.file_size,
                             "crc": i.CRC, "date_time": list(i.date_time)}
                            for i in z.infolist()]
                        rec["zip_entry_count"] = len(rec["zip_entries"])
                except Exception as e:
                    rec["zip_error"] = str(e)
            if ext in (".jsonl", ".ndjson") or (ext == ".json" and stt.st_size
                                                > 2_000_000):
                rec["first_line_keys"] = None
                try:
                    ln = head.splitlines()[0] if head.strip() else ""
                    if ln.startswith("{"):
                        rec["first_line_keys"] = sorted(json.loads(ln).keys())
                except Exception:
                    pass
            files.append(rec)

    by_cls = {}
    for r in files:
        by_cls.setdefault(r.get("classification", "ERROR"), []).append(
            r["relative_path"])

    dhan_copies = [r for r in files
                   if os.path.basename(r["relative_path"]).lower() == "dhan.py"]
    oi_like = [r for r in files if r.get("classification")
               == "TODAY_DIAGNOSTIC_EVIDENCE" or "oi" in
               os.path.basename(r["relative_path"]).lower()]
    zips = [r for r in files if r.get("extension") == ".zip"]

    rep.update({
        "directories": sorted(dirs), "file_count": len(files),
        "total_bytes": sum(r.get("size", 0) for r in files),
        "classification_counts": {k: len(v) for k, v in sorted(by_cls.items())},
        "classification_index": by_cls,
        "dhan_py_copies": [{k: r[k] for k in ("relative_path", "size", "sha256",
                                              "last_write_time")}
                           for r in dhan_copies],
        "oi_related": [{k: r.get(k) for k in ("relative_path", "size",
                                              "last_write_time",
                                              "first_line_keys")}
                       for r in oi_like],
        "zip_archives": [{k: r.get(k) for k in ("relative_path", "size", "sha256",
                                                "zip_entry_count")}
                         for r in zips],
        "files": files,
        "bundle_modified_by_this_phase": False,
    })
    json.dump(rep, open(os.path.join(OUTDIR, "TASK2_AUDIT_BUNDLE_INVENTORY.json"),
                        "w", encoding="utf-8", newline="\n"), indent=1,
              default=str, sort_keys=True)

    T = ["=" * 78, "TASK 2 / PHASE 12-0  AUDIT BUNDLE INVENTORY (read only)", "=" * 78,
         "bundle: %s" % BUNDLE,
         "files=%d  total_bytes=%d  dirs=%d" % (rep["file_count"],
                                                rep["total_bytes"], len(dirs)),
         "classification: %s" % json.dumps(rep["classification_counts"]), ""]
    for r in sorted(files, key=lambda x: -x.get("size", 0)):
        T.append("%12d  %s  %-28s %s" % (r.get("size", 0),
                                         r.get("last_write_time", "")[:19],
                                         r.get("classification", "ERROR"),
                                         r["relative_path"]))
    T.append("")
    T.append("sha256:")
    for r in sorted(files, key=lambda x: x["relative_path"]):
        T.append("  %s  %s" % (r.get("sha256", "-"), r["relative_path"]))
    txt = "\n".join(T)
    open(os.path.join(OUTDIR, "TASK2_AUDIT_BUNDLE_INVENTORY.txt"), "w",
         encoding="utf-8", newline="\n").write(txt + "\n")

    print("AUDIT_BUNDLE_FOUND=TRUE")
    print("files=%d total_bytes=%d dirs=%d" % (rep["file_count"],
                                               rep["total_bytes"], len(dirs)))
    print("classification=%s" % json.dumps(rep["classification_counts"]))
    print("dirs=%s" % json.dumps(sorted(dirs)[:20]))
    print("LARGEST 30:")
    for r in sorted(files, key=lambda x: -x.get("size", 0))[:30]:
        print("  %11d %s %-26s %s" % (r.get("size", 0),
                                      r.get("last_write_time", "")[:19],
                                      r.get("classification", "ERROR"),
                                      r["relative_path"]))
    print("DHAN.PY COPIES: %s" % json.dumps(rep["dhan_py_copies"], indent=1))
    print("ZIPS: %s" % json.dumps(rep["zip_archives"]))
    print("OI-RELATED: %s" % json.dumps(rep["oi_related"], indent=1)[:2500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
