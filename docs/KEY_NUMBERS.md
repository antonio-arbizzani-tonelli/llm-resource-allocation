# Extension key numbers

These numbers describe the new extension evidence. Original benchmarks and
their classifications remain unchanged. Every value below has a denominator,
timer/scientific scope, retained source and replay command. Formulation and
GH/AGH are Cheng and Nguyen's, arXiv:2604.07472; this repository is an independent
implementation. Inputs are synthetic and runtimes measure CPU allocation
software, with modeled GPU delays as coefficients.

## Confirmed matched-runtime numbers — WP1

The highlighted point is AGH, 16 queries, four models and four tiers, load 200,
AGH seed 37 and beta 0.8. Python and C++ execute in the same WSL environment
from the same retained prepared scientific input. Ratios compare these complete
implementations, including their different rich-trace and internal-check costs.
The Python public call includes its internal input validation and construction
of `PdmProblemData`; C++ receives the prepared coefficient lattice through
transport before the core timer. This compares the existing complete public
implementations, rather than an equal-operation microbenchmark or a pure
language effect.

| Metric | Value | Denominator and boundary | Source | Replay |
|---|---:|---|---|---|
| Core ratio of medians, Python/C++ | **120.5437**, 95% CI **[109.7530, 131.2151]** | Ten complete paired rounds (20 measured calls); public fresh-result solve including rich traces and independent validation; excludes startup, parsing, projection, output and destruction; same-process warmup excluded | [WP1 analysis, AGH 16x4x4/load200/core](../benchmarks/matched_runtime_2026-10-14/analysis/analysis.json) | Command A |
| Core Python median / IQR | 8.425024 / 0.832450 s | Ten Python calls at the same core boundary | [WP1 analysis](../benchmarks/matched_runtime_2026-10-14/analysis/analysis.json) | Command A |
| Core C++ median / IQR | 0.069892 / 0.009481 s | Ten C++ calls at the same core boundary | [WP1 analysis](../benchmarks/matched_runtime_2026-10-14/analysis/analysis.json) | Command A |
| Complete-invocation ratio of medians, Python/C++ | **99.7005**, 95% CI **[93.2556, 107.2592]** | Ten separate complete paired rounds (20 measured calls); one-solve Linux subprocess startup through exit, including imports, parsing, solve, projection, output and destruction; shared final-decision schema; external preflight excluded, no in-process warmup | [WP1 analysis, AGH 16x4x4/load200/invocation](../benchmarks/matched_runtime_2026-10-14/analysis/analysis.json) | Command A |
| Complete-invocation Python median / IQR | 9.883960 / 1.168888 s | Ten Python subprocess invocations | [WP1 analysis](../benchmarks/matched_runtime_2026-10-14/analysis/analysis.json) | Command A |
| Complete-invocation C++ median / IQR | 0.099137 / 0.014886 s | Ten C++ subprocess invocations | [WP1 analysis](../benchmarks/matched_runtime_2026-10-14/analysis/analysis.json) | Command A |
| Campaign coverage | **480/480** verified worker calls | 12 GH/AGH method/configuration points × two timer boundaries × two runtimes × ten rounds; six shape/load configurations | [WP1 status](../benchmarks/matched_runtime_2026-10-14/status.json) | Command A |
| Median paired core ratio / ratio IQR | **117.8295 / 12.6774**, median bootstrap 95% CI **[112.6376, 127.3708]** | Ten per-round Python/C++ duration ratios at the core boundary above; dimensionless IQR; distinct from the primary ratio of medians | [Retained initial WP1/core row](../benchmarks/matched_runtime_2026-10-14/extension_numbers_initial.json), [historical cross-platform verification](extension_summary_verification.json) | Command B |
| Median paired complete-invocation ratio / ratio IQR | **102.4151 / 12.0337**, median bootstrap 95% CI **[93.9038, 108.1649]** | Ten separate per-round Python/C++ subprocess duration ratios at the complete-invocation boundary above; dimensionless IQR; distinct from the primary ratio of medians | [Retained initial WP1/invocation row](../benchmarks/matched_runtime_2026-10-14/extension_numbers_initial.json), [historical cross-platform verification](extension_summary_verification.json) | Command B |

Primary intervals use 10,000 paired-round percentile bootstrap resamples with
local seed 20261014. Duration IQRs describe observed call variability, not
confidence intervals. Ten conditional pairs do not capture all thermal/systematic
effects. These pointwise values are not universal or language-only speedups.
The historical 103.93 ratio retains its original environment and timer scope.

