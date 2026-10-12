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
| OpenMP campaign acceleration | **5.16×** | Eight threads, 16 uniform AGH cases, computation timer. |
| Complete invocation acceleration | **1.73×** | Same uniform campaign, including process and transport overhead. |
| Python/C++ verification | **63/63** | Small synthetic, seeded-ordering and frozen-reference checks. |

The [results report](docs/RESULTS.md) gives baselines, formulas, timing scopes,
raw samples, solver outcomes and limitations. These are this project's
measurements, separate from the paper's published numerical results.

![Measured campaign scaling](benchmarks/portfolio/plots/openmp_scaling.png)

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
