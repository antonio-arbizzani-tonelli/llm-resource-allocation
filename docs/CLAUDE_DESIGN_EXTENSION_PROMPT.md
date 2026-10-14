# Presentation design guidance

The [English presentation draft](PRESENTATION_DRAFT.md) contains the current
narrative, proposed content and a ready-to-paste design prompt. The
[presentation brief](PRESENTATION_BRIEF.md) defines the audience and scope. This
file supplies reusable design guidance and the evidence contract for a future
visual presentation. The current deliverable is text only. No rendered deck,
PPTX, HTML presentation or PDF accompanies this draft.

The [original-campaign prompt](CLAUDE_DESIGN_PROMPT.md) preserves October 13
measurements. Its campaign-specific material belongs in historical context or
an optional appendix. It does not set the current structure or slide count.

## Reusable English design prompt

```text
Create a complete, editable English presentation about “LLM Resource Allocation”
by Antonio Arbizzani Tonelli. Use the supplied PRESENTATION_DRAFT.md as the
current narrative authority and PRESENTATION_BRIEF.md for audience and scope.
Write natural English for titles, captions and speaker notes. Preserve code
symbols, commands and filenames.

Create the visual presentation and English speaker notes from that draft.
Choose the number of slides from the content and speaking time. There is no
required slide count.

MAIN STORY

Explain the allocation problem before showing benchmark ratios. The allocator
chooses models, GPU resources and routing fractions under demand, budget and
service-level constraints. Introduce Stage 1 as deployment and nominal routing.
Give Stage 2 a short statement of scope: keep deployment fixed while adapting
routing and unmet demand. Reserve detailed operational campaigns for an
optional technical appendix.

Make Python/Pyomo, C++20 and OpenMP visible in the main story:
- Python supplies the scientific reference and independent validation.
- Pyomo constructs the P_DM MILP and Stage-2 LP. A configured HiGHS or Gurobi
  backend solves those mathematical models.
- Serial C++20 implements Stage-1 GH/AGH, costs, traces and validation.
- OpenMP distributes independent allocation cases across CPU threads. Each
  scientific solve retains serial arithmetic and ordered acceptance.

Then explain cross-language verification, matched Python/C++ runtime,
independent-case OpenMP throughput, and limits. Include native scaling only
if it helps the audience. Full solver comparisons and all detailed Stage-2
results belong in optional appendices. Keep the main narrative focused on
what the allocator does, how the implementations relate, and what the CPU
measurements establish.

ATTRIBUTION AND SCOPE

Attribute the formulation and GH/AGH algorithms to Cheng and Nguyen,
arXiv:2604.07472, with v2 as the main scientific source and v1 supplying the
explicit operational LP. Attribute the implementation, explicit unit
conventions, independent validation, C++ port and measurements to this project.

Experiments run CPU allocation software with synthetic project inputs. GPU
capacity and latency are modeled coefficients. Costs are outputs of the model,
not measured cloud bills. The project does not claim numerical reproduction
of the paper's tables, measured GPU inference, language-only acceleration,
heuristic optimality or a general method ranking. Native Stage 2 and MPI remain
future work.

VERIFICATION AND MAIN BENCHMARKS

The retained cross-language suite passes 63/63 checks. Its compared final
numeric values total 3,023, with zero bitwise differences. Explain the bounded
scope. Completion, independent constraint feasibility, objective agreement
and solver termination remain separate evidence.

For matched runtime, highlight AGH 16×4×4/load200, algorithm seed 37 and beta
0.8, in the same WSL environment. Keep the two independently measured timer
boundaries separate:
- Core Python/C++ ratio of medians: 120.5437, 95% interval
  [109.7530, 131.2151]. Medians: Python 8.425024 s, C++ 0.069892 s.
- Complete-invocation ratio of medians: 99.7005, interval
  [93.2556, 107.2592]. Medians: Python 9.883960 s, C++ 0.099137 s.
Each boundary has ten paired rounds. The core timer includes a public solve,
a fresh result, traces and independent validation, excluding startup, parsing,
projection, output and destruction. Python validates original inputs and builds
PdmProblemData inside that call. C++ receives its prepared coefficient lattice
before timing. These are implementation comparisons with different preparation
and trace costs, not equal-operation or pure-language speedups.
Complete invocation is a separate fresh Linux subprocess from startup through
exit. It has no in-process warmup. A ratio of medians differs from a median of
paired ratios. Never combine these timers or mix their samples.

For OpenMP, use the fixed mixed batch of 32 GH/AGH cases, unsorted,
cores/close/dynamic/chunk1, default allocator. Eight-thread core speedup is
4.0223, 95% interval [3.7636, 4.4243], efficiency 50.28%, against that setting's
own one-thread control. There are 30 paired core rounds. Team creation and
barriers are inside the timer. Parsing and output are outside. This is batch
throughput, not a faster individual solve or GPU inference. Keep the earlier
18-round campaign separate. Sorting benefit and physical causes of lost
efficiency remain unresolved.

OPTIONAL TECHNICAL APPENDICES

Keep the three Stage-2 evidence sets in separate sections:
1. Original October 13 campaign, standard absolute-only objective agreement:
   646 usable of 1,850 attempted LPs, 1,000 solver-infeasible attempts and
   204 objective-only rejections. Another 150 scenarios were skipped after
   three rejected Stage-1 sources, outside the attempted denominator.
   Adaptation recovers 256/1,344 frozen-routing failures. Paired summed C4+C5
   reduction is 5.857419% over 390 usable same-scenario pairs.
2. Retrospective optional-policy replay of those same retained decisions:
   850/1,850 usable and 344/1,344 frozen failures recovered. Relative objective
   tolerance 1e-12 accepts the 204 objective-only rejections. All 1,000
   solver-infeasible attempts stay rejected. No LP is solved and no decision
   is repaired. The default remains absolute 1e-8 USD and relative zero.
   Constraint tolerances and Stage-1 acceptance do not change. Reduction is
   5.957974%, interval [5.745418%, 6.063490%], over 506 usable pairs in 37
   source-grid bootstrap clusters. The changed cohort prevents a causal
   comparison with the original 390-pair reduction.
3. New October 14 matched-input solves with explicit relative 1e-12:
   144 sources complete, 136 are accepted, 6,800 LPs are attempted and 3,246
   are usable. Eight rejected P_DM sources skip 400 planned LPs. Keep each
   load's recovery denominator, usable cost pairs and interval. The all-method
   accepted-source intersection is 40/48 input identities. Pooled load-specific
   figures include unmatched accepted inputs and do not support a general
   method ranking.

Define cost reduction as
(sum frozen C4+C5 - sum adapted C4+C5) / sum frozen C4+C5
on identical scenarios where both decisions are usable. Give no savings value
to infeasible baselines. Preserve service/unmet-demand evidence when
interpreting modeled cost.

Other optional appendices may cover native scaling, solver budgets and all
rejected rows, timer/statistical definitions, large-instance parity limits,
and source/replay provenance. Observed-range scaling fits are descriptive,
not asymptotic complexity bounds. Time-limited solver incumbents are not
proven optima. Unavailable or failed Python references receive no invented
runtime or speedup.

SOURCE AND DESIGN CONTRACT

Every numerical claim or chart needs an identifiable artifact, exact row/key,
reference commit, campaign, units, estimator, denominator and acceptance scope.
Use the claim-to-source table below and the full draft. If a source cannot be
read, identify the missing path and request it. Do not reconstruct missing
measurements or replace a rejected result with a usable one.

Use a light background, readable type and a restrained
palette. Favor a clear allocation diagram and a few readable evidence figures.
Keep material caveats beside their result and full conditions in notes. Avoid
GPU-cluster imagery or decorative graphics that imply measured GPU serving.
Preserve chart values, axes, intervals and verification markers when redrawing.
Before delivery, inspect every rendered page for readability, overlap, source
attribution and consistency with this evidence contract.
```

