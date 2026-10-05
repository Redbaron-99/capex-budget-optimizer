"""
Run every analysis and write results + charts.

    python run.py            # full run (about 30 seconds)
    python run.py --quick    # fewer stability scenarios, for testing

Outputs go to results/ (CSVs) and charts/ (PNGs sized for LinkedIn).
"""
import sys
import json
from dataclasses import replace
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.model import load_projects, solve, check_feasibility, Settings
from src.analysis import monte_carlo, stability, guideline_cost, reserve_sweep

NAVY, GOLD, GREY, LIGHT = "#1F2A44", "#C9A227", "#9AA3B2", "#E8EBF0"
plt.rcParams.update({"font.family": "DejaVu Sans", "axes.spines.top": False,
                     "axes.spines.right": False, "axes.edgecolor": GREY,
                     "axes.titleweight": "bold", "axes.titlesize": 13})

ROOT = Path(__file__).parent
RES, CH = ROOT / "results", ROOT / "charts"
RES.mkdir(exist_ok=True); CH.mkdir(exist_ok=True)

quick = "--quick" in sys.argv
df = load_projects(ROOT / "data" / "projects.csv")
full = Settings()
naive = Settings(carryover=False, mandatory=False, dependencies=False, alternatives=False,
                 branch_cap=None, pillar_min={})
standard = replace(naive, pillar_min=full.pillar_min)

# ---------------------------------------------------------------- 1. scenarios
scen = {"1. ROI only (no rules)": naive,
        "2. ROI + pillar minimums (standard)": standard,
        "3. Improved model (all rules)": full,
        "4. Improved + 10% contingency": replace(full, reserve=0.10)}
rows, portfolios = [], {}
for name, s in scen.items():
    r = solve(df, s)
    mc = monte_carlo(df, r["selected"], r["budget_total"])
    viol = check_feasibility(df, r, full)
    portfolios[name] = r["selected"]
    rows.append({"scenario": name, "projects": r["n_selected"],
                 "planned_spend_k": r["spend_total"], "return_base_k": r["return_base"],
                 "return_p10_k": round(mc["return_p10"]), "prob_over_budget": round(mc["prob_over_budget"], 3),
                 "real_world_rule_violations": len(viol), "violations": "; ".join(viol)})
summary = pd.DataFrame(rows)
summary.to_csv(RES / "scenario_summary.csv", index=False)

sel = df.loc[portfolios["4. Improved + 10% contingency"]]
sel.reset_index()[["id", "name", "branch", "pillar", "cost_y1", "cost_y2", "cost_y3",
                   "cost_total", "return_base"]].to_csv(RES / "recommended_portfolio.csv", index=False)

# ---------------------------------------------------------------- 2. rule costs
gc, base = guideline_cost(df, full)
gc.to_csv(RES / "rule_costs.csv", index=False)

# ---------------------------------------------------------------- 3. reserve trade-off
sweep = reserve_sweep(df, full, [0, 0.02, 0.04, 0.06, 0.08, 0.10, 0.12, 0.14])
sweep.to_csv(RES / "reserve_tradeoff.csv", index=False)

# ---------------------------------------------------------------- 4. stability
freq = stability(df, full, n=40 if quick else 300)
stab = df[["name", "branch", "pillar", "cost_total", "return_base"]].join(freq)
stab.sort_values("selection_frequency", ascending=False).to_csv(RES / "project_confidence.csv")

# ---------------------------------------------------------------- charts
def save(fig, name):
    fig.savefig(CH / name, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)

# A. scenario comparison
fig, ax = plt.subplots(figsize=(8, 4.5))
labels = ["ROI only", "ROI +\npillar mins", "Improved\nmodel", "Improved +\n10% reserve"]
cols = [GREY, GREY, NAVY, GOLD]
bars = ax.bar(labels, summary["return_base_k"], color=cols)
for b, v, p, o in zip(bars, summary["real_world_rule_violations"], summary["prob_over_budget"], summary["return_base_k"]):
    ax.text(b.get_x() + b.get_width() / 2, o + 40,
            f"${o/1000:.2f}M\n{v} rule breaks\n{'>99%' if p > 0.99 else f'{p:.0%}'} overspend risk",
            ha="center", va="bottom", fontsize=8.5, color=NAVY)
ax.set_ylim(0, summary["return_base_k"].max() * 1.35)
ax.set_ylabel("Planned 3-year return (k CAD)")
ax.set_title("Higher planned return is not better if the plan breaks real rules")
save(fig, "A_scenario_comparison.png")

# B. reserve trade-off
sw = sweep[sweep["status"] == "Optimal"]
fig, ax = plt.subplots(figsize=(8, 4.5))
ax.plot(sw["reserve"] * 100, sw["return_base"], color=NAVY, marker="o", lw=2.2, label="Planned return")
ax.set_xlabel("Contingency reserve held back (% of budget)")
ax.set_ylabel("Planned 3-year return (k CAD)", color=NAVY)
ax2 = ax.twinx()
ax2.spines["right"].set_visible(True)
ax2.plot(sw["reserve"] * 100, sw["prob_over_budget"] * 100, color=GOLD, marker="s", lw=2.2)
ax2.set_ylabel("Chance of overspending budget (%)", color=GOLD)
ax2.set_ylim(0, 105)
ax.set_title("The price of certainty: reserve vs return vs overspend risk")
save(fig, "B_reserve_tradeoff.png")

# C. confidence
top = stab.sort_values("selection_frequency")
fig, ax = plt.subplots(figsize=(8, 9))
c = [GOLD if i in ("P22", "P23") else NAVY for i in top.index]
ax.barh([f"{i}  {n[:46]}" for i, n in zip(top.index, top["name"])], top["selection_frequency"] * 100, color=c)
ax.axvline(80, color=GREY, ls="--", lw=1)
ax.set_xlabel("% of uncertainty scenarios where the project is selected")
ax.set_title("Project confidence across return scenarios\n(gold = depot vs shuttle, the decision worth a network study)")
ax.tick_params(axis="y", labelsize=7.5)
save(fig, "C_project_confidence.png")

# D. rule costs
g = gc.sort_values("cost_of_rule")
fig, ax = plt.subplots(figsize=(8, 4.5))
ax.barh(g["rule"], g["cost_of_rule"], color=[GOLD if v < 0 else NAVY for v in g["cost_of_rule"]])
ax.axvline(0, color=GREY, lw=1)
ax.set_xlabel("Return given up because of the rule (k CAD; negative = rule adds value)")
ax.set_title("What each business rule costs")
save(fig, "D_rule_costs.png")

key = {
    "baseline_return": float(summary.iloc[1]["return_base_k"]),
    "baseline_violations": int(summary.iloc[1]["real_world_rule_violations"]),
    "improved_return": float(summary.iloc[2]["return_base_k"]),
    "improved_overspend_risk": float(summary.iloc[2]["prob_over_budget"]),
    "reserve10_return": float(summary.iloc[3]["return_base_k"]),
    "reserve10_overspend_risk": float(summary.iloc[3]["prob_over_budget"]),
    "depot_freq": float(freq["P22"]), "shuttle_freq": float(freq["P23"]),
}
(RES / "key_numbers.json").write_text(json.dumps(key, indent=2))
print(summary.drop(columns="violations").to_string(index=False))
print(json.dumps(key, indent=2))