Command A verifies retained bytes, final decisions and deterministic analysis
without rerunning timed algorithms:

```sh
python scripts/run_matched_runtime.py replay --output benchmarks/matched_runtime_2026-10-14
```

Command B creates a separate supplemental artifact, verifies the original WP1
manifest and accepted raw hashes, and defaults to the exact frozen source ZIP.
The ZIP has 91 verified prepared source entries; SHA-256
`10b741781c4c29bc9af0bdd66edaa6408060d8644b6d1297486d149653bea55d`.
Its provenance is additional to the unchanged original manifest. Later opt-in
Stage-2 source changes do not replace those frozen bytes.

```sh
python -B scripts/summarize_extension_results.py --wp1 benchmarks/matched_runtime_2026-10-14 --output docs/extension_numbers.json --wp2 benchmarks/openmp_diagnostics_2026-10-14/analysis/extension.json --wp3 benchmarks/stage2_policy_2026-10-14/analysis.json --wp4 benchmarks/stage2_robustness_2026-10-14/analysis.json --wp5 benchmarks/instance_scaling_2026-10-14/analysis/analysis.json --wp6 benchmarks/solver_quality_2026-10-14/analysis.json
```

The emitted supplemental JSON records its exact replay arguments and labels
both ratio estimands separately. Each supplemental median interval uses ten
complete pairs, 10,000 paired-round resamples and seed 20261014; its ratio IQR
uses R type-7 quartiles. The ten focused tests pass. The historical WSL Python
3.13.16/Windows Python 3.14.3 equality proof verifies the initial WP1 supplement
with the earlier WP3 analysis, now retained exactly as
[extension_numbers_initial.json](../benchmarks/matched_runtime_2026-10-14/extension_numbers_initial.json). Its raw SHA
matches the historical Windows digest; the byte difference from WSL is LF
versus CRLF encoding. The 25.429 s Windows duration is outside every
solve/invocation sample and applies only to that initial artifact. Historical
argv/hashes/observed fields are preserved
([scope record](extension_summary_verification_scope.json),
[environment clarification](EXTENSION_ENVIRONMENT.md)). The current
[extension_numbers.json](extension_numbers.json) now includes final WP2–6 and
has a separate [fresh verification](extension_summary_final_verification.json):
Windows Python 3.14.3 **30.57474 s**, WSL Python 3.13.16 **48.86380 s**, exit 0,
equal complete JSON values, CRLF/LF difference only. Delivered LF SHA-256 is
`010286b1ac5f4f723a13e800920b16569018ba0e7bccf7be5768500523685c8c`;
480 WP1 samples, 24 ratio rows and the frozen ZIP are verified. No solve runs.
Command B records the exact final supplied paths; the historical proof certifies
only the initial output. The initial JSON is a separate
supplemental benchmark artifact, outside the original 1,552-file inventory;
byte-preserving benchmark transport retains its raw Windows SHA unchanged.

## Confirmed OpenMP diagnostics — WP2

The workload is a fixed mixed batch of 32 synthetic GH/AGH cases. Every core
observation uses prepared native inputs, includes OpenMP team creation/barriers,
and excludes parsing/output and warmup. Speedups below are ratios of medians
with 30 paired rounds, 10,000 percentile bootstrap resamples and seed 20261014.
Each team speedup uses the one-thread version of that same setting; intervention
ratios instead divide the same-team control median by the candidate median.

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
reasonable local candidate when minimizing elapsed time; eight threads give
the higher observed efficiency of these two settings. The selected sorted
minimum does not establish an ordering benefit. All intervals are unadjusted
exploratory intervals across many dependent comparisons, with selection
optimism; no universal optimum or causal allocator/cache/frequency explanation
is claimed. WSL does not identify physical P/E cores or provide a physical SMT
intervention. Hardware counters and frequency/temperature time series are
unavailable. All negative controls remain in the linked CSVs and report.

The 32 excluded goldens pass independent Python feasibility and bitwise
objective checks. Timed batches match 64-bit compact final-decision/objective/
feasibility fingerprints; this is not full rich-trace parity. Complete-invocation
statistics have 29 samples per setting because the first warm-containing round
is excluded; the reported core statistics have all 30 rounds.

Command D verifies and unpacks the retained archive and regenerates statistics
without a compiler, timed executable, solver or scientific rerun:

