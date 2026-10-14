# LLM Resource Allocation

**A verified allocation model, a C++ implementation, and measured parallel performance.**

Large language model serving involves a coupled decision: which model should
serve each workload, on which GPU tier, with what parallelism, and at what cost?
An inexpensive placement can fail when demand changes. A fast algorithm is
useful only if its output still meets the constraints.

This personal scientific-computing project by **Antonio Arbizzani Tonelli**
turns that problem into an executable Python reference, independently checks
its decisions, ports the heuristics to C++20, and measures OpenMP execution of
independent experiments. Stage 2 re-optimizes routing under realized demand
while keeping the deployment fixed. Everything runs on a CPU; GPU capacity and
serving latency are modeled inputs.

## What the evidence shows

| Indicator | Recorded result | Meaning |
|---|---:|---|
| GPU rental reduction, GH → AGH | **11.1%** | 9 → 8 USD in eight controlled synthetic cases; total-cost gains are smaller. |
| OpenMP median campaign acceleration | **4.20×** | Eight observed threads, 32 mixed cases, 18 rounds, computation timer. |
| Complete invocation median acceleration | **2.27×** | Same mixed campaign, including process and transport overhead. |
| Larger Python/C++ verification | **185,832 values** | Sixteen full reference comparisons with zero bitwise differences. |
| Stage-2 feasibility recovery | **19.05%** | 256 usable adapted decisions among 1,344 frozen-routing failures. |
| Stage-2 paired operational-cost reduction | **5.86%** | Summed C4+C5 on 390 scenarios with both decisions usable. |

The [results report](docs/RESULTS.md) gives baselines, formulas, timing scopes,
raw samples, solver outcomes and limitations. These are this project's
measurements, separate from the paper's published numerical results.

![Median OpenMP campaign scaling](benchmarks/performance_2026-10-13/analysis/plots/openmp_core_scaling.png)

## From formulation to engineering

