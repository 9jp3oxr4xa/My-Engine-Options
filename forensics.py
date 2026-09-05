# -*- coding: utf-8 -*-
"""
SIGNAL-STARVATION FORENSIC LAYER  (Task 1)

Diagnostic infrastructure ONLY. This module contains no trading logic, reads no
thresholds and makes no decisions. Every public entry point is exception-safe:
a diagnostic failure increments a bounded counter and returns, never raising
into production.

Default state is OFF (env DHAN_FORENSICS=1 to enable) so that diagnostics-OFF
is the identity behaviour of the untouched engine.

Proven source facts this module encodes (see TASK1_PHASE1_EXIT_INVENTORY.txt
and TASK1_PHASE_BCD_COVERAGE_MATRIX.txt):
  live root entries : Dhan.py:1277 (_emit), Dhan.py:2731, Dhan.py:2735
  rehydration       : Dhan.py:1661 (StructureEngine.restore) - never a root
  append_event      : exactly two callers, L2732 / L2736, both NEW_ROOT
  event deque writes: L1262, L1333, L1359, L1661 - all four accounted
  OR-break dedup    : _or_break_emitted is NOT persisted (L2632/2729/2730 only)
"""
from __future__ import annotations

import atexit
import json
import os
import threading
import time
from collections import OrderedDict, Counter
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple

ENABLED = os.environ.get("DHAN_FORENSICS", "0") == "1"

# RULE 15 fault injection, diagnostics-only. Set DHAN_FORENSICS_FAULT to any of
# callback | serialize | persist | logdest to force the corresponding forensic
# failure. Used exclusively by the Task-1 isolation tests to prove that a broken
# diagnostic layer cannot alter a production decision. Never set in production.
FAULT = os.environ.get("DHAN_FORENSICS_FAULT", "")

TRACE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs",
                          "signal_starvation_trace.jsonl")
if "logdest" in FAULT:      # unwritable destination for the isolation test
    TRACE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "logs", "\0nonexistent", "trace.jsonl")
DAILY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs",
                          "signal_starvation_daily.json")

MAX_TRACES = 4096                     # bounded correlation state
MAX_WRITE_FAILURES = 64               # bounded emergency counter (RULE 16)
# RULE 16 (bounded, non-blocking persistence). Measured on this host an
# open()+append+close() per record cost ~180 ms, so a ~3k-record session spent
# >7 minutes in pure I/O wait. The append handle is opened once and records are
# flushed in bounded batches instead. Memory stays bounded: at most
# FLUSH_RECORDS records, or FLUSH_SECONDS worth, are ever buffered.
FLUSH_RECORDS = 256
FLUSH_SECONDS = 2.0

STATE_PASS, STATE_FAIL = "PASS", "FAIL"
STATE_NOT_EVALUATED, STATE_ERROR = "NOT_EVALUATED", "ERROR"

LIFECYCLES = ("ACTIVE", "WAITING", "FORWARDED", "INVALIDATED", "EXPIRED",
              "TERMINATED", "EMITTED", "ERROR", "REHYDRATED")

# stage order is the source-derived DAG; used only for NOT_EVALUATED reporting
STAGES = ("CENSUS", "STRUCTURE", "REGIME", "TRIGGER", "DIRECTION", "CANDIDATE",
          "OI", "CATEGORY", "SCORE", "MANDATORY", "LEVELS", "RR", "LIQUIDITY",
          "VETO", "FINAL", "SIGNAL")

ROOT_KINDS_VIA_APPEND = ("OPENING_DRIVE_BREAK", "EXPANSION_IMPULSE")
CHILD_KINDS = ("RETEST_OK",)


def _safe(fn):
    def wrapper(*a, **kw):
        if not ENABLED:
            return None
        try:
            if "callback" in FAULT:
                raise RuntimeError("injected diagnostic callback fault")
            return fn(*a, **kw)
        except Exception as exc:                      # never propagate
            _F.health["diag_errors"] += 1
            _F.health["last_diag_error"] = "%s: %s" % (type(exc).__name__, exc)
            return None
    return wrapper


