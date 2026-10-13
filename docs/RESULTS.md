# What the experiments establish

The project follows one engineering question: can allocation software become
faster while retaining the same scientific decisions? The evidence connects a
Python reference, independent feasibility checks, a C++ port and parallel
campaigns. Cost comparisons measure synthetic modeled decisions; runtime
comparisons measure the CPU allocation software.

## Larger-instance measurements, October 13

The [new performance study](PERFORMANCE.md) extends the engineering evidence
through 256x4x4 and 128x8x8 query/model/tier dimensions. Across nine shapes,
18 native method points retain five samples each. Sixteen full Python reference
comparisons check 185,832 numeric values without a bitwise difference. AGH
Python encounters MemoryError at the two largest endpoints; their separate
native measurements pass the existing Python final-decision validator and
bitwise objective checks, with full algorithm parity explicitly unavailable.

AGH's C++ median is **2.889 s at 128x4x4**, **7.156 s at 256x4x4** and
**7.471 s at 128x8x8**. The 128x4x4 full Python reference check takes
**340.978 s**, with projection/validation included. This comparison uses
different timer scopes and does not isolate a language effect.

The 32/64/128-case OpenMP study retains 18 rounds per setting. Its best observed
median core speedup is **4.20x**, with **2.27x** complete-invocation speedup and
**52.5%** observed-team efficiency: 32 mixed cases, dynamic schedule, eight
threads. For that batch, static scheduling reaches **3.08x** median core
speedup. Larger batches do not establish larger relative core gains. The
full setting table, IQRs and separate process timers remain visible.

![Larger query counts](../benchmarks/performance_2026-10-13/analysis/plots/query_scaling.png)

The [analysis JSON](../benchmarks/performance_2026-10-13/analysis/analysis.json)
and [compressed evidence](../benchmarks/performance_2026-10-13/evidence.zip)
preserve the verification mode, failures, samples and provenance. These results
add measured scalability and resource limits. The separate forty-worker Stage-2
study below is also complete. The later sections retain the October 11–12
evidence and scopes.

## Stage-2 adaptation and numerical boundaries, October 13

The [complete stress report](STAGE2_RESULTS.md) records **40/40 completed workers**,
**37/40 accepted sources** and **1,850 LP attempts**. Of those attempts, **646**
are scientifically usable, **1,000** are solver-infeasible, and **204** pass
independent constraints but fail the unchanged absolute objective-agreement
threshold. Three rejected P_DM sources explicitly skip 150 scenarios.

Adaptation recovers **256/1,344 frozen-routing failures (19.05%)**. On the
**390 identical scenarios where both decisions are usable**, summed modeled
operational C4+C5 decreases **5.8574%**. These are deterministic synthetic
cohorts, not real-world probabilities, a cloud bill, or a method ranking.

The 204 objective rejections all occur at load factor 100000. Solver/reference
differences are one to three floating-point spacings, with maximum relative
difference 3.4017e-16, but exceed the **1e-8 USD absolute threshold**. No rejected
metrics are made usable and no tolerance is changed. No complete fifty-point
grid is accepted. All eight Stage-1 P_DM solves retain time-limited incumbent
status rather than proven optimality.

![Operational stress outcomes](../benchmarks/stage2_stress_2026-10-13/plots/outcomes.png)

The [dataset](../benchmarks/stage2_stress_2026-10-13/README.md) supplies all
scenario/solver/validation evidence, numerical diagnostics and a solver-free
frozen-source replay. Larger-instance C++/OpenMP timings remain a separate
campaign with their own timer scopes.

The timing campaigns were recorded on October 11–12, 2026. They remain historical
measurements when the source later changes. The retained manifests identify
the measured inputs, configuration, environment and source hashes. The
[compact JSON](../benchmarks/portfolio/summary.json) and
[indicator CSV](../benchmarks/portfolio/indicators.csv) derive their values from
the shipped observations, without running the algorithms again.

## Allocation quality and solver evidence

The coherent Stage-1 campaign compares P_DM, GH and AGH on eight shared
synthetic cases: 2×2×2, 4×4×5, 6×6×10 and 10×10×10 query/model/GPU-tier
dimensions, at nominal load and a ×100,000 arrival multiplier. Each method has
one excluded warmup and three measured rounds, with seeds 37, 41 and 43.
Both exact-solver campaigns use a 20-second native optimization limit and
one-hour data residency. The complete public method call can exceed that limit.

