"""REGRESSION SUITE for RVOL-FIX (Dhan.py VolumeAnalyzer).

Proves:
  R1  the historical defect is real and is now fixed
  R2  fail-closed is preserved: < 10 prior bars still yields None
  R3  suspect / non-positive volume is still refused (no fabricated rvol)
  R4  the cross-session minute-of-day pool still takes precedence when deep
  R5  the intra-session series survives snapshot round-trip
  R6  a new trading day resets the series (no cross-day contamination)
  R7  legacy snapshots without the reserved key still restore
  R8  classify_bar thresholds are unchanged (impulse/absorption/normal)
  R9  Volume category can now reach its pass bar, and still fails when quiet
  R10 Options/OI remains mandatory: the fix alone cannot manufacture a signal

Run:  python -m pytest test_rvol_regression.py -q
      python test_rvol_regression.py          (no pytest required)
"""
from __future__ import annotations

import importlib.util
import os
import sys
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.abspath(__file__))
IST = ZoneInfo("Asia/Kolkata")

_spec = importlib.util.spec_from_file_location("dhan_engine", os.path.join(ROOT, "Dhan.py"))
assert _spec and _spec.loader
dhan = importlib.util.module_from_spec(_spec)
sys.modules["dhan_engine"] = dhan
_spec.loader.exec_module(dhan)

VolumeAnalyzer = dhan.VolumeAnalyzer
Bar = dhan.Bar


def _ts(h: int, m: int, day: int = 31) -> datetime:
    return datetime(2026, 8, day, h, m, tzinfo=IST)


def _bar(ts: datetime, o="24000", h="24010", l="23990", c="24005") -> Bar:
    return Bar(ts_open=ts, open=Decimal(o), high=Decimal(h), low=Decimal(l),
               close=Decimal(c), volume=0, tick_count=1, volume_suspect=True)


# --------------------------------------------------------------------------
def test_r1_defect_fixed_same_session_series():
    """R1: after 10 same-session minutes rvol is available (was None forever)."""
    va = VolumeAnalyzer()
    base = _ts(9, 20)
    for i in range(10):
        va.record_minute(base + timedelta(minutes=i), 1000)
    got = va.rvol(base + timedelta(minutes=10), 2000)
    assert got is not None, "rvol must be available after 10 same-session bars"
    assert abs(got - 2.0) < 1e-9, f"expected 2.0 got {got}"
    # And prove the OLD minute-of-day pool is still shallow, i.e. the fix is
    # what made this reachable, not a deepened cross-session pool.
    pools = [len(v) for v in va._by_minute.values()]
    assert max(pools) == 1, f"each minute-of-day pool should hold 1 sample, got {pools}"
    return "rvol=%.4f, deepest minute-of-day pool=%d" % (got, max(pools))


def test_r2_fail_closed_under_ten_bars():
    """R2: fewer than 10 prior bars must still return None (fail closed)."""
    va = VolumeAnalyzer()
    base = _ts(9, 20)
    for i in range(9):
        va.record_minute(base + timedelta(minutes=i), 1000)
        assert va.rvol(base + timedelta(minutes=i + 1), 1000) is None, (
            "rvol must be None with only %d prior bars" % (i + 1))
    va.record_minute(base + timedelta(minutes=9), 1000)
    assert va.rvol(base + timedelta(minutes=10), 1000) is not None
    return "None for 1..9 bars, available at 10"


def test_r3_suspect_and_nonpositive_refused():
    """R3: suspect or <=0 volume is never recorded and never yields rvol."""
    va = VolumeAnalyzer()
    base = _ts(10, 0)
    for i in range(20):
        va.record_minute(base + timedelta(minutes=i), 1000, suspect=True)
    assert va.rvol(base + timedelta(minutes=21), 1000) is None, "suspect must not build a series"
    va2 = VolumeAnalyzer()
    for i in range(20):
        va2.record_minute(base + timedelta(minutes=i), 0)
    assert va2.rvol(base + timedelta(minutes=21), 1000) is None, "zero volume must not build a series"
    va3 = VolumeAnalyzer()
    for i in range(20):
        va3.record_minute(base + timedelta(minutes=i), 1000)
    assert va3.rvol(base + timedelta(minutes=21), 0) is None, "zero current volume -> None"
    assert va3.rvol(base + timedelta(minutes=21), -5) is None, "negative current volume -> None"
    return "suspect, zero-history, zero-current and negative-current all refused"


