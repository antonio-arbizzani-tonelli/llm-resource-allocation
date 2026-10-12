# Architecture and scientific contracts

The project separates mathematical correctness from solver status and execution
speed. Python supplies the readable scientific reference, exact optimization,
and operational evaluation. C++20 implements the Stage-1 heuristics and their
independent checks; OpenMP schedules independent cases. The
[project overview](../README.md) introduces the problem, and the
[results report](RESULTS.md) describes the retained measurements.

## From problem data to accepted decisions

```text
validated problem data
    -> heuristic or algebraic optimization model
    -> plain decision state
    -> independent constraints and objective recomputation
    -> accepted result or explicit failure evidence
    -> experiment/reporting layer
```

Core algorithms consume domain records. They do not read files, select paper
tables, plot results, or inspect live solver variables. Exact runs add a
solver adapter, raw extraction, and domain normalization between model
construction and the plain decision state. Normalization does not rebalance
demand, repair auxiliary products, or adjust a decision to pass constraints.

| Layer | Main source | Contract |
|---|---|---|
| Domain and units | [domain](../src/llm_resource_allocation/domain) | Explicit typed inputs, immutable records, unit conventions, and boundary validation. |
| Scientific arithmetic | [math](../src/llm_resource_allocation/math) | Memory, capacity, delay, storage, and objective quantities independent of solvers. |
| GH and AGH | [algorithms](../src/llm_resource_allocation/algorithms) | Ordered construction/local search with traceable decisions and local seeded randomness. |
| Exact Stage 1 | [pyomo_pdm.py](../src/llm_resource_allocation/optimization/pyomo_pdm.py), [pdm_run.py](../src/llm_resource_allocation/optimization/pdm_run.py) | Deterministic mixed-integer model, extraction, solver evidence, and independent acceptance. |
| Stage 2 | [pyomo_stage2.py](../src/llm_resource_allocation/optimization/pyomo_stage2.py), [stage2_run.py](../src/llm_resource_allocation/optimization/stage2_run.py) | Operational LP on a fixed deployment under supplied realized demand/delays. |
| Independent validation | [placement.py](../src/llm_resource_allocation/validation/placement.py), [stage2.py](../src/llm_resource_allocation/validation/stage2.py) | Plain-data constraint residuals and objective recomputation. |
| Experiments | [experiments](../src/llm_resource_allocation/experiments) | Configured workloads, scenarios, repeated measurements, and retained provenance. |
| Native execution | [C++ guide](../cpp/README.md) | The same Stage-1 GH/AGH semantics, dense owned states, and independent-case scheduling. |

Pyomo is the algebraic modeling layer. HiGHS provides the open-source backend;
Gurobi is optional and requires its own installation/license. Backend choice
does not change scientific equations. A solver-reported optimum applies to
the constructed model, while a time-limited feasible incumbent retains its
distinct status. GH/AGH results are heuristic placements.

## Planning and operational adaptation

Stage 1 chooses deployments, parallel configurations, and nominal traffic
allocation under resource and service constraints. GH constructs a placement;
AGH adds query orderings, relocate, consolidation, and ordered multi-start.
M1 screens minimum parallelism, M2 scores candidate coverage, and M3 evaluates
delay-driven upgrades. The native API exposes these roles directly as
`select_m1`, `evaluate_m2`, `select_m3`, `run_gh`, and `run_agh`.

Python Stage 2 keeps the accepted Stage-1 deployment fixed and reoptimizes
operational routing and unmet demand for a supplied scenario. The
[integration adapter](../src/llm_resource_allocation/optimization/stage2_adapter.py)
checks the source result before constructing the fixed deployment. The
[integration runner](../src/llm_resource_allocation/optimization/stage2_integration.py)
retains source, scenario, LP, solver, and validation evidence, including
failures at each boundary. It does not silently replace a rejected Stage-1
source with a different placement.

Current units are explicit: requests/hour, seconds/request, decimal GB, and
period-wide USD. Historical literal conventions remain labelled separately.
Scenario evaluation preserves the selected unit convention and paper version;
results with different conventions are not merged into one benchmark.

## State, ordering, and numerical policy

In C++, `Problem::prepare()` validates external input and derives configuration
indices. Vectors follow query/model/tier order; the route index is
`(i * J + j) * K + k`. `Placement` owns routing fractions `x`, route-use flags
`z`, active-deployment flags `q`, unmet fractions `u`, configuration choices
`w`, GPU counts `y`, and supplied auxiliary products `v`. The validator uses
all these decisions directly, including `v`.

Results own trace snapshots. Local-search candidates copy their input, pass
the appropriate feasibility/conservation/objective checks, and become current
state only after acceptance. Public inputs are validated at their owning
boundary; internal records preserve the evidence produced by that boundary.
Algorithms do not mutate caller-owned state and roll it back later.

Stable ties, canonical scans, seeded shuffles, first acceptance, and early
stopping are part of reproducibility. C++ preserves Python's distinct floating
summation conventions and disables floating contraction/fast-math. Solver,
normalization, feasibility, and objective-comparison tolerances have separate
roles. Thresholds classify residuals; they do not alter scientific arithmetic.
Algorithm completion and independent feasibility are reported separately.

## Where parallelism belongs

The OpenMP campaign runner gives each worker an independent prepared problem,
options, seed, and result slot. It uses scoped thread teams and static or
dynamic scheduling, joins before publishing output, and preserves manifest
order. Parallel execution changes throughput and work assignment while each
solve keeps its serial acceptance/stopping sequence.

The separate validation probe tests a finer-grained alternative. Its measured
benefit was inconsistent against the serial control, so it remains an
experiment. Production validation is serial. MPI and native exact/operational
LP solvers are outside the implemented scope.

Tests combine hand-derived scientific cases, solver/reference comparisons,
frozen Python/C++ fixtures, bitwise campaign comparisons, and native sanitizers.
Source hashes and raw measurement samples connect reported results to the
implementation used. These checks support the tested scope; synthetic cases
and trace-shaped workloads retain their own provenance in the results report.