| Indicator | Recorded value | Interpretation |
|---|---:|---|
| GH → AGH GPU rental | 9 → 8 USD per planning horizon | **11.1% reduction in C1**, in all eight cases |
| Nominal total-score reduction | 0.087–0.278% | Other components dominate; C1 saving is not a total-cost percentage |
| GH/AGH mean unmet fraction | 0% | Both serve all modeled demand in these cases |
| HiGHS accepted placements | 72/72 | Six P_DM optima, 18 feasible time-limited incumbents, 48 heuristic results |
| Gurobi accepted placements | 69/72 | Six P_DM optima, 15 accepted feasible incumbents, 48 heuristic results |

AGH lowers rental by USD 1 while C2–C5 and service match GH. Under the
compute-pressure cases its total-score reduction is below 0.000003%. Every
AGH run executes six deterministic starts, zero random starts, and no strict
incumbent improvement after the first start. This campaign demonstrates the
configured local-search behavior; it does not establish a general benefit from
additional multi-start work.

The two 2×2×2 cases are the only cases with proven P_DM optima. Larger cases
retain incumbents and weak solver bounds. At nominal 10×10×10, Gurobi's
accepted median score is 724.0209 USD, compared with HiGHS's 1274.7587 USD and
AGH's 1150.0550 USD. The 43.20% lower Gurobi incumbent changes the ordering
seen against HiGHS. These are accepted-solution comparisons, with no proven
large-case optimum. Accepted P_DM outputs have 7.5% mean unmet fraction across
query types, within their configured caps; comparing cost alone hides that
service difference.

Three Gurobi outputs on the largest pressure case pass independent constraints
but fail objective agreement: a two-spacing binary64 difference of
`1.4901161193847656e-8` USD exceeds the preserved absolute `1e-8` threshold.
They remain rejected evidence, contribute to timing counts and are excluded
from accepted quality summaries.

The [HiGHS records](../benchmarks/reference/summary.csv),
[Gurobi records](../benchmarks/gurobi/summary.csv) and
[matched backend comparison](../benchmarks/backend_comparison/summary.csv)
retain component costs, timing quartiles, acceptance and solver evidence.
The supplied physical coefficients are synthetic. These dollar-valued model
scores are not an observed cloud bill or a reproduction of a paper table.

## Cross-language verification and timing

The recorded Python/C++ suite passes **63/63 checks**: 48 placement cases,
including four frozen cases, and 15 seeded-shuffle checks. The placement
comparisons contain **3,023 final numeric values with zero bitwise differences**.
A separate six-case 16/32/64-query campaign checks **20,494 final numeric values**
with zero bitwise differences. Compared GH transitions and AGH
ordering/acceptance/stopping evidence also match; raw C++ decisions undergo
independent Python validation.

| Serial AGH case | Python minimum [s] | C++ core minimum [s] | Implementation ratio |
|---|---:|---:|---:|
| 4×2×2, load 1 | 0.120182 | 0.001485 | 80.94× |
| 8×4×4, load 200 | 1.389794 | 0.013304 | 104.47× |
| 16×4×4, load 200 | 4.774378 | 0.045939 | 103.93× |

These minima use three warm repetitions with two individual calls per runtime.
Python runs on Windows and validates original inputs while retaining richer
trace objects. C++ runs under WSL using prepared inputs; its core timer excludes
startup, parsing and output. The ratio compares those implementations and
timing boundaries, and does not isolate a language effect. The
[serial samples](../benchmarks/portfolio/raw/serial/profile.json) and
[parity records](../benchmarks/portfolio/raw/serial/parity.json) retain the
underlying evidence.

## Parallelism at the scale that pays

OpenMP executes independent allocation cases with private results, local seeds
and deterministic output order. Each GH/AGH solve keeps its serial arithmetic
and ordered acceptance. Strong scaling uses fixed 16-case workloads and the
same OpenMP-linked binary's serial schedule as the baseline.

| Fixed batch | Serial core [s] | Dynamic 8 core [s] | Speedup | Efficiency | Complete-process speedup at 8 threads |
|---|---:|---:|---:|---:|---:|
| 16 large AGH | 0.690095 | 0.133782 | **5.16×** | 64.5% | **1.73×** |
| 8 large AGH + 4 medium AGH + 4 GH | 0.410155 | 0.080913 | **5.07×** | 63.4% | **1.96×** |

