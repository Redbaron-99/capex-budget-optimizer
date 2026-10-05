"""
Analysis layer on top of the model:
  * monte_carlo     stress-test a chosen portfolio against uncertain returns and cost overruns
  * stability       re-solve under many sampled return scenarios, count how often each
                    project is chosen (a "confidence score" per project)
  * guideline_cost  how much base return each business rule costs (remove one at a time)
  * pillar_frontier how base return changes as a pillar minimum is tightened
"""
from dataclasses import replace
import numpy as np
import pandas as pd

from .model import solve, Settings, YEARS


def _sample_returns(df, n, rng):
    lo, mode, hi = (df[c].to_numpy(float) for c in ("return_low", "return_base", "return_high"))
    # triangular needs lo < hi; fall back to the base value when the range collapses
    width = hi - lo
    safe_hi = np.where(width > 0, hi, lo + 1e-9)
    return rng.triangular(lo, np.clip(mode, lo, safe_hi), safe_hi, size=(n, len(df)))


def _sample_cost_factor(n, k, rng, mean_overrun=0.08, sd=0.12):
    # lognormal multiplier: median ~1.06, mean ~1.08, long right tail (capex overruns are skewed)
    sigma = np.sqrt(np.log(1 + (sd / (1 + mean_overrun)) ** 2))
    mu = np.log(1 + mean_overrun) - sigma ** 2 / 2
    return rng.lognormal(mu, sigma, size=(n, k))


def monte_carlo(df, selected, budget_total, n=5000, seed=7, contingency=0.0,
                mean_overrun=0.08, overrun_sd=0.12):
    """Simulate realized 3-year return and total spend for a fixed portfolio."""
    rng = np.random.default_rng(seed)
    mask = df.index.isin(selected)
    rets = _sample_returns(df, n, rng)[:, mask].sum(axis=1)
    costs = df.loc[mask, "cost_total"].to_numpy(float)
    spend = (_sample_cost_factor(n, mask.sum(), rng, mean_overrun, overrun_sd) * costs).sum(axis=1)
    over = spend > budget_total * (1 + contingency)
    return {
        "return_mean": float(rets.mean()),
        "return_p10": float(np.percentile(rets, 10)),
        "return_p50": float(np.percentile(rets, 50)),
        "return_p90": float(np.percentile(rets, 90)),
        "spend_p90": float(np.percentile(spend, 90)),
        "prob_over_budget": float(over.mean()),
        "returns": rets,
        "spend": spend,
    }


def stability(df, s: Settings, n=200, seed=11):
    """Selection frequency of each project across sampled return scenarios."""
    rng = np.random.default_rng(seed)
    draws = _sample_returns(df, n, rng)
    counts = pd.Series(0, index=df.index, dtype=float)
    work = df.copy()
    for k in range(n):
        work["scenario_return"] = draws[k]
        res = solve(work, replace(s, objective="scenario_return"))
        if res["status"] == "Optimal":
            counts[res["selected"]] += 1
    return (counts / n).rename("selection_frequency")


def guideline_cost(df, s: Settings):
    """Base-return impact of each rule: re-solve with that one rule switched off."""
    base = solve(df, s)["return_base"]
    rows = []
    toggles = {
        "Budget carryover (rule ON adds value)": replace(s, carryover=False),
        "Mandatory safety projects": replace(s, mandatory=False),
        "Project dependencies": replace(s, dependencies=False),
        "Mutually exclusive alternatives": replace(s, alternatives=False),
        "Branch fairness cap": replace(s, branch_cap=None),
    }
    for p in (s.pillar_min or {}):
        pm = dict(s.pillar_min); pm.pop(p)
        toggles[f"{p} minimum spend"] = replace(s, pillar_min=pm)
    for label, s2 in toggles.items():
        r = solve(df, s2)
        rows.append({"rule": label, "return_without_rule": r["return_base"],
                     "cost_of_rule": r["return_base"] - base})
    out = pd.DataFrame(rows)
    # carryover is a relaxation: switching it off LOWERS return, so its "cost" is negative (a gain)
    return out, base


def pillar_frontier(df, s: Settings, pillar, levels):
    rows = []
    for lv in levels:
        pm = dict(s.pillar_min or {}); pm[pillar] = lv
        r = solve(df, replace(s, pillar_min=pm))
        rows.append({"pillar": pillar, "min_spend": lv,
                     "return_base": r.get("return_base", np.nan), "status": r["status"]})
    return pd.DataFrame(rows)


def reserve_sweep(df, s: Settings, levels, n=5000, seed=7):
    """Trade-off between contingency reserve, planned return and overspend probability."""
    rows = []
    for lv in levels:
        r = solve(df, replace(s, reserve=lv))
        if r["status"] != "Optimal":
            rows.append({"reserve": lv, "status": r["status"]})
            continue
        mc = monte_carlo(df, r["selected"], r["budget_total"], n=n, seed=seed)
        rows.append({"reserve": lv, "status": r["status"], "n_selected": r["n_selected"],
                     "return_base": r["return_base"], "planned_spend": r["spend_total"],
                     "prob_over_budget": mc["prob_over_budget"], "return_p10": mc["return_p10"],
                     "spend_p90": mc["spend_p90"]})
    return pd.DataFrame(rows)
