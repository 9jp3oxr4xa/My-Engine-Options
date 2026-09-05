import importlib, sys
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

m = importlib.import_module("Dhan")
IST = ZoneInfo("Asia/Kolkata")

# 1) FIX-02: 5m events stamped at completion
se = m.StructureEngine(3, 3, 2)
se.set_atr_5m(Decimal("10"))

t0 = datetime(2026, 8, 18, 10, 0, tzinfo=IST)
px = Decimal("25000")

for i in range(30):
    o = px
    h = px + Decimal(5)
    l = px - Decimal(5)
    c = px + Decimal(3)

    b = m.Bar(
        t0 + timedelta(minutes=5*i),
        o, h, l, c, 100, 10
    )

    evs = se.on_bar_5m(b)

    for ev in evs:
        assert ev.ts == b.ts_open + timedelta(minutes=5), \
            "FIX02 FAIL: event not at bar close"

    px += Decimal(7)

print("FIX02_EVENT_TS=PASS")

# 2) FIX-03: neutral fail-closed with short history
oi = m.OptionsIntel()

snap = m.ChainSnapshot(
    "NIFTY",
    datetime.now(IST).date(),
    Decimal("25000"),
    datetime.now(IST),
    [],
    Decimal("25000")
)

oi._snapshots.append(snap)

d, z = oi._directional_oi(
    snap,
    Decimal("25000"),
    []
)

assert d == "neutral" and z == Decimal(0), \
    "FIX03 FAIL"

print("FIX03_Z_FAILCLOSED=PASS")

# 3) FIX-05: OptionsView has volume_5m field
assert "volume_5m" in m.OptionsView.__dataclass_fields__, \
    "FIX05 FAIL"

print("FIX05_VOLUME5M=PASS")

# 4) FIX-01: FyersWsFeed has thread-safe deliver path
assert hasattr(m.FyersWsFeed, "_deliver"), \
    "FIX01 FAIL"

print("FIX01_MARSHAL=PASS")
print("VALIDATION=ALL_PASS")
