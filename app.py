"""
Capex Budget Optimizer: interactive Streamlit app.

Run locally:  streamlit run app.py
Deploy free:  push to GitHub, then share.streamlit.io and point it at app.py
"""
from dataclasses import replace

import altair as alt
import pandas as pd
import streamlit as st

from src.model import load_projects, solve, check_feasibility, Settings, YEARS
from src.analysis import monte_carlo, stability

NAVY, GOLD, GREY = "#1F2A44", "#C9A227", "#9AA3B2"
st.set_page_config(page_title="Capex Budget Optimizer", page_icon="📊", layout="wide")


@st.cache_data
def projects(uploaded_bytes=None):
    if uploaded_bytes is not None:
        import io
        return load_projects(io.BytesIO(uploaded_bytes))
    return load_projects("data/projects.csv")


# ------------------------------------------------------------------ sidebar
st.sidebar.header("Data")
up = st.sidebar.file_uploader("Upload your own projects.csv (same columns)", type="csv")
df = projects(up.getvalue() if up else None)

st.sidebar.header("Budget (k CAD)")
budget = {t: st.sidebar.number_input(f"Year {t}", 0, 10000, v, 50)
          for t, v in zip(YEARS, (1200, 1300, 1500))}
reserve = st.sidebar.slider("Contingency reserve held back", 0, 20, 10, 1, format="%d%%") / 100

st.sidebar.header("Business rules")
carryover = st.sidebar.checkbox("Unspent budget carries over to next year", True)
mandatory = st.sidebar.checkbox("Force mandatory safety projects", True)
dependencies = st.sidebar.checkbox("Respect project dependencies", True)
alternatives = st.sidebar.checkbox("At most one option per alternative group", True)
use_cap = st.sidebar.checkbox("Branch fairness cap", True)
cap = st.sidebar.slider("Max share of budget for one branch", 10, 60, 30, 5, format="%d%%",
                        disabled=not use_cap) / 100

st.sidebar.header("Strategic minimums (3-year spend, k CAD)")
pillar_min = {}
for p, v in (("Safety", 350), ("Sustainability", 500), ("Digital", 500)):
    val = st.sidebar.number_input(p, 0, 3000, v, 50)
    if val > 0:
        pillar_min[p] = val

st.sidebar.header("Risk assumptions")
mean_ov = st.sidebar.slider("Average cost overrun", 0, 25, 8, 1, format="%d%%") / 100
sd_ov = st.sidebar.slider("Overrun variability (std dev)", 0, 30, 12, 1, format="%d%%") / 100

s = Settings(budget=budget, carryover=carryover, mandatory=mandatory, dependencies=dependencies,
             alternatives=alternatives, branch_cap=cap if use_cap else None,
             pillar_min=pillar_min, reserve=reserve)

# ------------------------------------------------------------------ header
st.title("Capex Budget Optimizer")
st.caption("Which projects should we fund over the next 3 years? A 0/1 integer program (PuLP + HiGHS) "
           "with real-world rules, contingency planning and Monte Carlo risk. "
           "Sample data is illustrative, for a fictional Western Canada equipment dealer.")

res = solve(df, s)
if res["status"] != "Optimal":
    st.error(f"No feasible plan ({res['status']}). The rules conflict with the budget: "
             "lower a strategic minimum, raise the budget or reduce the reserve.")
    st.stop()

mc = monte_carlo(df, res["selected"], res["budget_total"], mean_overrun=mean_ov, overrun_sd=sd_ov)
naive = solve(df, Settings(budget=budget, carryover=False, mandatory=False, dependencies=False,
                           alternatives=False, branch_cap=None, pillar_min={}))
naive_viol = check_feasibility(df, naive, replace(s, reserve=0))

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Projects funded", f"{res['n_selected']} / {len(df)}")
c2.metric("Planned spend", f"${res['spend_total']/1000:.2f}M",
          f"{res['spend_total']/res['budget_total']:.0%} of budget", delta_color="off")
c3.metric("Planned 3-yr return", f"${res['return_base']/1000:.2f}M")
c4.metric("Return, bad case (P10)", f"${mc['return_p10']/1000:.2f}M")
c5.metric("Chance of overspending", f"{mc['prob_over_budget']:.0%}")

st.info(f"For comparison, a pure 'maximize ROI' model would plan ${naive['return_base']/1000:.2f}M "
        f"but break {len(naive_viol)} of your rules"
        + (f": {', '.join(naive_viol[:4])}{'...' if len(naive_viol) > 4 else ''}." if naive_viol else "."))

tab1, tab2, tab3, tab4 = st.tabs(["Portfolio", "Budget and pillars", "Risk", "Project confidence"])

with tab1:
    sel = df.loc[res["selected"]].reset_index()
    show = sel[["id", "name", "branch", "pillar", "cost_y1", "cost_y2", "cost_y3", "cost_total", "return_base"]]
    st.dataframe(show.sort_values("return_base", ascending=False), width="stretch", hide_index=True)
    st.download_button("Download portfolio CSV", show.to_csv(index=False), "recommended_portfolio.csv")
    rejected = df.drop(res["selected"]).reset_index()
    with st.expander(f"Not funded ({len(rejected)})"):
        st.dataframe(rejected[["id", "name", "branch", "pillar", "cost_total", "return_base"]],
                     width="stretch", hide_index=True)

