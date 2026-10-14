# Stage-2 opt-in objective policy replay

All 2,027 archive entries pass SHA-256 verification. Independent replay verifies
40 Stage-1 reports, 1,850 frozen-routing reports and 850 extracted Stage-2 reports.
The original archive and its classifications remain unchanged; no LP was solved.

| Policy | Usable / attempted | New usable / objective rejections | Recovered / frozen failures | Paired cost scenarios | Paired C4+C5 reduction |
|---|---:|---:|---:|---:|---:|
| Absolute 1e-8 default | 646/1850 | 0/204 | 256/1344 | 390 | 5.857419% |
| Opt-in relative 1e-12 | 850/1850 | 204/204 | 344/1344 | 506 | 5.957974% |

The pooled paired figure divides the difference of cost sums by the frozen cost
sum over the same usable pairs. Frozen-infeasible decisions receive no baseline
cost savings. The selected-policy source-grid bootstrap 95% interval is
[0.05745418176046431, 0.060634898998714507]; the paired denominator is
506 scenarios in 37 contributing
source grids. Resampling unit, seed and 10,000 replicates are recorded in JSON.
Scenario-pair intervals are separately labeled sensitivity because grid points
within one deployment are dependent. Neither interval estimates a real-world
probability from this deterministic synthetic design.

All seven requested nonzero sensitivity coefficients recover the same objective
rejections. A 2e-6 injected relative error remains rejected under the selected
1e-12 policy. Recorded maximum relative disagreement is
3.4017459614298448e-16 among the 204 rejections;
the all-extracted maximum is separately recorded in JSON. Raw values remain intact.
No general solver-precision guarantee follows from this finite evidence.

All 1,000 solver-infeasible attempts remain unusable. Three rejected Stage-1
sources still skip 150 scenarios. Method cohorts remain unmatched and are not
ranked. Per-load denominators and paired bootstrap intervals are in analysis.json.

Replay: `python scripts/replay_stage2_policy.py --output benchmarks/stage2_policy_2026-10-14`.
Historical raw evidence: `../stage2_stress_2026-10-13/evidence.zip`; each new row
retains its original archive entry and SHA-256. The opt-in rule is
`|a-b| <= max(abs_tol, rel_tol * max(|a|,|b|))`; relative zero preserves defaults.