Large cases are 16×4×4/load200; medium cases are 8×4×4/load200. Dynamic
four-thread core efficiencies are 85.7% and 90.4%. Mixed static eight-thread
core time is 0.128316 seconds, versus 0.080913 with dynamic scheduling: the
same deliberately clustered jobs make scheduling cost visible.

![Core and complete-process scaling](../benchmarks/portfolio/plots/openmp_scaling.png)

The core timer includes first team creation in each child process and excludes
parse/output/destruction. Complete invocation includes Windows/WSL startup,
transport and those costs. Its uniform dynamic eight-thread minimum is
0.579886 seconds versus 1.002606 serial; mixed is 0.295880 versus 0.581234.
More threads do not consistently improve complete-process time. These
eight-thread ratios are observations at that setting, rather than the maximum
over every configuration.

Measurements use an Intel i7-13620H, GCC 13.3.0, C++20 `-O2 -g
-ffp-contract=off`, Ubuntu 24.04 under WSL, fixed core affinity and three
rotated measurement rounds. Speedup is `serial_min/parallel_min`; efficiency
is `100*speedup/observed_threads`. One-thread variation is visible and is not
a parallel speedup. Full warm evidence and compact timed outputs accompany
the [raw profile](../benchmarks/portfolio/raw/openmp/profile.json). This is
campaign throughput, with no single-instance or GPU-serving speedup claim.

## A measured decision to keep validation serial

The separate validator experiment tests original append, serial fixed slots
and OpenMP query blocks on 16/32/64-query cases. In the active-wait rotated
AGH comparison:

| Queries | Serial slots [s] | OMP 2 [s] | OMP 4 [s] | OMP 8 [s] |
|---|---:|---:|---:|---:|
| 32 | 0.102698 | 0.109183 | 0.133577 | 0.205992 |
| 64 | 0.559108 | 0.575182 | 0.631874 | 0.707663 |

![Validator experiment](../benchmarks/portfolio/plots/validation_grain.png)

Parallel regions add no robust whole-call benefit over serial slots. Passive
wait-policy comparisons are also retained: small differences are inconsistent
across minima and medians. Production validation stays serial, and slots
remain experimental because GH and complete-invocation evidence do not
consistently improve. The experiment passes 114 release and 12 sanitizer
complete scientific comparisons. This negative result explains the final
decomposition choice instead of hiding an unsuccessful optimization.

## Stage 2 and reproducibility

Stage 2 fixes deployment and re-optimizes routing and unmet fractions under
realized conditions. The [coherent example](../examples/stage2_quickstart.py)
uses one fixed GPU and explicit nominal/doubled-demand scenarios:

| Scenario | Offered [requests/h] | Routed fraction | Served [requests/h] | Unmet fraction | Reporting cost [USD / 3 h] |
|---|---:|---:|---:|---:|---:|
| Nominal | 6 | 1.0 | 6 | 0.0 | 43.8 |
| Demand doubled | 12 | 0.5 | 6 | 0.5 | 193.8 |

Both operational LP results pass independent feasibility and objective
agreement, while deployment stays fixed. The capacity constraint limits served
volume to six requests/hour; doubled demand increases explicitly unserved
demand rather than silently overloading the fixed resource. The delay charge
stays 36 USD because doubled arrivals and halved routing preserve served
volume. The higher total includes 150 USD unmet-demand charges. This is a
hand-checkable functionality and validation demonstration, with no measured
cloud-cost or robustness gain. The [recorded JSON](../benchmarks/stage2/reference.json)
contains inputs, costs, solver version and source hashes. Historical literal-unit
scenario experiments remain separate from the current coherent formulation.
See [the model](MODEL.md) and [experiment instructions](EXPERIMENTS.md).

To check retained hashes and regenerate the indicators using the standard
library:

```bash
python scripts/summarize_portfolio_results.py
```

To render the supplied scientific figures, install the optional plotting
dependencies and add `--plots`. The
[portable artifact manifest](../benchmarks/portfolio/raw/manifest.json)
records original artifact hashes and each publication transformation.
Numeric observations are preserved; machine-specific paths are removed or
made relative. Serial numeric inputs restore the original LF transport from
Windows CRLF saved files, and their recorded transport hashes are checked.
Native source inventories describe the historical measured
code. They are not evidence that a future source revision has the same bytes.
The original large per-call observer lists are excluded from the compact
publication, while aggregate timings, full warm decisions, exact inputs and
their hashes are retained. New experiments should use a new output directory
and record their own configuration and fingerprints.
