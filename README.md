# LLM Resource Allocation

Serving LLM workloads across heterogeneous GPU tiers requires choosing which
models to deploy, how to configure tensor and pipeline parallelism, and how to
route demand within latency, error, capacity and budget constraints. The
objective combines GPU rental and storage costs with penalties for delay and
unmet demand. This project implements a two-stage allocation model: Stage 1
chooses the deployment and routing; Stage 2 adapts routing to realized demand
while keeping that deployment fixed.

The repository provides a Python scientific reference, Pyomo optimization
models, serial C++20 implementations of the GH and AGH heuristics, and OpenMP
benchmarks that execute independent experimental cases in parallel. All
experiments run on CPUs. GPU capacities and serving latencies are modeled
inputs; the benchmarks measure allocation software.

The measured results include a same-WSL Python/C++ comparison, parallel campaign
scaling, and conditional Stage-2 recovery and cost comparisons. The tables below
summarize those results; [the results report](docs/RESULTS.md) and
[key numbers](docs/KEY_NUMBERS.md) retain the full conditions and evidence.

## Measured results

| Benchmark | Measured result | Workload |
|---|---|---|
| Serial AGH, Python/C++ | **120.5437** core ratio; **99.7005** complete-invocation ratio | 16×4×4, load 200; ten paired rounds per boundary in the same WSL environment. |
| OpenMP campaign | **4.0223×** core speedup; **50.28%** efficiency | Fixed 32-case mixed GH/AGH batch; eight threads versus one, 30 paired rounds. |
| Cross-language checks | **63/63** pass; **3,023** final values match bitwise | 48 placement cases, including four frozen fixtures, plus 15 seeded-shuffle checks. |
| Modeled GPU rental, GH → AGH | **9 → 8 USD** per horizon (**11.1%** in C1) | Eight controlled synthetic cases; total-score reductions are much smaller. |

The matched-runtime core timer includes the public solve, traces and independent
validation, and excludes startup, parsing, projection, output and destruction.
Python also performs input validation and builds `PdmProblemData` inside that
call; C++ receives prepared coefficients before timing. Complete invocation is
a separate single-solve subprocess measurement, from startup through exit,
with a shared final-decision output schema. Core calls have an excluded
same-process warmup; invocation calls have no in-process warmup and exclude
external preflight. The ratios compare these implementations and their
preparation and trace costs. The reported ratios divide the Python median by
the C++ median. Their paired-bootstrap
95% intervals are **[109.7530, 131.2151]** for core and
**[93.2556, 107.2592]** for invocation.

OpenMP parallelizes independent allocation cases; each GH/AGH solve retains
serial arithmetic and ordered acceptance. The reported setting is unsorted
`cores/close/dynamic/chunk1` with the default allocator. Its core-speedup
interval is **[3.7636, 4.4243]**. Sorting cases did not establish an improvement,
and the experimental parallel validator showed no robust whole-call benefit;
production validation remains serial. Earlier campaigns have separate timer
boundaries and baselines, detailed in [RESULTS.md](docs/RESULTS.md).

### Stage-2 results and numerical policy

These three evaluations use distinct evidence and acceptance conditions:

| Evaluation | Usable operational LPs | Recovery and paired modeled cost |
|---|---:|---|
| Original October 13 stress campaign | **646/1,850** | Adaptation recovers **256/1,344** frozen-routing failures (19.05%). Summed C4+C5 falls **5.8574%** over **390** usable same-scenario pairs. |
| Retrospective replay of those decisions, with optional relative objective tolerance | **850/1,850** | Recovers all **204/204** objective-only rejections; adaptation recovers **344/1,344** frozen failures (25.5952%). Paired C4+C5 reduction is **5.957974%** over **506** usable pairs. |
| New seeded October 14 campaign, with the optional Stage-2 policy selected | **3,246/6,800** | **144/144** sources completed, **136** accepted. Recovery is **22.22–32.79%** and paired C4+C5 reduction **4.9235–5.4335%**, depending on nominal load. |

The original policy uses an absolute objective-agreement threshold of `1e-8`
USD and zero relative tolerance. The retrospective replay selects relative
`1e-12`, runs no new optimization solves, and leaves the original classifications
intact. All **1,000** originally solver-infeasible attempts remain rejected.
The new campaign also selects relative `1e-12` for Stage 2; Stage-1 acceptance
retains its absolute-only default, so eight rejected sources skip 400 planned
LPs. In the original campaign, three rejected sources skip 150 scenarios.

