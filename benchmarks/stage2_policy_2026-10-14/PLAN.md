# Stage-2 objective policy replay plan

Written before replay execution. This experiment reads the published complete
AC-restart archive; it invokes no solver and changes none of its bytes.

Hypothesis: the 204 independently feasible objective rejections are representable
roundoff, with recorded differences of one to three ULP and maximum relative
disagreement 3.401745961429846e-16. An explicit relative coefficient of 1e-12
should recover them while still rejecting a deliberately injected relative
objective error of at least 1e-6. This coefficient is a conservative experiment
setting about 2,940 times the observed maximum, not a solver accuracy guarantee.
The historical absolute 1e-8 USD remains the default.

Metric: accept exactly when |a-b| <= max(1e-8, rel_tol*max(|a|,|b|)), after
unchanged independent feasibility validation. Replay all 1,850 operational
attempts, including the 1,000 solver-infeasible records; compare rel_tol=0 with
1e-12, 1e-11, 1e-10, 1e-9, 1e-8, 1e-7 and 1e-6. Report usable attempts,
newly usable attempts, recovered frozen failures, and paired C4+C5 reduction
with their denominators, pooled and separately by source load multiplier.
No rejected Stage-1 source is promoted by this Stage-2-only policy.

Success: all 204 rejections pass independent replay and the opt-in 1e-12
comparison, all former successes remain accepted, infeasible LPs stay unusable,
and the >=1e-6 mutation is rejected. Failure or partial recovery is retained.
There are no full-grid cost means when any point fails.

Uncertainty: percentile 95% paired bootstrap, 10,000 replicates with an explicit
local seed. Each replicate resamples complete contributing source grids, so the
50 deterministic points within one deployment stay together. A separately
labeled scenario-pair bootstrap is descriptive sensitivity. These synthetic
intervals do not estimate real-world probabilities and include AGH repeats of
the same deterministic input; method cohorts remain unmatched. No ranking.

Provenance: verify archive SHA-256 and every entry against the original evidence
manifest. Recompute all 40 Stage-1 reports, all 1,850 frozen-routing reports and
all 850 extracted Stage-2 reports with the original tolerances, preserving raw
decisions and objectives. Record new per-attempt classifications separately.

Estimated duration: below five minutes for hash/validator/bootstrap replay on
the recorded i7-13620H; no timing or performance claim. The replay writes derived
output atomically and can be rerun from the unchanged archive. Warmup and rotated
measurement order do not apply to this solver-free classification audit.

Replay command:

```bash
python scripts/replay_stage2_policy.py --output benchmarks/stage2_policy_2026-10-14
```
