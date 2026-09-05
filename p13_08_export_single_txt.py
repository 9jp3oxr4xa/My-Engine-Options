# -*- coding: utf-8 -*-
"""
NUCLEAR OPUS 5 - FORENSIC PACKAGE -> ONE SINGLE TEXT FILE
byte-preserving / zero loss / zero truncation / zero summary

Reads  C:\\Users\\Guest -A\\Desktop\\Dhan Test\\TASK2_PHASE13_FABLE_PACKAGE
Writes C:\\Users\\Guest -A\\Desktop\\Dhan Test\\TASK2_PHASE13_FABLE_PACKAGE_COMPLETE.txt

Preservation mechanism: every file is carried as BASE64 of its EXACT ORIGINAL
BYTES, so no decoding, newline normalisation, JSON reserialisation or BOM
rewriting can occur. Framing is ASCII with LF line ends and is written in
binary mode so every recorded offset is an exact byte offset.

Passes:
 1 enumerate + sha256 + size + encoding sniff (source is only read)
 2 dry-run byte accounting so manifest offsets are exact before writing
 3 write container (header, index, manifest, payload blocks, instructions)
 4 verify: structural scan, offset-driven decode of every payload,
   sha256 + length comparison against the recorded values AND against a
   fresh hash of the original file, then append FINAL_VERIFICATION

Fails closed: any defect sets EXPORT_STATUS=FAIL.

Self-reference note: a file cannot contain its own sha256. FINAL_VERIFICATION
therefore records PAYLOAD_SECTION_SHA256 (hash of every byte up to the end of
the last END_FILE, which IS self-verifiable) and the whole-file digest is
written to the sidecar .verification.json and printed.
"""
import base64
import hashlib
import json
import os
import time

DESK = r"C:\Users\Guest -A\Desktop"
PROJ = os.path.join(DESK, "Dhan Test")
SRC = os.path.join(PROJ, "TASK2_PHASE13_FABLE_PACKAGE")
OUT = os.path.join(PROJ, "TASK2_PHASE13_FABLE_PACKAGE_COMPLETE.txt")
SIDE = OUT + ".verification.json"
RAWDIR = "18_RAW_EVIDENCE"
LINE = 76                      # base64 chars per line
CHUNK = 57 * 50000             # 2,850,000 bytes -> exactly 50,000 full lines
TYPES = {".json": "JSON", ".jsonl": "JSONL", ".ndjson": "JSONL",
         ".txt": "TEXT", ".md": "MARKDOWN", ".csv": "CSV", ".py": "PYTHON",
         ".ps1": "POWERSHELL", ".log": "LOG", ".yaml": "YAML", ".yml": "YAML",
         ".trace": "TRACE", ".out": "OUT", ".err": "ERR", ".ini": "INI",
         ".cfg": "CFG", ".toml": "TOML"}


def sha256_file(p):
    h = hashlib.sha256()
    n = 0
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
            n += len(b)
    return h.hexdigest(), n


def sniff(p, size):
    if size == 0:
        return "EMPTY"
    with open(p, "rb") as fh:
        head = fh.read(65536)
    if head[:3] == b"\xef\xbb\xbf":
        return "UTF-8-BOM"
    if head[:2] == b"\xff\xfe":
        return "UTF-16-LE-BOM"
    if head[:2] == b"\xfe\xff":
        return "UTF-16-BE-BOM"
    if b"\x00" in head:
        return "BINARY_OR_UNKNOWN"
    try:
        head.decode("utf-8")
        return "UTF-8"
    except UnicodeDecodeError:
        # a multibyte sequence may straddle the sniff boundary
        try:
            head[:-4].decode("utf-8")
            return "UTF-8"
        except UnicodeDecodeError:
            return "BINARY_OR_UNKNOWN"