with tab2:
    a, b = st.columns(2)
    plan_b = {t: budget[t] * (1 - reserve) for t in YEARS}
    yr = pd.DataFrame({"Year": [f"Year {t}" for t in YEARS],
                       "Spend": [res["spend_by_year"][t] for t in YEARS],
                       "Budget": [budget[t] for t in YEARS],
                       "Planning budget": [plan_b[t] for t in YEARS]})
    bars = alt.Chart(yr).mark_bar(color=NAVY).encode(x="Year", y=alt.Y("Spend", title="k CAD"))
    tick = alt.Chart(yr).mark_tick(color=GOLD, thickness=3, size=60).encode(x="Year", y="Budget")
    a.subheader("Spend by year vs budget (gold)")
    a.altair_chart(bars + tick, width="stretch")
    a.caption("With carryover on, a year can exceed its own budget using money saved earlier.")

    pil = pd.DataFrame([{"Pillar": p, "Spend": v, "Minimum": pillar_min.get(p, 0)}
                        for p, v in res["spend_by_pillar"].items()])
    pb = alt.Chart(pil).mark_bar(color=NAVY).encode(x=alt.X("Spend", title="k CAD"), y=alt.Y("Pillar", sort="-x"))
    pt = alt.Chart(pil[pil["Minimum"] > 0]).mark_tick(color=GOLD, thickness=3, size=25).encode(x="Minimum", y="Pillar")
    b.subheader("Spend by pillar vs minimum (gold)")
    b.altair_chart(pb + pt, width="stretch")

with tab3:
    st.subheader("Monte Carlo: 5,000 simulated futures")
    st.write("Each project's return is drawn between its low and high estimate (triangular), and each "
             "project's cost gets a random overrun (lognormal, right-skewed) using the assumptions in the sidebar.")
    sim = pd.DataFrame({"Total spend (k CAD)": mc["spend"], "Realized return (k CAD)": mc["returns"]})
    h1 = alt.Chart(sim).mark_bar(color=NAVY, opacity=0.85).encode(
        x=alt.X("Total spend (k CAD)", bin=alt.Bin(maxbins=50)), y="count()")
    rule = alt.Chart(pd.DataFrame({"b": [res["budget_total"]]})).mark_rule(color=GOLD, size=3).encode(x="b")
    a, b = st.columns(2)
    a.altair_chart(h1 + rule, width="stretch")
    a.caption(f"Gold line = total budget. {mc['prob_over_budget']:.0%} of futures overspend.")
    h2 = alt.Chart(sim).mark_bar(color=GOLD, opacity=0.85).encode(
        x=alt.X("Realized return (k CAD)", bin=alt.Bin(maxbins=50)), y="count()")
    b.altair_chart(h2, width="stretch")
    b.caption(f"P10 ${mc['return_p10']/1000:.2f}M · median ${mc['return_p50']/1000:.2f}M · P90 ${mc['return_p90']/1000:.2f}M")

with tab4:
    st.subheader("How confident is each funding decision?")
    st.write("Re-solves the model under many sampled return scenarios and counts how often each "
             "project is chosen. Projects near 50% are coin flips: that is where better data pays off.")
    n = st.select_slider("Scenarios", [50, 100, 200], 100)
    if st.button("Run confidence analysis"):
        with st.spinner("Solving scenarios..."):
            f = stability(df, s, n=n)
        out = df[["name", "branch", "pillar", "cost_total"]].join(f).reset_index()
        out["selection_frequency"] = (out["selection_frequency"] * 100).round(0)
        chart = alt.Chart(out).mark_bar().encode(
            x=alt.X("selection_frequency", title="% of scenarios selected", scale=alt.Scale(domain=[0, 100])),
            y=alt.Y("id", sort="-x", title=None),
            color=alt.condition((alt.datum.selection_frequency > 25) & (alt.datum.selection_frequency < 75),
                                alt.value(GOLD), alt.value(NAVY)),
            tooltip=["id", "name", "branch", "selection_frequency"]).properties(height=700)
        st.altair_chart(chart, width="stretch")
        st.caption("Gold = uncertain decisions (25 to 75%). Network projects like a new depot are candidates "
                   "for a dedicated network study (e.g. anyLogistix) before committing.")

with st.expander("Method and assumptions"):
    st.markdown("""
- **Decision**: fund project (1) or not (0). Objective: maximize total base-case 3-year return.
- **Budget**: spend per year within the planning budget (budget minus reserve); unspent money can carry over.
- **Rules**: mandatory projects, prerequisites, mutually exclusive alternatives, branch cap, pillar minimums.
- **Risk**: Monte Carlo on returns (triangular low/base/high) and costs (lognormal overrun).
- **Confidence**: re-optimization under sampled returns; frequency of selection per project.
- **Limits**: returns are not discounted; overrun assumptions are illustrative; data is synthetic.
- Baseline for comparison: the textbook formulation (maximize ROI under yearly budgets and pillar minimums).
""")