```sh
python scripts/analyze_openmp_extension.py --output benchmarks/openmp_diagnostics_2026-10-14
```

The frozen WP2 PLAN's `run_openmp_diagnostics.py --analyze` command derives
the producer's original 2,000-resample summary. Command D reproduces the
10,000-resample extension statistics reported here; the PLAN remains unchanged.

Native WSL timing finished before unmeasured post-processing was interrupted
for prolonged drvfs I/O. Windows Python 3.14.3 on NTFS completed that processing;
no measured job, raw timing or scientific input changed. The
[fresh archive-only replay](../benchmarks/openmp_diagnostics_2026-10-14/analysis/archive_replay_verification.json)
takes 64.879 s and reproduces exact derived-artifact SHA-256 values with the
timed binary absent. That duration is outside all performance samples.

## Retrospective opt-in policy evidence — WP3

These are post-policy replay classifications of the same retained decisions,
not rewritten results of the original solver campaign. The original default
remains absolute 1e-8 USD and relative zero. The opt-in rule is
`|a-b| <= max(abs_tol, rel_tol * max(|a|,|b|))`, with selected relative 1e-12.
No LP is solved during this retrospective replay and no decision is repaired.

| Metric | Post-policy value | Historical default for context | Denominator and scope | Source | Replay |
|---|---:|---:|---|---|---|
| Scientifically usable Stage-2 attempts | **850/1,850** | 646/1,850 | Attempts from 37 accepted fixed-deployment sources; all 1,000 solver-infeasible attempts remain rejected | [WP3 selected/old policy analysis](../benchmarks/stage2_policy_2026-10-14/analysis.json) | Command C |
| Objective-only rejections recovered | **204/204** | 0/204 | Independently feasible extracted decisions rejected only for absolute objective disagreement | [WP3 analysis](../benchmarks/stage2_policy_2026-10-14/analysis.json) | Command C |
| Feasibility recovered by adaptation | **344/1,344 = 25.5952%** | 256/1,344 = 19.0476% | Independently infeasible frozen-routing baselines; rejected operational results contribute no recovery | [WP3 analysis](../benchmarks/stage2_policy_2026-10-14/analysis.json) | Command C |
| Paired summed C4+C5 reduction | **5.957974%**, cluster-bootstrap 95% CI **[5.745418%, 6.063490%]** | 5.857419% over 390 usable pairs | 506 same-scenario usable frozen/adapted pairs in 37 source grids; `(sum frozen - sum adapted) / sum frozen`; no savings assigned to infeasible baselines | [WP3 selected_policy](../benchmarks/stage2_policy_2026-10-14/analysis.json) | Command C |
| Material objective mutation rejection | **1/1 rejected** | No historical mutation statistic | Injected relative error approximately 2e-6, exceeding 1e-6; rejection tested under selected relative 1e-12 | [WP3 mutation_check](../benchmarks/stage2_policy_2026-10-14/analysis.json) | Command C |
| Relative-policy sensitivity | **7/7 nonzero coefficients** recover the same 204 rejections | Relative zero preserves 646 accepted attempts | Sweep 1e-12, 1e-11, 1e-10, 1e-9, 1e-8, 1e-7, 1e-6 on the retained 1,850 attempts | [WP3 sweep](../benchmarks/stage2_policy_2026-10-14/analysis.json) | Command C |

The paired interval resamples 37 source-grid clusters, with 10,000 draws and
seed 20261014. Scenario-pair intervals are separately labeled sensitivity;
grid points within a deployment are dependent. The changed usable cohorts mean
the two pooled cost reductions are not a causal policy improvement estimate.
The deterministic synthetic grid is not a real-world probability sample, and
the unmatched GH/AGH/P_DM cohorts support no method ranking. Three rejected
Stage-1 sources continue to skip 150 scenarios.

Command C independently replays the delivered historical archive and regenerates
the separate policy evidence:

```sh
python scripts/replay_stage2_policy.py --output benchmarks/stage2_policy_2026-10-14
```

## New matched Stage-2 cohorts — WP4

