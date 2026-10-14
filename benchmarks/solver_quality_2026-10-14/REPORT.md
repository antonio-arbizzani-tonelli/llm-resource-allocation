# WP6 solver-quality observations

four synthetic coherent V2 cases; cold limit-specific solves; accepted-only quality; no universal ranking

Attempted unique measured jobs: 20/20; independently accepted rows: 18/20 attempted unique jobs. Worker calls including retries: 20; completed worker result rows: 20; jobs without a completed result: 0. Warmup completed rows excluded: 3.

| Case | Method | Limit s | Accepted | Incumbent USD (diagnostic) | Bound USD | Normalized gap | Native gap | Usable objective USD |
|---|---|---:|---|---:|---:|---:|---:|---:|
| 10x10x10_L1 | gh | — | True | unavailable | unavailable | unavailable | unavailable | 1151.055 |
| 10x10x10_L1 | agh | — | True | unavailable | unavailable | unavailable | unavailable | 1150.055 |
| 10x10x10_L200 | agh | — | True | unavailable | unavailable | unavailable | unavailable | 228408.055 |
| 10x10x10_L200 | gh | — | True | unavailable | unavailable | unavailable | unavailable | 228409.055 |
| 10x10x10_L100000 | gh | — | True | unavailable | unavailable | unavailable | unavailable | 114200009 |
| 10x10x10_L100000 | agh | — | True | unavailable | unavailable | unavailable | unavailable | 114200008 |
| 6x6x10_L100000 | agh | — | True | unavailable | unavailable | unavailable | unavailable | 75840008.1 |
| 6x6x10_L100000 | gh | — | True | unavailable | unavailable | unavailable | unavailable | 75840009.1 |
| 10x10x10_L1 | highs | 20 | True | 1274.75872 | 11.4205725 | 0.991040993 | unavailable | 1274.75872 |
| 10x10x10_L200 | highs | 20 | True | 332096.378 | 1.64979133 | 0.999995032 | unavailable | 332096.378 |
| 10x10x10_L100000 | highs | 20 | True | 144835014 | 2.80833212 | 0.999999981 | unavailable | 144835014 |
| 6x6x10_L100000 | highs | 20 | True | 56407996.6 | 2.38087821 | 0.999999958 | unavailable | 56407996.6 |
| 10x10x10_L1 | highs | 120 | True | 915.548502 | 11.4551264 | 0.987488236 | unavailable | 915.548502 |
| 6x6x10_L100000 | highs | 120 | True | 30720031.7 | 2.76594359 | 0.99999991 | unavailable | 30720031.7 |
| 10x10x10_L100000 | highs | 120 | True | 54298973.6 | 2.83894415 | 0.999999948 | unavailable | 54298973.6 |
| 10x10x10_L200 | highs | 120 | False | 118464.126 | 1.86557761 | 0.999984252 | unavailable | unavailable |
| 10x10x10_L100000 | highs | 600 | True | 54298973.6 | 2.98910958 | 0.999999945 | unavailable | 54298973.6 |
| 6x6x10_L100000 | highs | 600 | False | 30720021.4 | 3.76686249 | 0.999999877 | unavailable | unavailable |
| 10x10x10_L1 | highs | 600 | True | 915.548502 | 12.1592943 | 0.986719115 | unavailable | 915.548502 |
| 10x10x10_L200 | highs | 600 | True | 108099.47 | 2.413336 | 0.999977675 | unavailable | 108099.47 |

Rankings exist only for complete accepted case/limit cohorts. Equal displayed costs do not establish unique placements. Rejected native incumbents and bounds are diagnostic. No time-limited incumbent is called optimal; solver status remains separate from independent acceptance.

The normalized gap is abs(incumbent-bound)/abs(incumbent), with the predeclared zero/missing-value rules. A separate backend-native MIPGap is unavailable through the approved APPSI adapter; no normalized value is called native.

Replay uses the frozen source, raw decisions, original normalization and default independent policies. Every retained attempt hash is checked, including failures/timeouts. Interrupted attempts and logs remain in raw/ or evidence.zip. A failed worker without complete decision extraction supplies no independently usable objective.

Gurobi skipped: WSL restricted license; academic license incompatible with WSL host. The three-way ordering question remains open.