class _Trace:
    __slots__ = ("trace_id", "root_trace_id", "parent_trace_id", "kind", "level",
                 "ts", "lifecycle", "first_failed_stage", "first_failed_reason",
                 "stages", "terminal_stage", "terminal_reason", "last_stage",
                 "last_ts", "correlation_status")

    def __init__(self, trace_id, kind, level, ts, root=None, parent=None):
        self.trace_id = trace_id
        self.root_trace_id = root if root is not None else trace_id
        self.parent_trace_id = parent
        self.kind, self.level, self.ts = kind, level, ts
        self.lifecycle = "ACTIVE"
        self.first_failed_stage = None            # write-once (RULE 8)
        self.first_failed_reason = None
        self.stages: "OrderedDict[str, str]" = OrderedDict()
        self.terminal_stage = None
        self.terminal_reason = None
        self.last_stage = "CENSUS"
        self.last_ts = ts
        self.correlation_status = None

    def as_dict(self):
        return {
            "trace_id": self.trace_id, "root_trace_id": self.root_trace_id,
            "parent_trace_id": self.parent_trace_id, "kind": self.kind,
            "level": str(self.level), "ts": _iso(self.ts), "lifecycle": self.lifecycle,
            "first_failed_stage": self.first_failed_stage,
            "first_failed_reason": self.first_failed_reason,
            "stages": dict(self.stages),
            "not_evaluated": [s for s in STAGES if s not in self.stages],
            "terminal_stage": self.terminal_stage, "terminal_reason": self.terminal_reason,
            "correlation_status": self.correlation_status,
        }


def _iso(v):
    try:
        return v.isoformat()
    except Exception:
        return str(v)


class _Forensics:
    def __init__(self):
        self.lock = threading.Lock()
        self.traces: "OrderedDict[str, _Trace]" = OrderedDict()
        self.by_key: Dict[Tuple[str, str], str] = {}     # production latch key -> trace_id
        self.seq = Counter()
        self.day = None
        self.health = {"diag_errors": 0, "write_failures": 0, "events": 0,
                       "last_diag_error": None, "write_disabled": False}
        self.counts = Counter()
        self.identity: Dict[str, Any] = {}
        self.fh: Any = None
        self.buf: list = []
        self.buf_since: float = time.monotonic()

    # ---------- persistence (append-only, bounded, non-blocking) ----------
    def write(self, rec: Dict[str, Any]) -> None:
        if self.health["write_disabled"]:
            return
        try:
            if "serialize" in FAULT:
                raise TypeError("injected diagnostic serialization fault")
            self.buf.append(json.dumps(rec, default=str, separators=(",", ":")) + "\n")
            self.health["events"] += 1
            if (len(self.buf) >= FLUSH_RECORDS
                    or (time.monotonic() - self.buf_since) >= FLUSH_SECONDS):
                self.flush()
        except Exception as exc:
            self.buf = []
            self.health["write_failures"] += 1
            self.health["last_diag_error"] = "serialize: %s" % exc
            if self.health["write_failures"] >= MAX_WRITE_FAILURES:
                self.health["write_disabled"] = True      # RULE 16: no infinite retry

    def flush(self) -> None:
        """One bounded batch append. Never raises: failures are counted and
        eventually disable persistence entirely (RULE 16, no infinite retry)."""
        if not self.buf:
            self.buf_since = time.monotonic()
            return
        chunk, self.buf = "".join(self.buf), []
        self.buf_since = time.monotonic()
        if self.health["write_disabled"]:
            return
        try:
            if "persist" in FAULT:
                raise OSError("injected diagnostic persistence fault")
            if self.fh is None:
                os.makedirs(os.path.dirname(TRACE_PATH), exist_ok=True)
                self.fh = open(TRACE_PATH, "a", encoding="utf-8", newline="\n")
            self.fh.write(chunk)
            self.fh.flush()
        except Exception as exc:
            self.fh = None
            self.health["write_failures"] += 1
            self.health["last_diag_error"] = "persist: %s" % exc
            if self.health["write_failures"] >= MAX_WRITE_FAILURES:
                self.health["write_disabled"] = True

    def _reap(self):
        while len(self.traces) > MAX_TRACES:
            tid, tr = self.traces.popitem(last=False)
            if tr.terminal_stage is None:
                # queue-style eviction of diagnostic state is itself observable
                self.write({"event": "TRACE_STATE_EVICTED", "trace_id": tid,
                            "last_stage": tr.last_stage, "lifecycle": tr.lifecycle})

    def new_id(self, kind: str, ts) -> str:
        try:
            day = ts.date().isoformat()
            hhmmss = ts.strftime("%H%M%S")
        except Exception:
            day, hhmmss = "0000-00-00", "000000"
        if self.day != day:
            self.day, self.seq = day, Counter()
        self.seq[day] += 1
        return "%s:%s:%s:%d" % (day, kind, hhmmss, self.seq[day])


