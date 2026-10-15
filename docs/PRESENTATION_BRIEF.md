# Presentation evidence guide

**LLM Resource Allocation: A verified reference and CPU performance study**, by
Antonio Arbizzani Tonelli, is available as a
[PDF](../presentations/llm-resource-allocation.pdf) and a
[PowerPoint file](../presentations/llm-resource-allocation.pptx). The presentation
introduces the allocation problem, the two-stage model, the Python
reference, the C++20 implementation, cross-language verification and CPU
benchmarks. Technical appendices retain units, solver comparisons and the three
separate Stage-2 evaluations. The [presentation files guide](../presentations/README.md)
records the supplied files and their checksums. Both corrected formats contain
21 content slides/pages, including the OpenMP throughput plot at position 10.
The other 20 PowerPoint slides and notes are unchanged from the first delivery;
PDF text outside page 10 is unchanged. The supplied files are preserved byte for
byte, and the reports below retain the complete OpenMP evidence.

## Scope

The formulation and GH/AGH algorithms come from Cheng and Nguyen,
[arXiv:2604.07472 v2](https://arxiv.org/abs/2604.07472v2), with
[v1](https://arxiv.org/abs/2604.07472v1) supplying the explicit Stage-2 LP.
The project contributes its implementation, documented interpretations and unit
conventions, independent validation, native port and recorded experiments.
It does not claim numerical replication of the paper's tables.

All reported experiments run allocation software on **CPUs with synthetic
inputs**. GPU capacities and serving latencies are **modeled coefficients**.
Dollar-valued objectives include model costs and penalties; they are not observed
cloud bills. Python supplies the scientific reference and independent validator;
Pyomo constructs LP/MILP models for a configured solver. Serial C++20 implements
Stage-1 GH/AGH. OpenMP distributes **independent cases** across CPU threads while
each solve retains serial arithmetic and acceptance order.

See [MODEL.md](MODEL.md), [ARCHITECTURE.md](ARCHITECTURE.md) and
[VALIDATION.md](VALIDATION.md) for the scientific and implementation boundaries.
Native C++ Stage 2 and MPI remain future work.

## Sources for the main results

The deck identifies public source commit
[`80a9625ab62a3c5c70ede7a9dae97a61158e250a`](https://github.com/antonio-arbizzani-tonelli/llm-resource-allocation/commit/80a9625ab62a3c5c70ede7a9dae97a61158e250a).
Its numerical payload matches extension checkpoint
`543ad4e640100a4c2a69febf17fe885bd452861e`. Documentation and presentation
publication adds no measurements. [KEY_NUMBERS.md](KEY_NUMBERS.md) and
[EXTENSION_REPORT.md](EXTENSION_REPORT.md) retain exact conditions, estimators,
intervals and replay provenance.

| Result | Exact evidence and selection | Interpretation |
|---|---|---|
| Cross-language verification | [Serial parity](../benchmarks/portfolio/raw/serial/parity.json): `passed=63`, `total=63`; sums of `cases[*].compared_numeric_values` and `bitwise_difference_count` give 3,023 and zero. | Bounded synthetic checks, including placement fixtures and seeded-shuffle checks; no general proof of equivalence. |
| Matched AGH runtime | [WP1 analysis](../benchmarks/matched_runtime_2026-10-14/analysis/analysis.json): `case=16x4x4_load200_agh`, separately `boundary=core` and `boundary=invocation`. | Python/C++ ratios of medians: 120.5437 core, 95% CI [109.7530, 131.2151]; 99.7005 complete invocation, CI [93.2556, 107.2592]. Ten paired rounds per boundary in one WSL environment. |
| OpenMP campaign throughput | [WP2 analysis](../benchmarks/openmp_diagnostics_2026-10-14/analysis/extension.json): setting `8_cores_close_dynamic_1_False_None` against `1_cores_close_dynamic_1_False_None`. | Fixed mixed 32-case GH/AGH batch, 30 paired core rounds; speedup 4.0223, 95% CI [3.7636, 4.4243], efficiency 50.28%. |
| Native scaling and solver comparisons | [Scaling and solver sections](EXTENSION_REPORT.md), with the linked raw and analysis artifacts. | Runtime and accepted-solution evidence for the specified cases. Selected configurations and time-limited incumbents do not establish universal performance or heuristic optimality. |

Core timing covers a fresh public solve, traces and independent validation. It
excludes startup, parsing, projection, output and destruction. Python validates
input and constructs `PdmProblemData` inside its public call; C++ receives a
prepared coefficient lattice before timing. Complete invocation measures a
separate Linux subprocess from startup through exit. These ratios compare the
recorded implementations and their preparation costs; they do not isolate a
programming-language effect. Keep ratios of medians separate from medians of
paired ratios and preserve the [recorded environment](EXTENSION_ENVIRONMENT.md).

The 30-round OpenMP campaign remains separate from the earlier 18-round campaign
in [PERFORMANCE.md](PERFORMANCE.md). Selected settings were evaluated on the same
data used to select them, without independent confirmation. The recorded
diagnostics do not establish physical causes for efficiency loss.

## Stage-2 appendices

The following evidence sets use different acceptance policies or inputs and must
be read separately:

| Evidence set | Usable / attempted LPs | Recovery / frozen-routing failures | Paired C4+C5 cost cohort |
|---|---:|---:|---|
| Original 13 October campaign, standard absolute-only objective agreement | 646/1,850 | 256/1,344 | 5.857419% reduction over 390 usable pairs |
| Retrospective replay, optional relative objective tolerance 1e-12 | 850/1,850 | 344/1,344 | 5.957974%, 95% CI [5.745418%, 6.063490%], over 506 usable pairs |
| New 14 October solves, explicit relative objective tolerance 1e-12 | 3,246/6,800 | Load-specific denominators | Separate load-specific pairs and intervals |

Sources: [original stress report](STAGE2_RESULTS.md),
[retrospective policy analysis](../benchmarks/stage2_policy_2026-10-14/analysis.json),
`old_policy` and `selected_policy`, and
[new-campaign analysis](../benchmarks/stage2_robustness_2026-10-14/analysis.json),
`by_load`. The retrospective replay solves no LP and repairs no decision. The
standard objective-agreement policy remains absolute 1e-8 USD and relative zero;
constraint tolerances and Stage-1 acceptance are unchanged.

Cost reduction is `(sum frozen C4+C5 - sum adapted C4+C5) / sum frozen C4+C5`
over identical scenarios where both decisions are usable. Infeasible baselines
receive no savings value. Different accepted cohorts support neither a causal
comparison of policies nor a general ranking of methods. These are conditional
synthetic-grid results, not measured cloud savings.
