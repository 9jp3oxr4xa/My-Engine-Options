"""
S4 PATCH — wire the SENSEX chain adapter into Dhan.py.

PROTOCOL
  1. BACKUP current (post-S3) Dhan.py with a timestamp.
  2. Validate the EXACT anchor and require count == 1, else ABORT.
  3. Apply one atomic in-memory edit, then write.
  4. py_compile.
  5. Auto-restore the backup if compilation fails.

SCOPE
  * Registers FyersChainAdapter for SENSEX only, alongside the untouched
    NIFTY -> NSEChainAdapter mapping.
  * Import is local to the branch so a missing/broken adapter module can
    never affect NIFTY startup.
  * Does NOT touch config.yaml. SENSEX stays out of engine.underlyings,
    so this code path is inert until S5 activation.
"""
from __future__ import annotations

import datetime
import os
import py_compile
import shutil
import sys

TARGET = "Dhan.py"

ANCHOR_LINES = [
    "    if nse_chain is not None:",
    "        engine.nse_chain = nse_chain",
    "        for _u in cfg.engine.underlyings:",
    '            if _u == "NIFTY":',
    "                engine.chain_adapters[_u] = nse_chain",
    "",
]

REPLACEMENT_LINES = [
    "    if nse_chain is not None:",
    "        engine.nse_chain = nse_chain",
    "        for _u in cfg.engine.underlyings:",
    '            if _u == "NIFTY":',
    "                engine.chain_adapters[_u] = nse_chain",
    "    # S4: per-underlying SENSEX chain provider (FYERS). NIFTY untouched.",
    "    # Import is local so an adapter fault can never break NIFTY startup.",
    '    if "SENSEX" in cfg.engine.underlyings:',
    "        try:",
    "            from fyers_chain_adapter import FyersChainAdapter",
    "        except Exception as _exc:",
    "            raise FatalConfigError(",
    '                f"SENSEX chain adapter unavailable: {_exc}") from _exc',
    "        engine.chain_adapters[\"SENSEX\"] = FyersChainAdapter(",
    "            symbol_map={\"SENSEX\": (instruments.by_name[\"SENSEX\"].fyers_symbol",
    "                                  or \"BSE:SENSEX-INDEX\")},",
    "            logger=logger,",
    "        )",
    "        log_event(logger, logging.INFO, \"sensex_chain_provider_selected\",",
    "                  provider=\"fyers_options_chain_v3\")",
    "",
]


def main() -> int:
    root = os.path.dirname(os.path.abspath(__file__))
    os.chdir(root)

    if not os.path.isfile(TARGET):
        print("S4_TARGET_MISSING")
        return 2

    src = open(TARGET, encoding="utf-8").read()

    if "FyersChainAdapter" in src:
        print("S4_PATCH=ALREADY_APPLIED")
        return 0

    anchor = "\n".join(ANCHOR_LINES)
    count = src.count(anchor)
    print(f"S4_ANCHOR_COUNT={count}")
    if count != 1:
        print("S4_ANCHOR_GATE=FAIL")
        print("S4_PATCH=ABORTED")
        return 2
    print("S4_ANCHOR_GATE=PASS")

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = f"Dhan_before_S4_fyers_chain_{stamp}.py"
    shutil.copy2(TARGET, backup)
    print(f"S4_BACKUP=PASS {backup} {os.path.getsize(backup)}")

    patched = src.replace(anchor, "\n".join(REPLACEMENT_LINES), 1)
    if patched == src:
        print("S4_PATCH=NO_CHANGE")
        return 2

    with open(TARGET, "w", encoding="utf-8", newline="") as fh:
        fh.write(patched)
    print("S4_PATCH=APPLIED")

    try:
        py_compile.compile(TARGET, doraise=True)
        print("PY_COMPILE=PASS")
    except Exception as exc:
        shutil.copy2(backup, TARGET)
        print(f"PY_COMPILE=FAIL {type(exc).__name__}")
        print("S4_ROLLBACK=RESTORED_S4_BACKUP")
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
