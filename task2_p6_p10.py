# -*- coding: utf-8 -*-
"""
TASK 2 / PHASES 6-10  SINGLE-VARIABLE CAUSAL TESTS

All operands here are the engine's OWN persisted values (logs/oi_diag.jsonl,
event=oi_snapshot, 19.5k polls). Nothing is reconstructed from a model of the
engine except in V0, whose only purpose is to PROVE the arithmetic model is
exact before any counterfactual is computed on it.

V0  control        recompute z from the persisted delta series and require an
                   exact match with the persisted z. Gate for everything below.
P7  M1 test        history admission. The engine records snapshots_len,
                   duplicates_dropped and informative_obs, so
                       rejected_by_basket_filter
                           = snapshots_len - duplicates_dropped - informative_obs
                   is the engine's own count of retained snapshots thrown away
                   by  `if len(legs) < len(atm_strikes): continue`  (line 2115).
                   Independent variable: basket change recency.
P8  M2 test        expiry composition of the retained window, reconstructed
                   exactly from the poll stream (deque maxlen 240) and validated
                   against the engine's own snapshots_len.
                   Independent variable: window expiry homogeneity.
P9  M3 test        ladder order: joint distribution of B3 and B4 on every poll
                   where the ladder actually ran.
P10 separation     2x2 of the two independent variables against outcomes.

Output: TASK2_P6_P10.json
"""
import collections
import json
import math
import os
import statistics as st
from datetime import datetime

R = r"C:\Users\Guest -A\Desktop\Dhan Test"
OI = os.path.join(R, "logs", "oi_diag.jsonl")
OUT = os.path.join(R, "TASK2_P6_P10.json")
DEQUE_MAX = 240
SYNTH_EXPIRY = {"2026-09-07"}
V0_SAMPLE = 400


def zcalc(deltas, lookback):
    """Documented engine formula (Dhan.py ~2150-2200)."""
    if len(deltas) < 10 or lookback <= 0:
        return None
    mu = st.fmean(deltas)
    sd = st.pstdev(deltas) if len(deltas) > 1 else 0.0
    win = sum(deltas[-lookback:])
    if sd == 0:
        return 0.0
    return (win - mu * lookback) / (sd * math.sqrt(lookback))


