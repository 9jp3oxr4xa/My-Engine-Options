"""P5 regression suite for OptionsIntel._directional_oi (P1+P2+P3).

Runs standalone (`python test_directional_oi_p1p2p3.py`) and under pytest.
Read-only with respect to logs/ and state/: the diag writer is stubbed and
only in-memory OptionsIntel instances are used.

Coverage
  P1  same-timescale confirmation, and the B4 branch that was structurally
      unreachable under the session-sign operand
  P2-A basket baseline registration does not flip verdicts
  P2-B per-strike normalization: a high-OI strike cannot dominate
  P2-C duplicate collapse changes nothing but the observation count, and
      still fails closed when informative observations are too few
  P3  price context gates on both unwinding branches (positive + negative)
  Frozen invariants: 1.5 thresholds, branch order, direction mapping,
      every non-neutral carries |z| >= 1.5, determinism, warmup fail-closed
"""
from __future__ import annotations

import ast
import os
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Tuple
from zoneinfo import ZoneInfo

import Dhan as E

IST = ZoneInfo("Asia/Kolkata")
T0 = datetime(2026, 8, 31, 10, 0, 0, tzinfo=IST)
EXPIRY = date(2026, 9, 3)
ATM = Decimal("24100")
LOW = Decimal("24050")          # the other basket strike (ATM-1)
OTHER = (Decimal("24000"), Decimal("24150"), Decimal("24200"))
BASE = 100_000

# ---- delta series (24 deltas -> 25 observations) --------------------------
FLAT: List[int] = [0] * 24
STRONG_POS: List[int] = [50] * 14 + [2000] * 10        # z ~ +3.7
STRONG_NEG: List[int] = [-50] * 14 + [-2000] * 10      # z ~ -3.7
_NOISE: List[int] = [1000, -1000] * 7
NEAR_FAIL_POS: List[int] = _NOISE + [1000] * 8 + [-1000] * 2   # z ~ 1.1
NEAR_PASS_POS: List[int] = _NOISE + [1000] * 9 + [-1000] * 1   # z ~ 1.6
NEAR_FAIL_NEG: List[int] = [-x for x in NEAR_FAIL_POS]
NEAR_PASS_NEG: List[int] = [-x for x in NEAR_PASS_POS]


def _cum(deltas: List[int], start: int = BASE) -> List[int]:
    out = [start]
    for d in deltas:
        out.append(out[-1] + d)
    return out


def _leg(oi: int, ltp: str = "100") -> E.OptionLeg:
    return E.OptionLeg(
        ltp=E._d(ltp), bid=E._d(ltp), ask=E._d(ltp), oi=int(oi),
        oi_prev=int(oi), volume=0, iv=Decimal(0), bid_qty=0, ask_qty=0,
    )


def _snap(oi_map: Dict[Decimal, Tuple[int, int]], spot: Decimal,
          ts: datetime) -> Any:
    strikes: List[E.ChainStrike] = []
    for stk in sorted(set(list(oi_map.keys()) + list(OTHER))):
        ce_oi, pe_oi = oi_map.get(stk, (BASE, BASE))
        strikes.append(E.ChainStrike(strike=stk, ce=_leg(ce_oi), pe=_leg(pe_oi)))
    return E.ChainSnapshot(
        underlying="NIFTY", expiry=EXPIRY, spot=spot, ts=ts,
        strikes=strikes, atm_strike=ATM,
    )


