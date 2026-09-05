"""
FIX-EV — persist / restore StructureEngine events across restarts.

DEFECT (proven from live evidence)
    StructureEngine.state() serialized swings/bias/levels but NOT the
    structure-event deque (`_events`). restore() additionally cleared the
    `_emitted` dedup latch.

    Live logs show `snapshot_restored` firing 15-24 times per session
    (frequent restarts). Every restart therefore erased all BOS / RETEST_OK /
    SWEEP events. Engine._scan_trigger only considers events whose age is
    <= 180 s, so a wiped deque means NO candidate can ever be produced.
    Result: `logs/decisions.jsonl` is 0 bytes across 4 sessions -- not one
    candidate ever reached scoring, even though analytics were healthy
    (356 x 1m bars, 71 x 5m bars, ADX 22.6, 15 swings, BEARISH bias).

    This is an ENGINEERING DEFECT, not a strategy filter.

FIX (minimal, additive)
    1. state()   -> also serialize the last events and the `_emitted` latch.
    2. restore() -> rebuild both.

    Freshness semantics are UNCHANGED (still 180 s). Restored stale events
    simply age out naturally, exactly as they would have without a restart.
    The `_emitted` latch is restored too, so re-emission/duplicate signals
    remain impossible. No strategy threshold is touched.

PROTOCOL: backup -> exact anchor (count must be 1) -> patch -> compile
          -> auto-rollback on failure.
"""
from __future__ import annotations

import datetime
import os
import py_compile
import shutil
import sys

TARGET = "Dhan.py"

STATE_ANCHOR = '''            "pd_close": str(self._prev_day_close) if self._prev_day_close else None,
        }
'''

STATE_NEW = '''            "pd_close": str(self._prev_day_close) if self._prev_day_close else None,
            # FIX-EV: structure events must survive a restart. Without this
            # the trigger scanner (180 s freshness window) sees an empty deque
            # after every snapshot restore and can never build a candidate.
            "events": [
                {
                    "kind": e.kind.value,
                    "level": str(e.level),
                    "ts": e.ts.isoformat(),
                    "swing": (
                        {
                            "kind": e.ref_swing.kind.value,
                            "price": str(e.ref_swing.price),
                            "ts": e.ref_swing.ts.isoformat(),
                            "idx": e.ref_swing.bar_index,
                        }
                        if e.ref_swing is not None else None
                    ),
                }
                for e in self._events
            ],
            # Preserve the emission latch so restored events can never be
            # re-emitted (no duplicate signals after a restart).
            "emitted": [[k[0], k[1]] for k in sorted(self._emitted)],
        }
'''

RESTORE_ANCHOR = '''        self._pending_bos = []
        self._pending_sweeps = []
        self._emitted = set()
'''

RESTORE_NEW = '''        self._pending_bos = []
        self._pending_sweeps = []
        # FIX-EV: rebuild the emission latch first, then the event deque.
        self._emitted = {
            (str(k[0]), str(k[1]))
            for k in s.get("emitted", [])
            if isinstance(k, (list, tuple)) and len(k) == 2
        }
        self._events = deque(maxlen=50)
        for x in s.get("events", []):
            try:
                sw = x.get("swing")
                ref = (
                    Swing(SwingKind(sw["kind"]), _d(sw["price"]),
                          datetime.fromisoformat(sw["ts"]), int(sw["idx"]), True)
                    if isinstance(sw, dict) else None
                )
                self._events.append(StructureEvent(
                    StructureKind(x["kind"]), _d(x["level"]),
                    datetime.fromisoformat(x["ts"]), ref,
                ))
            except Exception:
                # Malformed persisted event is dropped, never guessed.
                continue
'''


def main() -> int:
    root = os.path.dirname(os.path.abspath(__file__))
    os.chdir(root)

    if not os.path.isfile(TARGET):
        print("FIXEV_TARGET_MISSING")
        return 2

    src = open(TARGET, encoding="utf-8").read()

    if "FIX-EV" in src:
        print("FIXEV_PATCH=ALREADY_APPLIED")
        return 0

    c1 = src.count(STATE_ANCHOR)
    c2 = src.count(RESTORE_ANCHOR)
    print(f"FIXEV_STATE_ANCHOR_COUNT={c1}")
    print(f"FIXEV_RESTORE_ANCHOR_COUNT={c2}")
    if c1 != 1 or c2 != 1:
        print("FIXEV_ANCHOR_GATE=FAIL")
        print("FIXEV_PATCH=ABORTED")
        return 2
    print("FIXEV_ANCHOR_GATE=PASS")

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = f"Dhan_before_FIXEV_events_{stamp}.py"
    shutil.copy2(TARGET, backup)
    print(f"FIXEV_BACKUP=PASS {backup} {os.path.getsize(backup)}")

    patched = src.replace(STATE_ANCHOR, STATE_NEW, 1)
    patched = patched.replace(RESTORE_ANCHOR, RESTORE_NEW, 1)
    if patched == src:
        print("FIXEV_PATCH=NO_CHANGE")
        return 2

    with open(TARGET, "w", encoding="utf-8", newline="") as fh:
        fh.write(patched)
    print("FIXEV_PATCH=APPLIED")

    try:
        py_compile.compile(TARGET, doraise=True)
        print("PY_COMPILE=PASS")
    except Exception as exc:
        shutil.copy2(backup, TARGET)
        print(f"PY_COMPILE=FAIL {type(exc).__name__}: {exc}")
        print("FIXEV_ROLLBACK=RESTORED")
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