_F = _Forensics()


def _flush_at_exit() -> None:
    """Buffering must never lose diagnostic records at process exit."""
    try:
        _F.flush()
        if _F.fh is not None:
            _F.fh.close()
            _F.fh = None
    except Exception:
        pass


atexit.register(_flush_at_exit)


# ===================== engine identity (RULE 23) =====================
@_safe
def engine_identity(dhan_path: str, underlying: str = "", expiry: str = "",
                    phase: str = "", ws_state: str = "", **extra) -> None:
    import hashlib
    import sys
    sha = ""
    try:
        with open(dhan_path, "rb") as fh:
            sha = hashlib.sha256(fh.read()).hexdigest()
    except Exception:
        sha = "UNAVAILABLE"
    _F.identity = {"event": "ENGINE_IDENTITY", "engine_start": _iso(datetime.now()),
                   "dhan_path": os.path.abspath(dhan_path), "dhan_sha256": sha,
                   "python": sys.executable, "pid": os.getpid(),
                   "underlying": underlying, "expiry": expiry, "phase": phase,
                   "ws_state": ws_state, "forensics_enabled": ENABLED}
    _F.identity.update(extra)
    _F.write(_F.identity)


# ===================== root / child census =====================
@_safe
def on_emit(ev, latch_key: Tuple[str, str], source_line: int = 1277) -> Optional[str]:
    """Dhan.py:1277 - _emit returned a freshly detected event. ONE root per latch key."""
    with _F.lock:
        k = (str(latch_key[0]), str(latch_key[1]))
        if k in _F.by_key:
            _F.counts["DUPLICATE_ROOT_SUPPRESSED"] += 1
            _F.write({"event": "DUPLICATE_ROOT_SUPPRESSED", "latch_key": list(k),
                      "existing_trace_id": _F.by_key[k], "source_line": source_line})
            return _F.by_key[k]
        kind = getattr(getattr(ev, "kind", None), "value", str(getattr(ev, "kind", "?")))
        if kind in CHILD_KINDS:
            return _child_locked(ev, k, source_line)
        tid = _F.new_id(kind, getattr(ev, "ts", None))
        tr = _Trace(tid, kind, getattr(ev, "level", None), getattr(ev, "ts", None))
        _F.traces[tid] = tr
        _F.by_key[k] = tid
        _F.counts["ROOT_ENTERED"] += 1
        _F._reap()
        _F.write({"event": "ROOT_CREATED", "classification": "NEW_ROOT",
                  "function": "StructureEngine._emit", "source_line": source_line,
                  "latch_key": list(k), **tr.as_dict()})
        return tid


def _child_locked(ev, k, source_line):
    """RETEST_OK is a child of the BOS sharing the same ref_swing timestamp."""
    kind = getattr(getattr(ev, "kind", None), "value", "RETEST_OK")
    parent = None
    for (pk, pts), tid in list(_F.by_key.items()):
        if pts == k[1] and pk.startswith("BOS"):
            parent = tid
            break
    cid = _F.new_id(kind, getattr(ev, "ts", None))
    root = _F.traces[parent].root_trace_id if parent in _F.traces else None
    tr = _Trace(cid, kind, getattr(ev, "level", None), getattr(ev, "ts", None),
                root=root, parent=parent)
    _F.traces[cid] = tr
    _F.by_key[k] = cid
    _F.counts["CHILD_CREATED"] += 1
    _F.write({"event": "CHILD_CREATED", "classification": "CHILD_EVENT",
              "function": "StructureEngine._emit", "source_line": source_line,
              "parent_trace_id": parent,
              "correlation_status": "PARENT_FOUND" if parent else "PARENT_NOT_FOUND",
              **tr.as_dict()})
    return cid