def main():
    rows = []
    v0 = {"checked": 0, "matched_pe": 0, "matched_ce": 0, "max_abs_err": 0.0,
          "sd_zero_rows": 0, "mismatch_examples": []}
    with open(OI, encoding="utf-8", errors="replace") as fh:
        for ln in fh:
            ln = ln.strip()
            if not ln.startswith("{"):
                continue
            try:
                r = json.loads(ln)
            except Exception:
                continue
            if r.get("event") != "oi_snapshot":
                continue
            if str(r.get("expiry")) in SYNTH_EXPIRY:
                continue
            lt = r.get("live_terms") or {}

            # ---- V0 control on a bounded sample -------------------------
            if v0["checked"] < V0_SAMPLE and r.get("pe_deltas") and r.get("lookback_used"):
                lb = int(r["lookback_used"])
                for side, key, zk in (("pe", "pe_deltas", "z_pe"),
                                      ("ce", "ce_deltas", "z_ce")):
                    d = [float(x) for x in (r.get(key) or [])]
                    zc = zcalc(d, lb)
                    ze = r.get(zk)
                    if zc is None or ze is None:
                        continue
                    err = abs(zc - float(ze))
                    v0["max_abs_err"] = max(v0["max_abs_err"], err)
                    if err <= 1e-9:
                        v0["matched_%s" % side] += 1
                    elif len(v0["mismatch_examples"]) < 3:
                        v0["mismatch_examples"].append(
                            {"ts": r.get("ts"), "side": side, "recomputed": zc,
                             "persisted": float(ze), "lookback": lb,
                             "n_deltas": len(d)})
                if float(r.get("sd_pe") or 0) == 0 or float(r.get("sd_ce") or 0) == 0:
                    v0["sd_zero_rows"] += 1
                v0["checked"] += 1

            rows.append({
                "ts": r.get("ts"), "u": r.get("underlying"),
                "expiry": str(r.get("expiry")), "atm": str(r.get("atm")),
                "spot": r.get("spot"),
                "basket": tuple(r.get("basket_used_by_engine") or ()),
                "snap_len": r.get("snapshots_len"),
                "obs": lt.get("informative_obs"),
                "dups": lt.get("duplicates_dropped"),
                "stage": lt.get("stage"),
                "z_pe": r.get("z_pe"), "z_ce": r.get("z_ce"),
                "win_pe": r.get("win_pe"), "win_ce": r.get("win_ce"),
                "sd_pe": r.get("sd_pe"), "sd_ce": r.get("sd_ce"),
                "lb": r.get("lookback_used"),
                "branch": r.get("branch"), "verdict": r.get("verdict_engine"),
                "B1": lt.get("B1"), "B2": lt.get("B2"),
                "B3": lt.get("B3"), "B4": lt.get("B4"),
                "up": lt.get("up_move"), "dn": lt.get("down_move"),
                "ceu": lt.get("ce_unwind_above_spot"),
                "peu": lt.get("pe_unwind_below_spot"),
            })
    v0["exact_model"] = (v0["checked"] > 0 and not v0["mismatch_examples"]
                         and v0["max_abs_err"] <= 1e-9)

    rows.sort(key=lambda r: (r["u"] or "", r["ts"] or ""))
    per_u = collections.defaultdict(list)
    for r in rows:
        per_u[r["u"]].append(r)

    # ---- P7 / P8 / P10 : annotate every poll -------------------------------
    ann = []
    for u, seq in per_u.items():
        last_basket, since_change = None, 0
        for i, r in enumerate(seq):
            if r["basket"] != last_basket:
                since_change = 0
                last_basket = r["basket"]
            else:
                since_change += 1
            win = seq[max(0, i - (DEQUE_MAX - 1)):i + 1]
            exps = {w["expiry"] for w in win}
            rej = None
            if all(isinstance(r[k], int) for k in ("snap_len", "obs", "dups")):
                rej = r["snap_len"] - r["dups"] - r["obs"]
            ann.append({**r, "since_basket_change": since_change,
                        "recon_window_len": len(win),
                        "window_expiries": len(exps),
                        "window_mixed": len(exps) > 1,
                        "rejected_by_basket_filter": rej})

    have = [a for a in ann if a["rejected_by_basket_filter"] is not None]
    # reconstruction validity: engine snapshots_len vs reconstructed window
    recon_ok = sum(1 for a in have if a["snap_len"] == a["recon_window_len"])

    def dist(vals):
        vals = [v for v in vals if v is not None]
        if not vals:
            return None
        vals = sorted(vals)
        return {"n": len(vals), "min": vals[0], "p50": vals[len(vals) // 2],
                "p90": vals[int(len(vals) * 0.9)], "max": vals[-1],
                "mean": round(st.fmean(vals), 4)}

    P7 = {
        "polls_measured": len(have),
        "rejected_by_basket_filter": dist([a["rejected_by_basket_filter"]
                                           for a in have]),
        "informative_obs": dist([a["obs"] for a in have]),
        "duplicates_dropped": dist([a["dups"] for a in have]),
        "snapshots_len": dist([a["snap_len"] for a in have]),
        "rejection_share_of_retained": dist(
            [a["rejected_by_basket_filter"] / a["snap_len"]
             for a in have if a["snap_len"]]),
        "obs_by_since_basket_change": {},
        "polls_with_obs_lt_11": sum(1 for a in have if (a["obs"] or 0) < 11),
        "share_obs_lt_11": round(sum(1 for a in have if (a["obs"] or 0) < 11)
                                 / max(1, len(have)), 4),
        "basket_change_events": sum(1 for a in ann if a["since_basket_change"] == 0),
        "distinct_baskets": len({a["basket"] for a in ann}),
        "obs_equals_since_change_plus_1": sum(
            1 for a in have if a["obs"] == a["since_basket_change"] + 1),
        "obs_le_since_change_plus_1": sum(
            1 for a in have if (a["obs"] or 0) <= a["since_basket_change"] + 1),
    }
    for a in have:
        b = min(a["since_basket_change"], 30)
        P7["obs_by_since_basket_change"].setdefault(b, []).append(a["obs"] or 0)
    P7["obs_by_since_basket_change"] = {
        k: {"polls": len(v), "obs_p50": sorted(v)[len(v) // 2], "obs_max": max(v)}
        for k, v in sorted(P7["obs_by_since_basket_change"].items())}

    ev = [a for a in have if a["stage"] == "evaluated"]
    mixed = [a for a in ev if a["window_mixed"]]
    homo = [a for a in ev if not a["window_mixed"]]

    def absz(xs):
        out = []
        for a in xs:
            for k in ("z_pe", "z_ce"):
                try:
                    out.append(abs(float(a[k])))
                except Exception:
                    pass
        return out

    P8 = {
        "reconstruction_validated": {"polls": len(have), "snap_len_equals_recon":
                                     recon_ok, "share": round(recon_ok
                                                              / max(1, len(have)), 4)},
        "expiries_in_stream": dict(collections.Counter(a["expiry"] for a in ann)),
        "polls_with_mixed_expiry_window": sum(1 for a in ann if a["window_mixed"]),
        "share_mixed": round(sum(1 for a in ann if a["window_mixed"])
                             / max(1, len(ann)), 4),
        "evaluated_polls": len(ev),
        "evaluated_mixed": len(mixed), "evaluated_homogeneous": len(homo),
        "abs_z_mixed": dist(absz(mixed)),
        "abs_z_homogeneous": dist(absz(homo)),
        "sd_pe_mixed": dist([float(a["sd_pe"]) for a in mixed if a["sd_pe"] is not None]),
        "sd_pe_homogeneous": dist([float(a["sd_pe"]) for a in homo
                                   if a["sd_pe"] is not None]),
        "max_abs_z_mixed": max(absz(mixed)) if mixed else None,
        "max_abs_z_homogeneous": max(absz(homo)) if homo else None,
        "threshold": 1.5,
        "reaches_threshold_mixed": sum(1 for a in mixed if max(absz([a]) or [0]) >= 1.5),
        "reaches_threshold_homogeneous": sum(1 for a in homo
                                             if max(absz([a]) or [0]) >= 1.5),
    }

    P9 = {
        "evaluated_polls": len(ev),
        "B_joint": dict(collections.Counter(
            "B1=%s B2=%s B3=%s B4=%s" % (bool(a["B1"]), bool(a["B2"]),
                                         bool(a["B3"]), bool(a["B4"])) for a in ev)),
        "B3_only": sum(1 for a in ev if a["B3"] and not a["B4"]),
        "B4_only": sum(1 for a in ev if a["B4"] and not a["B3"]),
        "B3_and_B4": sum(1 for a in ev if a["B3"] and a["B4"]),
        "none": sum(1 for a in ev if not any(bool(a[b]) for b in
                                             ("B1", "B2", "B3", "B4"))),
        "branch_distribution": dict(collections.Counter(a["branch"] for a in ev)),
        "verdict_distribution": dict(collections.Counter(a["verdict"] for a in ev)),
        "price_context": {
            "up_move": sum(1 for a in ev if a["up"]),
            "down_move": sum(1 for a in ev if a["dn"]),
            "ce_unwind_above_spot": sum(1 for a in ev if a["ceu"]),
            "pe_unwind_below_spot": sum(1 for a in ev if a["peu"])},
    }

    cells = collections.defaultdict(list)
    for a in have:
        cells[("basket_stable" if a["since_basket_change"] >= 11
               else "basket_recent_change",
               "expiry_mixed" if a["window_mixed"] else "expiry_homogeneous")].append(a)
    P10 = {}
    for k, v in cells.items():
        z = absz([x for x in v if x["stage"] == "evaluated"])
        P10["%s|%s" % k] = {
            "polls": len(v),
            "obs_p50": dist([x["obs"] for x in v])["p50"] if v else None,
            "ladder_ran": sum(1 for x in v if x["stage"] == "evaluated"),
            "ladder_ran_share": round(sum(1 for x in v if x["stage"] == "evaluated")
                                      / max(1, len(v)), 4),
            "max_abs_z": max(z) if z else None,
            "abs_z_p50": dist(z)["p50"] if z else None,
            "non_neutral": sum(1 for x in v if x["verdict"] not in (None, "neutral")),
        }

    rep = {"generated": datetime.now().isoformat(),
           "V0_control": v0, "P7_M1_history_admission": P7,
           "P8_M2_expiry_composition": P8, "P9_M3_ladder_order": P9,
           "P10_confound_separation": P10,
           "counterfactuals_permitted": v0["exact_model"]}
    json.dump(rep, open(OUT, "w", encoding="utf-8", newline="\n"), indent=1,
              default=str, sort_keys=True)

    print("V0 control: checked=%d matched_pe=%d matched_ce=%d max_err=%.3g exact=%s"
          % (v0["checked"], v0["matched_pe"], v0["matched_ce"], v0["max_abs_err"],
             v0["exact_model"]))
    if v0["mismatch_examples"]:
        print("  mismatch:", json.dumps(v0["mismatch_examples"][0]))
    print("P7 polls=%d rejected_by_basket_filter=%s"
          % (P7["polls_measured"], json.dumps(P7["rejected_by_basket_filter"])))
    print("   informative_obs=%s" % json.dumps(P7["informative_obs"]))
    print("   obs<11 share=%s | basket_change_events=%d | distinct_baskets=%d"
          % (P7["share_obs_lt_11"], P7["basket_change_events"],
             P7["distinct_baskets"]))
    print("   obs == since_basket_change+1 : %d/%d  (<=: %d)"
          % (P7["obs_equals_since_change_plus_1"], P7["polls_measured"],
             P7["obs_le_since_change_plus_1"]))
    print("   obs by polls-since-basket-change:",
          json.dumps({k: v["obs_p50"] for k, v in
                      list(P7["obs_by_since_basket_change"].items())[:14]}))
    print("P8 recon validated %s | mixed-window share %s"
          % (json.dumps(P8["reconstruction_validated"]), P8["share_mixed"]))
    print("   evaluated mixed=%d homo=%d | |z| mixed=%s"
          % (P8["evaluated_mixed"], P8["evaluated_homogeneous"],
             json.dumps(P8["abs_z_mixed"])))
    print("   |z| homogeneous=%s" % json.dumps(P8["abs_z_homogeneous"]))
    print("   reaches 1.5: mixed=%d homo=%d"
          % (P8["reaches_threshold_mixed"], P8["reaches_threshold_homogeneous"]))
    print("P9 joint:", json.dumps(P9["B_joint"]))
    print("   B3_only=%d B4_only=%d both=%d none=%d | context=%s"
          % (P9["B3_only"], P9["B4_only"], P9["B3_and_B4"], P9["none"],
             json.dumps(P9["price_context"])))
    print("P10 cells:")
    for k, v in sorted(P10.items()):
        print("   %-38s %s" % (k, json.dumps(v)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
