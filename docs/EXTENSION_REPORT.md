# Extension results, 14 October 2026

Six studies extend the original evaluation: a matched Python/C++ runtime comparison,
OpenMP diagnostics, a retrospective Stage-2 tolerance replay, a new Stage-2
robustness campaign, native scaling across seeded instances and longer-limit solver
comparisons. The matched runtime study supports a local C++ advantage; the OpenMP
study shows sensitivity to thread and allocator settings; the Stage-2 studies
quantify feasibility recovery and modeled cost changes within their stated cohorts.

The formulation and GH/AGH algorithms come from Cheng and Nguyen's
[paper](https://arxiv.org/abs/2604.07472). This repository provides independent
Python/Pyomo and C++20 implementations and the engineering measurements below. All
experiments run on CPU with synthetic inputs. GPU capacity and latency are modeled
coefficients; OpenMP distributes independent experimental cases across CPU threads.
Model costs are not observed cloud bills. Instance shapes use `I x J x K`: queries,
models and GPU tiers.

[KEY_NUMBERS.md](KEY_NUMBERS.md) is the compact numerical reference.
[RESULTS.md](RESULTS.md) keeps the original campaigns separate. In particular, the
original Stage-2 classifications, the optional retrospective replay (WP3) and new
solves with that explicit option (WP4) are three distinct evaluations. The numerical
checkpoint is `543ad4e`; release chronology, archive recovery and verification
records are collected in the [provenance appendix](#provenance-and-verification).

## WP1 — matched Python/C++ runtime

This study compares the existing Python and serial C++20 implementations in the same
WSL environment, using identical prepared scientific inputs. It tests whether the
C++ advantage observed in the earlier cross-platform benchmark persists under
matched conditions; a point's paired interval must lie wholly above one to support
that conclusion.

Six shape/load configurations (4x2x2, 8x4x4 and 16x4x4 at loads 1 and 200), each
with GH and AGH, produce 12 method/configuration points. Every point has ten paired
rounds for each of two timer boundaries: 480/480 timed worker calls are verified,
with no recorded failed attempt. The campaign took approximately 22 minutes. Source,
binary and input hashes, excluded warm evidence, raw workers and environmental
observations are retained in the
[campaign](../benchmarks/matched_runtime_2026-10-14/PLAN.md).

The core boundary runs the complete public algorithm on its constructed input,
including rich traces and independent validation. It excludes startup, parsing,
projection, output and result destruction; each measured core call has a
same-process excluded warmup. A separate complete-invocation boundary measures a
single Linux subprocess through exit, including startup/imports, parsing, solve,
projection, output and destruction. Its final-decision JSON schema is shared; those
separate calls have no in-process warmup, and external preflight calls are excluded.
Internal input checks and trace representations remain implementation-specific costs
inside the solve. Neither ratio isolates a language-only effect. Specifically,
Python's public call includes internal input validation and `PdmProblemData`
construction, while C++ receives the prepared coefficient lattice through transport
before the core timer. These are the existing full public implementations; the core
ratio is not an equal-operation microbenchmark.

For AGH at 16x4x4/load200, median Python/C++ core durations are 8.425024/0.069892 s;
their IQRs are 0.832450/0.009481 s. The ratio of medians is 120.5437, with
paired-round bootstrap 95% CI [109.7530, 131.2151]. Separate complete-invocation
medians are 9.883960/0.099137 s, giving 99.7005 with 95% CI [93.2556, 107.2592].
Each estimate uses ten pairs, seed 20261014 and 10,000 bootstrap resamples. These
estimates apply to this local synthetic configuration.

The [complete
analysis](../benchmarks/matched_runtime_2026-10-14/analysis/analysis.json) preserves
all pointwise medians, duration IQRs and ratio-of-medians intervals.
`summarize_extension_results.py` additionally derives the median/Q1/Q3/IQR of
per-round ratios and a bootstrap interval for the median paired ratio. These are
distinct estimands, labeled separately in the supplemental numbers; neither replaces
the campaign's primary ratio-of-medians result. For the same AGH 16x4x4/load200
point, the median of paired core ratios is 117.8295, with ratio IQR 12.6774 and
bootstrap 95% CI [112.6376, 127.3708]. The median of paired complete-invocation
ratios is 102.4151, with ratio IQR 12.0337 and bootstrap 95% CI [93.9038, 108.1649].
Each denominator is ten complete measurement pairs; each median interval uses 10,000
paired-round resamples and seed 20261014. Ratio IQRs are dimensionless R type-7
quartiles. The primary analysis and supplemental JSON preserve both estimands. Their
frozen-source and cross-platform verification records are described in the
[provenance appendix](#wp1-source-snapshot-and-supplemental-analysis).

The results depend on the recorded WSL/Python 3.13.16 environment, compiler and
hardware. Host power and AC status were observed; background applications were not
independently verified. Ten pairs do not capture every thermal or systematic effect.
The historical 103.93 ratio retains its original Windows/WSL and timer
qualifications and is not pooled with this study.

Replay: `python scripts/run_matched_runtime.py replay --output
benchmarks/matched_runtime_2026-10-14`. Supplement: use Command B in
[KEY_NUMBERS](KEY_NUMBERS.md) for the exact final WP1–6 aggregation command, also
retained in the fresh verification JSON.

## WP2 — OpenMP efficiency diagnostics

This study tests scheduling, thread binding, case ordering and allocator settings
for the OpenMP runner. Each thread solves independent GH/AGH cases; OpenMP does not
parallelize a single placement algorithm or GPU inference. A comparison at the same
thread count supports a local improvement only when its paired interval lies wholly
above one. Worker wall-time accounting can show imbalance but cannot identify its
hardware cause.

The [plan](../benchmarks/openmp_diagnostics_2026-10-14/PLAN.md) uses the same mixed
32-case synthetic GH/AGH workload for every observation. All **201 settings × 30
rotated rounds = 6,030/6,030** observations completed with matching compact
projections and zero failed observations. Thread counts 1–16 cover all nine
schedule/chunk combinations at `cores/close`, and all placement/binding levels at
`dynamic/chunk1`; nine ordering/allocator settings at 1/8/16 threads complete the
factor-separable design. The full 585-setting interaction matrix is skipped, so
unmeasured interactions remain untested.

Core timing uses prepared native inputs, includes team creation and barriers, and
excludes parsing/output and warmup. There are 30 core samples per setting.
Complete-invocation statistics retain 29 samples per setting because the first round
includes excluded warmup. The 32 reference cases, evaluated outside timed samples,
pass the shared Python independent feasibility and bitwise objective checks. Every
timed batch matches a 64-bit FNV fingerprint of final x/z/q/u/w/y/v, objective
components and feasibility. This compact scope does not establish full rich-trace
parity.

| Core setting (`cores/close/dynamic/chunk1`, default allocator) | Median / IQR (s) | Speedup versus its own same-setting one-thread control, 95% CI | Efficiency |
|---|---:|---:|---:|
| Eight threads, unsorted | 0.250794 / 0.047142 | **4.0223 [3.7636, 4.4243]** | **50.28%** |
| Sixteen threads, unsorted | 0.221533 / 0.089694 | 4.5536 [3.9406, 5.0207] | 28.46% |
| Sixteen threads, sorted; fastest selected median | **0.220359 / 0.062718** | **4.7871 [4.5179, 5.2513]** | 29.92% |

Each speedup is a ratio of medians over 30 paired rounds, with 10,000 paired-round
percentile resamples and local seed 20261014. The sorted setting uses a sorted
one-thread baseline, so its 4.7871 cannot establish a sorting benefit relative to
the unsorted 4.5536. The direct same-team comparison is unsorted control / sorted
candidate = **1.0053 [0.9592, 1.1998]**; its interval includes one. All six ordering
comparisons, including both allocator policies at teams 1/8/16, have intervals
including one.

Restricting `MALLOC_ARENA_MAX=1` strongly slows the parallel workload: at eight
unsorted threads, default control / restricted candidate = **0.08390 [0.07616,
0.08836]**, with candidate median 2.989136 s. The direction is control time divided
by candidate time, so values below one indicate a slower candidate. Both sorted and
unsorted arena restrictions slow teams 8 and 16; both one-thread arena intervals
include one. Allocation counters are absent, so this sensitivity does not prove
allocation explains all baseline loss.

All one-factor comparisons, including negative and inconclusive results, remain in
[same_team_controls.csv](../benchmarks/openmp_diagnostics_2026-10-14/analysis/same_team_controls.csv).
Their descriptive unadjusted interval counts are:

| Factor | Comparisons | Interval wholly above one | Wholly below one | Includes one |
|---|---:|---:|---:|---:|
| Schedule | 96 | 0 | 50 | 46 |
| Chunk | 96 | 0 | 43 | 53 |
| Places | 32 | 0 | 2 | 30 |
| Bind | 32 | 1 | 0 | 31 |
| Ordering | 6 | 0 | 0 | 6 |
| Arena restriction | 6 | 0 | 4 | 2 |

These overlapping controls are dependent, and no multiplicity correction is applied.
The lone above-one binding interval is cores/spread versus cores/close at four
threads, 1.1377 [1.0703, 1.2643]; it remains exploratory. Selecting the fastest
median from 201 settings on the same data adds selection optimism. There is no
held-out confirmation or certified optimum. For this workload, unsorted
`cores/close/dynamic/chunk1` at 16 threads is a reasonable local elapsed-time
candidate; eight threads give higher observed efficiency of these two choices.
Confirm on an independent run/workload before general adoption.

### Efficiency accounting and unresolved causes

At the eight-thread baseline, the median wall-idle proxy is only 6.2262%, with
descriptive imbalance 4.6140% and other wall idle 1.0013%. Thus 50.28% efficiency is
not a measurement of approximately half the time idle. Per-round time accounting is
`Tp = T1/p + (max busy - mean busy) + remainder`; its median ideal contribution,
imbalance and signed remainder are 0.126097, 0.010638 and 0.104951 s. Signed
remainders, including negative values, are retained. Worker busy measures wall time
within jobs, including memory waits and descheduling, rather than CPU utilization.
Work-duration changes and other idle time do not distinguish
allocation/cache/frequency/contention from startup/barriers/scheduling or
instrumentation. The Amdahl-equivalent serial fraction, 14.1272% here, is a separate
response-time fit, not measured serial code or an additive component. Components are
calculated per round before medians; their medians need not sum.

| Causal hypothesis | Observation and limit |
|---|---|
| Load balance | Schedule/order interventions and per-worker wall times measured; imbalance remains descriptive. |
| Physical P/E cores and hyper-threading | Unresolved: WSL guest affinity/SMT topology cannot identify physical P/E cores or provide a physical SMT on/off intervention. |
| Memory bandwidth/cache | Unresolved: no workload hardware counters; `perf` executable unavailable. |
| Allocation | Arena sensitivity measured at selected teams; no allocation counters or unique contention attribution. |
| Frequency/throttling | Unresolved: frequency, governor and temperature observations unavailable in WSL; no time series. |
| Environment | Windows Balanced power plan observed before preparation; closed background apps unverified, with no fixed-frequency claim. |

The factor-separable design was chosen after the full interaction grid exceeded the
time budget. The [provenance record](#wp2-campaign-design-and-post-processing)
explains that change and the archive-only replay; neither changed the completed
timing observations.

Sources:
[analysis](../benchmarks/openmp_diagnostics_2026-10-14/analysis/extension.json),
[worker
statistics](../benchmarks/openmp_diagnostics_2026-10-14/analysis/thread_statistics.csv),
[decomposition](../benchmarks/openmp_diagnostics_2026-10-14/analysis/decomposition.csv),
[recovery](../benchmarks/openmp_diagnostics_2026-10-14/postprocessing_recovery.json),
[fresh replay
verification](../benchmarks/openmp_diagnostics_2026-10-14/analysis/archive_replay_verification.json).
Replay: `python scripts/analyze_openmp_extension.py --output
benchmarks/openmp_diagnostics_2026-10-14`. The command needs standard-library Python
and the shipped statistics helper; it verifies source/input/preparation/raw hashes
without a compiler, measured binary, optional solver license or scientific algorithm
rerun. The frozen WP2 PLAN records `run_openmp_diagnostics.py --analyze`, which
derives the producer's original 2,000-resample summary. The command above reproduces
this report's 10,000-resample extension statistics; the PLAN remains unchanged.

## WP3 — opt-in scale-aware Stage-2 objective agreement

This is a retrospective classification of retained decisions. It tests whether an
optional relative tolerance accepts roundoff-level objective disagreements while
still rejecting a materially incorrect objective. The original campaign's
absolute-only classifications remain unchanged.

The opt-in policy follows
[D-0105](EXTENSION_DECISIONS.md#d-0105--optional-scale-aware-stage-2-objective-agreement):
`|a-b| <= max(abs_tol, rel_tol * max(|a|,|b|))`. Absolute 1e-8 USD and relative zero
remain the defaults; selected relative 1e-12 is explicit. Solver-free replay
verifies all 2,027 historical archive entries, 40 Stage-1 reports, 1,850 frozen
reports and 850 extracted operational reports. No LP is rerun, and no historical
decision is repaired or reclassified in the old archive.

| Metric | Historical default | Opt-in relative 1e-12 | Denominator/scope |
|---|---:|---:|---|
| Scientifically usable operational attempts | 646 | 850 | 1,850 attempts from 37 accepted sources |
| Recovered feasibility | 256 | 344 | 1,344 independently infeasible frozen baselines |
| Usable cost pairs | 390 | 506 | Same-scenario frozen/adapted pairs, each usable |
| Paired summed C4+C5 reduction | 5.857419% | 5.957974% | Respective usable paired cohorts |

All 204/204 objective-only rejections are recovered; all 1,000 solver-infeasible
attempts remain unusable. Three rejected Stage-1 sources still skip 150 scenarios.
The original reduction uses 390 pairs from 33 contributing source grids; the
selected-policy reduction uses 506 pairs from 37 grids. Its source-grid cluster
bootstrap 95% interval is [5.745418%, 6.063490%], with local seed 20261014 and
10,000 resamples. Scenario-pair intervals are separately labeled sensitivity because
grid points within a fixed deployment are dependent. Changing the usable cohort
means the two pooled reductions are not a causal before/after improvement estimate.

All seven nonzero sweep coefficients from 1e-12 through 1e-6 recover the same 204
objective disagreements. Maximum recorded relative disagreement among the 204
rejections is 3.401745961429846e-16; the maximum across all 850 extracted reports is
1.1072651812353402e-15. A mutation with about 2e-6 relative objective error is
rejected under the selected 1e-12 policy. This finite dataset motivates a
configurable margin and does not guarantee future solver precision.

This study replays delivered evidence rather than running new Gurobi solves. The
fixed synthetic grid supplies conditional engineering evidence; it does not estimate
real-world probabilities. Cohorts still have three AGH seeds and one GH/P_DM source,
so there is no method ranking.

Source: [policy analysis](../benchmarks/stage2_policy_2026-10-14/analysis.json),
[policy report](../benchmarks/stage2_policy_2026-10-14/README.md). Replay: `python
scripts/replay_stage2_policy.py --output benchmarks/stage2_policy_2026-10-14`.

## WP4 — Stage-2 robustness and statistical scope

This campaign adds intermediate nominal loads and shared seeded inputs to the
earlier endpoint-heavy Stage-2 study. It measures feasibility recovery and modeled
operating costs while retaining rejected sources, infeasible LPs and cases with no
cost reduction.

All 144/144 planned Stage-1 workers completed in **2,871.436 s (47.86 minutes)**.
Four shapes (8x4x4, 16x4x4, 32x4x4, 16x8x8), four loads (200, 2,000, 20,000,
100,000), and instance seeds 11/23/37 supply 48 prepared inputs, each shared by
GH/AGH/ P_DM. AGH's algorithm seed is separately fixed at 37. The assumed uniform
[0.9,1.1] instance variation follows
[D-0106](EXTENSION_DECISIONS.md#d-0106--distinct-synthetic-instance-seeds-and-shared-cohorts).
It uses a separate factory and does not represent author data. HiGHS executes in WSL
Python 3.13.16 with 20-second Stage-1/Stage-2 limits; Gurobi is unavailable under
the applicable WSL license. Stage 2 uses opt-in relative 1e-12 and absolute 1e-8
USD; Stage-1 P_DM acceptance keeps its unchanged absolute-only policy.

Of 144 sources, **136 were accepted** and each attempted the original 50-scenario
grid: **6,800 LPs**, with **3,246 scientifically usable decisions** and **3,554 LPs
classified as infeasible by the solver**. The retained solver status is optimal for
all 3,246 successes and infeasible for all 3,554 unusable LPs; solver status and
independent acceptance remain distinct evidence. The eight rejected sources are all
time-limited P_DM incumbents (`feasible`, `maxTimeLimit`, incumbent present), one at
load 20,000 and seven at 100,000. Their retained C1–C5 sums disagree with solver
objectives by 1.490116e-8 to 5.960464e-8 USD, exceeding the unchanged Stage-1
absolute 1e-8 floor. The original acceptance policy is retained: each rejected
source skips 50 scenarios, for **400 skipped LPs** out of the 7,200 maximum.
Independent replay reproduced all source reports. Reconstructing the eight rejected
reports with their recorded tolerances found `is_feasible=True` and zero constraint
violations for each; all eight failed the unchanged default objective comparison.
They are objective-only rejections, and remain unusable Stage-1 sources under the
approved acceptance policy.

| Nominal load | Accepted sources / 36 | Usable / attempted LPs | Recovered / frozen failures | Usable cost pairs / contributing input clusters | Paired summed C4+C5 reduction, cluster-bootstrap 95% CI |
|---|---:|---:|---:|---:|---:|
| 200 | 36/36 | 870/1,800 | 330/1,260 (26.1905%) | 540 / 12 | **4.945490% [4.640838%, 5.177031%]** |
| 2,000 | 36/36 | 820/1,800 | 280/1,260 (22.2222%) | 540 / 12 | **4.923512% [4.628603%, 5.146725%]** |
| 20,000 | 35/36 | 930/1,750 | 400/1,220 (32.7869%) | 530 / 12 | **5.156249% [4.726027%, 5.526150%]** |
| 100,000 | 29/36 | 626/1,450 | 311/1,135 (27.4009%) | 315 / 12 | **5.433509% [4.983066%, 5.865710%]** |

The reduction is `(sum frozen - sum adapted) / sum frozen` over identical
scientifically usable frozen/adapted pairs. Frozen-infeasible baselines receive no
savings. Each interval resamples the twelve contributing shared-input paired
clusters, keeping all contributing method pairs from an input together, with 10,000
draws and seed 20261014. It does not resample every accepted source or an
independently copied method grid. Scenario-pair intervals are separately labeled
sensitivity. These conditional deterministic-grid figures are not real-world
probabilities, and changed cohorts across loads do not establish a causal effect of
increasing load. The per-load `newly_usable` counts are 0/0/229/375: the opt-in
Stage-2 objective policy classifies **604 additional usable results**, or 3,246
versus 2,642 under the old absolute-only policy on the same 6,800 attempted LPs.
This differs from **1,321 recovered decisions out of 4,875 frozen-routing
failures**. No recorded decision changes, and the unchanged Stage-1 P_DM policy is
not relaxed.

### Comparing methods on matched inputs

All methods receive identical input hashes, but Stage-1 acceptance differs. The
accepted-source intersection is **40/48 input identities**, with per-load counts
12/12, 12/12, 11/12 and 5/12. The pooled table above includes accepted unmatched
cells; only the separate matched-method analysis uses the intersection:

| Load | Accepted input intersection | GH usable / attempted | AGH usable / attempted | P_DM usable / attempted |
|---|---:|---:|---:|---:|
| 200 | 12/12 | 300/600 | 300/600 | 270/600 |
| 2,000 | 12/12 | 300/600 | 300/600 | 220/600 |
| 20,000 | 11/12 | 270/550 | 270/550 | 330/550 |
| 100,000 | 5/12 | 98/250 | 94/250 | 168/250 |

Matched input does not make deployments, unmet-demand caps, feasible cost-pair sets
or recovery denominators identical. These counts support conditional operational
summaries rather than a general method ranking. In particular, matched P_DM paired
cost reductions are approximately zero, retaining tiny signed roundoff values
(including -1.288558e-16 as a fraction at load 2,000). Method-specific recovery,
pair counts and intervals remain in the analysis; they are not replaced by pooled
denominators.

### Diagnosing the original infeasible LPs

All **1,000/1,000** original solver-infeasible records have at least one retained
sufficient algebraic contradiction; zero remain unexplained by this diagnostic.
Error-SLO certificates occur in 940 records and compute-capacity certificates in
120, with 60 overlaps: 880 error-only, 60 compute-only and 60 with both. At load
200, all 480 records have error certificates. At load 100,000, all 520 have a
certificate, with 460 error and 120 compute occurrences. Each arrival factor through
1.05 has 94 records; factors 1.1/1.15/1.2 have 114 each, including 40 compute
occurrences per factor. Demand balance and the retained unmet-demand cap support
mandatory service lower bounds; they are not independent exclusive causes. Margins
and supporting constraints are retained. These certificates do not identify a unique
irreducible infeasible subsystem (IIS) or rule out other bottlenecks, and no
historical LP/classification is altered.

Both the original and final archive-only replays passed, reproducing **144 source
reports, 6,800 frozen reports and 3,246 extracted operational reports**. The
[provenance appendix](#wp4-archive-transport-and-replay) records the four-part
archive and verifies its 7,233 original entry hashes.

Sources: [analysis](../benchmarks/stage2_robustness_2026-10-14/analysis.json),
[source results](../benchmarks/stage2_robustness_2026-10-14/source_results.json),
[LP attempts](../benchmarks/stage2_robustness_2026-10-14/attempts.csv), [historical
certificates](../benchmarks/stage2_robustness_2026-10-14/historical_infeasibility.json),
[initial independent
replay](../benchmarks/stage2_robustness_2026-10-14/replay_analysis.json), [multipart
verification](../benchmarks/stage2_robustness_2026-10-14/postprocessing_verification.json),
[fresh archive-only
replay](../benchmarks/stage2_robustness_2026-10-14/archive_replay_verification.json),
[public artifact
inventory](../benchmarks/stage2_robustness_2026-10-14/artifact_hashes.json),
[plan](../benchmarks/stage2_robustness_2026-10-14/PLAN.md). Replay command (original
and fresh archive-only verification passed): `python scripts/run_stage2_extension.py
--output benchmarks/stage2_robustness_2026-10-14 --replay`.

## WP5 — native scaling with instance variability

This study measures how native runtime varies with query count and the model/tier
menu across several seeded synthetic instances. The fitted exponents describe the
tested range; multiple instances reveal input variation that repeated timing of one
fixture cannot show.

All **90/90 native method/instance points** have **three measurements each, 270/270
verified samples**, with zero retained failed worker attempts. All 90 points are
independently feasible. Full Python algorithm/transition parity passes for all
**20/20** planned small points (GH/AGH, I=16/32, 4x4, five input seeds). The other
70 points receive unchanged final-decision feasibility and bitwise C1–C5 validation
without a full Python trace or an inferred Python runtime ratio.

The [plan](../benchmarks/instance_scaling_2026-10-14/PLAN.md) measures six query
levels **16, 32, 64, 128, 256, 384** with J=K=4, and four menus **4x4, 8x4, 8x8,
12x12** with I=64 (products 16/32/64/144). Instance seeds **11/23/37/41/53** are
separate from fixed AGH seed 37. Each cell uses the explicit uniform [0.9,1.1]
synthetic variation, load 200 and beta 0.8; no coefficient is selected using a solve
outcome. Shared 64x4x4 cells are measured once and reused by the two separate
analyses: **45 distinct inputs**, not 50.

Each point has one excluded external warm subprocess. Measured workers are fresh
single-solve processes without same-process warmup. Core timing covers the complete
public native solve, including traces and validation, and excludes startup, parsing,
projection/output and destruction. Process durations are separate. Fresh allocator
state does not remove machine-wide cache or thermal history. Source, binary, PLAN
and input fingerprints remain frozen; the source ZIP contains 93 verified entries,
SHA-256 `d40f62f15dc6d967d4ab6bc098af6e6da6062a63121dc073158d1c7b43b17514`.

| Fit | Complete / feasible method-instance points | Exponent, cluster-bootstrap 95% CI | Log-space R² |
|---|---:|---:|---:|
| Query count I, GH | 30/30, all feasible | **1.6615 [1.6402, 1.6798]** | **0.9903** |
| Query count I, AGH | 30/30, all feasible | **1.9402 [1.9254, 1.9600]** | **0.9975** |
| Menu product J*K, GH | 20/20, all feasible | **0.9455 [0.9185, 0.9707]** | **0.9928** |
| Menu product J*K, AGH | 20/20, all feasible | **1.4461 [1.4065, 1.4998]** | **0.9694** |

OLS fits `log(core time) = intercept + exponent * log(size)` over each instance's
median of three native repeats. A percentile bootstrap resamples the **five complete
instance-seed clusters**, retaining all size observations within each selected seed,
with **10,000 draws and seed 20261014**. Per-instance medians are held fixed during
cluster resampling; there is **no temporal-repeat bootstrap**. Repeats characterize
call variability rather than supply new independent instances. The shared source/RNG
seed across sizes motivates the cluster unit; five clusters still limit interval
precision.

All four R² values exceed the declared 0.8 descriptive-fit threshold. This does not
establish asymptotic complexity or justify extrapolation. The menu product is a
coarse descriptor across four different aspect ratios and structural branches; the
data do not isolate J from K or show that only their product matters. Every fitted
point's median/IQR, status, validation scope and raw duration remain in the retained
JSON/CSV, with PNG/SVG observed-range figures.

The campaign took **1,649.006364 s (27.48 minutes)**, including one recovered
checkpoint persistence interruption. Zero workers failed and no observation was
edited, discarded, duplicated or imputed. Final replay verified **1,337 files and
360 independent native validations**: 90 excluded warm points plus 270 measured
samples. The [provenance record](#wp5-checkpoint-recovery-and-plot-provenance)
separates that recovery and later axis-label edits from measured results.

Sources:
[analysis](../benchmarks/instance_scaling_2026-10-14/analysis/analysis.json),
[instance
medians/IQR](../benchmarks/instance_scaling_2026-10-14/analysis/instance_timings.csv),
[fit report/figures](../benchmarks/instance_scaling_2026-10-14/analysis/report.md),
[execution
summary](../benchmarks/instance_scaling_2026-10-14/execution_summary.json),
[checkpoint
recovery](../benchmarks/instance_scaling_2026-10-14/checkpoint_recovery.json),
[initial
replay](../benchmarks/instance_scaling_2026-10-14/replay_verification.json), [plot
presentation
provenance](../benchmarks/instance_scaling_2026-10-14/plot_presentation_verification.json),
[label provenance
clarification](../benchmarks/instance_scaling_2026-10-14/label_provenance_clarification.json),
[final
replay](../benchmarks/instance_scaling_2026-10-14/final_replay_verification.json).
Replay command (verification passed): `python scripts/run_instance_scaling.py replay
--output benchmarks/instance_scaling_2026-10-14`.

## WP6 — solver quality at longer limits

This study compares AGH with HiGHS incumbents at longer MILP time limits. Acceptance
still requires the original normalization, independent feasibility checks and
default Stage-1 objective agreement. Solver termination status alone does not make
an incumbent scientifically usable.

Four coherent synthetic V2 inputs are 10x10x10 at loads 1/200/100,000 and 6x6x10 at
load 100,000. Each receives GH/AGH once and fresh independent cold HiGHS solves at
**20/120/600 s**; incumbents are not carried between limits. The same retained input
supplies every method/limit cell. All **20/20 unique measured jobs completed**, with
20 measured worker calls, zero retries/failures/missing results, and **18/20
accepted results**: eight heuristics and ten of twelve HiGHS incumbents. Three
completed warmups are excluded, giving 23 completed worker reports. All twelve HiGHS
runs report an incumbent with `feasible`/`maxTimeLimit`, not an optimum. Gurobi is
skipped because the WSL license is restricted and the academic license is
incompatible with that host; the requested three-way AGH/HiGHS/Gurobi ordering
remains unanswered.

| Input | GH cost USD | AGH cost USD | HiGHS 20 s | HiGHS 120 s | HiGHS 600 s |
|---|---:|---:|---:|---:|---:|
| 10x10x10, load 1 | 1,151.055 | 1,150.055 | 1,274.759 | 915.549 | 915.549 |
| 10x10x10, load 200 | 228,409.055 | 228,408.055 | 332,096.378 | 118,464.126† | 108,099.470 |
| 10x10x10, load 100,000 | 114,200,009.223 | 114,200,008.223 | 144,835,014.405 | 54,298,973.597 | 54,298,973.597 |
| 6x6x10, load 100,000 | 75,840,009.137 | 75,840,008.137 | 56,407,996.571 | 30,720,031.651 | 30,720,021.382† |

Costs are rounded for presentation; complete native/independent values are retained
in JSON/CSV. **† Rejected native incumbent, diagnostic only:** no usable objective
is assigned and the cell is excluded from quality ordering. Both rejected objectives
agree with their independent recomputation under the unchanged absolute policy;
rejection concerns independent constraints. At 10x10x10/load200/120 s, four
violations cover demand balance, error SLO and two routing-admission bounds. At
6x6x10/load100,000/600 s, one error-SLO violation occurs at `q_long_0004`, with raw
slack -4.130979e-9 and configured threshold 1.040000e-12. These small residuals are
not repaired or accepted by relaxing defaults. Unlike WP4's eight objective-only
source rejections, these two rows are independently infeasible under the approved
Stage-1 policy.

| Limit | Accepted AGH/HiGHS pairs / planned | Median AGH / accepted HiGHS cost | Descriptive median bootstrap 95% interval |
|---|---:|---:|---:|
| 20 s | 4/4 | **0.845329** | **[0.687776, 1.344490]** |
| 120 s | 3/4 | **2.103171** | **[1.256138, 2.468748]** |
| 600 s | 3/4 | **2.103171** | **[1.256138, 2.112943]** |

This ratio divides AGH cost by the same-input accepted HiGHS incumbent cost: below
one favors AGH. At 20 s AGH has lower cost in three of four accepted case pairs; at
120 and 600 s HiGHS has lower cost in all three accepted pairs. The 120/600 cohorts
omit different rejected cases. A local ordering reversal is observed on two common
inputs: 10x10x10 at loads 1 and 100,000. These cases do not establish a general
ranking or a comparison with Gurobi. Intervals use the approved helper's **5,000
accepted-case resamples, seed 113**, over a four-case convenience cohort, rather
than the other packages' seed/grid units. They are descriptive, with no population
inference. Equal displayed 120/600 costs do not imply unique placements or proven
optimality.

### Bounds and gaps

Retained best bounds range from 1.649791 to 12.159294 USD, far below incumbents.
Derived normalized gaps range from **0.986719115 to 0.999999981**, leaving weak
optimality certificates even at 600 s. The approved APPSI adapter does not expose
native MIPGap: `native_gap` is unavailable, not zero, and no derived value is
labeled native. `normalized_gap` is separately
`abs(incumbent-bound)/abs(incumbent)`, zero for identical values and unavailable for
missing values or zero incumbent with nonzero difference. Rejected
incumbents/bounds/gaps remain diagnostic only. Solver bounds concern the constructed
MILP and do not establish scientific transcription correctness. No time-limited
result is called optimal.

The campaign took **3,225.756829929 s (53.76 minutes)**, including excluded warmups
and evidence I/O. Both archive-only replay proofs passed. The final proof verified
**149 archive entries, 75 frozen sources, five input records and 23 completed
reports**, reproducing exact analysis/CSV/report bytes and all 18/20 accepted
measured results without optional solver dependencies. See [portable replay and
rendering](#wp6-portable-replay-and-rendering) for the separate post-processing
observations.

Sources: [analysis](../benchmarks/solver_quality_2026-10-14/analysis.json), [all
rows/bounds](../benchmarks/solver_quality_2026-10-14/REPORT.md),
[execution](../benchmarks/solver_quality_2026-10-14/execution_summary.json),
[publication
verification](../benchmarks/solver_quality_2026-10-14/postprocessing_verification.json),
[initial fresh replay
verification](../benchmarks/solver_quality_2026-10-14/archive_replay_verification.json),
[final current-launcher
replay](../benchmarks/solver_quality_2026-10-14/archive_replay_final_verification.json).
Replay: `python scripts/extension_solver_quality.py summarize --output
benchmarks/solver_quality_2026-10-14`.

## WP7 — optional Python memory work

This optional study was skipped. The extension adds no allocation or resident memory
profile, lean-trace implementation or measured memory improvement. The historical
`MemoryError` evidence retains its original scope.

## Interpretation and remaining limits

The matched study supports a local performance advantage for the C++ implementation
under both timer boundaries. OpenMP diagnostics show allocator sensitivity but do
not establish a sorting benefit or isolate the hardware causes of efficiency loss.
The retrospective Stage-2 replay accepts all 204 observed objective-only rejections
under the explicit relative option while rejecting the tested material mutation. The
new campaign and scaling fits add conditional evidence across several loads and
synthetic inputs. Longer HiGHS limits change accepted-case cost ordering, while weak
bounds and two independently rejected incumbents limit the solver comparison.

These are synthetic CPU engineering results. They do not establish a pure language
effect, GPU inference performance, actual cloud savings, heuristic optimality or
replication of the paper's tables. Author calibration data, physical P/E-core, cache
and throttling measurements, the unavailable Gurobi comparison and optional memory
profiling remain outside the completed evidence.

## Provenance and verification

This appendix records the source snapshots, recovery steps and publication checks
behind the results. Replay and packaging durations below are unmeasured
post-processing; they are excluded from every algorithm and invocation sample.
Historical hashes and classifications retain their original scope.

### WP1 source snapshot and supplemental analysis

The [retained initial supplemental
JSON](../benchmarks/matched_runtime_2026-10-14/extension_numbers_initial.json)
contains all 24 boundary rows and the earlier WP3 analysis. Its ten focused tests
passed, and the historical [post-processing
verification](extension_summary_verification.json) establishes equal initial JSON
values/statistics under WSL Python 3.13.16 and Windows Python 3.14.3. Its exact
retained bytes match the recorded Windows SHA-256; only LF/CRLF newline encoding
differs from WSL. The 25.429 s Windows processing time belongs to this initial
artifact and is separate from all timed solves
([environment](EXTENSION_ENVIRONMENT.md), [proof
scope](extension_summary_verification_scope.json)). The current [supplemental
JSON](extension_numbers.json) now includes final WP2–6 and has its own [fresh
verification](extension_summary_final_verification.json): Windows Python 3.14.3 in
30.57474 s and WSL Python 3.13.16 in 48.86380 s, both exit 0, equal complete JSON
values and only CRLF/LF encoding differences. The delivered LF SHA-256 is
`010286b1ac5f4f723a13e800920b16569018ba0e7bccf7be5768500523685c8c`; 480 WP1 samples,
24 ratio rows, the frozen source ZIP and final supplied WP2–6 analysis paths/hashes
are included. No solve runs during aggregation. Historical observed fields, argv and
hashes remain unchanged; the old proof certifies only its retained initial output.
The initial JSON is placed as a supplemental benchmark artifact outside WP1's
original inventory, preserving its exact raw bytes through Git/export rather than
normalizing its historical Windows newlines. This transport placement does not
change a measured artifact or verification observation. Its default source
verification uses the separately added frozen `source_snapshot.zip`, with all 91
entries checked against WP1's prepared source hashes. The supplemental JSON records
that ZIP's provenance SHA-256 outside the unchanged original WP1 manifest, so later
opt-in Stage-2 source changes do not invalidate fresh-clone statistical replay.

The initial duration estimate was 3–12 minutes with a 30-minute allowance. An
excluded pilot forecast about 29.8 minutes; the completed run took about 22 minutes,
within the three-hour cutoff. The source ZIP contains 91 verified entries and has
SHA-256 `10b741781c4c29bc9af0bdd66edaa6408060d8644b6d1297486d149653bea55d`.

### WP2 campaign design and post-processing

The initial full-matrix forecast was 6.94 h, revised to 5.07 h after the pilot. Both
exceeded the three-hour limit. The 201-setting forecast was 1.75 h, using the
excluded pilot, 50% efficiency, serial cap, invocation overhead and per-setting
warmup. The factor-separable campaign therefore replaced the full matrix. Native WSL
timing completed all 30 rounds before prolonged drvfs I/O delayed unmeasured
post-processing. The producer was interrupted during final artifact inventory, after
analysis and evidence packaging. Windows Python 3.14.3 on NTFS completed metadata
and statistical replay without changing measured jobs, raw timings or scientific
inputs. A fresh archive-only replay, with binary and extracted raw/golden files
initially absent, automatically verifies/unpacks the archive and reproduces exact
derived-artifact SHA-256 values in 64.879 s. That processing time is outside all
performance samples.

Sources: [recovery
record](../benchmarks/openmp_diagnostics_2026-10-14/postprocessing_recovery.json)
and [archive-only
replay](../benchmarks/openmp_diagnostics_2026-10-14/analysis/archive_replay_verification.json).

### WP4 archive transport and replay

All four planned shapes ran, so the smaller-shape fallback was unused. The observed
47.86 minutes was below the 60–90-minute allowance and three-hour coordinator limit.
Initial solver-free independent replay **passes with exit 0**, reproducing **144
source reports, 6,800 frozen reports and 3,246 extracted operational reports**.
Public archive transport is repackaged into four parts after timing completion, with
byte sizes 60,115,865 / 57,409,619 / 60,377,639 / 5,050,821, all below 80 MB. This
is post-processing only: the original 180,575,293-byte completed ZIP is preserved
privately, SHA-256
`80c6a415e33954f44a76a8017d46dd274a38550682f6a6d4b460d27927be46fb`, and the frozen
`scientific-source-snapshot.zip` preserves the measured producer. Multipart
verification confirms all **7,233 original path/byte-count/SHA-256 triples**
unchanged, equal analysis JSON values and identical ASTs for eight scientific
producer functions. The original public ZIP is removed only after verified parts and
the private backup exist. Windows Python 3.14.3 spends 21.1857 s on this unmeasured
transport/report processing, outside campaign timing. No timing, scientific input or
arithmetic changes. The final fresh archive-only replay also **passes**, verifying
all **7,233 entries** and the measured source ZIP SHA-256, independently reproducing
**144 source / 6,800 frozen / 3,246 operational reports** and equal analysis JSON
values. It needs no timed binary or solver. The **246.1337 s** Windows Python 3.14.3
replay time is unmeasured post-processing, separate from the 2,871.436 s campaign
and 21.1857 s archival transport check. The final inventory retains 22 public
artifacts.

Sources: [multipart
verification](../benchmarks/stage2_robustness_2026-10-14/postprocessing_verification.json),
[archive-only
replay](../benchmarks/stage2_robustness_2026-10-14/archive_replay_verification.json)
and [public
inventory](../benchmarks/stage2_robustness_2026-10-14/artifact_hashes.json).

### WP5 checkpoint recovery and plot provenance

Total elapsed time is **1,649.006364 s (27.48 minutes)**, including one
checkpoint-persistence pause, within the 15–45-minute planning range and original
three-hour budget. A native Windows live read of `status.json` holds the NTFS
destination during WSL atomic replacement, causing `PermissionError` after a worker
completes. The persisted checkpoint has 218 samples; the fully written producer
temporary checkpoint has 219 accepted samples. Recovery verifies every retained
compressed/uncompressed stdout and stderr hash, warm bitwise final projection,
unchanged source/binary/PLAN/input fingerprints, all 218 prior records and other
checkpoint fields, plus independent validation of the one added record. It promotes
the exact complete producer temporary bytes, with both original checkpoints backed
up privately. No decision/time is edited and no observation discarded, duplicated,
repaired or imputed. Resume starts from 219 samples with 9,420 s remaining,
preserving the initial wall budget; subsequent monitoring uses subprocess stdout.
This is one coordinator persistence interruption, distinct from the zero worker
failures. No measured script, scientific arithmetic or default changes. Initial
replay **passes**, verifying **1,335 files and 360 independent native validations**
(90 excluded warm points plus 270 measured samples), reproducing analysis JSON
values in **72.6157 s** of unmeasured Windows Python 3.14.3 processing.

Visual QA identifies overlapping minor labels on log x-axes. A three-line
post-timing presentation change sets the exact tested major levels and hides minor
labels. The frozen 93-entry measured source ZIP, scientific/timing data, status and
analysis JSON SHA-256 remain unchanged. The closing audit confirms literal AST
equality for every helper function except `analyze`, using explicit UTF-8 parsing
for both the frozen and current source. An earlier encoding-unspecified comparison
falsely suggested display-label changes in `derived_analysis`; both retained sources
contain the same `R²` strings. The separate [label provenance
clarification](../benchmarks/instance_scaling_2026-10-14/label_provenance_clarification.json)
records that discarded comparison and confirms the original plot proof, which is
retained unchanged. Measured and renderer helper hashes are recorded separately.
Plot regeneration takes 4.4613 s of unmeasured processing. The **final replay
passes**, verifying **1,337 files and the same 360 independent validations** in
**72.26584 s**, without compiler, timed binary or solver execution. CSV/JSON
numerical results remain unchanged; The plot edits leave the measured algorithms
unchanged.

Sources: [checkpoint
recovery](../benchmarks/instance_scaling_2026-10-14/checkpoint_recovery.json),
[initial
replay](../benchmarks/instance_scaling_2026-10-14/replay_verification.json), [plot
verification](../benchmarks/instance_scaling_2026-10-14/plot_presentation_verification.json),
[label
clarification](../benchmarks/instance_scaling_2026-10-14/label_provenance_clarification.json)
and [final
replay](../benchmarks/instance_scaling_2026-10-14/final_replay_verification.json).

### WP6 portable replay and rendering

The WSL campaign takes **3,225.756829929 s (53.76 minutes)**, including excluded
warmups and evidence I/O, versus the predeclared **5,110 s (85.17-minute)**
forecast, below three hours. The full available HiGHS matrix runs; Gurobi's explicit
skip limits the ordering question. Portable archive publication takes **17.0403 s**
of unmeasured Windows Python 3.14.3 processing. Source/input bytes and scientific
summary values remain unchanged; only declared metadata SHA pointers are updated for
portable transport, with original provenance retained.

Fresh archive-only replay **passes, exit 0**, verifying **149 archive entries**,
frozen source/input hashes and every retained attempt, reproducing exact
`analysis.json`, `runs.csv` and `REPORT.md` bytes. It independently validates **23
completed reports (20 measured + three warmups)** and reproduces **18/20 accepted
measured results**. A fresh Windows Python 3.14.3 environment created without pip
has Pyomo/HiGHS/Gurobi/Matplotlib/pip absent in both parent and frozen-source child;
no current scientific source, compiler, timed binary or solver is used. Numerical
replay takes **4.8376 s**, total environment/replay proof **5.9576 s**, entirely
outside every measured solve. Standard-library Python >=3.13 suffices for numerical
replay; optional plots need Matplotlib.

Post-timing visual QA corrects crowded minor log-axis labels through a separate
opt-in current renderer: major ticks are exactly 20/120/600 and minor labels are
hidden. It first verifies the frozen numerical summary; measured source, archive,
prior replay evidence and analysis/CSV/report hashes stay unchanged. Only current
`plot_results`/CLI dispatch AST changes are allowed, with measured and renderer
hashes separately retained. No solve/algorithm executes. This presentation refresh
does not modify the frozen renderer or measurement scope ([plot
provenance](../benchmarks/solver_quality_2026-10-14/plot_presentation_verification.json)).

The **final current-launcher archive-only replay also passes**, using a second fresh
Windows Python 3.14.3 environment without pip or optional packages in either parent
or frozen-source child. It starts without unpacked evidence, current `src` or a
measured binary, verifies **149 archive entries, 75 frozen source files and five
input records**, and reproduces exact analysis/CSV/report bytes. It again
independently validates **23 completed reports** and accepts **18/20 measured
results**, with zero retries, failures or missing measured rows. Numerical replay
takes **18.477553 s**, and the full proof takes **20.110521 s**, outside all
measured solves. The initial 4.8376 s replay proof is preserved byte for byte; the
two processing durations are distinct execution observations and provide no
controlled performance comparison ([final
replay](../benchmarks/solver_quality_2026-10-14/archive_replay_final_verification.json)).

Sources: [publication
verification](../benchmarks/solver_quality_2026-10-14/postprocessing_verification.json),
[initial
replay](../benchmarks/solver_quality_2026-10-14/archive_replay_verification.json)
and [final
replay](../benchmarks/solver_quality_2026-10-14/archive_replay_final_verification.json).

### WP8 — delivery and final verification

The checkpoint uses the MIT license, and [CITATION.cff](../CITATION.cff) retains
software/scientific attribution. The final aggregate has a separate cross-platform
proof. All **seven pre-manifest checks passed** under WSL Python 3.13.16 with
`PYTHONPATH=src` in the publication checkout at that time. Their immutable
[proof](extension_release_preflight.json) records actual argv, exit 0, durations and
log hashes:

| Pre-manifest check | Verified result | Outer elapsed time |
|---|---|---:|
| Python regression | **1,131 tests, zero skips**; unittest time 147.301 s | 150.6005 s |
| Native release | Serial/OpenMP build and test targets pass | 15.8426 s |
| Native ASAN/UBSAN | Core and campaign tests pass | 30.5101 s |
| Live/frozen scientific parity | **63/63** cases | 4.1725 s |
| OpenMP parity | **90 comparisons**, ten independently checked Python cases | 3.8691 s |
| Stage-1 example | Pass | 1.4007 s |
| Stage-2 example | Pass | 1.8357 s |

Exact repository-root commands from that proof (Python is the WSL 3.13.16
environment and `PYTHONPATH=src`):

```sh
python -B -m unittest discover -s tests -q
make -C cpp -j4 all test openmp campaign-test
make -C cpp -j4 MODE=sanitize test campaign-test
python -B scripts/check_cpp_parity.py --frozen --output ./results/final_extension_checks/preflight_verified/parity.json
python -B scripts/check_openmp_campaign.py --output ./results/final_extension_checks/preflight_verified/openmp
python -B examples/stage1_quickstart.py
python -B examples/stage2_quickstart.py
```

These are **historical pre-manifest passes**, outside experiment timers. At
checkpoint `543ad4e`, the required repetition after the single manifest generation
also passed: **1,131 Python tests / zero skips**, native release and ASAN/UBSAN,
**63/63** live/frozen parity, **90** OpenMP comparisons, both examples and `python
scripts/prepare_release.py --check` for **3,568 files**. Python unittest took
181.611 s in that distinct closing run. The actual post-generation logs and
canonical handoff remain in the development workspace; the hashed public preflight
proof retains its earlier scope and is not rewritten.

A later publication update integrated the extension into the principal development
folder, preserving its editorial publication mappings and canonical model documents.
That integration's documentation update extended the publication allowlist to
3,569 files without changing experimental observations, source snapshots or
numerical defaults. The subsequently supplied PDF and PowerPoint presentation
are now available in [presentations/](../presentations/README.md), with their
source checkpoint, integrity hashes and known delivery issues documented there.

These records describe the numerical checkpoint and its later publication. They do
not certify subsequently edited documentation or a current release manifest. No
experiment or regression was rerun for this prose revision.
