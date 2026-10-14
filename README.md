# LLM Resource Allocation

Allocate LLM workloads across heterogeneous GPU tiers by choosing deployments,
tensor/pipeline parallelism and demand routing under latency, error, capacity
and budget constraints. The objective combines rental and storage costs with
delay and unmet-demand penalties. **Stage 1** selects deployment and routing;
**Stage 2** adjusts routing to realized demand while keeping deployment fixed.

Python provides the scientific reference and Pyomo LP/MILP models; HiGHS or
Gurobi solves those models. Serial C++20 implements the GH/AGH allocation
heuristics, while OpenMP distributes independent cases across CPU threads.
**All experiments use synthetic inputs on CPUs.** GPU capacities and serving
latencies are modeled inputs, not measurements of GPU inference.

## Selected results

| Study | Rounded result | Workload |
|---|---|---|
| Serial AGH, Python/C++ | About **120× core** and **100× complete-invocation** ratios | 16 queries, four models, four GPU tiers, load 200; ten paired rounds per boundary in the same WSL environment. |
| OpenMP campaign | About **4× core speedup**, **50% efficiency** | Fixed 32-case mixed GH/AGH batch; eight threads versus one, 30 paired rounds. |
| Cross-language verification | **63/63** checks pass; about **3,000** final values match bitwise | 48 placement cases, including four frozen fixtures, plus 15 seeded-shuffle checks. |

Timing ratios divide the Python median by the C++ median. Core timing includes
the public solve, traces and independent validation. Python also validates inputs
and constructs `PdmProblemData` inside that call; C++ receives prepared
coefficients before timing. Complete invocation separately measures a one-solve
subprocess from startup through exit. These are implementation-specific comparisons,
with different preparation costs, rather than general language-speed claims.
Each OpenMP solve keeps serial arithmetic and ordered acceptance.

[Results](docs/RESULTS.md) and [key numbers](docs/KEY_NUMBERS.md) provide exact
values, timer boundaries, confidence intervals, scheduling settings and evidence.

### Stage 2

In the seeded 14 October 2026 campaign, adaptation recovered about **22–33%**
of frozen-routing failures, depending on load. On scenarios where both decisions
were usable, summed delay/unmet-demand cost (C4+C5) fell by about **5%**. Infeasible
baselines receive no assigned savings, and unequal accepted cohorts support no
method ranking. The original stress campaign, retrospective optional-policy
replay and new seeded campaign remain separate evaluations with their respective
acceptance policies; the replay ran no new solves. See the
[Stage-2 results](docs/RESULTS.md#stage-2-adaptation-three-separate-evidence-sets),
[key numbers](docs/KEY_NUMBERS.md) and
[original stress report](docs/STAGE2_RESULTS.md) for denominators and conditions.

## Model and validation

The formulation follows Cheng and Nguyen's [paper v2](https://arxiv.org/abs/2604.07472v2),
with [v1](https://arxiv.org/abs/2604.07472v1) supplying the explicit Stage-2 LP.
This independent implementation documents interpretations and dimensional
adjustments in the [model](docs/MODEL.md), [units](docs/UNITS.md) and
[extension decisions](docs/EXTENSION_DECISIONS.md). Historical fixtures retain
their selected unit convention.

GH/AGH operate on plain domain records; Pyomo expresses optimization models.
Accepted decisions undergo solver-independent feasibility and objective checks.
Algorithm completion, independent acceptance and proven optimality are distinct:
a time-limited incumbent is not a proven optimum. See the
[architecture guide](docs/ARCHITECTURE.md).

## Install and run

Use Python 3.13 or later. From the repository root:

~~~bash
python -m venv .venv
~~~

Activate with `.venv\Scripts\Activate.ps1` in PowerShell or
`source .venv/bin/activate` on Linux/macOS, then:

~~~bash
python -m pip install -e .
python examples/stage1_quickstart.py
python examples/stage2_quickstart.py
python -m unittest discover -s tests -q
~~~

The base package pins Pyomo 6.10.0 and highspy 1.14.0. Both examples explicitly
select HiGHS. `SolverConfig()` defaults to Gurobi; base installations should
pass `SolverConfig(backend=SolverBackend.HIGHS)`. Gurobi requires a usable license
and `python -m pip install -e '.[gurobi]'`.

For Linux/WSL native execution, install GCC with C++20/OpenMP support and GNU Make:

~~~bash
make -C cpp -j4 all test openmp campaign-test
python scripts/check_cpp_parity.py --frozen
python scripts/check_openmp_campaign.py --output results/openmp/check
~~~

The serial C++ binary needs neither Python nor a solver. The
[C++ guide](cpp/README.md) covers native commands, scheduling and profiling.

## Further reading and limits

- [Extension report](docs/EXTENSION_REPORT.md): methods, controlled studies and negative results.
- [Experiment guide](docs/EXPERIMENTS.md) and [verification](docs/VALIDATION.md): reproduction and recorded checks.
- [Presentation draft](docs/PRESENTATION_DRAFT.md): narrative, visuals, sources and Claude Design prompt.
- [Publication guide](docs/GITHUB_PREPARATION.md): export workflow, [allowlist](configs/publication.json) and [SHA-256 manifest](release-manifest.json). Verify an unmodified published checkout with `python scripts/prepare_release.py --check`.

The evidence establishes bounded synthetic correctness and CPU performance.
Modeled dollar costs include penalties; they are not cloud bills. Author
calibration, paper-table numerical replication, matched larger Gurobi comparisons,
native C++ Stage 2 and MPI remain open. Hardware-specific timings and conditional
cost reductions do not establish GPU-serving performance, real cloud savings
or heuristic optimality.

Software by Antonio Arbizzani Tonelli, under the [MIT license](LICENSE).
[CITATION.cff](CITATION.cff) records attribution.