def _run(ce_low: List[int], pe_low: List[int],
         ce_atm: List[int], pe_atm: List[int],
         spot_first: str, spot_last: str,
         base_low: Tuple[int, int] = (BASE, BASE),
         base_atm: Tuple[int, int] = (BASE, BASE),
         duplicate_every: bool = False,
         n_snapshots: int | None = None) -> Tuple[str, Decimal, Dict[str, Any]]:
    """Build a snapshot history, evaluate, return (verdict, z, terms)."""
    cl, pl = _cum(ce_low, base_low[0]), _cum(pe_low, base_low[1])
    ca, pa = _cum(ce_atm, base_atm[0]), _cum(pe_atm, base_atm[1])
    n = len(cl)
    s0, s1 = Decimal(spot_first), Decimal(spot_last)
    intel = E.OptionsIntel(atm_band_strikes=3, oi_delta_lookback=10)
    intel._oi_diag_write = lambda row: None  # type: ignore[assignment]

    last = None
    ts = T0
    for i in range(n):
        frac = Decimal(i) / Decimal(max(1, n - 1))
        spot = (s0 + (s1 - s0) * frac).quantize(Decimal("0.05"))
        snap = _snap({LOW: (cl[i], pl[i]), ATM: (ca[i], pa[i])}, spot, ts)
        intel._snapshots.append(snap)
        ts += timedelta(seconds=30)
        if duplicate_every:
            dup = _snap({LOW: (cl[i], pl[i]), ATM: (ca[i], pa[i])}, spot, ts)
            intel._snapshots.append(dup)
            ts += timedelta(seconds=30)
        last = snap
        if n_snapshots is not None and len(intel._snapshots) >= n_snapshots:
            break

    assert last is not None
    band = intel._band_strikes(last, ATM)
    verdict, z = intel._directional_oi(last, ATM, band)
    return verdict, z, dict(intel._last_terms)


# ==========================================================================
# P1 — the branch that the session-sign operand made unreachable
# ==========================================================================
def test_p1_b4_bearish_pe_unwinding_is_reachable() -> None:
    """PE unwinding below spot during a down-move -> bearish via B4.

    Under the pre-patch formula this branch required session PE OI < 0,
    which held in 2 of 727 recorded snapshots, so it never fired.
    """
    v, z, t = _run(FLAT, STRONG_NEG, FLAT, FLAT, "24140", "24080")
    assert v == "bearish", (v, t.get("branch"))
    assert t["branch"] == "B4_bearish_pe_unwinding"
    assert abs(z) >= Decimal("1.5")
    assert t["down_move"] is True
    assert t["pe_unwind_below_spot"] is True


def test_p1_confirmation_operand_is_same_window() -> None:
    """B1 fires on the same window z is computed from, not a session sign."""
    v, z, t = _run(FLAT, STRONG_POS, FLAT, FLAT, "24100", "24100")
    assert v == "bullish"
    assert t["branch"] == "B1_bullish_pe_writing"
    assert t["term_win_pe_gt_0"] is True
    assert z >= Decimal("1.5")


