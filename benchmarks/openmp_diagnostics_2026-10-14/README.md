# OpenMP extension observations

Recorded 6030/6030 configuration/round attempts; 6030 complete projection-matching batches. Each batch contains 32 fixed synthetic GH/AGH cases. Timing uses the prepared-input native solve boundary including team creation and barriers, excluding parsing/output. Warmups are excluded from core observations.

The compact FNV comparison covers final decisions, objective components and feasibility. The separate 32 excluded goldens retain full projected evidence and the original shared Python independent feasibility/bitwise objective checks. Full rich-trace parity is not inferred from a compact fingerprint.

The fastest observed median is 0.220359407 s over 30 rounds at `16_cores_close_dynamic_1_True_None`, selected from 201 complete settings.

Against the cores/close/dynamic/chunk1/unsorted/default-arena control at the same team, the ratio of medians is 1.00533, paired bootstrap95% [0.959158, 1.19983] over 30 rounds. These data do not establish an improvement over that control.

Recommendation: use this setting as the measured local candidate and confirm it on an independent run/workload before adopting it generally. Selection used the same timing data across many configurations; the unadjusted intervals have selection optimism and do not certify an optimum.

Per-worker busy seconds and wall-idle percentages are in [thread_statistics.csv](analysis/thread_statistics.csv). All one-factor same-team schedule/chunk/place/bind/sort/arena comparisons and paired denominators are in [same_team_controls.csv](analysis/same_team_controls.csv). The time decomposition is in [decomposition.csv](analysis/decomposition.csv); median/IQR, boundaries, failures and hypotheses are in [extension.json](analysis/extension.json).

The time decomposition is `Tp = T1/p + (max busy - mean busy) + remainder`, using paired rounds and time units. Signed remainders are retained, including negative values. Per round, wall idle also equals `(max busy - mean busy)/core + (1 - max busy/core)`. Components are computed before medians; medians need not sum. The Amdahl-equivalent serial fraction is a separate response-time fit, not measured serial code and not an additive causal component. Busy includes stalls/descheduling and is not CPU utilization; the remainder does not identify allocation, cache or frequency causes.

| Hypothesis | Evidence and limit |
|---|---|
| load balance | measured schedule/order sensitivity and per-worker wall accounting; imbalance remains descriptive |
| physical p e and hyperthreading | unresolved: guest affinity/SMT topology does not identify physical P/E cores or provide a physical SMT on/off intervention |
| memory bandwidth and cache | unresolved: no workload hardware counters; perf observation: executable unavailable |
| allocation | MALLOC_ARENA_MAX sensitivity measured at selected teams; no allocation counters or causal contention attribution |
| frequency and throttling | unresolved: no frequency/temperature time series; governor=unavailable in WSL; frequency=unavailable in WSL; temperature=unavailable in WSL |
| environment | power plan and app observations are retained; no fixed-frequency or closed-app claim beyond recorded evidence |

All inputs and timings are synthetic CPU allocation-software observations. GPU delays are model coefficients. Allocation formulations and GH/AGH follow Cheng and Nguyen, arXiv2604.07472. No paper-table replication or universal hardware attribution is claimed.

Replay in a fresh clone (no measured binary, compiler, or optional solver license required):

```bash
python scripts/analyze_openmp_extension.py --output benchmarks/openmp_diagnostics_2026-10-14
```

The command verifies the archive, automatically unpacks raw/golden evidence, checks source/input/preparation hashes and raw sidecars, and recomputes statistics. Only standard-library Python and the shipped statistics helper are needed. No scientific algorithm is rerun. `evidence.zip` retains all observations, failures and goldens. Portable metadata replaces only the exact measured Linux workspace prefix with `.`; original SHA and portable SHA are retained in provenance.json. Complete originals, including measured sources/binary, remain in the ignored local results snapshot.