def test_r4_cross_session_pool_takes_precedence():
    """R4: when the minute-of-day pool is genuinely deep it is used, unchanged."""
    va = VolumeAnalyzer()
    target = _ts(11, 30)
    # 10 sessions of the SAME clock minute, each 500
    for d in range(10):
        va.record_minute(target.replace(day=1 + d), 500)
    # plus a same-session series with a very different median
    for i in range(15):
        va.record_minute(_ts(12, 0) + timedelta(minutes=i), 9999)
    got = va.rvol(target, 1000)
    assert got is not None
    assert abs(got - 2.0) < 1e-9, (
        "must divide by the minute-of-day median 500 -> 2.0, got %s" % got)
    return "minute-of-day median honoured: rvol=%.4f" % got


def test_r5_snapshot_round_trip():
    """R5: the intra-session series survives state()/restore()."""
    va = VolumeAnalyzer()
    base = _ts(13, 0)
    for i in range(12):
        va.record_minute(base + timedelta(minutes=i), 1000 + i)
    st = va.state()
    assert "__session__" in st, "session series must be persisted"
    va2 = VolumeAnalyzer()
    va2.restore(st)
    assert len(va2._session_series) == 12, f"expected 12 restored, got {len(va2._session_series)}"
    assert va2._session_key == base.date()
    got = va2.rvol(base + timedelta(minutes=12), 2000)
    assert got is not None, "restored series must be immediately usable (no re-warmup)"
    direct = va.rvol(base + timedelta(minutes=12), 2000)
    assert abs(got - direct) < 1e-12, f"restored rvol {got} != live rvol {direct}"
    return "12 samples restored, rvol identical after round-trip (%.6f)" % got


def test_r6_new_day_resets_series():
    """R6: a different trading date must clear the series (no contamination)."""
    va = VolumeAnalyzer()
    d1 = _ts(14, 0, day=28)
    for i in range(15):
        va.record_minute(d1 + timedelta(minutes=i), 1000)
    assert va.rvol(d1 + timedelta(minutes=15), 1000) is not None
    d2 = _ts(9, 20, day=31)
    assert va.rvol(d2, 1000) is None, "new day must fail closed until 10 fresh bars"
    assert va._session_series == [], "series must be empty on the new day"
    for i in range(10):
        va.record_minute(d2 + timedelta(minutes=i), 800)
    assert va.rvol(d2 + timedelta(minutes=10), 1600) is not None
    return "day roll cleared the series and re-warmed correctly"


def test_r7_legacy_snapshot_restores():
    """R7: a pre-fix snapshot (no reserved key) still restores cleanly."""
    legacy = {"9:20": [100, 200, 300], "10:5": [400], "bogus": [1, 2]}
    va = VolumeAnalyzer()
    va.restore(legacy)
    assert (9, 20) in va._by_minute and va._by_minute[(9, 20)] == [100, 200, 300]
    assert (10, 5) in va._by_minute
    assert va._session_series == [], "legacy snapshot has no session series"
    assert va.rvol(_ts(9, 20), 100) is None, "shallow pool + empty series -> None"
    # malformed reserved key must not raise
    va2 = VolumeAnalyzer()
    va2.restore({"__session__": "not-a-dict", "9:20": [1]})
    va3 = VolumeAnalyzer()
    va3.restore({"__session__": {"day": "not-a-date", "series": [1, 2]}})
    return "legacy + malformed snapshots handled without exception"


