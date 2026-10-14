# Matched-source Stage-2 robustness plan

Prepared before execution. New campaign evidence remains separate from every
published benchmark. The work has two separately reported parts.

## Historical infeasibility certificates

Re-read all 1,000 solver-infeasible records from the verified October 13 archive.
Identify sufficient contradictions between mandatory service (demand balance and
the retained unmet-demand cap), the fixed routing mask, error SLO, delay SLO,
and compute capacity. For example, if the minimum error over admitted routes
times (1-u_cap) exceeds epsilon, the LP is infeasible regardless of compute.
Retain the query, coefficient, lower bound, right-hand side and raw margin.

Report sufficient causes separately and permit overlaps. Balance and the unmet
cap impose the mandatory service obligation; they are supporting constraints,
not independent exclusive causes. A certificate does not identify a unique IIS
or prove that other bottlenecks are absent. Unknown cases stay explicitly
unexplained rather than receiving a fabricated label. Decompose by nominal load
multiplier and scenario arrival factor. No original LP or record is replaced.

## New matched instance cohorts

Hypothesis: moderate nominal loads may show different recovery/cost behavior
from the previously dominant 100000 endpoint. Three explicit instance seeds,
shared across GH/AGH/P_DM, remove the previous input-cohort asymmetry. A negative
result (no gain or pervasive infeasibility) is retained.

Planned shapes: 8x4x4, 16x4x4, 32x4x4, 16x8x8. Nominal load multipliers:
200, 2000, 20000, 100000. Instance seeds: 11, 23, 37. GH, AGH and P_DM receive
the exact same prepared instance for each shape/load/instance seed. AGH's separate
algorithm seed is 37. The opt-in generator in scripts/extension_instances.py
uses local independent uniform [0.9,1.1] factors for query arrivals and token
counts (rounded to positive integer tokens), and route delay components.
These are explicitly assumed synthetic variations, not recovered paper data.

Each accepted Stage-1 source has the original 50-point deterministic grid:
arrival multipliers 0.8/0.85/0.9/0.95/1/1.025/1.05/1.1/1.15/1.2 and shared
adverse delay/error multipliers 1/1.1/1.2/1.35/1.5. The original source caps
remain. The full plan contains 144 sources and at most 7,200 LP attempts.
HiGHS is selected explicitly in WSL; a licensed Gurobi runtime is unavailable
there. Stage-1 and Stage-2 solve limits are 20 seconds. Stage-1 retains its
default absolute objective policy. Stage-2 uses opt-in relative 1e-12 plus the
unchanged absolute floor 1e-8. An optimum is claimed only when solver evidence
reports it; a feasible time-limited incumbent is labeled accordingly.

Metrics: attempted/accepted sources, attempted/usable LPs, recovery divided by
frozen-routing failures, and (sum frozen C4+C5 - sum adapted C4+C5) / sum frozen
C4+C5 on identical feasible usable pairs. Report each nominal load separately;
infeasible baselines have no savings. Provide 95% paired bootstrap intervals
using 10,000 source-grid resamples and local seed 20261014. They quantify
conditional synthetic sensitivity, not a real-world probability. Also report
the intersection of accepted source identities across all three methods;
no ranking uses unmatched cohorts. Partial grids have no full-grid mean.

Success: complete planned coverage with exact input hashes shared across methods,
independent validation for every usable result, separate per-load denominators,
and replayable raw failures. Scientific benefit is not an exit condition.

Estimated duration: original 40 sources used 659.52 seconds; scaling by 144/40
gives roughly 40 minutes. Allow 60-90 minutes for backend/seed differences and
diagnostic/replay overhead. This is an estimate, not a hard worst-case bound:
7,200 consecutive 20-second limits would be much longer. The runner imposes a
three-hour wall budget, checkpoints after Stage 1 and every scenario, and stops
with all partial evidence retained. Before launch, a bounded smoke/pilot may
revise the estimate. If the estimate exceeds three hours, use only 8x4x4 and
16x4x4 (72 sources, at most 3,600 LPs), record the deviation, and retain all
completed wider-scope evidence.

Environment: the central extension environment record declares the i7-13620H,
WSL/Python/backend versions, power plan/governor and observed app state. Do not
assert that applications were closed or frequencies were fixed unless observed.
This campaign reports scientific decisions and integrated CPU planner timings;
it is not a serving-latency benchmark. No timing ratio is claimed, so warmup and
rotated timing order do not apply. Job order is deterministically rotated across
methods to avoid making one method consistently first.

Commands (execution remains pending until earlier work packages are committed):

```bash
python scripts/run_stage2_extension.py --output benchmarks/stage2_robustness_2026-10-14 --diagnose-original
python scripts/run_stage2_extension.py --output benchmarks/stage2_robustness_2026-10-14 --run
python scripts/run_stage2_extension.py --output benchmarks/stage2_robustness_2026-10-14 --run --resume
python scripts/run_stage2_extension.py --output benchmarks/stage2_robustness_2026-10-14 --analyze
```