def test_p1_no_session_operand_in_executable_body() -> None:
    """Static guarantee: no session-scoped term survives in the decision."""
    here = os.path.dirname(os.path.abspath(__file__))
    src = open(os.path.join(here, "Dhan.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    body_src = ""
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "OptionsIntel":
            for fn in node.body:
                if isinstance(fn, ast.FunctionDef) and fn.name == "_directional_oi":
                    stmts = fn.body[1:]          # drop the docstring
                    body_src = "\n".join(
                        ast.get_source_segment(src, st) or "" for st in stmts
                    )
    assert body_src, "could not extract _directional_oi body"
    for forbidden in ("sess_pe", "sess_ce", "_baseline_oi["):
        assert forbidden not in body_src, forbidden


# ==========================================================================
# P2 — normalization, drift, window semantics
# ==========================================================================
def test_p2b_high_oi_strike_cannot_dominate() -> None:
    """A 50x larger strike does not swamp the basket sum after normalization.

    ATM PE carries a large but proportionally tiny drift; the low strike
    carries the real flow. Raw summing would let the ATM noise decide.
    """
    big_noise = [4000, -4000] * 12                    # huge in absolute terms
    v, _z, t = _run(FLAT, STRONG_POS, FLAT, big_noise,
                    "24100", "24100",
                    base_low=(BASE, 20_000), base_atm=(BASE, 5_000_000))
    assert v == "bullish", t.get("branch")
    assert t["branch"] == "B1_bullish_pe_writing"


def test_p2c_duplicate_snapshots_do_not_change_the_verdict() -> None:
    """Collapsing identical provider snapshots is verdict-neutral."""
    v1, z1, t1 = _run(FLAT, STRONG_NEG, FLAT, FLAT, "24140", "24080")
    v2, z2, t2 = _run(FLAT, STRONG_NEG, FLAT, FLAT, "24140", "24080",
                      duplicate_every=True)
    assert (v1, str(z1)) == (v2, str(z2))
    assert t2["duplicates_dropped"] > 0
    assert t1["informative_obs"] == t2["informative_obs"]


def test_p2c_all_identical_snapshots_fail_closed() -> None:
    """No informative observations -> neutral, never a guess."""
    v, z, t = _run(FLAT, FLAT, FLAT, FLAT, "24100", "24100")
    assert v == "neutral"
    assert z == Decimal(0)
    assert t["stage"] == "informative_obs_lt_11"
    assert t["informative_obs"] == 1


def test_p2a_baseline_registration_does_not_alter_verdict() -> None:
    """Baseline bookkeeping is observational; repeat calls are stable."""
    v1, z1, _ = _run(FLAT, STRONG_POS, FLAT, FLAT, "24100", "24100")
    v2, z2, _ = _run(FLAT, STRONG_POS, FLAT, FLAT, "24100", "24100")
    assert (v1, str(z1)) == (v2, str(z2))


# ==========================================================================
# P3 — §12 price context on the unwinding branches (negative tests)
# ==========================================================================
def test_p3_b3_requires_up_move() -> None:
    """CE unwinding above spot but price falling -> NOT bullish."""
    v_ok, _z, t_ok = _run(FLAT, FLAT, STRONG_NEG, FLAT, "24000", "24020")
    assert v_ok == "bullish" and t_ok["branch"] == "B3_bullish_ce_unwinding"

    v_no, _z2, t_no = _run(FLAT, FLAT, STRONG_NEG, FLAT, "24020", "24000")
    assert v_no == "neutral", t_no.get("branch")
    assert t_no["branch"] == "B5_fallthrough_neutral"
    assert t_no["up_move"] is False


def test_p3_b3_requires_unwinding_leg_above_spot() -> None:
    """CE unwinding entirely below spot is not resistance dissolving."""
    v, _z, t = _run(FLAT, FLAT, STRONG_NEG, FLAT, "24300", "24400")
    assert t["up_move"] is True
    assert t["ce_unwind_above_spot"] is False
    assert v == "neutral"
    assert t["branch"] == "B5_fallthrough_neutral"


def test_p3_b4_requires_down_move() -> None:
    """PE unwinding below spot but price rising -> NOT bearish."""
    v, _z, t = _run(FLAT, STRONG_NEG, FLAT, FLAT, "24080", "24140")
    assert t["up_move"] is True and t["down_move"] is False
    assert v == "neutral"
    assert t["branch"] == "B5_fallthrough_neutral"


def test_p3_b4_requires_unwinding_leg_below_spot() -> None:
    """PE unwinding above spot is not support dissolving."""
    v, _z, t = _run(FLAT, STRONG_NEG, FLAT, FLAT, "24060", "24000")
    assert t["down_move"] is True
    assert t["pe_unwind_below_spot"] is False
    assert v == "neutral"
    assert t["branch"] == "B5_fallthrough_neutral"


# ==========================================================================
# Frozen behaviour: thresholds, order, mapping, warmup
# ==========================================================================
def test_writing_branches_unchanged() -> None:
    v_b1, z1, t1 = _run(FLAT, STRONG_POS, FLAT, FLAT, "24100", "24100")
    assert (v_b1, t1["branch"]) == ("bullish", "B1_bullish_pe_writing")
    assert z1 == t1_z(t1, "z_pe")

    v_b2, z2, t2 = _run(FLAT, FLAT, STRONG_POS, FLAT, "24100", "24100")
    assert (v_b2, t2["branch"]) == ("bearish", "B2_bearish_ce_writing")
    assert z2 == t1_z(t2, "z_ce")


def t1_z(terms: Dict[str, Any], key: str) -> Decimal:
    return Decimal(str(terms[key]))


def test_ladder_order_b1_before_b3() -> None:
    """PE writing and CE unwinding both armed: the earlier branch wins.

    PE OI rises hard (arms B1) while CE OI above spot unwinds hard during an
    up-move (arms B3). The ladder is B1 -> B2 -> B3 -> B4, so B1 must win.
    """
    v, z, t = _run(FLAT, STRONG_POS, STRONG_NEG, FLAT, "24000", "24020")
    assert t["B1"] is True and t["B3"] is True, t
    assert t["branch"] == "B1_bullish_pe_writing"
    assert v == "bullish"
    assert z == t1_z(t, "z_pe")


def test_ladder_order_b2_before_b4() -> None:
    """CE writing and PE unwinding both armed: B2 precedes B4."""
    v, z, t = _run(FLAT, STRONG_NEG, STRONG_POS, FLAT, "24140", "24080")
    assert t["B2"] is True and t["B4"] is True, t
    assert t["branch"] == "B2_bearish_ce_writing"
    assert v == "bearish"
    assert z == t1_z(t, "z_ce")


def test_same_sign_on_both_legs_stays_neutral() -> None:
    """Both legs building: no directional read, exactly as before.

    B1 requires z_ce <= 0 and B2 requires z_pe <= 0, so simultaneous CE and
    PE writing is deliberately not a signal.
    """
    v, _z, t = _run(FLAT, STRONG_POS, STRONG_POS, FLAT, "24100", "24100")
    assert v == "neutral"
    assert t["branch"] == "B5_fallthrough_neutral"
    assert t["B1"] is False and t["B2"] is False


def test_threshold_frozen_at_1_5() -> None:
    """|z| just under 1.5 stays neutral; just over 1.5 fires."""
    v_lo, z_lo, t_lo = _run(FLAT, NEAR_FAIL_POS, FLAT, FLAT, "24100", "24100")
    assert abs(z_lo) < Decimal("1.5"), z_lo
    assert v_lo == "neutral" and t_lo["branch"] == "B5_fallthrough_neutral"

    v_hi, z_hi, t_hi = _run(FLAT, NEAR_PASS_POS, FLAT, FLAT, "24100", "24100")
    assert abs(z_hi) >= Decimal("1.5"), z_hi
    assert v_hi == "bullish" and t_hi["branch"] == "B1_bullish_pe_writing"


def test_warmup_fails_closed() -> None:
    v, z, t = _run(FLAT, STRONG_POS, FLAT, FLAT, "24100", "24100",
                   n_snapshots=11)
    assert v == "neutral"
    assert z == Decimal(0)
    assert t["stage"] == "warmup_snapshots_lt_12"


def test_every_non_neutral_carries_abs_z_at_least_1_5() -> None:
    """Confluence uses `directional_z >= 1.5`; the ladder must honour it."""
    cases = [
        (FLAT, STRONG_POS, FLAT, FLAT, "24100", "24100"),
        (FLAT, FLAT, STRONG_POS, FLAT, "24100", "24100"),
        (FLAT, FLAT, STRONG_NEG, FLAT, "24000", "24020"),
        (FLAT, STRONG_NEG, FLAT, FLAT, "24140", "24080"),
        (FLAT, NEAR_PASS_POS, FLAT, FLAT, "24100", "24100"),
        (FLAT, NEAR_PASS_NEG, FLAT, FLAT, "24140", "24080"),
        (FLAT, NEAR_FAIL_NEG, FLAT, FLAT, "24140", "24080"),
    ]
    seen_non_neutral = 0
    for cl, pl, ca, pa, s0, s1 in cases:
        v, z, t = _run(cl, pl, ca, pa, s0, s1)
        if v != "neutral":
            seen_non_neutral += 1
            assert abs(z) >= Decimal("1.5"), (v, z, t.get("branch"))
    assert seen_non_neutral >= 5


def test_determinism_repeated_evaluation_is_identical() -> None:
    out = [
        _run(FLAT, STRONG_NEG, FLAT, FLAT, "24140", "24080")[:2]
        for _ in range(3)
    ]
    assert len({(v, str(z)) for v, z in out}) == 1


def test_neutral_magnitude_is_max_abs_z() -> None:
    """Fall-through still reports the larger |z| for the ledger detail."""
    v, z, t = _run(FLAT, NEAR_FAIL_POS, FLAT, FLAT, "24100", "24100")
    assert v == "neutral"
    expected = max(abs(t1_z(t, "z_pe")), abs(t1_z(t, "z_ce")))
    assert z == expected


# ==========================================================================
def main() -> int:
    tests = [(k, v) for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed: List[str] = []
    for name, fn in tests:
        try:
            fn()
            print(f"PASS  {name}")
        except AssertionError as exc:
            failed.append(name)
            print(f"FAIL  {name}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed.append(name)
            print(f"ERROR {name}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - len(failed)}/{len(tests)} passed")
    if failed:
        print("failing:", ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
