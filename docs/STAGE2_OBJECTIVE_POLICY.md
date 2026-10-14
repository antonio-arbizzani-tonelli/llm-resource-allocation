# Opt-in scale-aware Stage-2 objective agreement

The default remains the historical absolute 1e-8 USD agreement threshold.
Scientific constraints, extraction, normalization, independently recomputed
objectives and strict GH/AGH improvement are unchanged.

Use `run_stage2(problem, objective_relative_tolerance=1e-12)` to request the
separately recorded extension policy. `ObjectiveComparison` accepts an optional
`relative_tolerance`, default zero, and compares the observed values using:

```text
|solver - independent| <= max(absolute_tolerance,
                             relative_tolerance * max(|solver|, |independent|))
```

The maximum, rather than the sum, is part of this opt-in policy. Agreement is
inclusive. The record retains both observed objective values and the configured
absolute and relative tolerances. Its `applied_tolerance` property exposes the
scale-specific threshold. No value or decision is repaired. P_DM still constructs
the comparison with relative zero; this Stage-2 extension does not promote the
three rejected historical Stage-1 sources.

The requested experiment chooses 1e-12 as an explicit assumed coefficient:
the 204 historical objective rejections had one to three ULP disagreement,
with maximum relative difference about 3.40e-16. The selected coefficient is
approximately 2,940 times this observed maximum and is the lowest requested
sensitivity level. It is a conservative classification setting for this finite
evidence, not a bound on future solver error. Tests inject relative errors of
at least 1e-6 and verify rejection under the selected policy.

The [replay plan](../benchmarks/stage2_policy_2026-10-14/PLAN.md) defines the
solver-free experiment and failure criteria before execution. Its
[separate derived results](../benchmarks/stage2_policy_2026-10-14/README.md) retain
old and new classifications, sensitivity levels, paired denominators and
bootstrap details. The original published evidence remains unchanged.