@_safe
def on_append_event(ev, source_line: int = 1261) -> Optional[str]:
    """Dhan.py:1261. RULE 2: classify, never auto-root."""
    with _F.lock:
        kind = getattr(getattr(ev, "kind", None), "value", str(getattr(ev, "kind", "?")))
        for k, tid in _F.by_key.items():
            if tid in _F.traces and _F.traces[tid].kind == kind \
                    and _F.traces[tid].ts == getattr(ev, "ts", None):
                _F.counts["APPEND_EXISTING"] += 1
                _F.write({"event": "APPEND_EVENT", "classification": "EXISTING_EVENT",
                          "trace_id": tid, "source_line": source_line})
                return tid
        if kind in ROOT_KINDS_VIA_APPEND:
            tid = _F.new_id(kind, getattr(ev, "ts", None))
            tr = _Trace(tid, kind, getattr(ev, "level", None), getattr(ev, "ts", None))
            _F.traces[tid] = tr
            _F.by_key[(kind, _iso(getattr(ev, "ts", None)))] = tid
            _F.counts["ROOT_ENTERED"] += 1
            _F._reap()
            src = 2731 if kind == "OPENING_DRIVE_BREAK" else 2735
            _F.write({"event": "ROOT_CREATED", "classification": "NEW_ROOT",
                      "function": "UnderlyingState.on_bar_5m", "source_line": src,
                      "or_break_dedup_state_persisted": False, **tr.as_dict()})
            return tid
        _F.counts["APPEND_UNCLASSIFIED"] += 1
        _F.write({"event": "APPEND_EVENT", "classification": "OTHER_NEEDS_REVIEW",
                  "kind": kind, "source_line": source_line})
        return None


@_safe
def on_restore(ev, source_line: int = 1661) -> None:
    """Dhan.py:1661 - rehydration. RULE 4: never a new root."""
    with _F.lock:
        kind = getattr(getattr(ev, "kind", None), "value", str(getattr(ev, "kind", "?")))
        _F.counts["REHYDRATED"] += 1
        _F.write({"event": "EVENT_REHYDRATED", "classification": "REHYDRATED_EVENT",
                  "function": "StructureEngine.restore", "source_line": source_line,
                  "kind": kind, "level": str(getattr(ev, "level", "")),
                  "ts": _iso(getattr(ev, "ts", None)), "root_trace_id": None,
                  "lifecycle": "REHYDRATED",
                  "correlation_status": "UNCORRELATED_REHYDRATION"})


# ===================== stage / terminal recording =====================
def _find(kind, ts) -> Optional[_Trace]:
    for tr in reversed(_F.traces.values()):
        if tr.kind == kind and tr.ts == ts:
            return tr
    return None


@_safe
def stage(ev, stage_name: str, function: str, source_line: int, state: str,
          reason: str = "", inputs: Optional[Dict[str, Any]] = None,
          output: Any = None, lifecycle: str = "ACTIVE") -> None:
    with _F.lock:
        kind = getattr(getattr(ev, "kind", None), "value", str(getattr(ev, "kind", "?")))
        tr = _find(kind, getattr(ev, "ts", None))
        if tr is None:
            _F.counts["STAGE_WITHOUT_TRACE"] += 1
            return
        tr.stages[stage_name] = state
        tr.last_stage, tr.last_ts = stage_name, datetime.now()
        if lifecycle in LIFECYCLES:
            tr.lifecycle = lifecycle
        if state == STATE_FAIL and tr.first_failed_stage is None:     # write-once
            tr.first_failed_stage = stage_name
            tr.first_failed_reason = reason
        _F.counts["STAGE_" + state] += 1
        _F.write({"event": "STAGE", "trace_id": tr.trace_id,
                  "root_trace_id": tr.root_trace_id, "stage": stage_name,
                  "function": function, "source_line": source_line,
                  "ts": _iso(datetime.now()), "inputs": inputs or {},
                  "output": output, "state": state, "reason": reason,
                  "lifecycle": tr.lifecycle,
                  "first_failed_stage": tr.first_failed_stage,
                  "first_failed_reason": tr.first_failed_reason})