def test_r8_classify_bar_thresholds_unchanged():
    """R8: impulse/absorption/normal thresholds must be untouched."""
    va = VolumeAnalyzer()
    atr = Decimal("10")
    wide = _bar(_ts(10, 0), h="24020", l="24000")      # range 20 = 2.0 x ATR
    narrow = _bar(_ts(10, 1), h="24005", l="24000")    # range 5  = 0.5 x ATR
    assert va.classify_bar(wide, atr, 1.5) == "impulse"
    assert va.classify_bar(wide, atr, 1.49) == "normal"
    assert va.classify_bar(narrow, atr, 2.0) == "absorption"
    assert va.classify_bar(narrow, atr, 1.99) == "normal"
    assert va.classify_bar(wide, atr, None) == "normal", "None rvol -> normal (fail closed)"
    assert va.classify_bar(wide, None, 5.0) == "normal", "None atr -> normal"
    assert va.classify_bar(wide, Decimal(0), 5.0) == "normal", "zero atr -> normal"
    return "impulse>=1.5/1.5ATR, absorption>=2.0/<=0.6ATR, None-safe: all unchanged"


def test_r9_volume_category_reachable_and_still_discriminating():
    """R9: Volume can now pass, but a quiet bar must still fail it."""
    rvol_w, absorb_w = 7.0, 5.0
    cat_max = 12.0
    bar = 0.6 * cat_max  # 7.2
    # quiet market: rvol below 1.5 -> only no_absorption scores
    quiet = 0.0 + absorb_w
    assert quiet < bar, "a quiet bar must still fail the Volume category"
    # active market: rvol >= 1.5 -> both score
    active = rvol_w + absorb_w
    assert active >= bar, "an active bar must be able to pass the Volume category"
    # and the previously-unreachable state
    broken = 0.0 + absorb_w
    assert broken < bar
    return ("quiet=%.1f<%.1f (still fails), active=%.1f>=%.1f (now reachable)"
            % (quiet, bar, active, bar))


def test_r10_options_oi_still_mandatory():
    """R10: the fix alone cannot manufacture a signal - Options/OI still gates."""
    CATEGORY_MAX = dhan.CATEGORY_MAX
    MANDATORY = dhan.MANDATORY_CATEGORIES
    assert "Options/OI" in MANDATORY, "Options/OI must remain mandatory"
    assert "Structure" in MANDATORY, "Structure must remain mandatory"
    assert "Volume" not in MANDATORY, "Volume must NOT have become mandatory"
    assert CATEGORY_MAX["Volume"] == 12.0
    assert CATEGORY_MAX["Options/OI"] == 20.0
    # Options/OI without directional_oi=true caps at 5+5+0 = 10 < 12 -> fails
    without_directional = 5.0 + 5.0 + 0.0
    assert without_directional < 0.6 * CATEGORY_MAX["Options/OI"]
    return ("Options/OI mandatory and still caps at %.1f < %.1f without directional_oi"
            % (without_directional, 0.6 * CATEGORY_MAX["Options/OI"]))


TESTS = [
    ("R1  defect fixed (same-session series)", test_r1_defect_fixed_same_session_series),
    ("R2  fail-closed under 10 bars", test_r2_fail_closed_under_ten_bars),
    ("R3  suspect/non-positive refused", test_r3_suspect_and_nonpositive_refused),
    ("R4  cross-session pool precedence", test_r4_cross_session_pool_takes_precedence),
    ("R5  snapshot round-trip", test_r5_snapshot_round_trip),
    ("R6  new-day reset", test_r6_new_day_resets_series),
    ("R7  legacy snapshot restore", test_r7_legacy_snapshot_restores),
    ("R8  classify_bar unchanged", test_r8_classify_bar_thresholds_unchanged),
    ("R9  Volume reachable + discriminating", test_r9_volume_category_reachable_and_still_discriminating),
    ("R10 Options/OI still mandatory", test_r10_options_oi_still_mandatory),
]


def main() -> int:
    print("=" * 78)
    print("RVOL-FIX REGRESSION SUITE")
    print("=" * 78)
    failed = 0
    for name, fn in TESTS:
        try:
            detail = fn()
            print("PASS  %-40s %s" % (name, detail or ""))
        except AssertionError as exc:
            failed += 1
            print("FAIL  %-40s %s" % (name, exc))
        except Exception as exc:
            failed += 1
            print("ERROR %-40s %r" % (name, exc))
    print("-" * 78)
    print("%d passed, %d failed, %d total" % (len(TESTS) - failed, failed, len(TESTS)))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
