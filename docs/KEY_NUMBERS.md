# Extension key numbers

A compact reference for the six studies measured or replayed on 14 October 2026. The
[extension report](EXTENSION_REPORT.md) explains their methods and limitations;
[RESULTS.md](RESULTS.md) keeps the original campaigns separate. The formulation and
GH/AGH algorithms come from Cheng and Nguyen's
[paper](https://arxiv.org/abs/2604.07472); the implementations and measurements are
this project's work.

All experiments run on CPU with synthetic inputs. GPU capacity and latency are
modeled inputs. OpenMP distributes independent allocation cases across CPU threads.
Costs are model outputs, not measured cloud bills.

## Matched Python/C++ runtime — WP1

The example below uses AGH with 16 queries, four models, four tiers, load 200,
algorithm seed 37 and beta 0.8. Python and C++ ran in the same WSL environment with
the same prepared scientific input. The ratios compare the complete implementations,
including their different trace and internal-check costs. The Python public call
includes its internal input validation and construction of `PdmProblemData`; C++
receives the prepared coefficient lattice through transport before the core timer.
The comparison therefore includes implementation differences beyond language choice;
the two core timers do not cover identical preparation work.

| Metric | Value | Denominator and boundary | Source | Replay |
|---|---:|---|---|---|
| Core ratio of medians, Python/C++ | **120.5437**, 95% CI **[109.7530, 131.2151]** | Ten complete paired rounds (20 measured calls); complete public solve returning a fresh result, with rich traces and independent validation; excludes startup, parsing, projection, output and destruction; same-process warmup excluded | [WP1 analysis, AGH 16x4x4/load200/core](../benchmarks/matched_runtime_2026-10-14/analysis/analysis.json) | Command A |
| Core Python median / IQR | 8.425024 / 0.832450 s | Ten Python calls at the same core boundary | [WP1 analysis](../benchmarks/matched_runtime_2026-10-14/analysis/analysis.json) | Command A |
| Core C++ median / IQR | 0.069892 / 0.009481 s | Ten C++ calls at the same core boundary | [WP1 analysis](../benchmarks/matched_runtime_2026-10-14/analysis/analysis.json) | Command A |
| Complete-invocation ratio of medians, Python/C++ | **99.7005**, 95% CI **[93.2556, 107.2592]** | Ten separate complete paired rounds (20 measured calls); one-solve Linux subprocess startup through exit, including imports, parsing, solve, projection, output and destruction; shared final-decision schema; external preflight excluded, no in-process warmup | [WP1 analysis, AGH 16x4x4/load200/invocation](../benchmarks/matched_runtime_2026-10-14/analysis/analysis.json) | Command A |
| Complete-invocation Python median / IQR | 9.883960 / 1.168888 s | Ten Python subprocess invocations | [WP1 analysis](../benchmarks/matched_runtime_2026-10-14/analysis/analysis.json) | Command A |
| Complete-invocation C++ median / IQR | 0.099137 / 0.014886 s | Ten C++ subprocess invocations | [WP1 analysis](../benchmarks/matched_runtime_2026-10-14/analysis/analysis.json) | Command A |
| Campaign coverage | **480/480** verified worker calls | 12 GH/AGH method/configuration points × two timer boundaries × two runtimes × ten rounds; six shape/load configurations | [WP1 status](../benchmarks/matched_runtime_2026-10-14/status.json) | Command A |
| Median paired core ratio / ratio IQR | **117.8295 / 12.6774**, median bootstrap 95% CI **[112.6376, 127.3708]** | Ten per-round Python/C++ duration ratios at the core boundary above; dimensionless IQR; distinct from the primary ratio of medians | [Retained initial WP1/core row](../benchmarks/matched_runtime_2026-10-14/extension_numbers_initial.json), [historical cross-platform verification](extension_summary_verification.json) | Command B |
| Median paired complete-invocation ratio / ratio IQR | **102.4151 / 12.0337**, median bootstrap 95% CI **[93.9038, 108.1649]** | Ten separate per-round Python/C++ subprocess duration ratios at the complete-invocation boundary above; dimensionless IQR; distinct from the primary ratio of medians | [Retained initial WP1/invocation row](../benchmarks/matched_runtime_2026-10-14/extension_numbers_initial.json), [historical cross-platform verification](extension_summary_verification.json) | Command B |

Primary intervals use 10,000 paired-round percentile bootstrap resamples with local
seed 20261014. Duration IQRs describe observed call variability, not confidence
intervals. Ten conditional pairs do not capture all thermal/systematic effects.
These pointwise values are not universal or language-only speedups. The historical
103.93 ratio retains its original environment and timer scope.

The retained [primary
analysis](../benchmarks/matched_runtime_2026-10-14/analysis/analysis.json) and
[supplemental JSON](extension_numbers.json) label both ratio estimands separately.
Replay and aggregation commands are listed below; frozen-source, cross-platform and
archive verification details are in the report's [provenance
appendix](EXTENSION_REPORT.md#provenance-and-verification).

## OpenMP diagnostics — WP2

The workload is a fixed mixed batch of 32 synthetic GH/AGH cases. Every core
observation uses prepared native inputs, includes OpenMP team creation/barriers, and
excludes parsing/output and warmup. Speedups below are ratios of medians with 30
paired rounds, 10,000 percentile bootstrap resamples and seed 20261014. Each team
speedup uses the one-thread version of that same setting; intervention ratios
instead divide the same-team control median by the candidate median.

| Metric | Value | Denominator and scope | Source | Replay |
|---|---:|---|---|---|
| Completed campaign | **6,030/6,030**, zero failed observations | 201 settings × 30 rounds; each observation solves the same 32-case batch; all requested levels covered in a factor-separable design, full 585-setting interaction grid skipped | [WP2 analysis](../benchmarks/openmp_diagnostics_2026-10-14/analysis/extension.json) | Command D |
| Eight-thread unsorted baseline speedup / efficiency | **4.0223**, 95% CI **[3.7636, 4.4243]** / **50.28%** | `cores/close/dynamic/chunk1`, default allocator; same-setting one-thread median 1.008776 s; efficiency = speedup/8 | [WP2 analysis](../benchmarks/openmp_diagnostics_2026-10-14/analysis/extension.json) | Command D |
| Eight-thread baseline core median / IQR | **0.250794 / 0.047142 s** | 30 complete 32-case core batches | [WP2 analysis](../benchmarks/openmp_diagnostics_2026-10-14/analysis/extension.json) | Command D |
| Sixteen-thread unsorted core median / speedup | **0.221533 s / 4.5536**, 95% CI **[3.9406, 5.0207]** | Same baseline factors, 30 pairs against its own one-thread control; 28.46% efficiency | [WP2 analysis](../benchmarks/openmp_diagnostics_2026-10-14/analysis/extension.json) | Command D |
| Fastest selected setting, sorted sixteen-thread median / speedup | **0.220359 s / 4.7871**, 95% CI **[4.5179, 5.2513]** | Selected from 201 settings on the same data; 30 pairs against its own sorted one-thread control; no independent confirmation | [WP2 recommendation](../benchmarks/openmp_diagnostics_2026-10-14/analysis/extension.json) | Command D |
| Sorting effect at sixteen threads | **1.0053**, 95% CI **[0.9592, 1.1998]** | Unsorted control / sorted candidate, same team/factors/default allocator, 30 pairs; interval includes one, so improvement is unestablished | [Same-team controls](../benchmarks/openmp_diagnostics_2026-10-14/analysis/same_team_controls.csv) | Command D |
| Arena restriction effect at eight threads | **0.08390**, 95% CI **[0.07616, 0.08836]** | Default allocator control / `MALLOC_ARENA_MAX=1` candidate, same unsorted eight-thread setting, 30 pairs; candidate median 2.989136 s, so restriction slows the workload | [Same-team controls](../benchmarks/openmp_diagnostics_2026-10-14/analysis/same_team_controls.csv) | Command D |
| Eight-thread wall-idle proxy / Amdahl-equivalent serial fraction | **6.2262% / 14.1272%** | Medians of measured worker wall accounting / separate response-time fit; neither is measured CPU utilization nor a causal explanation of efficiency loss | [Worker statistics](../benchmarks/openmp_diagnostics_2026-10-14/analysis/thread_statistics.csv), [decomposition](../benchmarks/openmp_diagnostics_2026-10-14/analysis/decomposition.csv) | Command D |

For this workload, unsorted `cores/close/dynamic/chunk1` at 16 threads is a
reasonable local candidate when minimizing elapsed time; eight threads give the
higher observed efficiency of these two settings. The selected sorted minimum does
not establish an ordering benefit. All intervals are unadjusted exploratory
intervals across many dependent comparisons, with selection optimism; no universal
optimum or causal allocator/cache/frequency explanation is claimed. WSL does not
identify physical P/E cores or provide a physical SMT intervention. Hardware
counters and frequency/temperature time series are unavailable. All negative
controls remain in the linked CSVs and report.

The 32 reference cases, evaluated outside the timed samples, pass independent Python
feasibility and bitwise objective checks. Timed batches match 64-bit compact
final-decision/objective/ feasibility fingerprints; this is not full rich-trace
parity. Complete-invocation statistics have 29 samples per setting because the first
round, which contains warmup, is excluded; the reported core statistics have all 30
rounds.

The report retains all [same-team comparisons and accounting
limits](EXTENSION_REPORT.md#wp2--openmp-efficiency-diagnostics). Its provenance
appendix distinguishes the original 2,000-resample producer summary from the
10,000-resample analysis used here.

## Retrospective opt-in policy evidence — WP3

These results apply the optional policy to the original retained decisions. The
original solver campaign keeps its published classifications. Its default remains
absolute 1e-8 USD and relative zero. The opt-in rule is `|a-b| <= max(abs_tol,
rel_tol * max(|a|,|b|))`, with selected relative 1e-12. No LP is solved during this
retrospective replay and no decision is repaired.

| Metric | Post-policy value | Historical default for context | Denominator and scope | Source | Replay |
|---|---:|---:|---|---|---|
| Scientifically usable Stage-2 attempts | **850/1,850** | 646/1,850 | Attempts from 37 accepted fixed-deployment sources; all 1,000 solver-infeasible attempts remain rejected | [WP3 selected/old policy analysis](../benchmarks/stage2_policy_2026-10-14/analysis.json) | Command C |
| Objective-only rejections recovered | **204/204** | 0/204 | Independently feasible extracted decisions rejected only for absolute objective disagreement | [WP3 analysis](../benchmarks/stage2_policy_2026-10-14/analysis.json) | Command C |
| Feasibility recovered by adaptation | **344/1,344 = 25.5952%** | 256/1,344 = 19.0476% | Independently infeasible frozen-routing baselines; rejected operational results contribute no recovery | [WP3 analysis](../benchmarks/stage2_policy_2026-10-14/analysis.json) | Command C |
| Paired summed C4+C5 reduction | **5.957974%**, cluster-bootstrap 95% CI **[5.745418%, 6.063490%]** | 5.857419% over 390 usable pairs | 506 same-scenario usable frozen/adapted pairs in 37 source grids; `(sum frozen - sum adapted) / sum frozen`; no savings assigned to infeasible baselines | [WP3 selected_policy](../benchmarks/stage2_policy_2026-10-14/analysis.json) | Command C |
| Material objective mutation rejection | **1/1 rejected** | No historical mutation statistic | Injected relative error approximately 2e-6, exceeding 1e-6; rejection tested under selected relative 1e-12 | [WP3 mutation_check](../benchmarks/stage2_policy_2026-10-14/analysis.json) | Command C |
| Relative-policy sensitivity | **7/7 nonzero coefficients** recover the same 204 rejections | Relative zero preserves 646 accepted attempts | Sweep 1e-12, 1e-11, 1e-10, 1e-9, 1e-8, 1e-7, 1e-6 on the retained 1,850 attempts | [WP3 sweep](../benchmarks/stage2_policy_2026-10-14/analysis.json) | Command C |

The selected-policy interval resamples 37 contributing source-grid clusters, with
10,000 draws and seed 20261014; the historical 390-pair cost cohort has 33
contributing grids. Scenario-pair intervals are separately labeled sensitivity; grid
points within a deployment are dependent. The changed usable cohorts mean the two
pooled cost reductions are not a causal policy improvement estimate. The
deterministic synthetic grid is not a real-world probability sample, and the
unmatched GH/AGH/P_DM cohorts support no method ranking. Three rejected Stage-1
sources continue to skip 150 scenarios.

## New matched Stage-2 cohorts — WP4

All 144/144 planned sources completed in 2,871.436 s. Of these, 136 were accepted,
yielding 6,800 LP attempts: 3,246 usable successes and 3,554 solver-infeasible
results. Eight time-limited P_DM incumbents were rejected, leaving 400 planned LPs
unattempted. Their solver/independent C1–C5 differences exceed the unchanged Stage-1
absolute-only 1e-8 USD acceptance floor. Independent replay of all eight source
reports finds feasible placements with zero constraint violations; rejection is
objective-only, and those sources remain unusable under the approved unchanged
Stage-1 acceptance policy. The new Stage-2 solves use explicit relative 1e-12, HiGHS
and 20-second limits.

| Nominal load | Accepted sources / planned | Usable / attempted LPs | Recovered / frozen failures | Usable cost pairs / contributing shared-input clusters | Paired C4+C5 reduction, 95% CI |
|---|---:|---:|---:|---:|---:|
| 200 | 36/36 | 870/1,800 | 330/1,260 (26.1905%) | 540 / 12 | **4.945490% [4.640838%, 5.177031%]** |
| 2,000 | 36/36 | 820/1,800 | 280/1,260 (22.2222%) | 540 / 12 | **4.923512% [4.628603%, 5.146725%]** |
| 20,000 | 35/36 | 930/1,750 | 400/1,220 (32.7869%) | 530 / 12 | **5.156249% [4.726027%, 5.526150%]** |
| 100,000 | 29/36 | 626/1,450 | 311/1,135 (27.4009%) | 315 / 12 | **5.433509% [4.983066%, 5.865710%]** |

Source: [WP4 analysis](../benchmarks/stage2_robustness_2026-10-14/analysis.json),
[source results](../benchmarks/stage2_robustness_2026-10-14/source_results.json).
Each cost interval resamples the twelve contributing input clusters, preserving
contributing pairs across methods, with 10,000 draws and seed 20261014. The
estimator divides the difference of frozen/adapted cost sums by the same usable
frozen sum; infeasible baselines receive no savings. Pooled per-load figures include
unmatched accepted inputs. The accepted-source intersection is 40/48 input
identities: **12/12, 12/12, 11/12, 5/12** by ascending load. Only matched-method
summaries use this intersection; differing deployments, pair sets and recovery
denominators support no general method ranking. Matched P_DM paired cost savings are
approximately zero, with tiny signed roundoff retained. These are conditional
synthetic grid results.

Historical diagnosis covers **1,000/1,000** infeasible records with sufficient
certificates: 940 error-SLO, 120 compute-capacity, **60 overlapping**, zero
unexplained. Demand balance/unmet caps support those lower bounds; they are not
exclusive causes or a unique IIS. Source: [historical
diagnosis](../benchmarks/stage2_robustness_2026-10-14/historical_infeasibility.json).

Independent replay reproduced all **144 source reports, 6,800 frozen reports and
3,246 extracted operational reports**. The final archive-only check verified all
**7,233 entries** and the measured source snapshot. See the [WP4
provenance](EXTENSION_REPORT.md#wp4-archive-transport-and-replay) for the original
and final proofs and the four-part public archive.

## Native scaling with instance variability — WP5

Coverage is **90/90 method/instance points, 270/270 native samples, 20/20 small full
Python parity points**, zero retained failed worker attempts; all 90 points are
independently feasible. Five input seeds across six query levels and four menus
provide 45 distinct inputs, with shared 64x4x4 measured once. Total wall time is
**1,649.006364 s (27.48 minutes)**, including the documented checkpoint pause; this
is not a single solve duration.

| Fit | Feasible / complete instance points | Exponent, 95% cluster-bootstrap CI | Log-space R² |
|---|---:|---:|---:|
| Query I, GH | 30/30 | **1.6615 [1.6402, 1.6798]** | **0.9903** |
| Query I, AGH | 30/30 | **1.9402 [1.9254, 1.9600]** | **0.9975** |
| Menu J*K, GH | 20/20 | **0.9455 [0.9185, 0.9707]** | **0.9928** |
| Menu J*K, AGH | 20/20 | **1.4461 [1.4065, 1.4998]** | **0.9694** |

Source:
[analysis](../benchmarks/instance_scaling_2026-10-14/analysis/analysis.json),
[per-instance
medians/IQR](../benchmarks/instance_scaling_2026-10-14/analysis/instance_timings.csv),
[execution](../benchmarks/instance_scaling_2026-10-14/execution_summary.json). The
statistical input is each instance's median of three core solves. Intervals use
**five complete seed clusters**, **10,000 draws**, **seed 20261014**, holding those
medians fixed; **no temporal-repeat bootstrap** is used. Repeats are not independent
inputs. Core includes native traces/validation and excludes startup,
parsing/output/destruction; external warmup is excluded, with fresh measured
single-solve processes. Full Python parity covers I=16/32 at 4x4 only; the other 70
points have independent final-decision validation.

Query levels are **16/32/64/128/256/384**, J=K=4. Menus are **4x4/8x4/8x8/12x12**,
I=64, products **16/32/64/144**. Instance seeds **11/23/37/41/53** are separate from
AGH seed 37. Five clusters limit precision; menu aspect ratios/structural branches
confound a single product exponent. These are observed-range descriptive fits, with
no asymptotic complexity or extrapolation claim.

One checkpoint persistence interruption was recovered from verified producer bytes;
zero workers failed and no observation was edited, discarded or imputed. The [final
replay](../benchmarks/instance_scaling_2026-10-14/final_replay_verification.json)
verified **1,337 files and 360 native validations** (90 excluded warm points plus
270 measurements). Recovery and later plot-label changes are documented in the [WP5
provenance](EXTENSION_REPORT.md#wp5-checkpoint-recovery-and-plot-provenance).

## Longer-limit solver quality — WP6

**20/20 unique measured jobs completed, 18/20 accepted**: eight GH/AGH results and
ten of twelve HiGHS incumbents, with three excluded warmups, zero retries, zero
worker failures and zero missing results. WSL wall time is **3,225.756829929 s
(53.76 minutes)**. Four fixed coherent inputs cover 10x10x10 at loads 1/200/100,000
and 6x6x10 at 100,000; each MILP limit is a fresh cold solve. Gurobi was skipped
because its WSL license did not cover these cases.

| Limit | Accepted same-input AGH/HiGHS pairs | Median AGH / HiGHS cost | Descriptive bootstrap 95% CI |
|---|---:|---:|---:|
| 20 s | 4/4 | **0.845329** | **[0.687776, 1.344490]** |
| 120 s | 3/4 | **2.103171** | **[1.256138, 2.468748]** |
| 600 s | 3/4 | **2.103171** | **[1.256138, 2.112943]** |

Source: [analysis](../benchmarks/solver_quality_2026-10-14/analysis.json), [complete
cost/bound rows](../benchmarks/solver_quality_2026-10-14/REPORT.md),
[execution](../benchmarks/solver_quality_2026-10-14/execution_summary.json). Ratios
below one favor AGH. Three of four accepted cases favor AGH at 20 s; all three
accepted cases favor HiGHS at each longer limit. The longer cohorts exclude
different cases; this is a local ordering change, with no universal or three-way
Gurobi ranking. Median intervals use **5,000 accepted-case resamples and seed 113**,
not temporal repeats; four convenience inputs supply descriptive evidence only.

The rejected 10x10x10/load200/120 s and 6x6x10/load100,000/600 s incumbents agree on
objective but fail independent constraints under unchanged defaults; their usable
costs are unavailable. All twelve MILPs terminate with an incumbent at
`maxTimeLimit`, never a proven optimum. Bounds are 1.649791–12.159294 USD and
derived normalized gaps **0.986719115–0.999999981**, indicating weak certification.
`native_gap` is unavailable through the approved adapter. `normalized_gap =
abs(incumbent-bound)/abs(incumbent)` is separately derived, with the documented
zero/missing rules; rejected gaps are diagnostic only.

The [final archive-only
replay](../benchmarks/solver_quality_2026-10-14/archive_replay_final_verification.json)
verified **149 archive entries, 75 frozen source files, five input records and 23
completed reports** (20 measured plus three warmups). It reproduced exact
analysis/CSV/report bytes and the **18/20** accepted measured results without solver
dependencies. See the [WP6
provenance](EXTENSION_REPORT.md#wp6-portable-replay-and-rendering) for both replay
proofs; their processing times are outside every solve sample.

## Replay commands

Run these commands from the repository root. They verify retained evidence and
regenerate analyses without rerunning the timed algorithms or solving LPs or MILPs.
Their own elapsed times are post-processing costs, not benchmark samples. See
[EXTENSION_ENVIRONMENT.md](EXTENSION_ENVIRONMENT.md) for versions and replay
dependencies; WP6 numerical replay needs standard-library Python 3.13 or later, with
Matplotlib optional for plots.

| Label | Study | Command |
|---|---|---|
| A | WP1 matched runtime | `python scripts/run_matched_runtime.py replay --output benchmarks/matched_runtime_2026-10-14` |
| C | WP3 historical Stage-2 policy replay | `python scripts/replay_stage2_policy.py --output benchmarks/stage2_policy_2026-10-14` |
| D | WP2 10,000-resample OpenMP analysis | `python scripts/analyze_openmp_extension.py --output benchmarks/openmp_diagnostics_2026-10-14` |
| E | WP4 new Stage-2 campaign replay | `python scripts/run_stage2_extension.py --output benchmarks/stage2_robustness_2026-10-14 --replay` |
| F | WP5 instance scaling | `python scripts/run_instance_scaling.py replay --output benchmarks/instance_scaling_2026-10-14` |
| G | WP6 solver quality | `python scripts/extension_solver_quality.py summarize --output benchmarks/solver_quality_2026-10-14` |

Command B aggregates the final analyses into a separate supplemental artifact. It
verifies WP1's original manifest, accepted raw hashes and frozen source ZIP; the
exact arguments and input hashes are retained in the output.

```sh
python -B scripts/summarize_extension_results.py --wp1 benchmarks/matched_runtime_2026-10-14 --output docs/extension_numbers.json --wp2 benchmarks/openmp_diagnostics_2026-10-14/analysis/extension.json --wp3 benchmarks/stage2_policy_2026-10-14/analysis.json --wp4 benchmarks/stage2_robustness_2026-10-14/analysis.json --wp5 benchmarks/instance_scaling_2026-10-14/analysis/analysis.json --wp6 benchmarks/solver_quality_2026-10-14/analysis.json
```

## Verification scope

Optional WP7 memory profiling was skipped, so the extension supplies no new memory
profile or memory improvement claim. WP8's numerical checkpoint `543ad4e` passed
**1,131 Python tests with zero skips**, native release and ASAN/UBSAN checks,
**63/63** live/frozen parity cases, **90** OpenMP comparisons and both examples. The
pre-manifest proof and distinct post-manifest repetition retain their own scope in
the report's [delivery
record](EXTENSION_REPORT.md#wp8--delivery-and-final-verification). These are
historical verification results, not tests rerun for this document.
