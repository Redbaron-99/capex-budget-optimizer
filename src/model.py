"""
Capex portfolio selection as a 0/1 integer program (PuLP + HiGHS).

Baseline (the textbook formulation): pick projects to maximize 3-year return
subject to a hard budget per year, optionally with minimum spend per strategic pillar.

Extensions in this version (each can be switched on/off with Settings):
  * carryover        unspent budget in year t rolls into year t+1
  * mandatory        safety/compliance projects are forced in
  * dependencies     a project can only be funded if its prerequisite is funded
  * alternatives     mutually exclusive options (pick at most one per group)
  * branch_cap       no single branch takes more than X% of the 3-year budget
  * pillar_min       minimum 3-year spend per strategic pillar
  * reserve          hold back a share of each year's budget as contingency for overruns
All money values are in thousands of CAD (k$).
"""
from dataclasses import dataclass, field
import pandas as pd
import pulp

YEARS = [1, 2, 3]


@dataclass
class Settings:
    budget: dict = field(default_factory=lambda: {1: 1200, 2: 1300, 3: 1500})
    carryover: bool = True
    mandatory: bool = True
    dependencies: bool = True
    alternatives: bool = True
    branch_cap: float | None = 0.30          # share of total budget; None = off
    pillar_min: dict = field(default_factory=lambda: {
        "Safety": 350, "Sustainability": 500, "Digital": 500})
    reserve: float = 0.0                     # contingency held back from each year's budget
    objective: str = "return_base"           # column used as the objective


def load_projects(path="data/projects.csv") -> pd.DataFrame:
    df = pd.read_csv(path, dtype={"requires": str, "exclusive_group": str})
    df["requires"] = df["requires"].fillna("")
    df["exclusive_group"] = df["exclusive_group"].fillna("")
    df["cost_total"] = df[[f"cost_y{t}" for t in YEARS]].sum(axis=1)
    return df.set_index("id")


def planning_budget(s: Settings) -> dict:
    return {t: s.budget[t] * (1 - s.reserve) for t in YEARS}


def _build(df, s: Settings, objective_col: str):
    ids = list(df.index)
    m = pulp.LpProblem("capex_selection", pulp.LpMaximize)
    x = pulp.LpVariable.dicts("x", ids, cat="Binary")

    m += pulp.lpSum(df.at[i, objective_col] * x[i] for i in ids)

    spend = {t: pulp.lpSum(df.at[i, f"cost_y{t}"] * x[i] for i in ids) for t in YEARS}
    budget = planning_budget(s)

    # budget: hard yearly caps, or with carryover of unspent money
    if s.carryover:
        carry = {t: pulp.LpVariable(f"carry_{t}", lowBound=0) for t in YEARS}
        prev = 0
        for t in YEARS:
            m += carry[t] == budget[t] + prev - spend[t], f"budget_y{t}"
            prev = carry[t]
    else:
        for t in YEARS:
            m += spend[t] <= budget[t], f"budget_y{t}"

    if s.mandatory:
        for i in ids:
            if df.at[i, "mandatory"] == 1:
                m += x[i] == 1, f"mandatory_{i}"

    if s.dependencies:
        for i in ids:
            req = df.at[i, "requires"]
            if req:
                m += x[i] <= x[req], f"requires_{i}_{req}"

    if s.alternatives:
        for g, grp in df[df["exclusive_group"] != ""].groupby("exclusive_group"):
            m += pulp.lpSum(x[i] for i in grp.index) <= 1, f"alt_{g}"

    total_budget = sum(s.budget.values())
    if s.branch_cap is not None:
        for b, grp in df[df["branch"] != "Multi"].groupby("branch"):
            m += (pulp.lpSum(df.at[i, "cost_total"] * x[i] for i in grp.index)
                  <= s.branch_cap * total_budget), f"branch_cap_{b.replace(' ', '_')}"

    for p, floor in (s.pillar_min or {}).items():
        grp = df[df["pillar"] == p]
        m += (pulp.lpSum(df.at[i, "cost_total"] * x[i] for i in grp.index) >= floor), f"pillar_{p}"

    return m, x


def solve(df, s: Settings | None = None) -> dict:
    """Solve and return a result dict. Infeasible models return status != 'Optimal'."""
    s = s or Settings()
    solver = pulp.HiGHS(msg=False)

    m, x = _build(df, s, s.objective)
    m.solve(solver)
    status = pulp.LpStatus[m.status]
    if status != "Optimal":
        return {"status": status}

    chosen = [i for i in df.index if x[i].value() > 0.5]
    sel = df.loc[chosen]
    spend = {t: float(sel[f"cost_y{t}"].sum()) for t in YEARS}
    return {
        "status": status,
        "selected": chosen,
        "n_selected": len(chosen),
        "return_base": float(sel["return_base"].sum()),
        "return_low": float(sel["return_low"].sum()),
        "return_high": float(sel["return_high"].sum()),
        "spend_by_year": spend,
        "spend_total": sum(spend.values()),
        "budget_total": float(sum(s.budget.values())),
        "spend_by_pillar": sel.groupby("pillar")["cost_total"].sum().to_dict(),
        "spend_by_branch": sel.groupby("branch")["cost_total"].sum().to_dict(),
        "model": m,
    }


def check_feasibility(df, res: dict, s: Settings) -> list[str]:
    """Independent re-check of every business rule on a solution (no solver involved)."""
    errs = []
    sel = df.loc[res["selected"]]
    budget = planning_budget(s)
    carry = 0.0
    for t in YEARS:
        avail = budget[t] + (carry if s.carryover else 0)
        used = sel[f"cost_y{t}"].sum()
        if used > avail + 1e-6:
            errs.append(f"year {t}: spend {used} > available {avail}")
        carry = avail - used
    if s.mandatory:
        for i in df.index[df["mandatory"] == 1]:
            if i not in res["selected"]:
                errs.append(f"mandatory {i} missing")
    if s.dependencies:
        for i in sel.index:
            r = df.at[i, "requires"]
            if r and r not in res["selected"]:
                errs.append(f"{i} selected without prerequisite {r}")
    if s.alternatives:
        for g, n in sel[sel["exclusive_group"] != ""].groupby("exclusive_group").size().items():
            if n > 1:
                errs.append(f"group {g} has {n} options")
    if s.branch_cap is not None:
        cap = s.branch_cap * sum(s.budget.values())
        for b, v in sel[sel["branch"] != "Multi"].groupby("branch")["cost_total"].sum().items():
            if v > cap + 1e-6:
                errs.append(f"branch {b} {v} > cap {cap}")
    for p, floor in (s.pillar_min or {}).items():
        v = sel.loc[sel["pillar"] == p, "cost_total"].sum()
        if v < floor - 1e-6:
            errs.append(f"pillar {p} {v} < {floor}")
    return errs
