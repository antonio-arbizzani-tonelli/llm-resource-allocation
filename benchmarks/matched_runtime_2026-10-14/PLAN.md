# WP1: matched Python/C++ allocation runtime

This plan precedes execution. These are synthetic CPU allocation workloads;
modeled GPU delay coefficients are not measured GPU inference latency.

## Hypothesis and success/failure criterion

The serial C++ implementation remains faster than the complete Python reference
when both execute inside the same WSL distribution, on the same recorded CPU,
from the same prepared scientific input and with the same solve boundary.
Evidence supports this claim for a method/shape/load only when all ten paired
rounds pass unchanged-decision verification and the paired bootstrap 95% CI for
the ratio of median core durations is wholly above one. An interval containing
one is inconclusive; a wholly lower interval supports the opposite result.
Failures and incomplete pairs remain recorded and excluded with their reasons.

## Inputs, timer boundaries and controls

- Six configurations: 4x2x2, 8x4x4 and 16x4x4, each at loads 1 and 200;
  GH and AGH are separate points (12 points). AGH seed is 37; beta is 0.8.
  Coherent v2 units and the existing synthetic interpolation are unchanged.
- Each point retains a full domain JSON and a numeric C++ input. The Python
  worker reconstructs the immutable domain input before timing and requires its
  reserialized numeric transport to equal the retained C++ input byte for byte.
- Core timer: enter the public GH/AGH solve on the constructed input, return a
  fresh complete result, including algorithm, rich trace and independent
  scientific validation. Exclude process startup, input parsing, output
  projection, serialization and destruction. Implementation-specific internal
  input checks/problem-data construction remain part of each public solve.
  No cached Phase-1 result or partial algorithm is substituted.
- Each measured core call has one same-process, untimed warmup. Warmup results
  are destroyed before the timer starts. Every sample uses a fresh result owner.
- A separately reported complete invocation timer surrounds Linux subprocess
  startup through exit, for a single solve with the same final-decision JSON
  schema in both workers. It includes imports/startup, parsing, solve, projection,
  output and destruction. Those separate calls have no in-process warmup;
  preflight invocations warm external OS caches and are excluded. Core warmup
  time never enters the reported complete-invocation samples.
- Ten paired rounds per point and per timer boundary. Alternate Python/C++
  order each round and rotate the point order. Bootstrap whole paired rounds
  with local seed 20261014, 10,000 resamples; median and R type-7 IQR are reported.
  The estimand is median Python duration / median C++ duration, not the median
  of per-round ratios. These small-sample conditional CIs do not capture all
  thermal/systematic effects or establish a language-only effect.
- Record lscpu/uname/compiler/Python and exact binary/source/input hashes,
  observed Windows power/AC and available WSL governor/frequency metadata.
  Record app/activity observations without claiming all background apps closed.
  Coordinate timing to avoid simultaneous campaigns, builds or test runs.

## Validation, retention and reproducibility

Full untimed warm evidence compares final arrays, C1-C5, GH transitions and AGH
ordering/acceptance evidence through the existing parity authority. Final
numeric values and C1-C5 must also match bitwise. Every measured final decision
is checked bitwise against its runtime's full warm reference, and all supplied
native decisions receive unchanged-domain independent Python validation before
being called usable. No auxiliary/routing decision is repaired.

The campaign writes input SHA-256 files, raw stdout/stderr and failure records,
per-invocation checkpoint records, source/binary fingerprints, plots, CSV/JSON
analysis and exact argv replay records below this directory. Resume accepts
completed jobs only when inputs, scientific sources and binary fingerprints
still match. A manifest covers all retained files after execution. No existing
benchmark or scientific default changes.

## Duration estimate and stop boundary

Retained 16x4x4/load200 Python AGH reference wall is 3.402 s (including untimed
projection/extra validation); native median is 0.041 s. The older 8x4x4 sample
is shorter. The 12-point matrix, preflights, 120 warmed core pairs and 120
single-invocation pairs is estimated at approximately 3-12 minutes, with 30
minutes allowed for software/runtime differences. Preparation and plots are
additional. Each subprocess is capped at 120 s; the coordinator checkpoints
after every attempt and stops at a configurable 10,800 s wall budget. If fresh
pilot evidence projects beyond three hours, retain the pilot and skip the
remainder explicitly. WSL Python must be >=3.13; unavailable prerequisites are
recorded rather than substituting a Windows interpreter.

## Commands

Run from the published repository checkout inside WSL. Preparation builds only
the opt-in adapter; the existing serial/campaign executables and scientific
sources remain unchanged.

```sh
python scripts/run_matched_runtime.py prepare --output benchmarks/matched_runtime_2026-10-14
python scripts/run_matched_runtime.py run --output benchmarks/matched_runtime_2026-10-14 --rounds 10 --environment-json PATH_TO_OBSERVED_ENVIRONMENT.json
python scripts/run_matched_runtime.py analyze --output benchmarks/matched_runtime_2026-10-14
python scripts/run_matched_runtime.py replay --output benchmarks/matched_runtime_2026-10-14
```

Use the same `run` command to resume; interrupted worker files are preserved.
Exact compiler argv and every worker argv are saved by the harness.
