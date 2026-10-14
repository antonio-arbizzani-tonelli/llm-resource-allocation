# Extension execution and post-processing environment

The new extension's measured Python workers and new optimization solves execute
inside WSL Ubuntu with Python 3.13.16. WP1's serial C++ workers execute inside
that same WSL distribution. Their recorded source/input/binary fingerprints,
compiler/hardware information, power observations and exact timer boundaries
remain authoritative in the campaign artifacts. This document does not replace
or edit those frozen environmental records.

The inherited October 13 campaigns retain their own historical platform and
solver metadata. Retrospective policy replay reads those retained decisions;
it does not rerun their optimization solves or rewrite their classifications.

## Supplemental statistical post-processing

Windows Python 3.14.3 is used only for unmeasured analysis/replay where explicitly
recorded. It is not a substitute for a WSL measured worker or new optimization
solve. Hash verification, JSON parsing and bootstrap resampling have their own
processing duration, outside every scientific solve/core/invocation sample.

The first WP1 supplement with the earlier WP3 analysis runs with WSL Python
3.13.16, then replays under Windows Python 3.14.3. Both verify the original
1,552-file WP1 evidence manifest, 480
accepted raw samples and the exact 91-entry frozen source ZIP. Their complete
JSON values and all 24 supplemental rows match exactly, including both primary
ratio-of-medians and supplemental median-paired-ratio statistics. Raw output
bytes differ only in LF versus CRLF newline encoding; their newline-normalized
SHA-256 matches. These findings are recorded in
[extension_summary_verification.json](extension_summary_verification.json).

That historical proof now binds the exact retained
[extension_numbers_initial.json](../benchmarks/matched_runtime_2026-10-14/extension_numbers_initial.json), raw SHA-256
`fd2770a2f2220f3510cb4bf262b10b098e5180551dade2dc6373354d70508d3d`.
This matches the historical Windows digest byte for byte. The original observed
fields, argv (whose output path was then `docs/extension_numbers.json`) and
hashes remain unchanged. The
[companion scope record](extension_summary_verification_scope.json) identifies
the retained artifact without rewriting that history.
Its placement under the benchmark's byte-preserving Git/export rules avoids
text newline normalization. This transport-only supplemental artifact sits
outside WP1's original 1,552-file inventory and preserves the raw historical
Windows SHA; the former untracked docs copy is removed.

The complete Windows post-processing invocation takes **25.429 s**. This is
hashing/reading/resampling/serialization time, not allocation runtime, and never
enters a reported Python/C++ speedup. No reliable total start timer was retained
for the first WSL processing invocation; its elapsed duration is explicitly
null. WSL drvfs I/O stalls were observed, so an elapsed time is not imputed.
No allocation algorithm was executed during either initial supplemental
derivation. The 25.429 s duration and cross-platform equality apply to that
initial WP1-plus-earlier-WP3 output. The current
[extension_numbers.json](extension_numbers.json) includes final WP2–6 analyses
and has a distinct
[fresh final verification](extension_summary_final_verification.json).

The final producer runs under Windows Python 3.14.3 in **30.57474 s** and WSL
Python 3.13.16 in **48.86380 s**, both exit 0, with exactly equal complete JSON
values. Raw bytes differ only by CRLF/LF; the delivered LF artifact SHA-256 is
`010286b1ac5f4f723a13e800920b16569018ba0e7bccf7be5768500523685c8c`.
Both runs verify WP1's frozen source ZIP, original evidence, 480 accepted
samples and all 24 paired-ratio rows, and include the final supplied WP2–6
analysis paths/hashes. No allocation solve executes. These processing durations
are separate from campaign solve/core/invocation times and from the historical
25.429 s proof.

Replay the exact final portable argv from the repository root. This creates the
current aggregate; the retained initial artifact and its historical argv remain
separate:

```sh
python -B scripts/summarize_extension_results.py --wp1 benchmarks/matched_runtime_2026-10-14 --output docs/extension_numbers.json --wp2 benchmarks/openmp_diagnostics_2026-10-14/analysis/extension.json --wp3 benchmarks/stage2_policy_2026-10-14/analysis.json --wp4 benchmarks/stage2_robustness_2026-10-14/analysis.json --wp5 benchmarks/instance_scaling_2026-10-14/analysis/analysis.json --wp6 benchmarks/solver_quality_2026-10-14/analysis.json
```

The default source authority is
`benchmarks/matched_runtime_2026-10-14/source_snapshot.zip`, SHA-256
`10b741781c4c29bc9af0bdd66edaa6408060d8644b6d1297486d149653bea55d`.
Its source entries are checked against the original prepared inventory, and
the ZIP's additional provenance is recorded outside the unchanged WP1 manifest.
Later opt-in source changes therefore do not substitute for the frozen bytes.

The final WP6 archive-only replay uses a fresh Windows Python 3.14.3 environment
created without pip. Pyomo, HiGHS, Gurobi and Matplotlib are absent in both
the current launcher and its frozen-source child; current `src`, a measured
binary and unpacked evidence are initially absent. All numerical artifacts
reproduce byte for byte, with 23 completed reports and 18/20 accepted measured
results. The **18.477553 s** numerical replay and **20.110521 s** total proof
are unmeasured post-processing, distinct from the preserved initial 4.8376 s
replay observation. They do not compare solver or replay performance
([final current-launcher proof](../benchmarks/solver_quality_2026-10-14/archive_replay_final_verification.json)).

## Release preflight and final gate

All seven checks in [the immutable pre-manifest proof](extension_release_preflight.json)
pass under WSL Python 3.13.16, using `PYTHONPATH=src` from this public checkout:
1,131 Python tests with zero skips, native release and ASAN/UBSAN checks,
63/63 live/frozen parity cases, 90 OpenMP comparisons with ten independently
checked Python cases, and both Stage-1/Stage-2 examples. Their actual argv,
durations, exit codes and log hashes are retained in that proof. These checks
are outside experiment timers and are labeled **pre-manifest**.

At numerical checkpoint `543ad4e`, the required post-manifest repetition also
passes: 1,131 tests / zero skips (181.611 s unittest), native release/sanitizer,
63/63 parity, 90 OpenMP comparisons, both examples and verification of 3,568
publication files. Post-generation logs and the canonical handoff retain those
actual passes in the development workspace. The public preflight proof remains
the separately scoped earlier record. The later presentation/integration update
does not change campaign environment evidence or experimental timings.