The formulation and GH/AGH algorithms come from Cheng and Nguyen's
[paper v2](https://arxiv.org/abs/2604.07472v2); [v1](https://arxiv.org/abs/2604.07472v1)
also specifies the operational LP. The personal contribution is the checked
implementation and engineering evidence: explicit dimensional conventions,
immutable decision records, solver-independent validation, cross-language
verification, reproducible benchmarks, profiling, and parallel execution.

The dimensional interpretation is documented in [the model](docs/MODEL.md).
The [architecture](docs/ARCHITECTURE.md) explains the scientific and software
boundaries. An exploratory parallel validator was retained as an experiment
after controlled measurements failed to establish a robust benefit. Production
parallelism therefore uses independent cases, whose measured benefit is clear.

| Component | Python | C++20 |
|---|---|---|
| Exact deterministic allocation (`P_DM`) | Pyomo + HiGHS or Gurobi | — |
| GH and AGH | Reference implementation | Serial implementation |
| Fixed-deployment Stage-2 LP | Coherent and historical unit conventions | — |
| Independent validation | Placement and Stage 2 | Placement |
| Parallel experiment campaigns | Preparation and comparison | OpenMP |

## Run a complete small example

Use Python 3.13 or later. From the repository root:

```bash
python -m venv .venv
```

Activate with `.venv\Scripts\Activate.ps1` in PowerShell or
`source .venv/bin/activate` on Linux/macOS, then:

```bash
python -m pip install -e .
python examples/stage1_quickstart.py
python examples/stage2_quickstart.py
python -m unittest discover -s tests -q
```

Both examples select the open-source HiGHS backend explicitly. The base package
pins Pyomo 6.10.0 and highspy 1.14.0. Gurobi is optional and needs a usable
license: `python -m pip install -e ".[gurobi]"`. `SolverConfig()` defaults to
Gurobi; pass `SolverConfig(backend=SolverBackend.HIGHS)` in base installations.

For native execution on Linux or WSL with GCC supporting C++20 and GNU Make:

```bash
make -C cpp -j4 all test openmp campaign-test
python scripts/check_cpp_parity.py --frozen
python scripts/check_openmp_campaign.py --output results/openmp/check
```

The [C++ guide](cpp/README.md) includes native commands, frozen inputs,
sanitizers, OpenMP scheduling and profiling. The serial binary has no solver
or Python dependency.

## Explore or reproduce

- [Model and Stage 2](docs/MODEL.md): what is optimized and independently checked.
- [Results](docs/RESULTS.md): cost, runtime, parity and parallel efficiency.
- [Stage-2 stress results](docs/STAGE2_RESULTS.md): adaptation, paired costs and numerical rejections.
- [Experiment guide](docs/EXPERIMENTS.md): configurations and reproduction commands.
- [Verification](docs/VALIDATION.md): checks performed on this release.
- [Presentation brief](docs/PRESENTATION_BRIEF.md): an Italian narrative for Claude Design.
- [Claude Design prompt](docs/CLAUDE_DESIGN_PROMPT.md): copy or attach it to create the presentation from published evidence.

Scientific sources live under `src/llm_resource_allocation/`; native code under
`cpp/`; tests under `tests/`; measured evidence under `benchmarks/`.
The [publication allowlist](configs/publication.json) and
[SHA256 manifest](release-manifest.json) identify the delivered files.
Run `python scripts/prepare_release.py --check` to verify them.

This release establishes bounded synthetic correctness and performance evidence.
Recovered author calibration and a quantitative reproduction of all paper
tables remain open. MPI and native C++ solver/Stage-2 integration are future
work. The software is available under the [MIT license](LICENSE).

## Overnight experiment extension

The [overnight campaign guide](docs/NIGHTLY_CAMPAIGN.md) describes the prepared
52-job scaling and Stage-2 sensitivity plan, execution command, runtime limits
and recoverable evidence. The [October 13 performance study](docs/PERFORMANCE.md)
now measures nine larger shapes and 32/64/128-case OpenMP batches. AGH C++ median
is **2.889 s at 128x4x4** and **7.156 s at 256x4x4**; the latter uses independent
final-decision validation after a full Python reference MemoryError. Best
observed median OpenMP acceleration is **4.20x core / 2.27x full invocation**.
All modes, raw evidence and failures are retained. The [Stage-2 stress study](docs/STAGE2_RESULTS.md)
also completes all forty workers: 37 accepted sources produce 1,850 LP attempts,
with 646 scientifically usable decisions, 1,000 infeasible LPs and 204 numerical
objective rejections. It records recovery and paired cost benefits without
relaxing tolerances or assigning savings to infeasible baselines. The earlier
campaigns retain their original scopes and observations.

## Extension results

The October 14 extension adds separate controlled measurements and retrospective
policy evidence. The [extension report](docs/EXTENSION_REPORT.md) records each
work package's hypotheses, outcomes, deviations and open work;
[key numbers](docs/KEY_NUMBERS.md) give denominators, timer boundaries, sources
and replay commands. The [extension decisions](docs/EXTENSION_DECISIONS.md)
describe the opt-in numerical policy and explicit synthetic input assumptions.

The [updated Claude Design prompt](docs/CLAUDE_DESIGN_EXTENSION_PROMPT.md)
develops the original presentation into a 12-slide Italian research talk. It
selects the controlled extension results, pins their numerical source commit,
and supplies speaker-note, appendix and claim-traceability instructions.

| Confirmed extension result | Value | Denominator and scope |
|---|---:|---|
| Matched Python/C++ core ratio of medians | **120.5437**, 95% CI **[109.7530, 131.2151]** | AGH 16x4x4/load200, ten same-WSL paired rounds; public solve with rich traces and independent validation, excluding startup/parsing/projection/output/destruction; same-process warmup excluded. |
| Same point, complete-invocation ratio | **99.7005**, 95% CI **[93.2556, 107.2592]** | Ten separate same-WSL paired single-solve Linux invocations, startup through exit, using the same final-decision schema; external preflight excluded, no in-process warmup. |
| Matched-runtime coverage | **480/480** verified timed calls | 12 GH/AGH points × two boundaries × two runtimes × ten rounds. |
| OpenMP eight-thread baseline speedup | **4.0223**, 95% CI **[3.7636, 4.4243]**, **50.28% efficiency** | 30 paired 32-case batches; unsorted cores/close/dynamic/chunk1/default allocator against its own one-thread control. |
| OpenMP fastest selected setting | **0.220359 s**, speedup **4.7871**, 95% CI **[4.5179, 5.2513]** | Sorted sixteen-thread setting, selected from 201 settings on the same data; its own sorted one-thread control. Sorting versus the same-team unsorted control is **1.0053 [0.9592, 1.1998]**, so improvement is unestablished. |
| Retrospective opt-in Stage-2 acceptance | **850/1,850** usable attempts | Relative objective tolerance 1e-12 recovers 204/204 independently feasible objective-only rejections; original absolute-default results remain 646/1,850. |
| Retrospective opt-in feasibility recovery | **344/1,344 (25.5952%)** | Frozen-routing failures with usable adapted decisions; original default remains 256/1,344. |
| Retrospective opt-in paired C4+C5 reduction | **5.957974%**, 95% CI **[5.745418%, 6.063490%]** | 506 usable same-scenario pairs, resampling 37 source-grid clusters; no savings assigned to infeasible baselines. |
| New matched Stage-2 cohort coverage | **144/144** completed sources, **136** accepted; **3,246/6,800** usable LPs | Four shapes × four nominal loads × three input seeds × GH/AGH/P_DM; eight objective-only rejected P_DM sources skip 400 LPs. Original and fresh archive-only independent replays pass. |
| Multi-instance native query scaling exponents, GH / AGH | **1.6615 [1.6402, 1.6798] / 1.9402 [1.9254, 1.9600]** | Six query levels 16–384 at 4x4, 30 feasible instances per method, five seed-cluster bootstrap units; 10,000 draws, seed 20261014. Descriptive observed-range fits. |
| Multi-instance native scaling coverage | **90/90 points, 270/270 samples, 20/20 small Python parity** | 45 distinct synthetic inputs, three repeats per point; all independently feasible, zero worker failures, one verified checkpoint-persistence recovery. Final replay passes with 1,337 files/360 native validations. |
| Longer-limit solver coverage | **20/20** completed, **18/20** accepted | Eight heuristic results and 10/12 HiGHS incumbents, three warmups excluded; zero worker failures/retries, two independent-constraint rejections retained; Gurobi skipped. |
| Median AGH / accepted HiGHS cost, 20/120/600 s | **0.845329 / 2.103171 / 2.103171** | 4/4, 3/4 and 3/4 accepted same-case pairs from four fixed synthetic inputs; longer cohorts differ, no universal ranking or optimum claim. |

The runtime ratios include implementation-specific trace and input-check costs
on this local synthetic CPU workload. Python's public core call includes input
validation and `PdmProblemData` construction; C++ receives the prepared
coefficient lattice through excluded transport. The comparison uses the
existing full public implementations, rather than an equal-operation
microbenchmark or pure-language ratio. Core calls have an excluded same-process
warmup; complete-invocation calls are distinct measurements with external
preflight excluded.

The OpenMP study completes **201 settings × 30 rounds = 6,030/6,030** batches
with zero failed observations; the full 585-setting interaction matrix is
skipped after its forecast exceeds three hours. Unsorted cores/close/dynamic/
chunk1 at sixteen threads is a local elapsed-time candidate (0.221533 s), while
eight threads give higher observed efficiency. Restricting the allocator to
`MALLOC_ARENA_MAX=1` slows eight-thread batches: control/candidate ratio
**0.08390 [0.07616, 0.08836]**. Intervals are exploratory and unadjusted for
multiple comparisons; the fastest selection has no independent confirmation.
Worker wall accounting describes imbalance, but unavailable WSL hardware
counters and frequency/temperature observations leave P/E, SMT, cache and
throttling causes unresolved. Compact final fingerprints do not claim rich-trace
parity. The [report](docs/EXTENSION_REPORT.md) retains every negative control,
timer denominator and the unmeasured NTFS post-processing recovery.

The policy results come from solver-free replay of retained
decisions under an explicit opt-in objective-agreement rule. The LP, independent
constraints, defaults and original benchmark classifications remain unchanged.
The deterministic sensitivity grid and unmatched method cohorts support
conditional results without a method ranking.

The new Stage-2 campaign completes in 47.86 minutes. At nominal loads 200,
2,000, 20,000 and 100,000, recovery is respectively **330/1,260**, **280/1,260**,
**400/1,220** and **311/1,135** frozen failures. Paired C4+C5 reductions are
**4.945490%, 4.923512%, 5.156249% and 5.433509%**, based on 540/540/530/315
usable pairs and twelve contributing shared-input clusters per load; intervals
and complete denominators are in [KEY_NUMBERS](docs/KEY_NUMBERS.md). Pooled
figures include unmatched accepted sources; the shared accepted-input
intersection is 12/12, 12/12, 11/12 and 5/12, so pooled results supply no method
ranking. All 1,000 historical infeasible records have sufficient error/capacity
certificates, with overlapping causes retained. Initial independent replay
verifies 144 source, 6,800 frozen and 3,246 operational reports. Post-timing
four-part archival packaging preserves every one of 7,233 original entry hashes;
its processing duration is outside campaign timing. The final
[fresh archive-only replay](benchmarks/stage2_robustness_2026-10-14/archive_replay_verification.json)
also passes in 246.1337 s of unmeasured Windows analysis, verifying all entries,
the source snapshot and the same independent reports without a timed binary or
solver. The eight P_DM placements are independently feasible
but rejected by the unchanged Stage-1 absolute objective policy; they are not
rescued sources.

The native scaling campaign completes in 27.48 minutes, including a checkpoint
pause. Menu-product exponents are **0.9455 [0.9185, 0.9707] for GH** and
**1.4461 [1.4065, 1.4998] for AGH**, across four menus at I=64. Different aspect
ratios/structural branches qualify this product fit. All four log-space R²
values and per-instance median/IQRs are in [KEY_NUMBERS](docs/KEY_NUMBERS.md).
Bootstrap resamples five complete seed grids while holding each median of
three repeats fixed; repeats are not independent instances, and no temporal
bootstrap is applied. No asymptotic or extrapolated scaling claim follows.
A live NTFS read interrupts checkpoint replacement after 218 persisted records;
the exact 219-record producer partial is verified and promoted, with original
backups and no edited, discarded, duplicated or imputed observations. Resume
preserves the original three-hour budget. Independent replay passes; the
[final replay](benchmarks/instance_scaling_2026-10-14/final_replay_verification.json)
verifies 1,337 files and 360 warm/measured native validations in 72.26584 s of
unmeasured Windows analysis. A small post-timing plot-label correction retains
the measured source ZIP and all CSV/JSON numbers, with renderer provenance
recorded separately. The
[closing label clarification](benchmarks/instance_scaling_2026-10-14/label_provenance_clarification.json)
confirms the original scoped AST proof using explicit UTF-8 parsing; an
encoding-dependent comparison suggesting extra label changes is discarded.
Numerical results remain unchanged.

Optional WP7 memory work is skipped; no new profiling, lean trace or memory
improvement is claimed.

The longer-limit campaign completes in 53.76 minutes. At 20 s AGH costs less
in three of four accepted pairs; at 120/600 s HiGHS costs less in all three
accepted pairs, with different rejected cases omitted. Both rejected incumbents
agree on objective but fail independent constraints under unchanged defaults.
All twelve MILPs reach `maxTimeLimit`; derived normalized gaps remain
0.986719115–0.999999981. Native MIPGap is unavailable, and no time-limited
incumbent is called optimal. The
[initial archive-only replay](benchmarks/solver_quality_2026-10-14/archive_replay_verification.json)
reproduces 23 completed reports and exact analysis/CSV/report bytes without a
solver or optional packages; its 4.8376 s numerical replay is unmeasured.
The
[final current-launcher replay](benchmarks/solver_quality_2026-10-14/archive_replay_final_verification.json)
also passes in a fresh environment without optional packages, verifying 149
archive entries, 75 frozen sources, five inputs and the same report/acceptance
counts and exact numerical artifacts. Its 18.477553 s numerical processing
time is outside all solves; the initial proof remains unchanged.

WP1–6 measurements and package replays are complete. The
[final aggregate verification](docs/extension_summary_final_verification.json)
confirms equal complete Windows/WSL JSON values, with only newline encoding
different and no solves rerun. All seven
[pre-manifest checks](docs/extension_release_preflight.json) pass: **1,131 Python
tests with zero skips**, native release/ASAN/UBSAN, **63/63** live/frozen parity,
**90 OpenMP comparisons** with ten independently checked Python cases, and both
examples. These are explicitly pre-manifest results. At extension checkpoint
`543ad4e`, the post-manifest repetition also passes: 1,131 Python tests with zero
skips, native release/sanitizer, 63/63 parity cases, 90 OpenMP comparisons,
both examples and verification of 3,568 publication files. The actual closing
logs and canonical handoff are retained in the development workspace; the
hashed public preflight proof remains the separately scoped earlier record.

[CITATION.cff](CITATION.cff) provides software and scientific attribution;
the software uses the [MIT license](LICENSE).

