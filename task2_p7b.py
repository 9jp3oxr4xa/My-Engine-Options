# -*- coding: utf-8 -*-
"""
TASK 2 / PHASE 7b  -  V0 REPAIR + CORRECTED SINGLE-VARIABLE TEST

Phase 7 refuted M1 as originally formulated (admission is NOT a function of how
recently the basket changed: obs medians are flat at ~62 across every recency
bucket). Two things must therefore be fixed before any root cause is claimed:

V0  the arithmetic model failed (19/400). Hypothesis to test here: the diag
    record truncates the delta arrays, so mu/sd recomputed from the logged array
    are not the engine's. Test = restrict the control to rows whose logged array
    is complete (len(deltas) == informative_obs - 1) and require exactness there.

M1' the correct independent variable is ATM DISPLACEMENT across the retained
    window, not basket-change count: the basket-presence filter discards a
    retained snapshot when the CURRENT basket strikes are absent from it, which
    is a function of how far the ATM has travelled, not of how many times it
    stepped.

SELECTION the decisive question for "0 of 190": are candidate-time polls drawn
    from the same distribution as all polls? Each of the 190 candidates is joined
    to its own poll annotation and compared against the population.

Output: TASK2_P7B.json
"""
import bisect
import collections
import json
import math
import os
import statistics as st
from datetime import datetime

R = r"C:\Users\Guest -A\Desktop\Dhan Test"
OI = os.path.join(R, "logs", "oi_diag.jsonl")
LED = os.path.join(R, "TASK2_LEDGER.json")
OUT = os.path.join(R, "TASK2_P7B.json")
DEQUE_MAX = 240
SYNTH = {"2026-09-07"}


