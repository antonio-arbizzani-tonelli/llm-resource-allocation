# LLM Resource Allocation

Scientific replication and performance-engineering project based on two versions of the same work:

- `2604.07472v2.pdf` — *Scalable Joint Resource Allocation for SLO-Constrained LLM Inference in Heterogeneous GPU Clouds*
- `2604.07472v1.pdf` — *Fast Heterogeneous Serving: Scalable Mixed-Scale LLM Allocation for SLO-Constrained Inference*

Paper v2 is the primary scientific specification. Paper v1 is retained as a required secondary source, particularly for its explicit Stage-2 operational LP and for versioned experimental comparisons.

The installable project is `llm-resource-allocation`; its Python package is
`llm_resource_allocation`. The GitHub snapshot currently includes domain types,
mathematical primitives, synthetic placement fixtures, and independent placement
and objective validation, plus the deterministic `P_DM` problem data, Pyomo
model builder, raw extraction, domain normalization, HiGHS/Gurobi solver adapter,
and independently validated run records, with focused solver/run tests.
Publication proceeds component by component. The
implementation status, test command, and documentation map below describe the
full local reference; Stage-2 optimization, algorithms, experiments, the remaining
tests, and documentation remain outside the published
snapshot.

## Project goals

The project is developed in three phases:

1. **Python scientific reference implementation**
2. **Serial C++ implementation**
3. **C++ + MPI performance and scalability implementation**

The historical Python snapshot `PYREF-2026-09-14-M11.2` is preserved. The
current Python reference and its later revisions are identified in
`docs/REPLICATION_STATUS.md` for serial C++ parity work. Its priorities are,
in order:

1. correctness;
2. verifiability;
3. reproducibility;
4. clarity;
5. performance.

Algorithms, numerical values, or model semantics must not be altered merely to obtain results closer to those reported in the papers.

## Scientific components

The reference implementation separates the following components:

- **`P_DM` / DM** — exact deterministic placement MILP;
- **GH** — Greedy Heuristic;
- **AGH** — Adaptive Greedy Heuristic;
- **Stage 2** — fixed-deployment operational routing LP;
- **independent validation** — solver-independent objective and constraint checking;
- **experiment protocols** — stress, rolling, sensitivity, and paper-comparison workflows.

Pyomo is used only where an LP/MILP is scientifically present. Procedural algorithms such as GH and AGH remain ordinary Python logic and are kept separate from solver-specific objects.

The Python design combines immutable domain/evidence objects, configured
independent validators, and pure mathematical/algorithmic functions. See
[Python design and ownership](docs/PYTHON_DESIGN.md) for responsibilities,
usage, and the rationale grounded in the supplied course material.

## Current status

The exact `P_DM` pipeline, GH, and AGH are complete on deterministic synthetic verification cases.

AGH currently includes:

- deterministic and random ordering infrastructure;
- ordered GH construction;
- one prospective relocate move;
- deterministic first-improvement relocate scanning;
- accepted-state refresh within a pass;
- up to three relocate passes;
- transactional whole-route GPU consolidation;
- one deterministic ascending-load consolidation scan with strict full-objective acceptance;
- one complete supplied-ordering start through GH, relocate, consolidation, and fresh independent validation;
- the complete eight-deterministic-plus-adaptive-random sequential schedule;
- strict incumbent selection and global five-consecutive-nonimproving stopping with immutable trace evidence;
- a public final AGH result that freshly and independently validates the exact retained incumbent and its full versioned C1-C5 objective.

The exact single-scenario Stage-2 operational LP is implemented through a
public immutable runner with strict transport, independent validation, typed
failure evidence, and separate D-0067 C4+C5 optimization versus realized C3
reporting. One canonical adapter now converts accepted `P_DM`, GH, and AGH
results to the same fixed `z,w,y` boundary without carrying Stage-1 `x,u`.
One explicit realized scenario can then be evaluated through the existing
Stage-2 runner with immutable integrated evidence. An explicit assumed
sampling policy can now reproducibly generate one independently domain-checked
scenario without changing the audited paper protocol. Explicit ordered
scenario sequences can be evaluated and aggregated, and a bounded immutable
runner now composes policy, local namespaced generation, repeated Stage-2
evaluation, expected cost, and strict SLO-violation evidence. This is synthetic
reference infrastructure; the unpublished paper sampler and calibrated
paper-scale experiment remain unavailable.

The same bounded path is verified for explicit v1 and v2 semantics, and a
controlled comparison layer separates objective-only, protocol/scenario-only,
and combined native-path differences. These remain synthetic/reference checks,
not paper numerical replication.

No exact numerical reproduction of the published paper experiments is currently claimed because the papers do not provide all parameters required to reconstruct the complete experimental instance.