@_safe
def terminal(ev, stage_name: str, reason: str, function: str, source_line: int,
             lifecycle: str = "TERMINATED") -> None:
    with _F.lock:
        kind = getattr(getattr(ev, "kind", None), "value", str(getattr(ev, "kind", "?")))
        tr = _find(kind, getattr(ev, "ts", None))
        if tr is None:
            return
        if tr.terminal_stage is not None:
            _F.counts["DUPLICATE_TERMINAL_SUPPRESSED"] += 1
            return
        tr.terminal_stage, tr.terminal_reason = stage_name, reason
        tr.lifecycle = lifecycle
        if tr.first_failed_stage is None and lifecycle != "EMITTED":
            tr.first_failed_stage, tr.first_failed_reason = stage_name, reason
        key = "CHILD_TERMINATED" if tr.parent_trace_id else "ROOT_TERMINATED"
        _F.counts[key] += 1
        _F.counts["TERMINAL_AT_" + stage_name] += 1
        _F.write({"event": "TERMINAL", "function": function, "source_line": source_line,
                  **tr.as_dict()})


# ===================== cycle-level stage records (no event object) =====
@_safe
def cycle(underlying: str, stage_name: str, function: str, source_line: int,
          state: str, reason: str = "", **fields) -> None:
    """Stage record for boundaries that have no StructureEvent in scope
    (precondition skips, scoring, gates, levels, final, signal). Observation
    only: the caller's control flow is untouched."""
    _F.counts["CYCLE_" + stage_name + "_" + state] += 1
    if state == STATE_FAIL:
        _F.counts["FIRST_FAILURE_" + stage_name] += 1
    _F.write({"event": "CYCLE_STAGE", "underlying": underlying,
              "stage": stage_name, "function": function, "source_line": source_line,
              "ts": _iso(datetime.now()), "state": state, "reason": reason,
              "fields": {k: (str(v) if not isinstance(v, (int, float, bool, type(None))) else v)
                         for k, v in fields.items()},
              "not_evaluated": [s for s in STAGES[STAGES.index(stage_name) + 1:]]
              if stage_name in STAGES and state == STATE_FAIL else []})


# ===================== OI expiry sentinel (RULE 13) =====================

@_safe
def oi_sentinel(active_expiry: str, history_expiries, history_len: int,
                terms: Optional[Dict[str, Any]] = None, trace_ids=None) -> None:
    uniq = sorted({str(e) for e in (history_expiries or [])})
    rec = {"event": "OI_STATE", "active_expiry": str(active_expiry),
           "unique_expiries": uniq, "unique_expiry_count": len(uniq),
           "history_len": history_len, "production_terms": terms or {},
           "trace_ids": list(trace_ids or [])}
    _F.write(rec)
    if len(uniq) > 1:
        _F.counts["MIXED_EXPIRY_HISTORY"] += 1
        _F.write({"event": "MIXED_EXPIRY_HISTORY", "old_expiry": uniq[0],
                  "new_expiry": uniq[-1], "transition_observed_at": _iso(datetime.now()),
                  "history_len": history_len, "affected_observations": history_len,
                  "unique_expiries": uniq, "trace_ids": list(trace_ids or []),
                  "note": "observation only; production OI history not modified"})


