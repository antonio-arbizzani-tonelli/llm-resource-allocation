# Presentation brief

The [English presentation draft](PRESENTATION_DRAFT.md) is the current narrative
and source map. This brief supports its review and a future visual design pass.
The current deliverable is text only. It does not include rendered slides, an
HTML deck, a PPTX or a PDF.

Author: **Antonio Arbizzani Tonelli**. Audience: scientific-computing faculty,
C++ developers and technical portfolio reviewers. Suggested title: **LLM Resource
Allocation**. Suggested subtitle: **A verified reference and CPU performance
study**. Let the narrative determine the length. There is no required slide count.

Use the [current design guidance](CLAUDE_DESIGN_EXTENSION_PROMPT.md) with the draft.
The [original-campaign prompt](CLAUDE_DESIGN_PROMPT.md) retains historical evidence
and is not the current presentation structure.

## Main narrative

Open with the allocation problem: choose model deployments, GPU types and routing
fractions while respecting demand, a resource budget and service-level constraints.
Then introduce the software question: how much CPU time does the allocator need,
and which work can run concurrently without changing an individual solve?

Develop the main story in this order, allowing a topic to span more than one slide
in a future deck:

1. **Allocation problem.** Explain the decisions and the constraints in plain
   English before introducing algorithm names.
2. **Model.** Explain Stage-1 deployment and routing, the modeled cost components,
   and GH/AGH as alternatives to the P_DM MILP. Give Stage 2 a short scope statement:
   deployment stays fixed while routing and unmet demand adapt.
3. **Implementations.** Make Python/Pyomo, C++20 and OpenMP visible. Python provides
   the scientific reference and independent validator. Pyomo constructs MILP/LP
   models for a configured solver. Serial C++20 implements Stage-1 GH/AGH. OpenMP
   distributes independent allocation cases across CPU threads.
4. **Verification.** Explain why completion, independent feasibility, objective
   agreement and solver termination are separate evidence. Use the bounded
   cross-language suite as a concrete example.
5. **Runtime benchmarks.** Present the same-WSL Python/C++ measurements with separate
   core and complete-invocation boundaries. Keep the implementation differences
   beside the ratios they qualify.
6. **OpenMP.** Show the throughput of a fixed batch against its own one-thread
   control. Each allocation solve retains serial arithmetic and acceptance order.
7. **Limits and next work.** State what the local evidence supports and which
   scientific and engineering questions remain open. MPI remains future work.

Native scaling can follow the runtime section if it helps the audience. Full
solver-quality comparisons and detailed Stage-2 campaigns belong in optional
appendices. Their inclusion must not crowd out the allocation problem,
implementation boundaries or interpretation of the performance measurements.

## Attribution and scope

