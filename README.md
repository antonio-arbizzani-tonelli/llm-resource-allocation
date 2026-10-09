# LLM Resource Allocation

Python scientific reference implementation for allocating LLM workloads across
heterogeneous GPU tiers under latency, error, capacity and budget constraints.
This publication covers the deterministic `P_DM` model, the M1–M3 mechanisms,
Greedy Heuristic (GH) and Adaptive Greedy Heuristic (AGH).

The primary specification is [paper v2](https://arxiv.org/abs/2604.07472v2),
*Scalable Joint Resource Allocation for SLO-Constrained LLM Inference in
Heterogeneous GPU Clouds*. [Paper v1](https://arxiv.org/abs/2604.07472v1),
*Fast Heterogeneous Serving: Scalable Mixed-Scale LLM Allocation for
SLO-Constrained Inference*, supplies secondary scientific and versioned objective
references.

## Installation

Python 3.13 or later is required. From the repository root:

```bash
python -m venv .venv
```

Activate the virtual environment with `.venv\Scripts\Activate.ps1` in PowerShell
or `source .venv/bin/activate` on Linux/macOS, then install:

```bash
python -m pip install -e .
```

The core dependencies are Pyomo 6.10.0 and highspy 1.14.0.

Exact model solves default to Gurobi, which requires the optional package and a
usable Gurobi license:

```bash
python -m pip install -e ".[gurobi]"
```

HiGHS can be selected explicitly, as shown below. GH and AGH implement their
construction and search loops directly; they do not call an optimization solver.
The paper's Python 3.13/Gurobi 11 environment is reference metadata, distinct from
the installed package versions.

## Run GH and AGH

The included tiny instances are synthetic, hand-checkable verification fixtures.
This example runs both heuristics on the smallest instance:

```python
from llm_resource_allocation.algorithms.agh import run_agh
from llm_resource_allocation.algorithms.gh import run_gh
from llm_resource_allocation.algorithms.gh_phase1 import GHPhase1Config
from llm_resource_allocation.data.tiny_instances import make_minimal_tiny_instance

instance = make_minimal_tiny_instance()
config = GHPhase1Config(budget_fraction=0.8)

gh = run_gh(instance, config)
print("GH completed:", gh.algorithm_completed)
print("GH feasible:", gh.independently_feasible)

agh = run_agh(instance, config, random_seed=37)
print("AGH completed:", agh.completed)
print("Executed starts:", agh.executed_start_count)
if agh.completed:
    print("Objective:", agh.final_objective_breakdown.total)
else:
    print("Failure reasons:", agh.failure_reasons)
```

`GHPhase1Config` makes the Phase-1 budget fraction explicit. Inputs are immutable
`ProblemInstance` records containing query types, model footprints, GPU tiers,
parallelism choices, workload/SLO coefficients and global resource limits.
Identifiers determine stable model/tier/route ordering. A route is identified by
`(query_id, model_id, gpu_tier_id)`.

GH activates model/tier deployments in its first phase, then routes demand and
considers parallelism upgrades in its second phase. M1 checks candidate
configurations, M2 evaluates marginal cost and coverage, and M3 selects eligible
parallelism upgrades within the remaining rental budget.

Each AGH start follows this sequence:

```text
query ordering → GH → up to 3 relocate passes → one consolidation scan
```

Relocate transfers an entire positive route fraction to a different active
model/tier pair. It adopts the first feasible destination that strictly lowers
the full objective. Consolidation scans active pairs by initial compute
utilization, tries to redistribute all routes of a source pair, and then
deactivates that source. A consolidation proposal is adopted only as a complete,
feasible, strictly improving transaction.

The multistart schedule begins with eight deterministic query orderings:
ascending and descending arrival rate, unmet-demand penalty, storage per token,
and error SLO. Exact ties retain the original query order. These are followed by
up to `R` query permutations generated with an explicit local random seed.
For `N = I × J × K` (query types × models × GPU tiers):

| Problem scale `N` | Scheduled random starts `R` |
|---|---:|
| `N ≤ 500` | 20 |
| `500 < N ≤ 2000` | 10 |
| `2000 < N ≤ 5000` | 5 |
| `N > 5000` | 3 |

The search keeps the first completed feasible start and replaces it only for a
strictly lower objective. It stops after five consecutive starts without an
incumbent change or after exhausting the schedule. Early stopping can leave
deterministic or random starts unexecuted. The seed, ordering, attempts and
termination reason remain available in the result records.

## Solve the deterministic model

```python
from llm_resource_allocation.data.tiny_instances import make_minimal_tiny_instance
from llm_resource_allocation.optimization.pdm_run import execute_and_record_pdm_run
from llm_resource_allocation.optimization.problem_data import PdmProblemData
from llm_resource_allocation.optimization.solver import SolverBackend, SolverConfig

problem = PdmProblemData(make_minimal_tiny_instance())
record = execute_and_record_pdm_run(
    problem,
    SolverConfig(backend=SolverBackend.HIGHS),
)
print("Accepted incumbent:", record.accepted_run)
print("Solver status:", record.solver_evidence.result.status)
```

Pyomo constructs the MILP. Solver execution, extraction, domain normalization,
independent feasibility validation and objective comparison are separate layers.
A time-limited feasible incumbent is not a proven optimum. An accepted run
requires an incumbent, independent feasibility and agreement between solver and
recomputed objectives.

## Validation and source map

Scientific algorithms operate on plain immutable decision records. The same
backend-neutral validator checks complete placements from GH, AGH and exact
solves, recomputing constraint residuals and all five objective components.
AGH independently revalidates its final retained incumbent and checks objective
consistency. Derived counts and output views are properties of retained evidence;
independent reports and measured solver outcomes remain stored separately.

| Location | Responsibility |
|---|---|
| [domain](src/llm_resource_allocation/domain/) | Scientific inputs, units and input validation |
| [math](src/llm_resource_allocation/math/) | Solver-independent equations and decision state |
| [algorithms](src/llm_resource_allocation/algorithms/) | M1–M3, GH and AGH construction/search |
| [optimization](src/llm_resource_allocation/optimization/) | `P_DM` model, solver adapter and extraction |
| [validation](src/llm_resource_allocation/validation/) | Independent placement and objective checks |
| [verification](src/llm_resource_allocation/verification/) | Analytic enumeration oracle for 1×1×1 cases |
| [tests](tests/) | Mathematical primitives, tiny cases and algorithm boundaries |

Run the test suite from the repository root after installation:

```bash
python -m unittest discover -s tests -q
```

The full suite includes Gurobi integration cases. Install the optional Gurobi
dependency and configure its license before running all solver tests.

Focused tests use hand-derived values and synthetic cases to check feasibility,
demand preservation, rejected-proposal state preservation, deterministic order
and strict objective improvement. This command is a verification instruction;
it does not imply that the latest revision has been executed.

## Scientific limits

GH and AGH are heuristics; their results are not certified optimal. Synthetic
verification does not establish numerical replication of the paper's tables.
Complete calibrated paper inputs are not provided by the tiny fixtures.

Paper v2 is the default scientific policy. The printed objective factors are
preserved, including the data-storage horizon/rate ambiguity and the delay term's
seconds versus per-millisecond coefficient. The objective is therefore the
implemented paper expression; a dimensionally consistent total in USD is not
claimed. Input names carry units to keep those distinctions visible.

A project license has not yet been selected; see the package metadata in
[pyproject.toml](pyproject.toml).