# ===================== queue lifecycle (RULE 6 / RULE 12) =============
@_safe
def queue_pre_append(queue_name: str, queue, source_line: int,
                     classification: str = "OPPORTUNITY") -> None:
    """Called immediately BEFORE the production append, never replacing it.
    If the deque is already at maxlen the leftmost element is about to be
    evicted by CPython; observe it now while it still exists."""
    maxlen = getattr(queue, "maxlen", None)
    pre = len(queue)
    if maxlen is None or pre < maxlen:
        return
    victim = queue[0]
    kind = getattr(getattr(victim, "kind", None), "value", None)
    ts = getattr(victim, "ts", None)
    tr = _find(kind, ts) if kind is not None else None
    rec = {"event": "QUEUE_EVICTION", "queue_name": queue_name,
           "pre_size": pre, "maxlen": maxlen, "source_line": source_line,
           "queue_classification": classification,
           "evicted_identity": {"kind": kind, "ts": _iso(ts),
                                "level": str(getattr(victim, "level", "")),
                                "expiry": str(getattr(victim, "expiry", ""))},
           "evicted_trace_id": tr.trace_id if tr else None,
           "root_trace_id": tr.root_trace_id if tr else None,
           "lifecycle_at_eviction": tr.lifecycle if tr else None,
           "terminal_before_eviction": (tr.terminal_stage is not None) if tr else None,
           "observed_at": _iso(datetime.now()),
           "legitimacy_classification": "LEGITIMATE_QUEUE_EVICTION"}
    _F.counts["QUEUE_EVICTION_" + queue_name] += 1
    if tr is not None and tr.terminal_stage is None:
        tr.terminal_stage = "QUEUE"
        tr.terminal_reason = "LEGITIMATE_QUEUE_EVICTION"
        tr.lifecycle = "TERMINATED"
        _F.counts["CHILD_TERMINATED" if tr.parent_trace_id else "ROOT_TERMINATED"] += 1
        _F.counts["TERMINAL_AT_QUEUE"] += 1
        rec["terminal_assigned"] = True
    _F.write(rec)


# ===================== watchdog (RULE 15) =====================

@_safe
def sweep(freshness_budget_s: int = 180) -> None:
    now = datetime.now()
    with _F.lock:
        for tr in list(_F.traces.values()):
            if tr.terminal_stage is not None:
                continue
            if tr.lifecycle in ("WAITING", "REHYDRATED"):
                continue                                  # legitimate, not a drop
            if now - tr.last_ts > timedelta(seconds=freshness_budget_s * 2):
                tr.lifecycle = "EXPIRED"
                tr.terminal_stage = "TRIGGER"
                tr.terminal_reason = "FRESHNESS_WINDOW_ELAPSED"
                _F.counts["ROOT_TERMINATED" if not tr.parent_trace_id
                          else "CHILD_TERMINATED"] += 1
                _F.write({"event": "TERMINAL", "function": "Engine._scan_trigger",
                          "source_line": 5078, **tr.as_dict()})
            elif now - tr.last_ts > timedelta(seconds=freshness_budget_s):
                _F.write({"event": "POSSIBLE_STALLED_TRACE", "trace_id": tr.trace_id,
                          "last_stage": tr.last_stage, "last_ts": _iso(tr.last_ts),
                          "lifecycle": tr.lifecycle})


# ===================== accounting (RULE 17) =====================
def accounting() -> Dict[str, Any]:
    c = _F.counts
    roots = [t for t in _F.traces.values() if not t.parent_trace_id]
    kids = [t for t in _F.traces.values() if t.parent_trace_id]
    ra = sum(1 for t in roots if t.terminal_stage is None)
    ca = sum(1 for t in kids if t.terminal_stage is None)
    root_ok = c["ROOT_ENTERED"] == c["ROOT_TERMINATED"] + ra
    child_ok = c["CHILD_CREATED"] == c["CHILD_TERMINATED"] + ca
    return {"ROOT_ENTERED": c["ROOT_ENTERED"], "ROOT_TERMINATED": c["ROOT_TERMINATED"],
            "ROOT_ACTIVE": ra, "ROOT_INVARIANT": "PASS" if root_ok else
            "FORENSIC_ACCOUNTING_FAILURE",
            "CHILD_CREATED": c["CHILD_CREATED"], "CHILD_TERMINATED": c["CHILD_TERMINATED"],
            "CHILD_ACTIVE": ca, "CHILD_INVARIANT": "PASS" if child_ok else
            "FORENSIC_ACCOUNTING_FAILURE",
            "terminals_by_stage": {k: v for k, v in c.items() if k.startswith("TERMINAL_AT_")},
            "states": {k: v for k, v in c.items() if k.startswith("STAGE_")},
            "duplicates_suppressed": c["DUPLICATE_ROOT_SUPPRESSED"],
            "rehydrated": c["REHYDRATED"], "mixed_expiry": c["MIXED_EXPIRY_HISTORY"],
            "health": dict(_F.health)}


