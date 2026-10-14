# Matched WSL Python/C++ runtime

Synthetic CPU allocation software; modeled GPU delays are coefficients.

State: completed. Verified samples: 480; retained failed attempts: 0.

Core: public fresh-result solve including validation/traces; excludes startup, input parsing, projection, output and destruction.
Invocation: separate single-solve Linux subprocess, startup through exit, same final-decision schema; no in-process warmup.

| Case | Boundary | Pairs | Python median / IQR (s) | C++ median / IQR (s) | Median ratio [95% CI] |
|---|---|---:|---:|---:|---:|
| 4x2x2_load1_gh | core | 10/10 | 0.00695387 / 0.00159166 | 0.00010816 / 1.39677e-05 | 64.292 [60.175, 76.295] |
| 4x2x2_load1_gh | invocation | 10/10 | 1.87673 / 0.314329 | 0.0280983 / 0.0111986 | 66.791 [56.156, 86.901] |
| 4x2x2_load1_agh | core | 10/10 | 0.17436 / 0.0379649 | 0.00208953 / 0.000317512 | 83.444 [72.447, 97.070] |
| 4x2x2_load1_agh | invocation | 10/10 | 1.83932 / 0.46537 | 0.0269229 / 0.00490031 | 68.318 [64.241, 79.144] |
| 4x2x2_load200_gh | core | 10/10 | 0.00607285 / 0.00286468 | 0.000110288 / 6.22152e-05 | 55.064 [37.896, 79.112] |
| 4x2x2_load200_gh | invocation | 10/10 | 1.65832 / 0.240398 | 0.0244548 / 0.00743999 | 67.812 [57.953, 83.671] |
| 4x2x2_load200_agh | core | 10/10 | 0.18609 / 0.0306312 | 0.00201628 / 0.000378056 | 92.293 [82.986, 103.620] |
| 4x2x2_load200_agh | invocation | 10/10 | 1.84571 / 0.370105 | 0.0237456 / 0.00842529 | 77.729 [64.221, 94.715] |
| 8x4x4_load1_gh | core | 10/10 | 0.0511631 / 0.0115018 | 0.000584794 / 0.000201722 | 87.489 [66.826, 94.503] |
| 8x4x4_load1_gh | invocation | 10/10 | 1.81474 / 0.518827 | 0.0278323 / 0.00752562 | 65.203 [58.157, 75.639] |
| 8x4x4_load1_agh | core | 10/10 | 2.04137 / 0.536084 | 0.0191715 / 0.00213675 | 106.479 [91.440, 133.505] |
| 8x4x4_load1_agh | invocation | 10/10 | 4.07133 / 0.902741 | 0.0531793 / 0.0082605 | 76.559 [73.067, 89.828] |
| 8x4x4_load200_gh | core | 10/10 | 0.0574806 / 0.0164366 | 0.000633244 / 0.000107421 | 90.772 [77.856, 107.899] |
| 8x4x4_load200_gh | invocation | 10/10 | 1.8938 / 0.668243 | 0.0262763 / 0.00609109 | 72.073 [61.297, 104.219] |
| 8x4x4_load200_agh | core | 10/10 | 2.24621 / 0.265294 | 0.0204782 / 0.00165517 | 109.688 [99.953, 118.862] |
| 8x4x4_load200_agh | invocation | 10/10 | 4.30527 / 0.894286 | 0.0537473 / 0.00917649 | 80.102 [68.720, 93.615] |
| 16x4x4_load1_gh | core | 10/10 | 0.157849 / 0.0603619 | 0.0015147 / 0.000225647 | 104.211 [85.035, 132.469] |
| 16x4x4_load1_gh | invocation | 10/10 | 1.73933 / 0.777537 | 0.0298218 / 0.00219137 | 58.324 [55.880, 88.210] |
| 16x4x4_load1_agh | core | 10/10 | 8.10942 / 1.44445 | 0.0725475 / 0.00748442 | 111.781 [99.264, 126.157] |
| 16x4x4_load1_agh | invocation | 10/10 | 9.85035 / 0.858223 | 0.102339 / 0.0106502 | 96.252 [91.538, 101.564] |
| 16x4x4_load200_gh | core | 10/10 | 0.158873 / 0.0369438 | 0.0016483 / 0.000195807 | 96.386 [91.270, 109.963] |
| 16x4x4_load200_gh | invocation | 10/10 | 1.96225 / 0.310523 | 0.0308759 / 0.00734409 | 63.553 [55.382, 79.339] |
| 16x4x4_load200_agh | core | 10/10 | 8.42502 / 0.83245 | 0.0698919 / 0.00948141 | 120.544 [109.753, 131.215] |
| 16x4x4_load200_agh | invocation | 10/10 | 9.88396 / 1.16889 | 0.0991365 / 0.0148864 | 99.700 [93.256, 107.259] |

- Ratios compare these implementations including their different trace/input-check costs, not pure languages.
- Bootstrap resamples paired rounds; ten conditional observations cannot describe every system effect.
- Core samples and invocation samples are distinct solves with separately retained evidence.
- Scientific completion, independent feasibility and measured runtime are separate statuses.

Replay: `python scripts/run_matched_runtime.py replay --output benchmarks/matched_runtime_2026-10-14`.
Analysis: `python scripts/run_matched_runtime.py analyze --output benchmarks/matched_runtime_2026-10-14`.