All 144/144 planned sources complete in 2,871.436 s. Of these, 136 are accepted,
yielding 6,800 LP attempts: 3,246 usable successes and 3,554 solver-infeasible
results. Eight rejected time-limited P_DM incumbents skip 400 planned LPs.
Their solver/independent C1–C5 differences exceed the unchanged Stage-1
absolute-only 1e-8 USD acceptance floor.
All eight source reports now independently replay and give feasible placements
with zero constraint violations; rejection is objective-only, and those sources
remain unusable under the approved unchanged Stage-1 acceptance policy.
The new Stage-2 solves use explicit relative 1e-12, HiGHS and 20-second limits.

| Nominal load | Accepted sources / planned | Usable / attempted LPs | Recovered / frozen failures | Usable cost pairs / contributing shared-input clusters | Paired C4+C5 reduction, 95% CI |
|---|---:|---:|---:|---:|---:|
| 200 | 36/36 | 870/1,800 | 330/1,260 (26.1905%) | 540 / 12 | **4.945490% [4.640838%, 5.177031%]** |
| 2,000 | 36/36 | 820/1,800 | 280/1,260 (22.2222%) | 540 / 12 | **4.923512% [4.628603%, 5.146725%]** |
| 20,000 | 35/36 | 930/1,750 | 400/1,220 (32.7869%) | 530 / 12 | **5.156249% [4.726027%, 5.526150%]** |
| 100,000 | 29/36 | 626/1,450 | 311/1,135 (27.4009%) | 315 / 12 | **5.433509% [4.983066%, 5.865710%]** |

Source: [WP4 analysis](../benchmarks/stage2_robustness_2026-10-14/analysis.json),
[source results](../benchmarks/stage2_robustness_2026-10-14/source_results.json).
Each cost interval resamples the twelve contributing input clusters, preserving
contributing pairs across methods, with 10,000 draws and seed 20261014.
The estimator divides the difference of frozen/adapted cost sums by the same
usable frozen sum; infeasible baselines receive no savings. Pooled per-load
figures include unmatched accepted inputs. The accepted-source intersection
is 40/48 input identities: **12/12, 12/12, 11/12, 5/12** by ascending load.
Only matched-method summaries use this intersection; differing deployments,
pair sets and recovery denominators support no general method ranking.
Matched P_DM paired cost savings are approximately zero, with tiny signed
roundoff retained. These are conditional synthetic grid results.

Historical diagnosis covers **1,000/1,000** infeasible records with sufficient
certificates: 940 error-SLO, 120 compute-capacity, **60 overlapping**, zero
unexplained. Demand balance/unmet caps support those lower bounds; they are not
exclusive causes or a unique IIS. Source:
[historical diagnosis](../benchmarks/stage2_robustness_2026-10-14/historical_infeasibility.json).

Command E's initial independent replay **passes, exit 0**, verifying
144 source reports, 6,800 frozen reports and 3,246 extracted operational reports
([replay evidence](../benchmarks/stage2_robustness_2026-10-14/replay_analysis.json)).
Post-timing archive transport now uses four parts, all below 80 MB; verification
preserves all 7,233 original entry triples and analysis values, with unchanged
scientific producer ASTs and measured source snapshot. Its 21.1857 s Windows
Python 3.14.3 processing time is unmeasured
([transport verification](../benchmarks/stage2_robustness_2026-10-14/postprocessing_verification.json)).
The **final fresh archive-only replay also passes**: all 7,233 entries and the
measured source ZIP SHA-256 verify, the same 144/6,800/3,246 independent reports
reproduce and analysis JSON values match. It requires no timed binary or solver,
takes **246.1337 s** under Windows Python 3.14.3, and is entirely outside the
campaign's performance samples
([fresh replay verification](../benchmarks/stage2_robustness_2026-10-14/archive_replay_verification.json)).
WP4 is closed; its [public inventory](../benchmarks/stage2_robustness_2026-10-14/artifact_hashes.json)
retains 22 artifacts.

```sh
python scripts/run_stage2_extension.py --output benchmarks/stage2_robustness_2026-10-14 --replay
```

## Native scaling with instance variability — WP5

Coverage is **90/90 method/instance points, 270/270 native samples, 20/20 small
full Python parity points**, zero retained failed worker attempts; all 90 points
are independently feasible. Five input seeds across six query levels and four
menus provide 45 distinct inputs, with shared 64x4x4 measured once. Total wall
time is **1,649.006364 s (27.48 minutes)**, including the documented checkpoint
pause; this is not a single solve duration.

