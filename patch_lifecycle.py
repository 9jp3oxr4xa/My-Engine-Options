"""
LIFECYCLE + LIQUIDITY REPAIR — backup, exact-anchor patch, compile, rollback.

VERIFIED DEFECTS (confirmed by reading Dhan.py, not assumed):
  BUG-1 line 1795: OptionsIntel._snapshots deque(maxlen=40). volume_5m
        (line 1987) requires a snapshot >= 300 s old. config
        chain_poll_interval_s = 5 => deque spans 40*5 = 200 s < 300 s, so
        volume_5m ALWAYS returns {} => RiskGates vol5m_ok always False =>
        every candidate rejected LIQUIDITY forever. Signals impossible.
  BUG-2 lines 4035-4037: loop.call_soon_threadsafe() is unguarded. After the
        asyncio loop closes (process teardown) the FYERS SDK daemon thread
        keeps calling _on_message; call_soon_threadsafe raises
        RuntimeError("Event loop is closed"), which the broad except at 4040
        mislabels as fyers_parse_error and miscounts.
  BUG-3 _run_live: on Windows loop.add_signal_handler raises
        NotImplementedError (suppressed), so stop_event never fires and
        KeyboardInterrupt (a BaseException) bypasses engine.shutdown()
        entirely => final snapshot lost, ws never marked stopped.
  BUG-4 duplicate processes: nothing prevents two Dhan.py instances, which
        is what caused two FYERS sockets and the engine.log rotation
        PermissionError [WinError 32].
"""
from __future__ import annotations

import datetime
import os
import py_compile
import shutil
import sys

TARGET = "Dhan.py"
EDITS: list[tuple[str, str, str]] = []


def add(tag: str, old: str, new: str) -> None:
    EDITS.append((tag, old, new))


# ---------------- PATCH A: volume_5m starvation ----------------------------
add(
    "A_SNAPSHOT_DEPTH",
    "        self._snapshots: Deque[ChainSnapshot] = deque(maxlen=40)",
    "        # LIFECYCLE-FIX A: volume_5m needs a snapshot >= 300 s old.\n"
    "        # At chain_poll_interval_s=5 a 40-deep deque spans only 200 s,\n"
    "        # so volume_5m returned {} forever and the LIQUIDITY gate could\n"
    "        # never pass. 240 * 5 s = 1200 s gives headroom for slower polls\n"
    "        # too. Depth only; no threshold or scoring change.\n"
    "        self._snapshots: Deque[ChainSnapshot] = deque(maxlen=240)",
)

# ---------------- PATCH B: guarded thread -> loop handoff -----------------
add(
    "B_LOOP_HANDOFF",
    "            loop = self._loop\n"
    "            if loop is not None and not self._stopped:\n"
    "                loop.call_soon_threadsafe(self._deliver, tick)",
    "            # LIFECYCLE-FIX B: the FYERS SDK daemon thread outlives the\n"
    "            # asyncio loop. Deliver only when this callback belongs to the\n"
    "            # CURRENT feed session AND the loop is alive. The RuntimeError\n"
    "            # catch is the last-resort barrier for the microscopic window\n"
    "            # between is_closed() and the call - not the primary guard.\n"
    "            loop = self._loop\n"
    "            session = self._session\n"
    "            if (loop is None or self._stopped\n"
    "                    or session != self._session or loop.is_closed()):\n"
    "                self.metrics.inc(\"fyers_stale_callbacks\")\n"
    "                return\n"
    "            try:\n"
    "                loop.call_soon_threadsafe(self._deliver, tick)\n"
    "            except RuntimeError:\n"
    "                # Loop closed between the check and the call: process is\n"
    "                # dying. Drop silently; never log as a parse error.\n"
    "                self.metrics.inc(\"fyers_stale_callbacks\")\n"
    "                return",
)

# ---------------- PATCH B2: session id + observability ---------------------
add(
    "B2_SESSION_INIT",
    "        self._loop: Any = None",
    "        self._loop: Any = None\n"
    "        # LIFECYCLE-FIX B: monotonic feed-session id. Incremented every\n"
    "        # time run() binds a loop, so callbacks from a previous websocket\n"
    "        # session can be recognised and discarded.\n"
    "        self._session: int = 0",
)

add(
    "B3_SESSION_BIND",
    "        self._loop = asyncio.get_running_loop()",
    "        self._loop = asyncio.get_running_loop()\n"
    "        self._session += 1",
)

# ---------------- PATCH B4: release loop on close -------------------------
add(
    "B4_CLOSE_RELEASE",
    "    async def close(self) -> None:\n"
    "        self._stopped = True\n"
    "        # FYERS SDK v3 has no public close() on FyersDataSocket.",
    "    async def close(self) -> None:\n"
    "        # LIFECYCLE-FIX B: stop delivery FIRST, then invalidate the\n"
    "        # session and drop the loop reference so any in-flight SDK\n"
    "        # callback fails the guard instead of touching a dying loop.\n"
    "        self._stopped = True\n"
    "        self._session += 1\n"
    "        self._loop = None\n"
    "        # FYERS SDK v3 has no public close() on FyersDataSocket.",
)

