# WP5: C++ scalability across synthetic instances

This plan precedes execution. The experiment measures CPU allocation software,
using the unchanged Cheng/Nguyen GH/AGH formulations and serial scientific
routines. Synthetic delay coefficients are not observed GPU latency.

## Hypotheses and evidence criteria

Query count and model/tier menu size explain a substantial part of log runtime
variation, while independently seeded inputs expose variation hidden by repeats
of one fixture. Fit `log(time) = intercept + exponent * log(size)` and report the
exponent, cluster bootstrap 95% CI and log-space R-squared. Six query sizes and
five complete instance seeds per size are required for a completed query fit.
Four menu sizes and five seeds are required for the menu fit. Missing cells,
scientific rejections, failed workers and deviations remain explicit.
An R-squared below 0.8 is declared a weak descriptive fit. No exponent is called
an asymptotic complexity bound, and no extrapolated scaling claim is made.

## Matrix and assumptions

- Queries: 16, 32, 64, 128, 256 and 384 at a fixed 4x4 menu.
- Menu: 4x4, 8x4, 8x8 and 12x12, with 64 queries held fixed.
- Five instance seeds: 11, 23, 37, 41 and 53. The shared 64x4x4 cells are
  measured once and reused in both analyses: 45 distinct instances, 90 native
  method/instance points. These are input seeds, separate from AGH seed 37.
- The parent-owned `extension_instances.py` supplies explicit independent
  uniform factors [0.9,1.1] for query arrivals/tokens and route delays. Coherent
  v2 units, load 200, beta 0.8 and original scientific defaults are retained.
  No input coefficient is selected using an observed algorithm outcome.
- Each point has one excluded warm native solve and three individual measured
  solves, with point order rotated/reversed by round. No parallel campaigns,
  builds or tests run during timing. Hardware/power/AC/governor observations,
  compiler, binary and source/input SHA-256 fingerprints are retained.
  Warmup is an external pilot in its own subprocess. Every measured worker is
  a fresh process containing one solve; it performs no same-process warmup.
  Thus each core measurement starts with fresh process/allocator state while
  retaining any machine-wide cache or thermal effects from earlier workers.
  Preparation verifies five distinct numeric input hashes per shape and the
  same numeric input for GH/AGH within each seed. PLAN bytes are hashed and
  frozen alongside inputs, sources and binary.
- Native core boundary is the WP1 opt-in adapter: fresh complete public solve,
  including traces and independent native validation; excludes startup/parsing,
  output projection/serialization and destruction. The production science and
  existing benchmark files remain unchanged. Process durations are separate.

## Validation and statistical units

Every supplied native final decision is decoded unchanged and receives the
shared independent Python validator. Feasibility classification and C1-C5 must
match bitwise; all measured outputs match their full warm final decision.
Incomplete/scientifically infeasible algorithm outcomes remain visible and
timing summaries include their actual completion/feasibility status. A runtime
measurement alone never makes a placement scientifically usable.

Optional complete Python algorithm/transition parity is restricted to 16/32
queries at 4x4; other points claim only final-decision validation. No large full
Python trace is constructed. Missing Python parity is explicitly labeled and
does not produce a Python runtime ratio. Existing frozen/full parity remains
part of the final project verification.

The regression uses the median of three native repeats for each method/instance,
so repeats are not additional independent instances. Query size is I; menu size
is J*K, with fixed I=64 and differing aspect ratios reported. The menu exponent
is a coarse empirical summary of these four menus, not evidence that only J*K
matters. Ordinary least squares is applied in log space. A local seed-20261014
percentile bootstrap resamples the five complete instance-seed clusters, keeping
each selected seed's size observations together (10,000 draws). This accounts
for shared source/RNG-seed dependence across sizes; five clusters still limit
uncertainty estimation. Repeats measure temporal variation only.

## Duration estimate, checkpoint and stop boundary

Retained AGH medians at 16/32/64/128/256x4x4 are approximately
0.041/0.118/0.713/2.889/7.156 s. Scaling the last point to 384 with the old
descriptive exponent near 1.86 gives approximately 15 s; this is used only for
planning. Four solves x five seeds across the six sizes cost roughly nine
minutes of native AGH time; GH, menu points, independent validation, optional
small Python parity and process overhead yield an estimated 15-45 minutes.
Fresh warm subprocess and independent-validation durations update a conservative
projected budget before measured rounds; resume counts only unfinished samples.
A projection beyond the remaining coordinator budget is skipped,
retaining the warm evidence and explicit reason. Each worker is capped at
180 s and the coordinator's remaining time, with completed attempts checkpointed
and raw failures preserved. The optional Python reference receives its own
remaining-time check. A configurable budget of at most three hours stops new work.

## Retention and replay

Retain full domain JSON/native numeric inputs and SHA-256, per-worker exact
portable argv, compressed raw stdout including failures, stderr, independent
validation evidence, preflight status and checkpoints. Resume checks scientific
source/binary/input and finished output hashes. Deliver JSON/CSV analysis,
PNG/SVG figures, runtime matrix, empirical fits and deterministic solver-free
replay. No existing result or benchmark is rewritten.

Run inside the same WSL Python environment after WP1 has built its opt-in
adapter and after previous work-package timings have ended:

```sh
python scripts/run_instance_scaling.py prepare --output benchmarks/instance_scaling_2026-10-14
python scripts/run_instance_scaling.py run --output benchmarks/instance_scaling_2026-10-14 --repeats 3 --python-reference-max-queries 32 --environment-json OBSERVED_ENVIRONMENT.json
python scripts/run_instance_scaling.py analyze --output benchmarks/instance_scaling_2026-10-14
python scripts/run_instance_scaling.py replay --output benchmarks/instance_scaling_2026-10-14
```

Repeat the same `run` command to resume. The optional Python limit can be zero
only as an explicitly recorded execution deviation; native validation remains
mandatory for every supplied complete state.
