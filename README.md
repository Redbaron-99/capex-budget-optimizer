# Capex Budget Optimizer

   **Live app:** https://capex-budget-optimizer-vijay.streamlit.app/
Which capital projects should a business fund over the next three years, given a fixed budget,
strategic targets and real operating rules? This project answers that with integer programming in
Python (PuLP + HiGHS), then stress-tests the answer with Monte Carlo simulation.

The usual textbook approach selects projects to maximize ROI under yearly budgets and minimum spend
per strategic pillar. This project starts there and adds the rules a real capex review runs into.

**Data is synthetic**: 40 project requests for a fictional heavy equipment dealer with six branches
in Western Canada (Surrey, Kamloops, Kelowna, Prince George, Calgary, Edmonton). Values are in
thousands of CAD.

## What this version adds

| Addition | Why it matters in a real capex review |
|---|---|
| Budget carryover | Money not spent in year 1 is usually still available in year 2 |
| Mandatory projects | A failed crane inspection is not optional, whatever its ROI |
| Dependencies | RFID rollout is useless without the yard management system |
| Mutually exclusive alternatives | Build a depot *or* run a shuttle, not both |
| Branch fairness cap | No single branch takes more than 30% of the budget |
| Contingency reserve | Plans that use 99% of the budget almost always overspend |
| Monte Carlo risk | Returns drawn from low/base/high ranges, costs get skewed overruns |
| Rule cost analysis | Shows how much return each business rule costs (or adds) |
| Project confidence | Re-solves under 300 scenarios and counts how often each project is picked |

## Results on the sample data

| Model | Planned 3-yr return | Real-world rule breaks | Chance of overspending |
|---|---|---|---|
| ROI only | $3.38M | 6 | >99% |
| ROI + pillar minimums (textbook approach) | $3.12M | 2 | >99% |
| Improved model, all rules | $3.10M | 0 | >99% |
| Improved model + 10% contingency | $2.81M | 0 | 13% |

What the numbers say:

1. The textbook model looks slightly better ($3.12M) but skips a mandatory safety project and
   funds both the depot and the shuttle. Once every rule is enforced, carryover recovers almost all of
   that gap ($3.10M, valid plan).
2. Planning to spend the full budget, with an assumed 8% average cost overrun, overspends in more than
   99% of simulated futures. Holding back 10% cuts that to 13% and costs about $295k of planned return.
   That is the price of certainty, and it is a management choice, not a model output.
3. Mandatory safety projects cost about $95k of return. The safety and sustainability minimums cost
   $60k and $50k. The digital minimum and the branch cap cost nothing at this budget.
4. Most decisions are stable (selected in 90%+ of scenarios). The depot vs shuttle choice is not:
   52% vs 41%. That is the one decision worth a dedicated network study. See
   [docs/anylogistix_phase2.md](docs/anylogistix_phase2.md).

All of this depends on the assumptions in the sample data. The point is the method, not the numbers.

## The model

- Decision: `x_i = 1` if project *i* is funded.
- Objective: maximize sum of base-case 3-year returns.
- Budget with carryover: `carry_t = budget_t x (1 - reserve) + carry_(t-1) - spend_t`, `carry_t >= 0`.
- Mandatory: `x_i = 1`. Dependency: `x_i <= x_prereq`. Alternatives: `sum of group <= 1`.
- Branch cap: branch total spend `<= 30% x total budget`. Pillar minimums: pillar spend `>= floor`.

`src/model.py` also has `check_feasibility`, which re-checks every rule on a solution without the
solver. It is how the "rule breaks" column is counted.

## Run it

```bash
pip install -r requirements.txt
python run.py            # results/ CSVs and charts/ PNGs (about 40 seconds)
streamlit run app.py     # interactive app
```

Works in Google Colab too: upload the folder, `!pip install -r requirements.txt`, `!python run.py`.

## Deploy the app (free public link)

1. Push this folder to a GitHub repo.
2. Go to [share.streamlit.io](https://share.streamlit.io), pick the repo, main file `app.py`, deploy.

## Use your own data

Replace `data/projects.csv` (or upload a CSV in the app) with the same columns:
`id, name, branch, pillar, cost_y1..3, return_low, return_base, return_high, mandatory, requires,
exclusive_group, validate_in_anylogistix`.

## Limits

- Returns are not discounted (no NPV). Easy to add, left out to stay comparable with the original.
- Overrun assumptions (8% average, 12% std dev) are illustrative. Change them in the app.
- Projects are independent apart from the explicit rules. Real portfolios have synergies.

## Project layout

```
data/projects.csv          40 synthetic project requests
src/model.py               integer program and rule checker
src/analysis.py            Monte Carlo, confidence, rule costs, reserve trade-off
run.py                     runs everything, writes results/ and charts/
app.py                     Streamlit app
docs/anylogistix_phase2.md how to validate the depot decision in anyLogistix
```