Cost reductions compare sums of C4+C5 only where both frozen and adapted
decisions are usable. Infeasible baselines receive no assigned savings.
Changing usable cohorts and unequal accepted method cohorts prevent a method
ranking from these pooled figures. Per-load denominators, confidence intervals
and sources are in [KEY_NUMBERS.md](docs/KEY_NUMBERS.md); the
[original stress report](docs/STAGE2_RESULTS.md) preserves the original results.

## Formulation and implementations

The formulation and GH/AGH algorithms follow Cheng and Nguyen's
[paper v2](https://arxiv.org/abs/2604.07472v2), with
[v1](https://arxiv.org/abs/2604.07472v1) supplying the explicit Stage-2 LP.
This is an independent implementation. Project interpretations and assumptions,
including dimensional adjustments for current instances, are documented in
[the model](docs/MODEL.md), [units](docs/UNITS.md) and
[extension decisions](docs/EXTENSION_DECISIONS.md). Historical fixtures retain
their explicitly selected unit convention.

| Component | Python | C++20 |
|---|---|---|
| Deterministic allocation MILP (`P_DM`) | Pyomo, with HiGHS or Gurobi | — |
| GH and AGH | Scientific reference | Serial implementations |
| Fixed-deployment Stage-2 LP | Pyomo, with coherent and historical unit conventions | — |
| Independent validation | Placement and Stage 2 | Placement |
| Parallel experiment campaigns | Input preparation and comparison | OpenMP across independent cases |

Pyomo expresses the LP/MILP; HiGHS and Gurobi solve it. GH and AGH operate on
plain domain records. Accepted decisions undergo solver-independent feasibility
and objective checks. Algorithm completion, independent acceptance and proven
solver optimality are separate outcomes; a time-limited incumbent remains an
incumbent. The [architecture guide](docs/ARCHITECTURE.md) explains these boundaries.

## Install and run

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

Both examples select HiGHS explicitly. The base package pins Pyomo 6.10.0 and
highspy 1.14.0. `SolverConfig()` defaults to Gurobi; base installations should
pass `SolverConfig(backend=SolverBackend.HIGHS)`. Gurobi needs a usable license
and the optional package: `python -m pip install -e ".[gurobi]"`.

For native execution on Linux or WSL, use GCC with C++20/OpenMP support and GNU Make:

```bash
make -C cpp -j4 all test openmp campaign-test
python scripts/check_cpp_parity.py --frozen
python scripts/check_openmp_campaign.py --output results/openmp/check
```

The [C++ guide](cpp/README.md) covers native commands, frozen inputs, sanitizers,
scheduling and profiling. The serial C++ binary needs neither Python nor a solver.

## Explore the evidence

The [presentation draft](docs/PRESENTATION_DRAFT.md) gives an English narrative,
slide text, recommended visuals, exact sources and a prompt for Claude Design.
Rendered slides are prepared separately.

- [Results](docs/RESULTS.md): allocation quality, runtime, parity and parallel efficiency.
- [Key numbers](docs/KEY_NUMBERS.md): numerical definitions, denominators, sources and replay commands.
- [Extension report](docs/EXTENSION_REPORT.md): controlled studies, negative results, provenance and limitations.
- [Experiment guide](docs/EXPERIMENTS.md): configurations and reproduction instructions.
- [Verification](docs/VALIDATION.md): recorded checks and their scope.
- [Presentation draft](docs/PRESENTATION_DRAFT.md), [brief](docs/PRESENTATION_BRIEF.md) and [design prompt](docs/CLAUDE_DESIGN_EXTENSION_PROMPT.md): narrative, visuals and claim-to-source mapping for Claude Design.
- [Publication review](docs/PUBLICATION_REVIEW.md) and [publication guide](docs/GITHUB_PREPARATION.md): baseline, checks and export workflow.

Source is under `src/llm_resource_allocation/`, native code under `cpp/`, tests
under `tests/`, and measured artifacts under `benchmarks/`. Published snapshots
include a [file allowlist](configs/publication.json) and
[SHA-256 manifest](release-manifest.json). To check an unmodified published
checkout, run `python scripts/prepare_release.py --check`.

The results establish bounded synthetic correctness and CPU performance evidence.
Modeled dollar costs are allocation scores, including penalties. Author
calibration, quantitative paper-table replication, matched large-case Gurobi
comparisons, native C++ Stage 2 and MPI remain open work. Hardware-specific
speedups and conditional cost comparisons do not establish GPU inference
performance, real cloud savings or heuristic optimality.

Software by Antonio Arbizzani Tonelli, available under the [MIT license](LICENSE).
[CITATION.cff](CITATION.cff) records software and scientific attribution.