def dist(v):
    v = sorted(x for x in v if x is not None)
    if not v:
        return None
    return {"n": len(v), "min": round(v[0], 4), "p10": round(v[len(v) // 10], 4),
            "p50": round(v[len(v) // 2], 4), "p90": round(v[int(len(v) * .9)], 4),
            "max": round(v[-1], 4), "mean": round(st.fmean(v), 4)}


def main():
    polls, v0 = [], {"complete_rows": 0, "matched": 0, "max_err": 0.0,
                     "truncated_rows": 0, "examples": []}
    with open(OI, encoding="utf-8", errors="replace") as fh:
        for ln in fh:
            ln = ln.strip()
            if not ln.startswith("{"):
                continue
            try:
                r = json.loads(ln)
            except Exception:
                continue
            if r.get("event") != "oi_snapshot" or str(r.get("expiry")) in SYNTH:
                continue
            lt = r.get("live_terms") or {}
            obs, lb = lt.get("informative_obs"), r.get("lookback_used")
            pd_ = r.get("pe_deltas") or []
            cd_ = r.get("ce_deltas") or []

            # ---- V0 repair: only rows whose logged series is complete -------
            if isinstance(obs, int) and lb and pd_:
                if len(pd_) == obs - 1:
                    v0["complete_rows"] += 1
                    ok = True
                    for d, zk in ((pd_, "z_pe"), (cd_, "z_ce")):
                        d = [float(x) for x in d]
                        if len(d) < 10:
                            ok = False
                            break
                        mu, sd = st.fmean(d), st.pstdev(d)
                        z = 0.0 if sd <= 0 else ((sum(d[-int(lb):]) - mu * int(lb))
                                                 / (sd * math.sqrt(int(lb))))
                        err = abs(z - float(r.get(zk)))
                        v0["max_err"] = max(v0["max_err"], err)
                        if err > 1e-9:
                            ok = False
                            if len(v0["examples"]) < 2:
                                v0["examples"].append(
                                    {"ts": r.get("ts"), "recomputed": z,
                                     "persisted": float(r.get(zk)), "n": len(d),
                                     "lookback": int(lb)})
                    v0["matched"] += 1 if ok else 0
                else:
                    v0["truncated_rows"] += 1

            rej = None
            if all(isinstance(x, int) for x in (r.get("snapshots_len"),
                                                lt.get("duplicates_dropped"), obs)):
                rej = r["snapshots_len"] - lt["duplicates_dropped"] - obs
            zs = []
            for k in ("z_pe", "z_ce"):
                try:
                    zs.append(abs(float(r.get(k))))
                except Exception:
                    pass
            polls.append({
                "ts": r.get("ts"), "u": r.get("underlying"),
                "atm": float(r.get("atm")), "expiry": str(r.get("expiry")),
                "obs": obs, "rej": rej, "snap": r.get("snapshots_len"),
                "stage": lt.get("stage"), "maxz": max(zs) if zs else None,
                "verdict": r.get("verdict_engine"), "branch": r.get("branch"),
            })
    v0["exact_model_on_complete_rows"] = (v0["complete_rows"] > 0
                                          and v0["matched"] == v0["complete_rows"])

    polls.sort(key=lambda p: (p["u"] or "", p["ts"] or ""))
    per_u = collections.defaultdict(list)
    for p in polls:
        per_u[p["u"]].append(p)

    ann = []
    for u, seq in per_u.items():
        for i, p in enumerate(seq):
            w = seq[max(0, i - (DEQUE_MAX - 1)):i + 1]
            atms = [x["atm"] for x in w]
            step = 50.0 if (p["u"] or "").upper().startswith("NIFTY") else 100.0
            disp = abs(p["atm"] - atms[0]) / step
            span = (max(atms) - min(atms)) / step
            ann.append({**p, "atm_disp_strikes": disp, "atm_span_strikes": span,
                        "distinct_atms": len(set(atms)),
                        "window_expiries": len({x["expiry"] for x in w})})

    have = [a for a in ann if a["rej"] is not None]

    # ---- M1' : rejection / obs as a function of ATM travel -----------------
    buckets = collections.defaultdict(list)
    for a in have:
        buckets[min(int(a["atm_span_strikes"]), 8)].append(a)
    m1 = {}
    for k in sorted(buckets):
        v = buckets[k]
        z = [x["maxz"] for x in v if x["stage"] == "evaluated"]
        m1["atm_span_%d_strikes" % k] = {
            "polls": len(v), "obs": dist([x["obs"] for x in v]),
            "rejected": dist([x["rej"] for x in v]),
            "ladder_ran_share": round(sum(1 for x in v if x["stage"] == "evaluated")
                                      / len(v), 4),
            "obs_lt_11_share": round(sum(1 for x in v if (x["obs"] or 0) < 11)
                                     / len(v), 4),
            "max_abs_z": dist(z),
            "non_neutral_share": round(sum(1 for x in v if x["verdict"]
                                           not in (None, "neutral")) / len(v), 4)}

    # ---- SELECTION: candidate-time polls vs population ---------------------
    led = json.load(open(LED, encoding="utf-8"))["ledger"]
    idx = {u: [x["ts"] for x in seq] for u, seq in
           ((u, sorted(v, key=lambda p: p["ts"])) for u, v in per_u.items())}
    ann_by_u = collections.defaultdict(list)
    for a in ann:
        ann_by_u[a["u"]].append(a)
    for u in ann_by_u:
        ann_by_u[u].sort(key=lambda a: a["ts"])

    joined, unjoined = [], 0
    for c in led:
        seq = ann_by_u.get(c["underlying"]) or []
        if not seq:
            unjoined += 1
            continue
        ts_list = [a["ts"] for a in seq]
        i = bisect.bisect_left(ts_list, c["oi_ts"] or c["candidate_ts"])
        best = None
        for j in (i - 1, i, i + 1):
            if 0 <= j < len(seq):
                if best is None or abs(len(seq[j]["ts"]) - 0) == 0:
                    if seq[j]["ts"][:19] == (c["oi_ts"] or "")[:19]:
                        best = seq[j]
                        break
                    if best is None:
                        best = seq[j]
        if best is None:
            unjoined += 1
            continue
        joined.append({"cid": c["candidate_id"], "dir": c["direction"],
                       "semantic": c["semantic_directional_oi"], **best})

    pop_ev = [a for a in have if a["stage"] == "evaluated"]
    cand_ev = [j for j in joined if j["stage"] == "evaluated"]
    selection = {
        "candidates_joined": len(joined), "candidates_unjoined": unjoined,
        "population": {
            "polls": len(have),
            "obs": dist([a["obs"] for a in have]),
            "rejected": dist([a["rej"] for a in have]),
            "obs_lt_11_share": round(sum(1 for a in have if (a["obs"] or 0) < 11)
                                     / max(1, len(have)), 4),
            "ladder_ran_share": round(len(pop_ev) / max(1, len(have)), 4),
            "max_abs_z_when_evaluated": dist([a["maxz"] for a in pop_ev]),
            "non_neutral_share": round(sum(1 for a in have if a["verdict"]
                                           not in (None, "neutral"))
                                       / max(1, len(have)), 4),
            "atm_span_strikes": dist([a["atm_span_strikes"] for a in have])},
        "candidate_times": {
            "polls": len(joined),
            "obs": dist([j["obs"] for j in joined]),
            "rejected": dist([j["rej"] for j in joined]),
            "obs_lt_11_share": round(sum(1 for j in joined if (j["obs"] or 0) < 11)
                                     / max(1, len(joined)), 4),
            "ladder_ran_share": round(len(cand_ev) / max(1, len(joined)), 4),
            "max_abs_z_when_evaluated": dist([j["maxz"] for j in cand_ev]),
            "non_neutral_share": round(sum(1 for j in joined if j["verdict"]
                                           not in (None, "neutral"))
                                       / max(1, len(joined)), 4),
            "atm_span_strikes": dist([j["atm_span_strikes"] for j in joined])},
    }
    p_match = selection["population"]["non_neutral_share"] / 2.0
    selection["chance_of_zero_agreement_in_190"] = (
        (1 - p_match) ** len(led) if 0 < p_match < 1 else None)
    selection["p_match_definition"] = ("half the poll-level non-neutral share, i.e. "
                                       "the chance a non-neutral OI verdict happens "
                                       "to match the candidate's own direction")

    rep = {"generated": datetime.now().isoformat(), "V0_repair": v0,
           "M1_prime_atm_displacement": m1, "SELECTION_candidate_vs_population":
           selection}
    json.dump(rep, open(OUT, "w", encoding="utf-8", newline="\n"), indent=1,
              default=str, sort_keys=True)

    print("V0 repair: complete_rows=%d matched=%d truncated=%d max_err=%.3g exact=%s"
          % (v0["complete_rows"], v0["matched"], v0["truncated_rows"],
             v0["max_err"], v0["exact_model_on_complete_rows"]))
    if v0["examples"]:
        print("   example:", json.dumps(v0["examples"][0]))
    print("M1' obs / rejection vs ATM span of the retained window:")
    for k, v in m1.items():
        print("   %-22s polls=%-6d obs_p50=%-5s rej_p50=%-5s obs<11=%-6s "
              "ladder=%-6s nonneutral=%s"
              % (k, v["polls"], v["obs"]["p50"] if v["obs"] else None,
                 v["rejected"]["p50"] if v["rejected"] else None,
                 v["obs_lt_11_share"], v["ladder_ran_share"],
                 v["non_neutral_share"]))
    P, C = selection["population"], selection["candidate_times"]
    print("SELECTION joined=%d unjoined=%d" % (len(joined), unjoined))
    for name, d in (("population", P), ("candidate_times", C)):
        print("   %-16s obs_p50=%-5s rej_p50=%-5s obs<11=%-7s ladder=%-7s "
              "maxz_p50=%-7s nonneutral=%s"
              % (name, d["obs"]["p50"] if d["obs"] else None,
                 d["rejected"]["p50"] if d["rejected"] else None,
                 d["obs_lt_11_share"], d["ladder_ran_share"],
                 (d["max_abs_z_when_evaluated"] or {}).get("p50"),
                 d["non_neutral_share"]))
    print("   atm_span pop=%s cand=%s"
          % (json.dumps(P["atm_span_strikes"]), json.dumps(C["atm_span_strikes"])))
    print("   chance of 0/190 agreement under the population rate: %s"
          % selection["chance_of_zero_agreement_in_190"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