| Fit | Feasible / complete instance points | Exponent, 95% cluster-bootstrap CI | Log-space R² |
|---|---:|---:|---:|
| Query I, GH | 30/30 | **1.6615 [1.6402, 1.6798]** | **0.9903** |
| Query I, AGH | 30/30 | **1.9402 [1.9254, 1.9600]** | **0.9975** |
| Menu J*K, GH | 20/20 | **0.9455 [0.9185, 0.9707]** | **0.9928** |
| Menu J*K, AGH | 20/20 | **1.4461 [1.4065, 1.4998]** | **0.9694** |

Source: [analysis](../benchmarks/instance_scaling_2026-10-14/analysis/analysis.json),
[per-instance medians/IQR](../benchmarks/instance_scaling_2026-10-14/analysis/instance_timings.csv),
[execution](../benchmarks/instance_scaling_2026-10-14/execution_summary.json).
The statistical input is each instance's median of three core solves. Intervals
use **five complete seed clusters**, **10,000 draws**, **seed 20261014**, holding
those medians fixed; **no temporal-repeat bootstrap** is used. Repeats are not
independent inputs. Core includes native traces/validation and excludes startup,
parsing/output/destruction; external warmup is excluded, with fresh measured
single-solve processes. Full Python parity covers I=16/32 at 4x4 only; the other
70 points have independent final-decision validation.

Query levels are **16/32/64/128/256/384**, J=K=4. Menus are **4x4/8x4/8x8/12x12**,
I=64, products **16/32/64/144**. Instance seeds **11/23/37/41/53** are separate
from AGH seed 37. Five clusters limit precision; menu aspect ratios/structural
branches confound a single product exponent. These are observed-range
descriptive fits, with no asymptotic complexity or extrapolation claim.

A Windows live-read lock interrupts one WSL atomic checkpoint replacement
after 218 persisted samples. The exact complete producer temporary checkpoint
contains 219; recovery verifies all retained hashes/warm projections and the
one added record's independent validation before promotion, preserving all
previous records/fields and original backups. Resume uses the initial budget
with 9,420 s remaining; no observations are edited, discarded, duplicated or
imputed. Source/binary/PLAN/input fingerprints remain unchanged
([checkpoint recovery](../benchmarks/instance_scaling_2026-10-14/checkpoint_recovery.json)).
The frozen source ZIP has 93 verified entries, SHA-256
`d40f62f15dc6d967d4ab6bc098af6e6da6062a63121dc073158d1c7b43b17514`.

Command F's initial replay **passes**: 1,335 files and 360 independent native
validations (90 excluded warm points plus 270 measurements), with JSON values
reproduced in 72.6157 s of unmeasured Windows Python 3.14.3 processing
([initial replay](../benchmarks/instance_scaling_2026-10-14/replay_verification.json)).
A post-timing label correction uses exact tested major levels and hides minor
log-axis labels; the measured 93-entry source ZIP, data/status and analysis JSON
hash stay unchanged, with measured/renderer helper hashes separately recorded
([plot provenance](../benchmarks/instance_scaling_2026-10-14/plot_presentation_verification.json)).
The closing
[label clarification](../benchmarks/instance_scaling_2026-10-14/label_provenance_clarification.json)
confirms the earlier proof with explicit UTF-8 parsing: only `analyze` has a
changed AST; the frozen/current `derived_analysis` display strings both read
`R²`. An encoding-unspecified comparison suggesting extra changes is discarded.
Arithmetic, measured data, analysis JSON and the original proof remain unchanged.
The **final replay passes**, verifying **1,337 files / 360 native validations**
in **72.26584 s**, without compiler, timed binary or solver execution. CSV/JSON
numbers are unchanged
([final replay](../benchmarks/instance_scaling_2026-10-14/final_replay_verification.json)).
WP5 is closed; all replay/rendering times are outside performance samples.

```sh
python scripts/run_instance_scaling.py replay --output benchmarks/instance_scaling_2026-10-14
```

## Longer-limit solver quality — WP6

**20/20 unique measured jobs complete, 18/20 accepted**: eight GH/AGH results
and ten of twelve HiGHS incumbents, with three excluded warmups, zero retries,
zero worker failures and zero missing results. WSL wall time is
**3,225.756829929 s (53.76 minutes)** versus 5,110 s forecast. Four fixed coherent
inputs cover 10x10x10 at loads 1/200/100,000 and 6x6x10 at 100,000; each MILP
limit is a fresh cold solve. Gurobi is explicitly skipped under the WSL license.

