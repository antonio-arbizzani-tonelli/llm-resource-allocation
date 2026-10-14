# Presentation draft

This is an English narrative and source plan for a future presentation. It does
not create or revise slides, HTML, PDF or PowerPoint files. The number of slides
should follow the audience and speaking time. The sections below describe
proposed slides that can be combined or expanded without changing their claims.

The main story is the allocation problem, the model, Python/Pyomo, C++20,
cross-language verification, runtime measurements and OpenMP. Detailed Stage-2
evaluations belong in an optional appendix. MPI remains future work.

## Source snapshot and existing material

All repository paths and selectors in this draft refer to public commit
[`80a9625ab62a3c5c70ede7a9dae97a61158e250a`](https://github.com/antonio-arbizzani-tonelli/llm-resource-allocation/commit/80a9625ab62a3c5c70ede7a9dae97a61158e250a),
abbreviated **80a9625** below. Its scientific source and numerical artifacts match
the extension checkpoint
[`543ad4e640100a4c2a69febf17fe885bd452861e`](https://github.com/antonio-arbizzani-tonelli/llm-resource-allocation/commit/543ad4e640100a4c2a69febf17fe885bd452861e).
The later commit adds presentation and publication documentation. A source citation
on a future slide should include the artifact path, selector and this commit.
Relative links below point to the retained artifacts in the delivered repository.

The existing local English HTML teaching deck, `docs/presentation/index.html`,
contains thirty slides dated October 9 in `build_manifest.json`. Its model
diagrams, distinction between planning and operation, and independent-validation
explanation remain useful starting points. Its chronology needs rebuilding:
C++ and MPI appear as later phases, Stage 2 is mainly paper theory and author
results, and its unit discussion preserves older literal arithmetic. Those
statements cannot describe the current implementation. The earlier Italian HTML
draft under `docs/presentation_drafts/html/` has the same historical limitation.
Neither directory is part of the public presentation deliverable.

Keep the technical concepts and attribution. Replace the long algorithm lecture
with the shorter narrative below, using current coherent-unit descriptions and
retained public evidence. An introductory portfolio presentation does not need
the full M1–M3 derivation or every local-search transition. Preserve those details
in technical notes or appendices. At the start of this review, no project
PPTX/PDF was found among the historical local presentation files. HTML/PDF
draft work created later in the session remains local and is excluded from
publication. The published deliverable is this Markdown narrative and source
plan, together with the brief and design prompts.

## Proposed main story

### Allocation under service constraints

**Essential on-slide text**

> LLM Resource Allocation
>
> Antonio Arbizzani Tonelli
>
> Choose model deployments and route demand across heterogeneous GPU options
> while meeting budget, capacity and service-level constraints.
>
> This project implements and verifies the allocation software, then measures
> its CPU runtime.

**Recommended visual:** a simple conceptual diagram connecting query demand,
an allocator and model/GPU alternatives. Show cost and service constraints beside
the allocator. Label the GPU resources as modeled. Avoid cluster photographs
that imply an experimental GPU installation.

**Source at 80a9625:** [MODEL.md](MODEL.md), opening and “Stage 1: choose a
deployment”. Attribute the formulation and GH/AGH to Cheng and Nguyen,
[paper v2](https://arxiv.org/abs/2604.07472v2), with
[v1](https://arxiv.org/abs/2604.07472v1) as the secondary source. There is no
numerical project claim on this slide.

### The allocation model

**Essential on-slide text**

> Stage 1 chooses deployments, parallel configurations and nominal routing.
>
> The objective combines GPU rental, storage, delay and unmet-demand costs.
>
> Constraints enforce resource limits, budget and service levels.
>
> Stage 2 keeps deployment fixed and adapts routing to a supplied scenario.

Add a short visible caption: **GPU capacity and latency are model inputs. All
runtime experiments execute allocation software on CPU.**

**Recommended visual:** one planning diagram with the model's input categories,
decisions and accepted output. A small continuation can show fixed deployment
feeding operational routing. Explain only the model features needed to understand
the implementation and experiments. Keep full variable tables in the appendix.

**Source at 80a9625:** [MODEL.md](MODEL.md), “Stage 1”, “Physical units and explicit
assumptions” and “Stage 2”. The explicit operational LP comes from paper v1
Eq. (12a)–(12f). Coherent KV, resident-data and period-cost conventions are
documented project choices in [UNITS.md](UNITS.md), not conversion factors
claimed to have been printed in the paper. Historical literal fixtures remain
separately identified.

### Python and Pyomo as the scientific reference

**Essential on-slide text**

> Python implements the reference algorithms and independent scientific checks.
>
> Pyomo builds the Stage-1 MILP and Stage-2 LP for a configured solver.
>
> Extracted decisions become plain domain data before validation.
>
> Completion, constraint feasibility, objective agreement and solver termination
> remain separate evidence.

**Recommended visual:** a readable software flow from validated inputs through
algorithm or model/solver, plain decision state, independent checks and accepted
result. Show the solver boundary explicitly. Pyomo constructs a model and a
backend solves it. Avoid representing GH/AGH orchestration as Pyomo optimization.

**Source at 80a9625:** [ARCHITECTURE.md](ARCHITECTURE.md), “From problem data to
accepted decisions”; `src/llm_resource_allocation/optimization/pyomo_pdm.py`,
`pyomo_stage2.py`, `pdm_run.py` and `stage2_run.py`;
`src/llm_resource_allocation/validation/placement.py` and `stage2.py`.
These are implementation responsibilities, not measured performance claims.

### C++20 implements the same Stage-1 heuristics

**Essential on-slide text**

> Serial C++20 implements GH and AGH with explicit owned state and deterministic
> ordering.
>
> The port preserves the reference's scientific decisions and numerical rules.
>
> Input preparation, algorithms, validation and experiment scheduling have
> separate responsibilities.
>
> Native exact optimization and native Stage 2 remain future work.

**Recommended visual:** align the Python and C++ implementations under shared
problem inputs and decision fields. Make clear that the native implementation
covers Stage-1 GH/AGH rather than every Python component. Add OpenMP only at
the experiment-scheduling layer, preparing the later parallelism discussion.

**Source at 80a9625:** [cpp/README.md](../cpp/README.md), implementation and scope;
`cpp/src/gh.cpp`, `cpp/src/agh.cpp`, `cpp/src/core.cpp` and
`cpp/src/campaign.cpp`; [ARCHITECTURE.md](ARCHITECTURE.md), “State, ordering,
and numerical policy” and “Where parallelism belongs”. Preserve the documented
floating-point order and acceptance boundaries when describing the port.

### Verification before performance comparison

**Essential on-slide text**

> The retained export check passes 63/63 cross-language cases.
>
> Their 3,023 compared final numeric values have zero bitwise differences.
>
> Independent constraints and objective checks complement parity.
>
> Verification coverage is explicit, including points where full Python
> algorithm comparison is unavailable.

**Recommended visual:** two implementations producing decisions, followed by
two distinct checks: cross-language comparison and independent scientific
validation. Keep the count in a small evidence caption. Do not imply that
bitwise agreement alone proves the paper was transcribed correctly.

**Source at 80a9625:** [cpp_parity.json](../benchmarks/release_checks/cpp_parity.json),
top-level `passed=63`, `total=63`; sum the numeric-comparison cases'
`compared_numeric_values` fields to obtain 3,023, with zero
`bitwise_difference_count` in those cases. Separate shuffle cases also belong
to the 63-case check and do not carry a final-numeric comparison field.
[VALIDATION.md](VALIDATION.md), “Checks performed before publication”, explains
the retained checkpoint. The matched campaign separately records per-case
`preflight` comparison and independent validation in
[WP1 status](../benchmarks/matched_runtime_2026-10-14/status.json).

**Speaker-note limit:** these are synthetic checks. Historical large AGH Python
runs that failed with `MemoryError` have no completed Python timing or full
algorithm parity. Do not combine the release fixture count with the separate
large-instance campaign's count as one undifferentiated test total.

### Matched runtime: core and complete invocation

**Essential on-slide text**

> AGH, 16 query types × 4 model options × 4 GPU-tier options, nominal load 200
>
> Same WSL environment, ten paired rounds for each timer
>
> Core Python/C++ ratio of medians: 120.54×, 95% CI [109.75, 131.22]
>
> Complete-invocation ratio: 99.70×, 95% CI [93.26, 107.26]

Visible qualification: **Synthetic CPU workload. Existing implementations have
different preparation costs. These ratios do not isolate programming-language
effects.**

**Recommended visual:** separate core and invocation comparisons, with explicit
timer labels. Use [core_ratios.png](../benchmarks/matched_runtime_2026-10-14/analysis/core_ratios.png)
and [invocation_ratios.png](../benchmarks/matched_runtime_2026-10-14/analysis/invocation_ratios.png),
or recommend redrawing only the selected case from the retained numbers. Keep
the interval and implementation qualification. Core medians are Python
8.425024 s and C++ 0.069892 s. Invocation medians are Python 9.883960 s and
C++ 0.099137 s.

**Source at 80a9625:** [WP1 analysis](../benchmarks/matched_runtime_2026-10-14/analysis/analysis.json),
`rows` where `case="16x4x4_load200_agh"`; select `boundary="core"` and
`boundary="invocation"` separately. Use `python.median_seconds`,
`cpp.median_seconds` and `ratio.{ratio_of_medians,ci95_low,ci95_high}`.
[KEY_NUMBERS.md](KEY_NUMBERS.md), “Confirmed matched-runtime numbers — WP1”, and
[EXTENSION_ENVIRONMENT.md](EXTENSION_ENVIRONMENT.md) define conditions.

**Speaker notes:** core covers a fresh public solve, traces and internal
validation, excluding startup, parsing, projection/output and destruction.
Python validates input and prepares problem data inside the core call. C++
receives a prepared lattice before timing. Invocation covers a separate Linux
subprocess from startup through exit. These are separate paired samples.
Intervals use paired-round percentile bootstrap. A median of paired ratios is
a different estimator from the ratios of medians shown here.

### Native scaling, if the audience needs a growth result

**Essential on-slide text**

> Native GH/AGH were measured across query counts 16–384 at fixed 4×4 menus.
>
> Five input seeds per size, three core samples per method and input.
>
> Observed log-log slopes: GH 1.6615 [1.6402, 1.6798],
> AGH 1.9402 [1.9254, 1.9600].
>
> These are fits over the measured range, not asymptotic complexity bounds.

**Recommended visual:** [query_scaling.png](../benchmarks/instance_scaling_2026-10-14/analysis/query_scaling.png).
Retain data points, axes, intervals and parity-status explanation. This topic
can move to the appendix when the main presentation needs fewer details.

**Source at 80a9625:** [WP5 analysis](../benchmarks/instance_scaling_2026-10-14/analysis/analysis.json),
`fits` where `family="query"` and `method="gh"` or `"agh"`, then
`fit.{exponent,ci95_exponent_low,ci95_exponent_high}`. The `points` rows supply
the measured shape, seed, repetitions and verification mode. Intervals resample
five whole seed grids while holding per-instance median durations fixed.
Full Python parity covers the twenty I=16/32 points only. Other points retain
independent final-decision validation. The separate menu-scaling fit does not
establish a universal exponent for the product of menu dimensions.

### OpenMP runs independent cases concurrently

**Essential on-slide text**

> Parallel work unit: one independent allocation case
>
> Fixed mixed batch of 32 GH/AGH cases, thirty paired core rounds
>
> Eight-thread speedup: 4.0223×, 95% CI [3.7636, 4.4243]
>
> Efficiency: 50.28%, using its own one-thread control
>
> Each individual GH/AGH solve remains serial.

Visible conditions: **cores / close / dynamic / chunk 1; unsorted; default
allocator. CPU allocation software with synthetic inputs.**

**Recommended visual:** show independent input cases distributed among workers,
then the [same-setting speedup series](../benchmarks/openmp_diagnostics_2026-10-14/plots/speedup.png).
Keep one-thread and team-size comparisons tied to the same workload and factors.
Do not portray OpenMP as tensor/pipeline parallel GPU execution.

**Source at 80a9625:** [WP2 analysis](../benchmarks/openmp_diagnostics_2026-10-14/analysis/extension.json),
`settings` where `key="8_cores_close_dynamic_1_False_None"`, then
`speedup_vs_same_setting_one_thread.{ratio_of_medians,ci95_low,ci95_high}`
and `valid_rounds=30`. Efficiency is the displayed speedup divided by eight.
The corresponding one-thread key is `1_cores_close_dynamic_1_False_None`.
The native scheduling implementation is `cpp/src/campaign.cpp`.

**Speaker notes:** core includes team creation and barriers but excludes
parsing/output and warmup. This confirms a local measured throughput gain for
the stated batch. The settings search remains exploratory. A selected minimum
among many settings does not establish an optimum. Sorting improvement at
sixteen threads is unestablished because its interval includes one. Physical
P/E-core, cache, SMT and throttling causes remain unresolved in WSL. The older
18-round campaign's 4.20× core and 2.27× invocation results retain their original
scope and must not be spliced with this campaign's thirty-round figures.

### Contribution, limits and next work

**Essential on-slide text**

> Implemented: Python/Pyomo reference, serial C++20 GH/AGH, independent checks
> and OpenMP across experimental cases.
>
> Measured: local CPU runtime on retained synthetic inputs, with explicit timer
> boundaries and verification coverage.
>
> Still open: author-data calibration, native exact/Stage-2 integration,
> memory profiling and a validated MPI implementation.

**Recommended visual:** a restrained implementation/evidence map and repository
link. Distinguish completed software from proposed work without a release
timeline. The spoken conclusion should connect each claim to the evidence that
supports it, rather than repeat a large headline speedup.

**Source at 80a9625:** [ARCHITECTURE.md](ARCHITECTURE.md), “Where parallelism
belongs”; [EXTENSION_REPORT.md](EXTENSION_REPORT.md), limitations and deferred
work; [KEY_NUMBERS.md](KEY_NUMBERS.md), comparison boundaries.
The paper's calibration is unavailable. Local runtime ratios do not demonstrate
GPU-serving acceleration or real cloud savings. Heuristic results are not proven
optima. The synthetic verification does not complete numerical replication of
the paper's tables. Optional memory work was not performed.

## Optional technical appendices

### Solver budgets and accepted costs

**Essential on-slide text:** For 10×10×10/load1, accepted modeled costs are AGH
1,150.055 USD, HiGHS 1,274.759 USD at 20 s, and HiGHS 915.549 USD at 120/600 s.
The HiGHS results are time-limited incumbents, with weak bounds and no optimality proof.
This single-input ordering change supports no general method ranking.

**Recommended visual:** a small same-input cost comparison, with solver status
beside each value. Put the full accepted/rejected table in notes or another
appendix. Use the retained [solver report](../benchmarks/solver_quality_2026-10-14/REPORT.md)
rather than simplifying away rejected rows.

**Source at 80a9625:** [WP6 analysis](../benchmarks/solver_quality_2026-10-14/analysis.json),
`rows` with IDs `10x10x10_L1_agh`, `10x10x10_L1_highs_20`,
`10x10x10_L1_highs_120` and `10x10x10_L1_highs_600`; use
`usable_objective_usd`, `accepted`, `solver_status`, `best_bound_usd` and
`normalized_gap`. Longer-limit accepted cohorts exclude different inputs.
Gurobi is unavailable under the recorded WSL license, so the extension provides
no new three-backend ranking.

### Original Stage-2 evaluation, standard policy

**Essential on-slide text:** October 13 campaign: forty completed source jobs,
thirty-seven accepted sources, 1,850 operational LP attempts. Outcomes: 646
usable, 1,000 solver-infeasible, 204 objective-only rejections. Another 150
scenarios were skipped after rejected sources and lie outside 1,850 attempts.
Adaptation recovers 256/1,344 frozen-routing failures, or 19.05%.

**Recommended visual:** [original outcomes plot](../benchmarks/stage2_stress_2026-10-13/plots/outcomes.png),
with skipped scenarios separate. Optional cost caption: summed C4+C5 decreases
5.857419% over 390 usable frozen/adapted pairs. Give no savings to infeasible
frozen baselines.

**Source at 80a9625:** [original analysis](../benchmarks/stage2_stress_2026-10-13/analysis/analysis.json),
top-level `completed_jobs`, `accepted_sources` and `rejected_source_diagnostics`;
`overall.{attempted_scenarios,stage2_status_counts,frozen_infeasible_scenarios,
recovered_scenarios,paired_cost_scenarios,paired_cost_reduction_fraction_of_baseline_sum}`.
The retained original policy uses absolute objective agreement 1e-8 USD and
relative zero. Completed jobs and solver-optimal status do not imply scientific
acceptance. [STAGE2_RESULTS.md](STAGE2_RESULTS.md) explains that distinction.

### Retrospective optional-policy replay

**Essential on-slide text:** Reevaluate the same retained decisions with optional
relative objective tolerance 1e-12. No new LP solve or decision repair. All
204/204 objective-only rejections become usable, giving 850/1,850 usable
attempts. All 1,000 infeasible attempts remain rejected. Adaptation recovers
344/1,344 frozen failures, or 25.60%.

**Recommended visual:** [policy comparison](../benchmarks/stage2_policy_2026-10-14/plots/policy_comparison.png),
clearly labeled retrospective. If showing cost, include 5.957974%, 95% interval
[5.745418%, 6.063490%], over 506 usable pairs in thirty-seven source grids.
The changed cohort prevents interpreting the difference from the original
390-pair cost result as a causal policy benefit.

**Source at 80a9625:** [WP3 analysis](../benchmarks/stage2_policy_2026-10-14/analysis.json),
`old_policy` and `selected_policy`, especially `usable`, `newly_usable`,
`frozen_failures`, `recovered`, `paired_scenarios`, `paired_reduction_fraction`
and `source_cluster_bootstrap.ci95`. [STAGE2_OBJECTIVE_POLICY.md](STAGE2_OBJECTIVE_POLICY.md)
defines `|a-b| <= max(abs_tol, rel_tol * max(|a|,|b|))`. Defaults stay absolute
1e-8 USD and relative zero. Constraint tolerances and Stage-1 acceptance remain
unchanged. The evidence establishes acceptance of these observed roundoff
cases, not universal solver precision.

### New matched Stage-2 campaign

**Essential on-slide text:** Separate October 14 campaign: 144 sources complete,
136 accepted, 6,800 LPs attempted, 3,246 usable and 3,554 infeasible. Eight
rejected sources leave 400 planned LPs unattempted. These new solves use
explicit relative objective tolerance 1e-12.

**Recommended visual:** [per-load plot](../benchmarks/stage2_robustness_2026-10-14/plots/per_load.png)
with conditional denominators. Use the following values only when their table
or legible captions can remain attached:

| Nominal load | Recovered / frozen failures | Paired usable cost scenarios | Summed C4+C5 reduction, 95% interval |
|---|---:|---:|---:|
| 200 | 330/1,260 (26.1905%) | 540 | 4.945490% [4.640838%, 5.177031%] |
| 2,000 | 280/1,260 (22.2222%) | 540 | 4.923512% [4.628603%, 5.146725%] |
| 20,000 | 400/1,220 (32.7869%) | 530 | 5.156249% [4.726027%, 5.526150%] |
| 100,000 | 311/1,135 (27.4009%) | 315 | 5.433509% [4.983066%, 5.865710%] |

**Source at 80a9625:** [WP4 analysis](../benchmarks/stage2_robustness_2026-10-14/analysis.json),
`completed_sources`, `accepted_sources`, `attempted_lps`, `status_counts`, and
`by_load` keys `"200.0"`, `"2000.0"`, `"20000.0"`, `"100000.0"`. Within each
row use `recovered`, `frozen_failures`, `paired_scenarios`,
`paired_reduction_fraction` and `source_cluster_bootstrap.ci95`. Intervals
resample twelve shared-input clusters per load. The accepted three-method
intersection is 40/48 input identities; these pooled per-load rows contain
unmatched accepted inputs. They do not establish a method ranking.

All cost reductions divide the difference of frozen/adapted C4+C5 sums by the
usable frozen sum. Infeasible baselines receive no savings. Lower modeled cost
may accompany greater unmet demand. These are conditional synthetic-grid
results, not real-world probabilities or cloud bills.

### Verification and statistics details

**Essential on-slide text:** Each retained campaign has its own sources,
inputs, timer definitions and accepted cohort. Historical and new evidence
remain distinct. Preserve resource failures and rejected incumbents.

**Recommended visual:** an evidence table rather than another headline graph.
Keep historical October 13 complete-reference comparisons separate from the
new scaling study's twenty full Python parity points and ninety independent
native method/input points. Distinguish ratio of medians, median paired ratio,
IQR and bootstrap interval. Avoid combining their most favorable values.

**Sources at 80a9625:** [historical performance analysis](../benchmarks/performance_2026-10-13/analysis/analysis.json),
`serial[*].verification_mode`, `compared_numeric_values`, `coverage` and
`limitations`; [WP5 analysis](../benchmarks/instance_scaling_2026-10-14/analysis/analysis.json),
top-level coverage fields and `points[*].verification_mode`;
[KEY_NUMBERS.md](KEY_NUMBERS.md), measurement/statistics contracts;
[EXTENSION_ENVIRONMENT.md](EXTENSION_ENVIRONMENT.md), CPU/WSL versions and
measurement conditions. Statistical intervals retain their stated conditional
interpretation and bootstrap unit.

## Ready-to-paste Claude Design prompt

```text
Create a complete, editable English technical presentation for the portfolio project
“LLM Resource Allocation”, by Antonio Arbizzani Tonelli.

Use the supplied docs/PRESENTATION_DRAFT.md as the narrative and source plan.
Choose the slide count from the content and audience. Do not inherit an older
twelve-slide requirement. Keep slides readable and adapt the speaking length
to the requested delivery context. If no speaking time is supplied, favor a
concise main story and optional technical appendices.

Repository: https://github.com/antonio-arbizzani-tonelli/llm-resource-allocation
Pin numerical/source evidence to public commit:
80a9625ab62a3c5c70ede7a9dae97a61158e250a
Its numerical artifacts match checkpoint:
543ad4e640100a4c2a69febf17fe885bd452861e

The draft may have been written after those commits. Read the supplied draft
for the revised narrative, then resolve its evidence paths at the pinned
source snapshot. Do not assume the draft itself exists at the source commit.
If a necessary artifact is inaccessible, name it and request it. Do not invent
values, plots, confidence intervals, missing timings or solver outcomes.

Audience: scientific-computing faculty, C++ developers and technical portfolio
reviewers. Use natural English, a restrained tone and concrete explanations.
Open with the resource-allocation problem. Explain the model briefly, then
Python/Pyomo, serial C++20 GH/AGH, cross-language verification, matched runtime
and OpenMP across independent experimental cases. MPI is future work.
Detailed solver-budget and Stage-2 results belong in optional appendices.

Attribute formulation and GH/AGH to Cheng and Nguyen, arXiv:2604.07472 v2.
Use v1 for the explicit operational LP. Attribute the implementation,
explicit unit conventions, validation, native port and measurements to this
project. Distinguish paper formulation, implemented software and observed
results. Numerical replication of the paper's tables remains incomplete.

All runtime experiments measure allocation software running on CPU. GPU
capacity, latency and price are modeled coefficients. OpenMP schedules
independent cases concurrently. It does not parallelize the individual
scientific solve or perform GPU tensor/pipeline parallel execution.

For the highlighted AGH 16×4×4/load200 comparison, show separate core and
complete-invocation ratios of medians, with intervals and ten paired rounds.
Use the exact draft/artifact values. Keep the preparation-cost asymmetry
visible: Python validates/prepares problem data inside its core call, while
C++ receives a prepared lattice. These existing-implementation comparisons
cannot isolate a language effect. Do not substitute median paired ratios or
historical workflow timers for the selected estimators.

For OpenMP, use the fixed 32-case unsorted/default-allocator workload with
cores/close/dynamic/chunk1 and thirty paired core rounds. Compare each team size
with the same-setting one-thread control. State local measured throughput
gain with its confidence interval. Keep exploratory settings selection,
unestablished sorting benefit and unresolved physical causes explicit.
Never combine the older eighteen-round results with this campaign's figures.

If including scaling, label fitted slopes as descriptive over the measured
range. Do not write asymptotic complexity or extrapolate. Preserve the limits
of Python parity and do not assign a Python time to a failed run.

Keep three Stage-2 appendix evaluations separate: original standard-policy
campaign, retrospective optional-policy replay of the same decisions, and
new matched solves. Preserve attempted/usable/skipped denominators, source
acceptance, conditional recovery and paired-cost definitions. The optional
relative objective tolerance changes neither original classifications nor
defaults, constraint tolerances or Stage-1 acceptance. No savings belong to
infeasible baselines. Different accepted cohorts support no general ranking.

Use published verified plots listed in the draft, or redraw a selected case
from the identified JSON/CSV values. Preserve axes, units, intervals and
verification markers. Use editable data charts where appropriate. Every
numerical claim and chart needs an identifiable artifact path plus exact
case/row/key and source commit in notes. Add readable on-slide units,
campaign date, timer/acceptance scope and denominator. Do not crop away
qualification markers. Put paper facts and project measures in distinct
attributions. Supply a final claim-to-source table.

Use clear typography, open space, a restrained palette and simple conceptual
diagrams. Avoid slogans, dense algorithm lectures and images suggesting a
real GPU installation. Keep implementation details only when they explain
the result. Include the GitHub link and honest limitations. Do not claim
universal speedups, real cloud savings, heuristic optimality, completed MPI
or native Stage-2 results.

Deliver the complete visual presentation with editable content, English
speaker notes, optional technical appendices and a claim-to-source table.
Inspect every rendered slide for legibility, overlap, source attribution and
scientific consistency. Do not stop at an outline or a written slide plan.
```