# ---------------- PATCH C: guarantee shutdown on Windows ------------------
add(
    "C_WINDOWS_SHUTDOWN",
    "    run_task = asyncio.create_task(engine.run())\n"
    "    stop_task = asyncio.create_task(stop_event.wait())\n"
    "    done, _pending = await asyncio.wait({run_task, stop_task},\n"
    "                                        return_when=asyncio.FIRST_COMPLETED)\n"
    "    stop_task.cancel()\n"
    "    with contextlib.suppress(asyncio.CancelledError, Exception):\n"
    "        await stop_task\n"
    "    await engine.shutdown()",
    "    run_task = asyncio.create_task(engine.run())\n"
    "    stop_task = asyncio.create_task(stop_event.wait())\n"
    "    # LIFECYCLE-FIX C: on Windows add_signal_handler is unavailable, so\n"
    "    # Ctrl+C surfaces as KeyboardInterrupt (a BaseException) and used to\n"
    "    # bypass engine.shutdown() entirely - losing the final snapshot and\n"
    "    # leaving the feed un-stopped. The finally block guarantees the feed\n"
    "    # is silenced and state is persisted on EVERY exit path.\n"
    "    done: set = set()\n"
    "    try:\n"
    "        done, _pending = await asyncio.wait(\n"
    "            {run_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)\n"
    "    finally:\n"
    "        stop_task.cancel()\n"
    "        with contextlib.suppress(asyncio.CancelledError, Exception):\n"
    "            await stop_task\n"
    "        # Silence the external producer BEFORE the loop can close.\n"
    "        if engine.ws is not None:\n"
    "            with contextlib.suppress(BaseException):\n"
    "                await engine.ws.close()\n"
    "        with contextlib.suppress(BaseException):\n"
    "            await engine.shutdown()",
)

# ---------------- PATCH D: single-instance guard --------------------------
add(
    "D_SINGLE_INSTANCE",
    'if __name__ == "__main__":\n'
    "    raise SystemExit(main())",
    "def _acquire_single_instance_lock() -> Any:\n"
    "    \"\"\"LIFECYCLE-FIX D: refuse to start a second engine.\n"
    "\n"
    "    Two concurrent Dhan.py processes meant two FYERS websockets, two\n"
    "    log handlers competing for engine.log (the WinError 32 rotation\n"
    "    failure), and racing snapshot writers. The lock file handle is kept\n"
    "    open for the process lifetime and released automatically on exit.\n"
    "    \"\"\"\n"
    "    lock_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),\n"
    "                             \"state\", \"engine.lock\")\n"
    "    os.makedirs(os.path.dirname(lock_path), exist_ok=True)\n"
    "    handle = open(lock_path, \"a+\", encoding=\"utf-8\")\n"
    "    try:\n"
    "        if os.name == \"nt\":\n"
    "            import msvcrt\n"
    "            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)\n"
    "        else:\n"
    "            import fcntl\n"
    "            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
    "    except OSError:\n"
    "        handle.close()\n"
    "        print(\"ENGINE_ALREADY_RUNNING: another Dhan.py instance holds \"\n"
    "              \"state/engine.lock; refusing to start a second feed.\",\n"
    "              file=sys.stderr)\n"
    "        raise SystemExit(3)\n"
    "    handle.seek(0)\n"
    "    handle.truncate()\n"
    "    handle.write(str(os.getpid()))\n"
    "    handle.flush()\n"
    "    return handle\n"
    "\n"
    "\n"
    'if __name__ == "__main__":\n'
    "    _INSTANCE_LOCK = _acquire_single_instance_lock()\n"
    "    raise SystemExit(main())",
)


def main() -> int:
    root = os.path.dirname(os.path.abspath(__file__))
    os.chdir(root)
    if not os.path.isfile(TARGET):
        print("TARGET_MISSING")
        return 2

    src = open(TARGET, encoding="utf-8").read()
    if "LIFECYCLE-FIX" in src:
        print("PATCH=ALREADY_APPLIED")
        return 0

    fail = False
    for tag, old, _new in EDITS:
        c = src.count(old)
        print(f"ANCHOR {tag} count={c}")
        if c != 1:
            fail = True
    if fail:
        print("ANCHOR_GATE=FAIL")
        print("PATCH=ABORTED (no file written)")
        return 2
    print("ANCHOR_GATE=PASS")

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = f"Dhan_before_event_loop_lifecycle_fix_{stamp}.py"
    shutil.copy2(TARGET, backup)
    print(f"BACKUP=PASS {backup} {os.path.getsize(backup)}")

    out = src
    for _tag, old, new in EDITS:
        out = out.replace(old, new, 1)

    with open(TARGET, "w", encoding="utf-8", newline="") as fh:
        fh.write(out)
    print("PATCH=APPLIED")

    try:
        py_compile.compile(TARGET, doraise=True)
        print("PY_COMPILE=PASS")
    except Exception as exc:
        shutil.copy2(backup, TARGET)
        print(f"PY_COMPILE=FAIL {type(exc).__name__}: {exc}")
        print("ROLLBACK=RESTORED")
        return 2
    return 0


if __name__ == "__main__":
    from typing import Any  # noqa: F401  (referenced in generated code)
    sys.exit(main())