Attribute the formulation and GH/AGH algorithms to Cheng and Nguyen,
[arXiv:2604.07472 v2](https://arxiv.org/abs/2604.07472v2), with
[v1](https://arxiv.org/abs/2604.07472v1) supplying the explicit operational LP.
The project contributes its implementation, explicit unit conventions, independent
validation, native port and recorded experiments. It does not introduce GH/AGH or
claim numerical replication of the paper's tables.

Experiments execute allocation software on **CPU**. GPU capacity and latency are
**modeled inputs**. Modeled USD costs are outputs of the allocation model, not
observed cloud bills. OpenMP measures independent-case campaign throughput, not
GPU inference or parallel execution of one GH/AGH solve.

Use [MODEL.md](MODEL.md), [ARCHITECTURE.md](ARCHITECTURE.md) and
[VALIDATION.md](VALIDATION.md) for the scientific and implementation boundaries.
Current coherent units remain separate from historical literal-unit fixtures.
Native Stage 2 and MPI remain future work.

## Evidence for the main story

The reviewed public reference is
[`80a9625ab62a3c5c70ede7a9dae97a61158e250a`](https://github.com/antonio-arbizzani-tonelli/llm-resource-allocation/commit/80a9625ab62a3c5c70ede7a9dae97a61158e250a).
Its numerical payload matches extension checkpoint
`543ad4e640100a4c2a69febf17fe885bd452861e`. Include the reference commit, source path
and exact row or key with each numerical claim. The draft and
[design-guidance source table](CLAUDE_DESIGN_EXTENSION_PROMPT.md#claim-to-source-table)
provide the detailed mapping.

| Topic | Retained evidence | Source selection |
|---|---|---|
| Cross-language checks | 63/63 checks pass. 3,023 compared final numeric values have zero bitwise differences. This is bounded synthetic verification. | [Serial parity](../benchmarks/portfolio/raw/serial/parity.json), `passed`, `total`, and sums of `cases[*].compared_numeric_values` and `bitwise_difference_count`. |
| Matched runtime | AGH 16×4×4/load200: Python/C++ ratio of medians 120.5437 core, 95% CI [109.7530, 131.2151], and 99.7005 invocation, CI [93.2556, 107.2592]. Ten separate paired rounds per boundary. | [WP1 analysis](../benchmarks/matched_runtime_2026-10-14/analysis/analysis.json), `rows` with `case=16x4x4_load200_agh`, separately `boundary=core` and `invocation`. |
| OpenMP | Fixed 32-case mixed GH/AGH batch, 30 paired core rounds. Eight-thread speedup 4.0223, 95% CI [3.7636, 4.4243], efficiency 50.28%. | [WP2 analysis](../benchmarks/openmp_diagnostics_2026-10-14/analysis/extension.json), `settings` key `8_cores_close_dynamic_1_False_None`, against `1_cores_close_dynamic_1_False_None`. |

The matched core timer covers a fresh public solve, traces and independent
validation. It excludes startup, parsing, projection, output and destruction.
Python validates input and constructs `PdmProblemData` inside its public call.
C++ receives a prepared coefficient lattice before its timer. The ratios compare
these implementations, including their different preparation and trace costs.
They do not isolate a programming-language effect.

Complete invocation measures a separate Linux subprocess from startup through
exit. Keep a ratio of medians distinct from a median of paired ratios. Preserve
[the environment and conditions](EXTENSION_ENVIRONMENT.md). The newer 30-round
OpenMP results remain separate from the earlier 18-round results in
[PERFORMANCE.md](PERFORMANCE.md).

## Optional technical appendices

Keep the following Stage-2 evidence sets separate even when they share an appendix:

| Evidence set | Usable / attempted LPs | Recovery / frozen failures | Cost cohort |
|---|---:|---:|---|
| Original 13 October, standard absolute-only objective agreement | 646/1,850 | 256/1,344 | 5.857419% paired summed C4+C5 reduction over 390 usable pairs |
| Retrospective replay, optional relative objective tolerance 1e-12 | 850/1,850 | 344/1,344 | 5.957974% [5.745418%, 6.063490%] over 506 usable pairs |
| New 14 October solves, explicit relative objective tolerance 1e-12 | 3,246/6,800 | Separate load-specific denominators | Separate load-specific pairs and intervals |

Sources: [original report](STAGE2_RESULTS.md),
[policy analysis](../benchmarks/stage2_policy_2026-10-14/analysis.json),
`old_policy` and `selected_policy`, and
[new-campaign analysis](../benchmarks/stage2_robustness_2026-10-14/analysis.json),
`by_load`. The replay solves no LP and repairs no decision. The default remains
absolute 1e-8 USD and relative zero. Constraint tolerances and Stage-1 acceptance
remain unchanged.

Cost reduction is `(sum frozen C4+C5 - sum adapted C4+C5) / sum frozen C4+C5`
over identical scenarios where both decisions are usable. Infeasible baselines
receive no savings value. The original and retrospective cost cohorts differ,
so their pooled reductions do not estimate a causal benefit of changing policy.
Accepted method cohorts also differ and support no general ranking. These are
conditional synthetic-grid results, not measured cloud savings.

Other optional material includes native scaling, full solver rows and rejected
incumbents, larger-instance parity limits, timer/statistical details and
source/replay provenance. Use [KEY_NUMBERS.md](KEY_NUMBERS.md) and
[EXTENSION_REPORT.md](EXTENSION_REPORT.md) without pooling campaigns or hiding
failures.

## Design and review

Use natural English, readable type, a light background and restrained colors.
Prefer a simple allocation diagram and a small number of well-labeled evidence
figures. Avoid imagery that implies a measured GPU cluster.

Every chart needs an identifiable source, campaign, units, estimator, denominator
and acceptance scope. Keep timer boundaries and material limitations beside the
result. Put full details and exact row selectors in notes or a source table.
A future rendered presentation requires a separate request and visual review of
every page. The current text draft makes no claim to completed visual validation.
