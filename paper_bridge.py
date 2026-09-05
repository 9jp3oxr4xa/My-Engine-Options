import json
import os
import time
from pathlib import Path

LOG = Path("logs")
SIGNALS = LOG / "decisions.jsonl"
STATE = Path("state") / "paper_positions.json"

REQUIRED = ("id", "ts", "underlying", "direction", "strike", "expiry",
            "option_entry", "option_stop", "targets", "spot_ref")


def load_state():
    STATE.parent.mkdir(parents=True, exist_ok=True)
    if not STATE.exists():
        return {"open": [], "seen_ids": [], "offset": 0}
    try:
        s = json.loads(STATE.read_text(encoding="utf-8"))
        s.setdefault("open", [])
        s.setdefault("seen_ids", [])
        s.setdefault("offset", 0)
        return s
    except Exception:
        corrupt = STATE.with_name(f"paper_positions_corrupt_{int(time.time())}.json")
        try:
            STATE.rename(corrupt)
            print(f"PAPER_STATE=CORRUPT preserved={corrupt}", flush=True)
        except OSError:
            print("PAPER_STATE=CORRUPT (could not preserve)", flush=True)
        return {"open": [], "seen_ids": [], "offset": 0}


def save_state(s):
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, STATE)


def paper_open(row):
    return {
        "id": row["id"], "ts": row["ts"], "underlying": row["underlying"],
        "direction": row["direction"], "strike": row["strike"],
        "expiry": row["expiry"], "entry": row["option_entry"],
        "stop": row["option_stop"], "t1": row["targets"][0],
        "t2": row["targets"][1], "spot_ref": row["spot_ref"],
        "status": "OPEN", "entry_source": "SIGNAL",
    }


def main():
    print("PAPER_BRIDGE_START=PASS", flush=True)
    state = load_state()
    seen = set(state["seen_ids"])
    SIGNALS.parent.mkdir(parents=True, exist_ok=True)
    SIGNALS.touch(exist_ok=True)
    size = SIGNALS.stat().st_size
    offset = state["offset"] if state["offset"] <= size else 0
    with SIGNALS.open("r", encoding="utf-8") as f:
        f.seek(offset)
        buf = ""
        while True:
            chunk = f.readline()
            if not chunk:
                time.sleep(0.5)
                continue
            buf += chunk
            if not buf.endswith("\n"):
                continue  # partial write in progress; wait for the rest
            line, buf = buf, ""
            state["offset"] = f.tell()
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                save_state(state)
                continue
            if row.get("type") != "signal":
                save_state(state)
                continue
            sid = row.get("id")
            if not sid or sid in seen:
                save_state(state)
                continue
            missing = [k for k in REQUIRED if k not in row]
            if missing:
                print(f"PAPER_SKIP id={sid} missing={missing}", flush=True)
                seen.add(sid)
                state["seen_ids"] = sorted(seen)
                save_state(state)
                continue
            pos = paper_open(row)
            state["open"].append(pos)
            seen.add(sid)
            state["seen_ids"] = sorted(seen)
            save_state(state)
            print("\n=== PAPER SIGNAL ACCEPTED ===", flush=True)
            for k, v in pos.items():
                print(f"{k} = {v}", flush=True)
            print("PAPER_ENTRY=PASS", flush=True)


if __name__ == "__main__":
    main()