| Limit | Accepted same-input AGH/HiGHS pairs | Median AGH / HiGHS cost | Descriptive bootstrap 95% CI |
|---|---:|---:|---:|
| 20 s | 4/4 | **0.845329** | **[0.687776, 1.344490]** |
| 120 s | 3/4 | **2.103171** | **[1.256138, 2.468748]** |
| 600 s | 3/4 | **2.103171** | **[1.256138, 2.112943]** |

Source: [analysis](../benchmarks/solver_quality_2026-10-14/analysis.json),
[complete cost/bound rows](../benchmarks/solver_quality_2026-10-14/REPORT.md),
[execution](../benchmarks/solver_quality_2026-10-14/execution_summary.json).
Ratios below one favor AGH. Three of four accepted cases favor AGH at 20 s;
all three accepted cases favor HiGHS at each longer limit. The longer cohorts
exclude different cases; this is a local ordering change, with no universal
or three-way Gurobi ranking. Median intervals use **5,000 accepted-case
resamples and seed 113**, not temporal repeats; four convenience inputs supply
descriptive evidence only.

The rejected 10x10x10/load200/120 s and 6x6x10/load100,000/600 s incumbents
agree on objective but fail independent constraints under unchanged defaults;
their usable costs are unavailable. All twelve MILPs terminate with an incumbent
at `maxTimeLimit`, never a proven optimum. Bounds are 1.649791–12.159294 USD
and derived normalized gaps **0.986719115–0.999999981**, indicating weak
certification. `native_gap` is unavailable through the approved adapter.
`normalized_gap = abs(incumbent-bound)/abs(incumbent)` is separately derived,
with the documented zero/missing rules; rejected gaps are diagnostic only.

Command G's fresh archive-only replay **passes, exit 0**: 149 archive entries,
frozen source/input hashes, 23 completed reports (20 measured + three warmups),
18/20 accepted results and exact analysis/CSV/report bytes reproduced. A fresh
Windows Python 3.14.3 environment has no pip, Pyomo, HiGHS, Gurobi or Matplotlib
in parent/child and uses no current source, compiler, binary or solver.
Numerical replay takes **4.8376 s**, complete proof **5.9576 s**, unmeasured;
publication processing is separately **17.0403 s**
([replay verification](../benchmarks/solver_quality_2026-10-14/archive_replay_verification.json),
[publication](../benchmarks/solver_quality_2026-10-14/postprocessing_verification.json)).

The **final current-launcher replay also passes** in a second fresh environment
with no optional packages or unpacked evidence initially present. It verifies
149 archive entries, 75 frozen sources and five input records; exact
analysis/CSV/report bytes, 23 completed reports and 18/20 accepted measured
results reproduce, with zero retries/failures/missing measured rows.
Numerical replay is **18.477553 s**, complete proof **20.110521 s**, outside
measured solves. The initial proof is retained unchanged; these distinct
processing observations do not constitute a performance comparison
([final current-launcher replay](../benchmarks/solver_quality_2026-10-14/archive_replay_final_verification.json)).

```sh
python scripts/extension_solver_quality.py summarize --output benchmarks/solver_quality_2026-10-14
```

## Optional skip and release verification

| Package | Current numeric status | Required final denominators and scope |
|---|---|---|
| WP7 optional memory work | Skipped | No new allocation/resident-memory profile, lean trace or memory improvement claim |
| WP8 pre-manifest verification | **7/7 checks pass**, including **1,131 Python tests / zero skips** | WSL Python 3.13.16, native release/sanitizer, 63/63 live/frozen parity, 90 OpenMP comparisons/ten Python independent cases and both examples; separately repeated after manifest generation |

Source: [actual pre-manifest commands/log hashes](extension_release_preflight.json).
Python takes 147.301 s inside unittest (150.6005 s outer); native release
15.8426 s and ASAN/UBSAN 30.5101 s; live/frozen parity 4.1725 s and OpenMP
3.8691 s. At numerical checkpoint `543ad4e`, the post-manifest repetition also
passes: 1,131 tests / zero skips (181.611 s unittest), native release/sanitizer,
63/63 parity, 90 OpenMP comparisons, both examples and verification of 3,568
publication files. Actual closing logs/canonical handoff remain in the
development workspace; this hashed preflight evidence retains its earlier scope.
The [extension report](EXTENSION_REPORT.md) records hypotheses, deviations,
unresolved scope and the final delivery verdict.
