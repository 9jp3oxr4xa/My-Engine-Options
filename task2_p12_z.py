# -*- coding: utf-8 -*-
"""
TASK 2 / PHASE 12A + 12D  (READ ONLY)

Anchored to today's PROVEN live source (bundle 01_SOURCE\\Dhan.py, 550d18d3...).

1. extracts _directional_oi exactly (ast line span) and prints its predicates
2. tests the arithmetic identity spotted in a live row:  mu == win / lookback
   If mu*lookback == win then z = (win - mu*lookback)/(sd*sqrt(lb)) == 0 by
   construction and the |z| >= 1.5 predicates are unsatisfiable.
3. measures where that identity holds, against informative_obs vs lookback_used,
   and cross-tabs it with the branch actually taken and with candidate times.

Emits TASK2_P12_Z_DEGENERACY.json
"""
import ast
import collections
import json
import math
import os
import re

PROJ = r"C:\Users\Guest -A\Desktop\Dhan Test"
B = os.path.join(PROJ, "Audit Bundle Sep 02")
LIVE = os.path.join(B, "01_SOURCE", "Dhan.py")
DIAG = os.path.join(B, "02_TODAY_LOGS", "logs", "oi_diag.jsonl")
TOK = re.compile(r"(return |continue|if |elif |else:|1\.5|lookback|informative|"
                 r"duplicates|len\(legs\)|atm_strikes|avg_oi|mean|stdev|sqrt|"
                 r"z_ce|z_pe|win|mu|sd|B[1-5]|bull|bear|neutral|expiry|basket)")


def f(x, d=None):
    try:
        return float(x)
    except Exception:
        return d