def b64_payload_len(n):
    """exact byte length of the wrapped base64 payload (newlines included,
    no trailing newline)"""
    if n == 0:
        return 0, 0
    full = n // 57
    rem = n % 57
    chars = full * LINE + (4 * ((rem + 2) // 3) if rem else 0)
    lines = full + (1 if rem else 0)
    return chars + (lines - 1), lines


def main():
    t0 = time.time()
    if not os.path.isdir(SRC):
        print("EXPORT_STATUS=FAIL missing source root")
        return 1

    # ---------------------------------------------------- pass 1: enumerate
    entries = []
    for root, dirs, fns in os.walk(SRC):
        dirs.sort()
        for fn in sorted(fns):
            p = os.path.join(root, fn)
            rel = os.path.relpath(p, SRC)
            st = os.stat(p)
            sha, n = sha256_file(p)
            if n != st.st_size:
                print("EXPORT_STATUS=FAIL size race on %s" % rel)
                return 1
            ext = os.path.splitext(fn)[1].lower()
            entries.append({
                "abs": p, "rel": rel, "sort": rel.replace("\\", "/"),
                "size": n, "sha256": sha, "ext": ext,
                "type": TYPES.get(ext, "BINARY_OR_UNKNOWN"),
                "encoding": sniff(p, n),
                "mtime": time.strftime("%Y-%m-%dT%H:%M:%S",
                                       time.localtime(st.st_mtime)),
                "in_raw": rel.split(os.sep)[0] == RAWDIR})
    entries.sort(key=lambda e: e["sort"])
    for i, e in enumerate(entries, 1):
        e["id"] = i

    total = sum(e["size"] for e in entries)
    raw = [e for e in entries if e["in_raw"]]
    raw_bytes = sum(e["size"] for e in raw)
    man_canon = "\n".join("%s|%d|%s" % (e["sort"], e["size"], e["sha256"])
                          for e in entries)
    man_sha = hashlib.sha256(man_canon.encode("utf-8")).hexdigest()

    dirs_all = sorted({os.path.dirname(e["rel"]) or "." for e in entries})
    types_all = {}
    for e in entries:
        types_all[e["type"]] = types_all.get(e["type"], 0) + 1
    mtimes = sorted(e["mtime"] for e in entries)
    dhan = [e for e in entries if e["rel"].lower().endswith(".py")
            and "dhan" in os.path.basename(e["rel"]).lower()]
    dhan_hashes = sorted({e["sha256"] for e in dhan})

    def sel(pred):
        return [e for e in entries if pred(e)]

    groups = {
        "MANIFEST_OR_HASH_FILES": sel(lambda e: any(
            k in e["rel"].upper() for k in ("MANIFEST", "INTEGRITY", "HASH"))),
        "REPORT_FILES": sel(lambda e: e["type"] in ("MARKDOWN", "TEXT")),
        "LOG_FILES": sel(lambda e: e["type"] in ("LOG", "TRACE", "OUT", "ERR")),
        "JSON_FILES": sel(lambda e: e["type"] == "JSON"),
        "JSONL_FILES": sel(lambda e: e["type"] == "JSONL"),
        "TASK1_ARTIFACTS": sel(lambda e: "TASK1" in e["rel"].upper()),
        "TASK2_ARTIFACTS": sel(lambda e: "TASK2" in e["rel"].upper()),
        "PYTHON_FILES": sel(lambda e: e["type"] == "PYTHON"),
    }

    # -------------------------------------- pass 2: exact byte accounting
    def block_prefix(e, begin, end):
        return ("BEGIN_FILE\n"
                "FILE_ID=%d\n"
                "RELATIVE_PATH=%s\n"
                "TYPE=%s\n"
                "EXTENSION=%s\n"
                "ORIGINAL_BYTE_LENGTH=%d\n"
                "SHA256=%s\n"
                "TEXT_ENCODING_DETECTED=%s\n"
                "SOURCE_MTIME=%s\n"
                "BASE64_PAYLOAD_BEGIN_OFFSET=%012d\n"
                "BASE64_PAYLOAD_END_OFFSET=%012d\n"
                "BASE64_BEGIN\n" % (e["id"], e["rel"], e["type"], e["ext"]
                                    or "NONE", e["size"], e["sha256"],
                                    e["encoding"], e["mtime"], begin, end))

    def header_text(with_offsets):
        L = []
        A = L.append
        A("BEGIN_MASTER_FORENSIC_PACKAGE\n")
        A("FORMAT_VERSION=1\n")
        A("GENERATED_AT=%s\n" % time.strftime("%Y-%m-%dT%H:%M:%S"))
        A("SOURCE_ROOT=%s\n" % SRC)
        A("FILE_COUNT=%d\n" % len(entries))
        A("TOTAL_SOURCE_BYTES=%d\n" % total)
        A("ENCODING=ASCII_CONTAINER_WITH_BASE64_FILE_PAYLOADS\n")
        A("PRESERVATION_MODE=BYTE_EXACT\n")
        A("ORIGINAL_PACKAGE_MODIFIED=FALSE\n")
        A("BASE64_LINE_WIDTH=%d\n" % LINE)
        A("FRAMING_NEWLINE=LF\n")
        A("SOURCE_MANIFEST_SHA256=%s\n" % man_sha)
        A("PACKAGE_GENERATION_TIME=%s\n" % time.strftime("%Y-%m-%dT%H:%M:%S"))
        A("SOURCE_FILE_COUNT=%d\n" % len(entries))
        A("SOURCE_TOTAL_BYTES=%d\n" % total)
        A("RAW_EVIDENCE_COUNT=%d\n" % len(raw))
        A("RAW_EVIDENCE_BYTES=%d\n" % raw_bytes)
        A("EARLIEST_FILE_TIMESTAMP=%s\n" % (mtimes[0] if mtimes else "NONE"))
        A("LATEST_FILE_TIMESTAMP=%s\n" % (mtimes[-1] if mtimes else "NONE"))
        A("DATE_RANGE_OF_FILES=%s..%s\n" % (mtimes[0][:10] if mtimes else "-",
                                            mtimes[-1][:10] if mtimes else "-"))
        A("TASK1_ARTIFACT_COUNT=%d\n" % len(groups["TASK1_ARTIFACTS"]))
        A("TASK2_ARTIFACT_COUNT=%d\n" % len(groups["TASK2_ARTIFACTS"]))
        A("DHAN_PY_COPIES_FOUND=%d\n" % len(dhan))
        A("DHAN_PY_DISTINCT_HASHES=%d\n" % len(dhan_hashes))
        A("\nBEGIN_LIST_OF_DIRECTORIES\n")
        for d in dirs_all:
            A("DIR=%s\n" % d)
        A("END_LIST_OF_DIRECTORIES\n")
        A("\nBEGIN_LIST_OF_FILE_TYPES\n")
        for k in sorted(types_all):
            A("TYPE=%s COUNT=%d\n" % (k, types_all[k]))
        A("END_LIST_OF_FILE_TYPES\n")
        A("\nBEGIN_DHAN_PY_INVENTORY\n")
        for e in dhan:
            A("DHAN_PY FILE_ID=%d SHA256=%s BYTES=%d PATH=%s\n"
              % (e["id"], e["sha256"], e["size"], e["rel"]))
        for h in dhan_hashes:
            A("DHAN_PY_HASH=%s\n" % h)
        A("END_DHAN_PY_INVENTORY\n")
        for gname, lst in groups.items():
            A("\nBEGIN_%s COUNT=%d\n" % (gname, len(lst)))
            for e in lst:
                A("FILE_ID=%d BYTES=%d PATH=%s\n" % (e["id"], e["size"],
                                                     e["rel"]))
            A("END_%s\n" % gname)
        A("\nBEGIN_INDEX\n")
        A("# FILE_ID|RELATIVE_PATH|TYPE|SIZE|SHA256\n")
        for e in entries:
            A("%d|%s|%s|%d|%s\n" % (e["id"], e["rel"], e["type"], e["size"],
                                    e["sha256"]))
        A("END_INDEX\n")
        A("\nBEGIN_MASTER_MANIFEST\n")
        for e in entries:
            b, x = with_offsets.get(e["id"], (0, 0))
            A("FILE_ID=%d\n" % e["id"])
            A("RELATIVE_PATH=%s\n" % e["rel"])
            A("TYPE=%s\n" % e["type"])
            A("EXTENSION=%s\n" % (e["ext"] or "NONE"))
            A("ORIGINAL_BYTE_LENGTH=%d\n" % e["size"])
            A("SHA256=%s\n" % e["sha256"])
            A("TEXT_ENCODING_DETECTED=%s\n" % e["encoding"])
            A("BASE64_PAYLOAD_BEGIN_OFFSET=%012d\n" % b)
            A("BASE64_PAYLOAD_END_OFFSET=%012d\n" % x)
            A("\n")
        A("END_MASTER_MANIFEST\n")
        A("\nBEGIN_PAYLOADS\n")
        return "".join(L)

    zero = {e["id"]: (0, 0) for e in entries}
    head_len = len(header_text(zero).encode("ascii"))
    pos = head_len
    offsets = {}
    for e in entries:
        pre = len(block_prefix(e, 0, 0).encode("ascii"))
        begin = pos + pre
        plen, _ = b64_payload_len(e["size"])
        end = begin + plen
        offsets[e["id"]] = (begin, end)
        pos = end + len("\nBASE64_END\nEND_FILE\n\n")
    header = header_text(offsets)
    if len(header.encode("ascii")) != head_len:
        print("EXPORT_STATUS=FAIL header length not offset-stable")
        return 1

    # ------------------------------------------------ pass 3: write container
    defects = []
    with open(OUT, "wb") as out:
        out.write(header.encode("ascii"))
        for e in entries:
            b, x = offsets[e["id"]]
            out.write(block_prefix(e, b, x).encode("ascii"))
            if out.tell() != b:
                defects.append("offset drift at FILE_ID=%d (%d != %d)"
                               % (e["id"], out.tell(), b))
            first = True
            with open(e["abs"], "rb") as fh:
                while True:
                    chunk = fh.read(CHUNK)
                    if not chunk:
                        break
                    enc = base64.b64encode(chunk)
                    for i in range(0, len(enc), LINE):
                        if not first:
                            out.write(b"\n")
                        out.write(enc[i:i + LINE])
                        first = False
            if out.tell() != x:
                defects.append("payload length drift at FILE_ID=%d (%d != %d)"
                               % (e["id"], out.tell(), x))
            out.write(b"\nBASE64_END\nEND_FILE\n\n")
        payload_end = out.tell()
        out.write(b"END_PAYLOADS\n\n")
        out.write(b"BEGIN_EXTRACTION_INSTRUCTIONS\n"
                  b"1. Parse BEGIN_FILE blocks.\n"
                  b"2. Read RELATIVE_PATH.\n"
                  b"3. Read ORIGINAL_BYTE_LENGTH.\n"
                  b"4. Read SHA256.\n"
                  b"5. Read BASE64 payload (all lines between BASE64_BEGIN and"
                  b" BASE64_END, concatenated with no separators).\n"
                  b"6. Base64 decode.\n"
                  b"7. Verify byte length equals ORIGINAL_BYTE_LENGTH.\n"
                  b"8. Verify sha256 of the decoded bytes equals SHA256.\n"
                  b"9. Write the recovered bytes to RELATIVE_PATH in binary"
                  b" mode (never text mode - text mode would rewrite line"
                  b" endings).\n"
                  b"10. Repeat for every FILE_ID.\n"
                  b"Random access alternative: seek to"
                  b" BASE64_PAYLOAD_BEGIN_OFFSET and read"
                  b" (END_OFFSET - BEGIN_OFFSET) bytes; strip LF; decode.\n"
                  b"END_EXTRACTION_INSTRUCTIONS\n\n")
        instr_end = out.tell()

    # ------------------------------------------------ pass 4: verification
    ids, paths, blocks = [], [], 0
    with open(OUT, "rb") as fh:
        for line in fh:
            if line == b"BEGIN_FILE\n":
                blocks += 1
            elif line.startswith(b"FILE_ID=") and blocks and len(ids) < blocks:
                ids.append(int(line.split(b"=", 1)[1]))
            elif line.startswith(b"RELATIVE_PATH=") and \
                    len(paths) < len(ids):
                paths.append(line.split(b"=", 1)[1].rstrip(b"\n")
                             .decode("utf-8", "replace"))
    verified = sha_bad = len_bad = decode_bad = missing = path_bad = 0
    mutations = []
    with open(OUT, "rb") as fh:
        for e in entries:
            b, x = offsets[e["id"]]
            fh.seek(b)
            raw_b64 = fh.read(x - b)
            if len(raw_b64) != x - b:
                missing += 1
                continue
            try:
                data = base64.b64decode(raw_b64.replace(b"\n", b""),
                                        validate=True)
            except Exception as exc:
                decode_bad += 1
                defects.append("decode failure FILE_ID=%d %s" % (e["id"], exc))
                continue
            if len(data) != e["size"]:
                len_bad += 1
                defects.append("length mismatch FILE_ID=%d" % e["id"])
                continue
            d = hashlib.sha256(data).hexdigest()
            if d != e["sha256"]:
                sha_bad += 1
                defects.append("sha mismatch FILE_ID=%d" % e["id"])
                continue
            now_sha, now_n = sha256_file(e["abs"])
            if now_sha != e["sha256"] or now_n != e["size"]:
                mutations.append(e["rel"])
                continue
            verified += 1
    if blocks != len(entries):
        defects.append("block count %d != file count %d" % (blocks,
                                                            len(entries)))
    if len(set(ids)) != len(ids):
        defects.append("duplicate FILE_IDs")
    dup_ids = len(ids) - len(set(ids))
    for got, e in zip(paths, entries):
        if got != e["rel"]:
            path_bad += 1
    byte_exact = (verified == len(entries) and not sha_bad and not len_bad
                  and not decode_bad and not missing and not path_bad
                  and not mutations and not defects)

    with open(OUT, "rb") as fh:
        prefix_sha = hashlib.sha256()
        left = payload_end
        while left:
            b = fh.read(min(1 << 20, left))
            prefix_sha.update(b)
            left -= len(b)
    prefix_sha = prefix_sha.hexdigest()

    status = "PASS" if byte_exact else "FAIL"
    with open(OUT, "ab") as out:
        out.write(("BEGIN_FINAL_VERIFICATION\n"
                   "SOURCE_FILE_COUNT=%d\n"
                   "SOURCE_TOTAL_BYTES=%d\n"
                   "RAW_EVIDENCE_FILE_COUNT=%d\n"
                   "RAW_EVIDENCE_TOTAL_BYTES=%d\n"
                   "EXPORTED_FILE_COUNT=%d\n"
                   "EXPORTED_TOTAL_BYTES=%d\n"
                   "FILES_VERIFIED=%d\n"
                   "BYTE_EXACT_RECONSTRUCTION=%s\n"
                   "SHA256_MISMATCHES=%d\n"
                   "BYTE_LENGTH_MISMATCHES=%d\n"
                   "DECODE_FAILURES=%d\n"
                   "MISSING_FILE_PAYLOADS=%d\n"
                   "DUPLICATE_FILE_IDS=%d\n"
                   "PATH_MISMATCHES=%d\n"
                   "ORIGINAL_SOURCE_MUTATIONS=%d\n"
                   "SOURCE_PACKAGE_MODIFIED=FALSE\n"
                   "SOURCE_MANIFEST_SHA256=%s\n"
                   "FINAL_TEXT_FILE=%s\n"
                   "PAYLOAD_SECTION_END_OFFSET=%d\n"
                   "PAYLOAD_SECTION_SHA256=%s\n"
                   "FINAL_TEXT_FILE_SHA256=NOT_SELF_REFERENTIAL_SEE_SIDECAR"
                   " (a file cannot contain its own digest; the whole-file"
                   " sha256 is in %s and PAYLOAD_SECTION_SHA256 above covers"
                   " every byte through the last END_FILE)\n"
                   "VERIFICATION_DEFECTS=%d\n"
                   "EXPORT_STATUS=%s\n"
                   "END_FINAL_VERIFICATION\n"
                   "END_MASTER_FORENSIC_PACKAGE\n"
                   % (len(entries), total, len(raw), raw_bytes, blocks,
                      sum(e["size"] for e in entries), verified,
                      "TRUE" if byte_exact else "FALSE", sha_bad, len_bad,
                      decode_bad, missing, dup_ids, path_bad, len(mutations),
                      man_sha, OUT, payload_end, prefix_sha,
                      os.path.basename(SIDE), len(defects), status))
                  .encode("ascii", "replace"))

    final_sha, final_n = sha256_file(OUT)
    json.dump({"final_text_file": OUT, "final_text_file_size": final_n,
               "final_text_file_sha256": final_sha,
               "payload_section_end_offset": payload_end,
               "payload_section_sha256": prefix_sha,
               "instructions_end_offset": instr_end,
               "source_manifest_sha256": man_sha,
               "source_file_count": len(entries), "source_total_bytes": total,
               "raw_evidence_file_count": len(raw),
               "raw_evidence_total_bytes": raw_bytes,
               "files_verified": verified,
               "byte_exact_reconstruction": byte_exact,
               "sha256_mismatches": sha_bad,
               "byte_length_mismatches": len_bad,
               "decode_failures": decode_bad,
               "missing_file_payloads": missing,
               "duplicate_file_ids": dup_ids,
               "path_mismatches": path_bad,
               "original_source_mutations": mutations,
               "defects": defects, "export_status": status,
               "elapsed_s": round(time.time() - t0, 1)},
              open(SIDE, "w", encoding="utf-8", newline="\n"), indent=1)

    print("FINAL_TEXT_FILE=%s" % OUT)
    print("FILE_COUNT=%d" % len(entries))
    print("TOTAL_SOURCE_BYTES=%d" % total)
    print("RAW_EVIDENCE_FILE_COUNT=%d" % len(raw))
    print("TOTAL_RAW_EVIDENCE_BYTES=%d" % raw_bytes)
    print("EXPORTED_FILE_COUNT=%d" % blocks)
    print("BYTE_EXACT_RECONSTRUCTION=%s" % ("TRUE" if byte_exact else "FALSE"))
    print("SHA256_MISMATCHES=%d" % sha_bad)
    print("BYTE_LENGTH_MISMATCHES=%d" % len_bad)
    print("MISSING_FILE_PAYLOADS=%d" % missing)
    print("DECODE_FAILURES=%d" % decode_bad)
    print("DUPLICATE_FILE_IDS=%d" % dup_ids)
    print("PATH_MISMATCHES=%d" % path_bad)
    print("ORIGINAL_SOURCE_MUTATIONS=%d" % len(mutations))
    print("SOURCE_PACKAGE_MODIFIED=FALSE")
    print("FINAL_TEXT_FILE_SIZE=%d" % final_n)
    print("FINAL_TEXT_FILE_SHA256=%s" % final_sha)
    print("EXPORT_STATUS=%s" % status)
    print("elapsed=%.1fs defects=%d" % (time.time() - t0, len(defects)))
    for d in defects[:10]:
        print(" ! %s" % d)
    return 0 if byte_exact else 1


if __name__ == "__main__":
    raise SystemExit(main())
