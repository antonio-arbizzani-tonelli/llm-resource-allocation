# Solver-quality extension

See [REPORT.md](REPORT.md) for accepted-only comparisons and complete attempted/completed denominators. Raw numerical rejections, solver failures, worker timeouts and interrupted attempts remain in evidence.zip. Native incumbent/bound observations are separate from independently recomputed usable costs. The approved adapter does not expose native MIPGap; normalized_gap is explicitly derived.

Replay without a solver or current scientific source:

```bash
python scripts/extension_solver_quality.py summarize --output benchmarks/solver_quality_2026-10-14
```

The command verifies the portable inventory, archive membership/entry SHA, frozen source/input hashes, all retained attempt hashes and raw normalization/independent validation/objective comparison, then delegates to the hashed source snapshot. It automatically unpacks archived raw/input/source files. Standard-library Python>=3.13 is sufficient for numerical replay; optional --plots needs Matplotlib. No compiler, measured binary or proprietary solver license is required. Original-to-portable SHA provenance and runtime-artifact hashes remain machine readable.

Optional presentation refresh with the current renderer (Matplotlib required):

```bash
python scripts/extension_solver_quality.py render --output benchmarks/solver_quality_2026-10-14
```

This command first replays the frozen numerical summary without plotting, then refreshes only the current presentation. plot_presentation_verification.json distinguishes measured and renderer source hashes and verifies unchanged numerical outputs, the measured archive, prior replay evidence and all function ASTs except plot_results/main.