def stats(v):
    v = sorted(x for x in v if x is not None)
    if not v:
        return {}
    n = len(v)
    return {"n": n, "min": v[0], "p50": v[n // 2], "p90": v[int(n * .9)],
            "max": v[-1], "mean": round(sum(v) / n, 6)}


def main():
    src = open(LIVE, encoding="utf-8", errors="replace").read()
    lines = src.splitlines()
    tree = ast.parse(src)
    span = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and \
                node.name == "_directional_oi":
            span = (node.lineno, node.end_lineno)
            break
    print("== TODAY'S LIVE SOURCE _directional_oi span=%s ==" % (span,))
    body = []
    if span:
        for i in range(span[0], span[1] + 1):
            body.append((i, lines[i - 1]))
        for n, t in body:
            s = t.rstrip()
            if s.strip() and TOK.search(s) and not s.lstrip().startswith("#"):
                print("%5d| %s" % (n, s[:148]))

    rows = []
    with open(DIAG, encoding="utf-8", errors="replace") as fh:
        for ln in fh:
            ln = ln.strip()
            if ln.startswith("{"):
                try:
                    rows.append(json.loads(ln))
                except Exception:
                    pass

    ident = collections.Counter()
    zbuck = collections.Counter()
    gap = collections.Counter()
    branch_by_ident = collections.Counter()
    num_abs, z_abs, obs_v, lb_v = [], [], [], []
    cross = collections.Counter()
    cand_rows = []
    per_strike_ok = collections.Counter()

    for r in rows:
        lt = r.get("live_terms") if isinstance(r.get("live_terms"), dict) else None
        if r.get("event") == "oi_candidate":
            cand_rows.append(r)
        if not lt or lt.get("lookback_used") is None:
            continue
        lb = int(lt["lookback_used"])
        obs = lt.get("informative_obs")
        for side in ("ce", "pe"):
            mu, sd, win, z = (f(lt.get("mu_%s" % side)), f(lt.get("sd_%s" % side)),
                              f(lt.get("win_%s" % side)), f(lt.get("z_%s" % side)))
            if None in (mu, sd, win, z):
                continue
            num = win - mu * lb
            num_abs.append(abs(num))
            z_abs.append(abs(z))
            ident["mu_times_lb_equals_win_%s=%s"
                  % (side, abs(num) <= 1e-9 * max(1.0, abs(win)))] += 1
            zbuck["|z|<1e-12" if abs(z) < 1e-12 else
                  "|z|<0.5" if abs(z) < .5 else
                  "|z|<1.5" if abs(z) < 1.5 else "|z|>=1.5"] += 1
        if obs is not None:
            obs_v.append(obs)
            lb_v.append(lb)
            gap["obs-1-lb=%d" % (int(obs) - 1 - lb)] += 1
            deg = abs(f(lt.get("win_pe"), 0) - f(lt.get("mu_pe"), 0) * lb) <= 1e-9
            cross["obs_minus_1_eq_lb=%s AND z_pe_zero=%s"
                  % (int(obs) - 1 == lb, deg)] += 1
            branch_by_ident["%s|%s" % (deg, lt.get("branch"))] += 1
        # per-strike state completeness for counterfactual feasibility
        avg, psd = lt.get("avg_oi"), lt.get("per_strike_window_delta")
        if isinstance(avg, dict) and isinstance(psd, dict):
            same = set(avg) == set(psd)
            per_strike_ok["keys_match=%s" % same] += 1
            if same:
                wce = sum(psd[k] / avg[k] for k in psd if k.endswith("|CE")
                          and avg.get(k))
                wpe = sum(psd[k] / avg[k] for k in psd if k.endswith("|PE")
                          and avg.get(k))
                per_strike_ok["win_ce_reproduced=%s"
                              % (abs(wce - f(lt.get("win_ce"), 0)) < 1e-9)] += 1
                per_strike_ok["win_pe_reproduced=%s"
                              % (abs(wpe - f(lt.get("win_pe"), 0)) < 1e-9)] += 1

    czb = collections.Counter()
    cnum = []
    for c in cand_rows:
        lb = c.get("lookback_used")
        if not lb:
            continue
        for side in ("ce", "pe"):
            mu, sd, win = (f(c.get("mu_%s" % side)), f(c.get("sd_%s" % side)),
                           f(c.get("sess_%s" % side)))
            z = f(c.get("z_%s" % side))
            if z is None:
                continue
            czb["|z|<1e-12" if abs(z) < 1e-12 else
                "|z|<1.5" if abs(z) < 1.5 else "|z|>=1.5"] += 1
        cnum.append(1)

    rep = {"live_source": LIVE, "func_span": span,
           "rows_total": len(rows), "candidates": len(cand_rows),
           "IDENTITY_mu_times_lookback_equals_win": dict(ident),
           "abs_numerator_stats": stats(num_abs), "abs_z_stats": stats(z_abs),
           "z_buckets": dict(zbuck),
           "informative_obs_stats": stats(obs_v), "lookback_stats": stats(lb_v),
           "obs_minus_1_minus_lookback": dict(gap),
           "crosstab_obs_eq_lb_vs_z_zero": dict(cross),
           "branch_by_degeneracy": dict(branch_by_ident),
           "per_strike_state_reproduces_win": dict(per_strike_ok),
           "candidate_z_buckets": dict(czb)}
    json.dump(rep, open(os.path.join(PROJ, "TASK2_P12_Z_DEGENERACY.json"), "w",
                        encoding="utf-8", newline="\n"), indent=1, default=str,
              sort_keys=True)

    print("\n== Z DEGENERACY TEST ON TODAY'S DATA ==")
    print("rows=%d candidates=%d" % (len(rows), len(cand_rows)))
    print("identity mu*lb==win : %s" % json.dumps(dict(ident)))
    print("abs numerator: %s" % json.dumps(stats(num_abs)))
    print("abs z        : %s" % json.dumps(stats(z_abs)))
    print("z buckets    : %s" % json.dumps(dict(zbuck)))
    print("informative_obs: %s" % json.dumps(stats(obs_v)))
    print("obs-1-lookback : %s" % json.dumps(dict(sorted(gap.items())[:12])))
    print("crosstab       : %s" % json.dumps(dict(cross)))
    print("branch|degenerate: %s" % json.dumps(dict(branch_by_ident)))
    print("per-strike state reproduces win: %s" % json.dumps(dict(per_strike_ok)))
    print("candidate z buckets: %s" % json.dumps(dict(czb)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