## Source reference

The reviewed public source is
[`80a9625ab62a3c5c70ede7a9dae97a61158e250a`](https://github.com/antonio-arbizzani-tonelli/llm-resource-allocation/commit/80a9625ab62a3c5c70ede7a9dae97a61158e250a).
Its numerical payload matches the extension checkpoint
`543ad4e640100a4c2a69febf17fe885bd452861e`. This guidance is a later editorial
revision. It does not claim to exist in that frozen source snapshot.

Resolve evidence paths at the reviewed commit. For example, append a path from
the table below to this base:

```text
https://github.com/antonio-arbizzani-tonelli/llm-resource-allocation/blob/80a9625ab62a3c5c70ede7a9dae97a61158e250a/
```

Use [KEY_NUMBERS.md](KEY_NUMBERS.md), [EXTENSION_REPORT.md](EXTENSION_REPORT.md),
[EXTENSION_ENVIRONMENT.md](EXTENSION_ENVIRONMENT.md),
[MODEL.md](MODEL.md), [ARCHITECTURE.md](ARCHITECTURE.md) and
[VALIDATION.md](VALIDATION.md) for interpretation and scope. Experimental data
remain in their own artifact directories and source snapshots. The original
prompt pins `8a11e7d533e929009ef5e1cae2dde6bdb18d217b`; that is historical context,
not a substitute for the later extension evidence.

## Claim-to-source table

Paths identify retained artifacts at the reviewed public commit. Optional
appendix material is separate from the recommended main story. Replay commands
in [KEY_NUMBERS.md](KEY_NUMBERS.md) inspect retained evidence outside measured
timings. This documentation revision requires no new benchmark or solver run.

| Claim or topic | Authoritative source and selector | Boundary or denominator |
|---|---|---|
| Paper formulation and model stages | [MODEL.md](MODEL.md), [UNITS.md](UNITS.md), linked paper v2 and v1 Eq. (12a–f) | Current coherent units are project interpretations. Historical literal fixtures remain separate. Stage 2 optimizes C4+C5 with deployment fixed. |
| Python/Pyomo and C++20/OpenMP responsibilities | [ARCHITECTURE.md](ARCHITECTURE.md), [native README](../cpp/README.md), [campaign.cpp](../cpp/src/campaign.cpp) | Pyomo is the modeling layer. C++ covers serial Stage-1 GH/AGH. OpenMP loops over independent cases. |
| 63/63 parity checks, 3,023 final values, zero bitwise differences | [Serial parity](../benchmarks/portfolio/raw/serial/parity.json), `passed`, `total`, sums of `cases[*].compared_numeric_values` and `bitwise_difference_count` | 48 placement cases, including four frozen, plus 15 seeded-shuffle checks. Bounded synthetic verification. |
| Core 120.5437 / invocation 99.7005 | [WP1 analysis](../benchmarks/matched_runtime_2026-10-14/analysis/analysis.json), `rows` with `case=16x4x4_load200_agh`, separately `boundary=core` and `invocation` | Ten paired rounds per separate timer. Ratio of medians, 10,000 paired-round bootstrap resamples, seed 20261014. Implementation preparation and trace costs differ. |
| WP1 campaign coverage 480/480 | [WP1 status](../benchmarks/matched_runtime_2026-10-14/status.json) | 12 method/configuration points × two boundaries × two runtimes × ten rounds. |
| Eight-thread OpenMP 4.0223 / 50.28% efficiency | [WP2 analysis](../benchmarks/openmp_diagnostics_2026-10-14/analysis/extension.json), `settings` key `8_cores_close_dynamic_1_False_None` | Fixed 32-case batch, 30 paired core rounds, same-setting one-thread key `1_cores_close_dynamic_1_False_None`. 10,000 resamples, seed 20261014. |
| Optional OpenMP controls and selection | [Same-team controls](../benchmarks/openmp_diagnostics_2026-10-14/analysis/same_team_controls.csv), [WP2 analysis](../benchmarks/openmp_diagnostics_2026-10-14/analysis/extension.json) | 201 exploratory settings. Each speedup uses its own one-thread control. Same-team intervention ratios answer a different question. Sorting benefit is unestablished. |
| Optional native scaling | [WP5 analysis](../benchmarks/instance_scaling_2026-10-14/analysis/analysis.json), `fits` rows by `family=query/menu` and `method=gh/agh` | Medians of three native core samples per instance. Five complete input-seed clusters, 10,000 bootstrap draws, seed 20261014. Fits describe the observed range. |
| Optional scaling verification scope | [WP5 analysis](../benchmarks/instance_scaling_2026-10-14/analysis/analysis.json), top-level counts and `points` | 90 method/instance points, 270 samples. Full Python parity covers 20 small points; the other 70 have independent final-decision validation. |
| Optional longer-limit solver quality | [WP6 analysis](../benchmarks/solver_quality_2026-10-14/analysis.json), `agh_incumbent_comparisons` by limit and all `rows`; [complete report](../benchmarks/solver_quality_2026-10-14/REPORT.md) | Four fixed inputs, fresh cold solves at 20/120/600 s. 20 measured jobs, 18 accepted. Accepted pair counts 4/4, 3/4 and 3/4 exclude different cases. All twelve MILPs are time-limited. |
| Optional original Stage 2 | [Original analysis](../benchmarks/stage2_stress_2026-10-13/analysis/analysis.json), [original report](STAGE2_RESULTS.md) | 646 usable of 1,850 attempts from 37 accepted sources. 150 skipped scenarios lie outside this denominator. |
| Optional retrospective policy replay | [WP3 analysis](../benchmarks/stage2_policy_2026-10-14/analysis.json), `old_policy`, `selected_policy`, `mutation_check`; [policy](STAGE2_OBJECTIVE_POLICY.md) | Same retained decisions, no solve or repair. 850/1,850 usable, 344/1,344 recovered, 506 usable cost pairs in 37 grids. Defaults remain unchanged. |
| Optional new Stage-2 campaign | [WP4 analysis](../benchmarks/stage2_robustness_2026-10-14/analysis.json), top-level counts and `by_load`; [source results](../benchmarks/stage2_robustness_2026-10-14/source_results.json) | 3,246/6,800 usable LPs from 136/144 accepted sources. Preserve load-specific recovery/cost denominators. Pooled cohorts include unmatched accepted inputs. |
| Optional historical parity and failed Python references | [PERFORMANCE.md](PERFORMANCE.md), [original prompt](CLAUDE_DESIGN_PROMPT.md) | Separate October 13 campaign: 16 full comparisons and 185,832 bit-identical values. Two AGH MemoryError endpoints have final-decision checks without full algorithm parity. |

For a later visual pass, select plots from the corresponding artifact directory
or redraw directly from the identified JSON/CSV. Preserve the plotted cohort,
units, timer, uncertainty and failure markers. A selected simple example can be
clearer than a dense all-cases figure, provided its selection is explicit and
its full source remains available.

The formulation and algorithms remain attributed to Cheng and Nguyen:
[v2](https://arxiv.org/abs/2604.07472v2),
[v1](https://arxiv.org/abs/2604.07472v1). The repository supplies the synthetic
campaign measurements and implementation evidence.