Milestone 11's historical frozen snapshot passed 730/730 tests on the declared
synthetic/reference scope. See `docs/PYTHON_REFERENCE_FREEZE.md` and its
historical SHA-256 manifest; the current regression and file identity are in
`docs/REPLICATION_STATUS.md`. This is not a paper numerical-replication claim.

For the authoritative and continuously updated status, see:

`docs/REPLICATION_STATUS.md`

## Installation

Python >= 3.13 is required.

```bash
python -m pip install -e .
```

For example, a published synthetic fixture is available through:

```python
from llm_resource_allocation.data.tiny_instances import make_minimal_tiny_instance

instance = make_minimal_tiny_instance()
```

The published deterministic model can be constructed directly:

```python
from llm_resource_allocation.optimization.problem_data import PdmProblemData
from llm_resource_allocation.optimization.pyomo_pdm import build_pdm_pyomo_model

problem_data = PdmProblemData(instance)
model = build_pdm_pyomo_model(problem_data)
```

This creates an unsolved Pyomo model with ordered variables, objective, and
constraints. Independent objective comparisons use `ObjectiveComparison(...)`
directly; the former `compare_objective_values` wrapper has been removed.

Both papers report Python 3.13 and Gurobi 11 for their exact optimization experiments. Development and CI also support HiGHS through Pyomo APPSI.

Execute and independently validate a complete deterministic run with:

```python
from llm_resource_allocation.optimization.pdm_run import execute_and_record_pdm_run
from llm_resource_allocation.optimization.solver import SolverConfig

record = execute_and_record_pdm_run(problem_data, SolverConfig())
print(record.accepted_run)
```

HiGHS is the default backend. Optional Gurobi support uses `gurobipy==13.0.3`:
install `python -m pip install -e ".[gurobi]"` and configure a valid license
separately, then select `SolverConfig(backend=SolverBackend.GUROBI)` after
importing `SolverBackend` from the solver module. Acceptance requires independent
feasibility and objective agreement; it does not by itself establish optimality.

## Tests

Run the complete regression suite with:

```bash
python -m unittest discover -s tests -q
```

During development, prefer focused tests for the component being modified. Run the complete repository regression at milestone closure or when repository state is uncertain.

A passing test suite is implementation evidence, not by itself evidence of numerical paper replication.

## Documentation

- `AGENTS.md`
  Permanent repository rules for scientific integrity, architecture, reading policy, verification, documentation, and handoffs.

- `docs/REPLICATION_STATUS.md`
  Authoritative current implementation and replication status, including the active next milestone.

- `docs/DECISIONS_INDEX.md`
  Compact index of scientific and implementation decisions.

- `docs/DECISIONS.md`
  Complete append-only decision record with provenance, ambiguity, impact, and testability.

- `docs/PAPER_COMPARISON.md`
  Material scientific and experimental differences between paper v1 and v2.

- `docs/PYTHON_REFERENCE_AUDIT.md`
  Final pre-freeze scientific, API, provenance, fixture, determinism,
  dependency, documentation, and test-readiness audit.

- `docs/PYTHON_REFERENCE_FREEZE.md`
  Authoritative frozen Python scope, APIs, parity fixtures, environment,
  tolerance contract, limits, verification, and freeze declaration.

- `docs/PYTHON_REFERENCE_SHA256SUMS.txt`
  Deterministically ordered SHA-256 identity for the frozen scientific files.

- `docs/model/MATHEMATICAL_MODEL.md`
  High-level scientific component map and links to the detailed model documents.

- `docs/model/PDM.md`
  Exact placement formulation, Pyomo model boundary, solver transport, extraction, normalization, independent validation, and exact-baseline evidence.

- `docs/model/GH.md`
  M1-M3 and the complete Greedy Heuristic reference implementation.

- `docs/model/AGH.md`
  Adaptive Greedy Heuristic specification and implementation status, including ordering, relocate, consolidation, and multi-start orchestration.

- `docs/model/STAGE2.md`
  Fixed-deployment operational Stage-2 LP and its versioned interpretation.

- `docs/model/EXPERIMENT_PROTOCOLS.md`
  Published experimental setup, stress and rolling protocols, Azure calibration issues, reference targets, and known missing inputs.

- `docs/MACROPROMPT_SUMMARIES/`
  Persistent milestone handoffs. Normally only the latest relevant handoff should be needed to resume work.

## Scientific evidence policy

A program run is not automatically a replication result.

Scientific results are accepted only after the produced decisions pass the independent objective and constraint validation appropriate to that component. Synthetic verification cases, solver evidence, algorithm completion, and numerical paper replication are kept as distinct evidence levels.

Published table values are treated as external regression targets, never as values to tune the implementation toward.

## Version policy

Use a shared scientific core whenever the two paper versions are compatible.

Version-specific behavior must remain explicit when the papers materially differ, including objective scaling, uncertainty protocols, experimental targets, or other published semantics.

Do not silently combine incompatible assumptions from v1 and v2.
