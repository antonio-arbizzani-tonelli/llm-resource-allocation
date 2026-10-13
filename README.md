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

Scientific sources live under `src/llm_resource_allocation/`; native code under
`cpp/`; tests under `tests/`; measured evidence under `benchmarks/`.
The [publication allowlist](configs/publication.json) and
[SHA256 manifest](release-manifest.json) identify the delivered files.
Run `python scripts/prepare_release.py --check` to verify them.

This release establishes bounded synthetic correctness and performance evidence.
Recovered author calibration and a quantitative reproduction of all paper
tables remain open. MPI and native C++ solver/Stage-2 integration are future
work. A reuse license has not yet been selected.

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

