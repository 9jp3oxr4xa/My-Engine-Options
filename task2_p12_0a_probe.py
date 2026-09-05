# -*- coding: utf-8 -*-
"""
TASK 2 / PHASE 12-0A/0D/0F PROBE  (READ ONLY)

1. dumps every small metadata/lineage/manifest file in the bundle verbatim
2. characterises oi_live.log (format, line count, samples)  <- new evidence
3. censuses the bundle's own oi_diag.jsonl: events, dates, schema completeness,
   the engine's own mirror agreement flags, and whether the delta arrays are
   complete relative to the series they came from
"""
import collections
import json
import os

B = r"C:\Users\Guest -A\Desktop\Dhan Test\Audit Bundle Sep 02"
SMALL = ["07_METADATA\\LINEAGE.txt", "07_METADATA\\CURRENT_DHAN_METADATA.json",
         "07_METADATA\\INTEGRITY_CHECK.json", "07_METADATA\\BUNDLE_METADATA.json",
         "04_TASK1_TASK2_SEPARATE\\TASK_LINEAGE_INVENTORY.txt",
         "05_SYSTEM\\ENVIRONMENT.txt", "05_SYSTEM\\TODAY_FILE_INVENTORY.txt",
         "06_HASHES\\MANIFEST.json", "02_TODAY_LOGS\\logs\\metrics.json"]
OILOG = os.path.join(B, "oi_live.log")
OIDIAG = os.path.join(B, "02_TODAY_LOGS", "logs", "oi_diag.jsonl")


def main():
    print("#" * 70)
    print("# SMALL METADATA FILES (verbatim, truncated at 2500 chars)")
    for rel in SMALL:
        p = os.path.join(B, rel)
        print("\n----- %s -----" % rel)
        if not os.path.exists(p):
            print("  <missing>")
            continue
        t = open(p, encoding="utf-8", errors="replace").read()
        print(t[:2500] + ("\n  ...[truncated %d chars]" % (len(t) - 2500)
                          if len(t) > 2500 else ""))

    print("\n" + "#" * 70)
    print("# oi_live.log CHARACTERISATION")
    n, jsonl, samples = 0, 0, []
    with open(OILOG, encoding="utf-8", errors="replace") as fh:
        for i, ln in enumerate(fh):
            n += 1
            s = ln.strip()
            if s.startswith("{"):
                jsonl += 1
            if i < 3 or (5000 <= i < 5002):
                samples.append((i, s[:1200]))
    print("lines=%d json_lines=%d" % (n, jsonl))
    for i, s in samples:
        print("  [%d] %s" % (i, s))
    with open(OILOG, "rb") as fh:
        fh.seek(max(0, os.path.getsize(OILOG) - 2000))
        tail = fh.read().decode("utf-8", "replace").splitlines()
    print("  [tail] %s" % (tail[-1][:1200] if tail else ""))

    print("\n" + "#" * 70)
    print("# BUNDLE oi_diag.jsonl CENSUS")
    ev = collections.Counter()
    dates = collections.Counter()
    keys = collections.Counter()
    mirror = collections.Counter()
    warm = collections.Counter()
    lens = collections.Counter()
    complete = collections.Counter()
    und = collections.Counter()
    exp = collections.Counter()
    first_row = None
    with open(OIDIAG, encoding="utf-8", errors="replace") as fh:
        for ln in fh:
            ln = ln.strip()
            if not ln.startswith("{"):
                continue
            try:
                r = json.loads(ln)
            except Exception:
                ev["PARSE_ERROR"] += 1
                continue
            ev[str(r.get("event"))] += 1
            dates[str(r.get("ts"))[:10]] += 1
            und[str(r.get("underlying"))] += 1
            exp[str(r.get("expiry"))] += 1
            for k in r:
                keys[k] += 1
            mirror[str(r.get("mirror_matches_engine"))] += 1
            warm[str(r.get("warmup_ok"))] += 1
            pd_ = r.get("pe_deltas")
            ps = r.get("pe_basket_series")
            if isinstance(pd_, list) and isinstance(ps, list):
                lens["series=%d deltas=%d" % (len(ps), len(pd_))] += 1
                complete["deltas_len_field_matches_array=%s"
                         % (r.get("deltas_len") == len(pd_))] += 1
                complete["deltas_equal_series_minus_1=%s"
                         % (len(pd_) == len(ps) - 1)] += 1
                complete["series_equals_snapshots_len=%s"
                         % (len(ps) == r.get("snapshots_len"))] += 1
            if first_row is None:
                first_row = r
    print("events=%s" % json.dumps(ev))
    print("dates=%s" % json.dumps(dates))
    print("underlyings=%s" % json.dumps(und))
    print("expiries=%s" % json.dumps(exp))
    print("mirror_matches_engine=%s" % json.dumps(mirror))
    print("warmup_ok=%s" % json.dumps(warm))
    print("field presence=%s" % json.dumps(dict(keys)))
    print("completeness=%s" % json.dumps(dict(complete)))
    top = sorted(lens.items(), key=lambda kv: -kv[1])[:12]
    print("series/deltas length pairs (top 12)=%s" % json.dumps(dict(top)))
    if first_row:
        r = dict(first_row)
        for k in ("pe_basket_series", "ce_basket_series", "pe_deltas", "ce_deltas"):
            v = r.get(k)
            if isinstance(v, list):
                r[k] = "[len=%d] %s ..." % (len(v), v[:4])
        print("FIRST ROW=%s" % json.dumps(r, default=str)[:2500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
