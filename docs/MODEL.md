# Allocation and operational rerouting

The project follows Cheng and Nguyen's [v2 formulation](https://arxiv.org/abs/2604.07472v2),
using [v1 Eq. (12a)–(12f)](https://arxiv.org/abs/2604.07472v1) for the explicit
operational LP. The algorithms are implemented independently here; the authors'
calibration data have not been recovered.

## Stage 1: choose a deployment

The deterministic problem jointly selects GPU counts, model placement,
tensor/pipeline parallelism, routed fractions and unmet fractions. It minimizes
five period costs: GPU rental C1, model storage C2, data storage C3, delay C4
and unmet demand C5. Constraints enforce demand balance, routing admission,
parallelism linkage, compute, per-GPU memory, per-query storage, latency, error
and a resource budget for C1+C2+C3.

`P_DM` expresses the problem as a MILP through Pyomo. GH constructs a placement
with the paper's M1–M3 mechanisms. AGH explores deterministic and seeded starts,
then applies relocate and consolidation. A complete heuristic construction is
accepted only if the independent validator accepts its decisions. A heuristic
has no optimality certificate; an exact solver's feasible time-limit incumbent
also remains distinct from a proven optimum.

| Decision | Meaning |
|---|---|
| `x[i,j,k]`, `u[i]` | Routed and unmet fractions for query type i. |
| `z[i,j,k]`, `q[j,k]` | Route admission and active deployment. |
| `w[j,k,n,m]`, `y[j,k]` | Chosen TP/PP configuration and GPU count. |
| `v[i,j,k,n,m]` | Linearized routing/configuration product. |

The validator evaluates the supplied auxiliary variable directly. It never
replaces it by a repaired product or rescales routing to force balance.

## Physical units and explicit assumptions

New instances use dimensionally coherent v2 units. Historical fixtures retain
the printed arithmetic through an explicit `LITERAL_PAPER` convention. These
are separate numerical conventions; results retain their convention.

With λ in requests/hour, a horizon H in hours, KV residency T in seconds,
data residency R in hours and delays in seconds/request:

```text
KV memory = sum beta * tokens * T * (lambda / 3600) * v / (TP * PP)
resident data = R * sum theta * tokens * lambda * x
C3 = H * storage_price * resident data
C4 = sum rho * 1000 * processing_delay * lambda * H
C5 = H * sum phi * u
```

This dimensional interpretation is a project choice, not an assertion that the
paper printed these conversion factors. R defaults to one hour and is
configurable. Storage capacity retains the query-indexed constraint closure.
The detailed [unit contract](UNITS.md) states all units and formulas.

## Stage 2: adapt routing with deployment fixed

Stage 2 receives an accepted Stage-1 deployment and an explicit realized
scenario. GPU counts `y*`, admissions `z*` and parallelism `w*` remain fixed;
the LP chooses only continuous `x` and `u`.

It minimizes C4+C5 subject to demand balance, realized compute capacity,
realized latency and error SLOs, unmet-fraction bounds and `x <= z*`. It follows
the paper's LP scope: routing-dependent memory, storage and the Stage-1 budget
are not reimposed as operational constraints. Reported C3 uses realized
arrivals and is separate from the optimized objective. Scenario-average total
cost is fixed C1+C2 plus mean(C3+C4+C5).

Coherent Stage 2 uses realized λ in both C3 and C4, the same H, and the same R
as the base instance. C4 includes the seconds-to-milliseconds factor. The
historical literal branch preserves its earlier arithmetic. Coherent v1 inputs
are rejected because that combination has no defined project convention.

Realizations explicitly supply arrivals, both delay components and effective
errors. Seeded generation must declare distribution, dependence and component
mapping assumptions. The papers do not supply a fully executable sampler, so
an assumed sampler cannot be described as recovered author data.

## Acceptance and traceability

Inputs, solver status, extracted decisions, numerical normalization,
independent feasibility and objective agreement are separate evidence.
Different numerical policies govern solver tolerances, extraction, feasibility
and objective comparison. A residual tolerance classifies a computed equation;
it does not change its arithmetic.

See [the architecture](ARCHITECTURE.md) for implementation responsibilities and
[the verification report](VALIDATION.md) for the release's evidence.