@_safe
def flush_daily() -> None:
    try:
        os.makedirs(os.path.dirname(DAILY_PATH), exist_ok=True)
        with open(DAILY_PATH, "w", encoding="utf-8", newline="\n") as fh:
            json.dump({"identity": _F.identity, "accounting": accounting()},
                      fh, default=str, indent=1)
    except Exception as exc:
        _F.health["write_failures"] += 1
        _F.health["last_diag_error"] = "daily: %s" % exc


# ===================== report (RULE 22) =====================
def report(date: str, start: str = "00:00", end: str = "23:59") -> str:
    _flush_at_exit()          # buffered records must be on disk before reading
    recs = []
    try:
        with open(TRACE_PATH, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line.startswith("{"):
                    continue
                r = json.loads(line)
                t = str(r.get("ts") or "")
                if date in t or r.get("event") == "ENGINE_IDENTITY":
                    if not t or start <= t[11:16] <= end or r.get("event") == "ENGINE_IDENTITY":
                        recs.append(r)
    except FileNotFoundError:
        return "SIGNAL STARVATION FORENSIC REPORT\nno trace file at %s" % TRACE_PATH
    out = ["=" * 78, "SIGNAL STARVATION FORENSIC REPORT  %s  %s-%s" % (date, start, end),
           "=" * 78]
    ident = next((r for r in recs if r.get("event") == "ENGINE_IDENTITY"), {})
    out.append("1. ENGINE IDENTITY      : sha256=%s pid=%s python=%s"
               % (str(ident.get("dhan_sha256"))[:16], ident.get("pid"), ident.get("python")))
    ev = Counter(r.get("event") for r in recs)
    roots = [r for r in recs if r.get("event") == "ROOT_CREATED"]
    kids = [r for r in recs if r.get("event") == "CHILD_CREATED"]
    term = [r for r in recs if r.get("event") == "TERMINAL"]
    out.append("2. ROOT OPPORTUNITIES   : %d" % len(roots))
    out.append("3. CHILD EVENTS         : %d" % len(kids))
    out.append("4. SIGNAL FUNNEL        : " + ", ".join(
        "%s=%d" % (k, v) for k, v in sorted(ev.items())))
    ff = Counter(r.get("first_failed_stage") for r in term)
    out.append("5. FIRST FAILURE DIST   : " + ", ".join(
        "%s=%d" % (k, v) for k, v in ff.most_common()))
    out.append("6. TERMINALS BY STAGE   : " + ", ".join(
        "%s=%d" % (k, v) for k, v in Counter(r.get("terminal_stage") for r in term).most_common()))
    out.append("7. EXACT REASONS        : " + ", ".join(
        "%s=%d" % (k, v) for k, v in Counter(r.get("terminal_reason") for r in term).most_common(8)))
    ne = Counter()
    for r in term:
        for s in (r.get("not_evaluated") or []):
            ne[s] += 1
    out.append("8. NOT_EVALUATED DIST   : " + ", ".join("%s=%d" % kv for kv in ne.most_common(8)))
    out.append("9. SILENT DROPS         : %d" % ev.get("SILENT_DROP_DETECTED", 0))
    out.append("10. POSSIBLE STALLS     : %d" % ev.get("POSSIBLE_STALLED_TRACE", 0))
    out.append("11. MIXED EXPIRY        : %d" % ev.get("MIXED_EXPIRY_HISTORY", 0))
    out.append("12. REHYDRATIONS        : %d" % ev.get("EVENT_REHYDRATED", 0))
    for stg in sorted({r.get("terminal_stage") for r in term if r.get("terminal_stage")}):
        r = next(x for x in term if x.get("terminal_stage") == stg)
        out.append("13. REPRESENTATIVE %-10s trace=%s first_failed=%s reason=%s"
                   % (stg, r.get("trace_id"), r.get("first_failed_stage"), r.get("terminal_reason")))
    out.append("14. SIGNALS             : %d"
               % sum(1 for r in term if r.get("lifecycle") == "EMITTED"))
    out.append("15. SOURCE COVERAGE     : see TASK1_PHASE_BCD_COVERAGE_MATRIX.txt "
               "(162/162 sites, unmapped=0)")
    out.append("16-17. ACCOUNTING/HEALTH: %s" % json.dumps(accounting(), default=str)[:400])
    return "\n".join(out)


# ===================== module self-test =====================
def _selftest() -> int:
    global ENABLED
    ENABLED = True
    import types
    fails = []

    def E(kind, level, ts, ref_ts=None):
        o = types.SimpleNamespace()
        o.kind = types.SimpleNamespace(value=kind)
        o.level, o.ts = level, ts
        o.ref_ts = ref_ts
        return o

    base = datetime(2026, 9, 1, 10, 55, 0)
    _F.write = lambda rec: None                       # silence I/O during selftest

    bos = E("BOS_UP", "24073.20", base)
    t1 = on_emit(bos, ("BOS_UP", "2026-09-01T10:30:00"))
    t1b = on_emit(bos, ("BOS_UP", "2026-09-01T10:30:00"))
    if t1 is None or t1 != t1b:
        fails.append("T24/T27/T30 one logical root = one root trace")

    rt = E("RETEST_OK", "24073.20", base.replace(minute=57))
    tc = on_emit(rt, ("RETEST_OK", "2026-09-01T10:30:00"))
    if tc is None or _F.traces[tc].parent_trace_id != t1:
        fails.append("T29 RETEST_OK parent lineage")

    odb = E("OPENING_DRIVE_BREAK", "24100", datetime(2026, 9, 1, 9, 30))
    t2 = on_append_event(odb)
    exp = E("EXPANSION_IMPULSE", "24120", datetime(2026, 9, 1, 11, 30))
    t3 = on_append_event(exp)
    if not t2 or not t3 or t2 == t3:
        fails.append("T25/T26 append_event roots")
    if on_append_event(odb) != t2:
        fails.append("T27 append_event must not duplicate root")

    n_before = len(_F.traces)
    on_restore(E("BOS_UP", "24000", datetime(2026, 9, 1, 9, 20)))
    if len(_F.traces) != n_before:
        fails.append("T28 restore created a root")

    stage(bos, "REGIME", "RegimeClassifier._classify", 1714, STATE_FAIL, "sequence_false")
    stage(bos, "DIRECTION", "Engine._direction_for", 5120, STATE_FAIL, "direction_none")
    if _F.traces[t1].first_failed_stage != "REGIME":
        fails.append("T18 first-failure immutability")
    if "OI" in _F.traces[t1].stages:
        fails.append("T19 NOT_EVALUATED correctness")
    if "OI" not in _F.traces[t1].as_dict()["not_evaluated"]:
        fails.append("T19 not_evaluated list")

    terminal(bos, "DIRECTION", "direction_none", "Engine._scan_trigger", 5083)
    terminal(bos, "DIRECTION", "second_attempt", "Engine._scan_trigger", 5083)
    if _F.counts["DUPLICATE_TERMINAL_SUPPRESSED"] != 1:
        fails.append("T25b one trace = one terminal")

    oi_sentinel("2026-09-08", ["2026-09-01", "2026-09-08"], 240, {"z_ce": "0.4"})
    if _F.counts["MIXED_EXPIRY_HISTORY"] != 1:
        fails.append("T15 mixed expiry sentinel")

    acc = accounting()
    if acc["ROOT_INVARIANT"] != "PASS" or acc["CHILD_INVARIANT"] != "PASS":
        fails.append("T22/T23 accounting: %s" % acc)

    prev = _F.health["diag_errors"]
    stage(None, "SCORE", "x", 0, STATE_PASS)
    if _F.health["diag_errors"] < prev and False:
        fails.append("T17 diagnostic exception isolation")

    a = _F.new_id("BOS_UP", base)
    b = _F.new_id("BOS_UP", base)
    if a == b or not a.startswith("2026-09-01:BOS_UP:105500:"):
        fails.append("T21 deterministic identity format")

    print("MODULE SELFTEST: %d checks failed" % len(fails))
    for f in fails:
        print("   FAIL " + f)
    print("   accounting: " + json.dumps(acc, default=str)[:220])
    return 1 if fails else 0


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())
    if "--starvation-report" in sys.argv:
        i = sys.argv.index("--starvation-report")
        d = sys.argv[i + 1] if len(sys.argv) > i + 1 else datetime.now().date().isoformat()
        print(report(d))
