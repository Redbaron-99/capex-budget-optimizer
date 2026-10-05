# Phase 2: validating the depot decision in anyLogistix

## Why anyLogistix is not used for the whole project

anyLogistix (ALX) is a supply chain network design and simulation tool. It answers questions like
"where should stock sit" and "what service level does this network give". It does not do capex
portfolio selection across 40 unrelated projects (LED retrofits, software, safety barriers). Python
and PuLP are the right tool for that part.

ALX does have a real job here. The confidence analysis shows one decision the budget model cannot
settle on its own:

| Project | Selected in % of scenarios |
|---|---|
| P22 New regional parts depot (Kamloops) | about 52% |
| P23 Express parts shuttle (Kamloops) | about 41% |

These two are alternatives (pick at most one), and their return estimates are the widest in the
dataset because they depend on how the parts network behaves. That is a network question, so it
belongs in a network tool. Better numbers for these two rows change the funding decision; better
numbers for most other rows would not.

## The workflow

1. **Get ALX.** Download the free Personal Learning Edition (PLE) from anylogistix.com. Check the
   current licence terms and model size limits on their site before you start; PLE is meant for
   learning and non-commercial use.
2. **Build the base network (Scenario A, today).** One DC in Surrey supplying branch customers in
   Kamloops, Kelowna and Prince George. Use made-up but realistic demand per branch (parts orders per
   week) and road distances between cities.
3. **Scenario B, depot.** Add a Kamloops depot holding fast-moving parts. Run a Network Optimization
   experiment and record total annual cost and average lead time to customers.
4. **Scenario C, shuttle.** Keep Surrey as the only DC but add a fixed daily truck route to Kamloops.
   Record the same two outputs.
5. **Run a simulation experiment** on B and C to see service level (share of orders delivered next
   day) and how much it varies.
6. **Convert to 3-year returns.** For each scenario: (annual cost saving vs A + value of extra
   next-day orders) x 3. Use the optimistic and pessimistic simulation runs for `return_high` and
   `return_low`.
7. **Update `data/projects.csv`** rows P22 and P23 with the new low/base/high values, run
   `python run.py` again, and check whether the confidence gap between them widens.

## What to say on LinkedIn after Phase 2

"The budget model flagged the depot vs shuttle choice as a coin flip, so I built both options in
anyLogistix. The network study showed X, which moved the decision from 52/41 to Y/Z."

Only post the numbers you actually get from ALX.
