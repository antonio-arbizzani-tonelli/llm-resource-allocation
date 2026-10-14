# Original-campaign design prompt

This prompt preserves the **October 13, 2026 campaigns**, their measurements
and the standard Stage-2 acceptance policy. For the current narrative, use the
[English presentation draft](PRESENTATION_DRAFT.md),
[brief](PRESENTATION_BRIEF.md) and
[design guidance](CLAUDE_DESIGN_EXTENSION_PROMPT.md). This file is historical
preparation material. Its detailed Stage-2 evidence can support an optional
appendix without setting the current main story or slide count. The current
deliverable is text only.

```text
Use the following evidence when preparing historical context or an optional
technical appendix for “LLM Resource Allocation”. Write English captions and
speaker notes. Keep code symbols, commands and filenames unchanged. Follow
PRESENTATION_DRAFT.md for the current main narrative. Create rendered slides
only if separately requested.

Author: Antonio Arbizzani Tonelli.
Audience: scientific-computing faculty, C++ developers and portfolio reviewers.
For a future visual deck, adapt length to the audience and speaking time.
There is no required slide count. Use 16:9 if a slide format is requested.
Title: “LLM Resource Allocation”.
Subtitle: “A verified reference and CPU performance study”.

SOURCE SNAPSHOT

Repository:
https://github.com/antonio-arbizzani-tonelli/llm-resource-allocation

Original numerical evidence commit:
8a11e7d533e929009ef5e1cae2dde6bdb18d217b

Resolve source paths at that commit. Read docs/RESULTS.md,
docs/PERFORMANCE.md, docs/STAGE2_RESULTS.md, docs/MODEL.md,
docs/ARCHITECTURE.md and docs/VALIDATION.md. The current brief also includes
later extension results. Keep them outside this historical deck unless
explicitly labeled as a separate campaign.

Each numerical claim and chart needs a source path and row or key in notes,
with the commit. Request an inaccessible source rather than reconstructing it.
Keep original sources and failed outcomes.

NARRATIVE AND ATTRIBUTION

Open with the allocation problem: choose models, GPU types and routing
fractions while respecting demand, cost and service-level constraints.
Stage 1 chooses deployment and nominal routing. Stage 2 fixes deployment
and adapts routing and unmet demand.

Attribute formulation and GH/AGH to Cheng and Nguyen, arXiv:2604.07472,
using v2 as the main source and v1 for the explicit operational LP. Attribute
implementation, unit conventions, independent validation, C++20 and
measurements to this project.

Make Python/Pyomo, C++20 and OpenMP visible. Python is the reference. Pyomo
constructs the MILP/LP for a configured solver. C++20 implements serial
GH/AGH. OpenMP runs independent cases concurrently. Each solve remains
serial. Experiments run CPU allocation software. GPU capabilities and
latencies are modeled inputs, not measured inference performance.

The current main story covers the allocation problem, model, Python/Pyomo and
C++20 implementations, parity, runtime boundaries, independent-case OpenMP
and limits. Keep the original Stage-2 outcomes, adaptation and numerical
rejections together in a clearly labeled optional historical appendix.
Keep full solver tables there as well.

ORIGINAL PERFORMANCE EVIDENCE

Sources: docs/PERFORMANCE.md and the recorded analysis/CSV under
benchmarks/performance_2026-10-13/analysis/. Cite matching method/shape rows.

- Sixteen complete Python/C++ comparisons verify 185,832 bit-identical values.
- C++ AGH core medians are 2.889 s at 128×4×4, 7.156 s at 256×4×4 and
  7.471 s at 128×8×8, with five samples per point.
- Dimensions mean query types × model alternatives × GPU-type alternatives.
- Python AGH fails with MemoryError at the two larger endpoints. Those C++
  decisions pass independent final-state checks, without full algorithm
  parity. No Python time or speedup exists for the failed runs.
- OpenMP: 32 mixed cases, dynamic scheduling, eight observed threads and
  eighteen rounds. Median speedup is 4.20× core and 2.27× complete invocation.
  Efficiency is 52.5%.
- Preserve the timer definitions from PERFORMANCE.md. Do not splice values
  with later matched-runtime or 30-round OpenMP campaigns.

ORIGINAL STAGE-2 EVIDENCE

Sources: benchmarks/stage2_stress_2026-10-13/analysis/analysis.json,
benchmarks/stage2_stress_2026-10-13/analysis/numerical_diagnostics.json,
and docs/STAGE2_RESULTS.md.

- Forty jobs complete. Thirty-seven initial allocations are accepted.
- Of 1,850 attempted LPs, 646 are usable, 1,000 are solver-infeasible and
  204 fail objective agreement despite independent constraint feasibility.
- Another 150 scenarios are skipped after three rejected Stage-1 sources.
  Keep them outside the 1,850-attempt denominator.
- Adaptation recovers 256/1,344 frozen-routing failures, or 19.05%.
- Summed C4+C5 decreases 5.857419% on 390 scenarios where both decisions
  are usable. Define it as (sum frozen − sum adapted) / sum frozen.
- Give no savings to infeasible baselines. These conditional synthetic-grid
  results are not real-world probabilities or cloud savings. Differing
  accepted method cohorts support no general ranking.

Explain numerical acceptance separately. The 204 objective-only rejections
have solver-optimal status and pass constraints but exceed the original
absolute objective-agreement threshold of 1e-8 USD. Differences are 1–3 ULP,
maximum relative about 3.40e-16, consistent with floating-point roundoff.
They remain excluded under this original policy. Keep solver termination,
constraint feasibility and objective agreement distinct.

The later opt-in relative policy is a separate retrospective evaluation.
Do not import its 850/1,850 acceptance count into original campaign metrics.

FIGURES AND DELIVERY

Use published plots under benchmarks/performance_2026-10-13/analysis/plots/
and benchmarks/stage2_stress_2026-10-13/plots/. Preserve values, axes, units,
sample counts and verification markers. Label experimental slides
“Synthetic project inputs; CPU allocation software”.

Use readable type, a light background and restrained colors. Avoid GPU-cluster
photography. Give each slide a clear subject and put detail in notes. Keep
limits beside the result they qualify.

For the current text review, retain English draft content, notes and a
claim-to-source table. A later, separately requested rendered presentation
requires visual checks for overlap, chart readability, numerical consistency
and attribution. Native Stage 2, native solver integration and MPI remain
future work. Claim no heuristic optimality, real GPU acceleration or numerical
replication of the paper's tables.
```
