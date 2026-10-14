# C++ scaling across synthetic instances

State: completed; 90/90 complete method/instance points; 270/270 verified native samples.
Full small-point Python parity: 20/20 points; failures retained: 0.

Core is a fresh complete public solve including validation/traces; excludes startup, input parsing, output projection/serialization and destruction.
Warmup is one excluded external subprocess pilot per point. Measured workers are fresh single-solve processes, without same-process warmup.

| Family | Method | Instance points | Feasible | Exponent [cluster bootstrap 95% CI] | Log-space R² |
|---|---|---:|---:|---:|---:|
| query | gh | 30/30 | 30 | 1.6615 [1.6402, 1.6798] | 0.9903 |
| query | agh | 30/30 | 30 | 1.9402 [1.9254, 1.9600] | 0.9975 |
| menu | gh | 20/20 | 20 | 0.9455 [0.9185, 0.9707] | 0.9928 |
| menu | agh | 20/20 | 20 | 1.4461 [1.4065, 1.4998] | 0.9694 |

- Input seeds are separate from the fixed AGH seed 37; repeats are not independent instances.
- Warmup is one excluded external subprocess pilot per point; measured workers are fresh single-solve processes without same-process warmup. Process/allocator state is fresh, while machine-wide cache/thermal history may persist.
- The fit includes all complete verified native measurements, with scientific feasibility/status shown separately.
- Five seed clusters limit confidence-interval precision and do not represent every possible workload.
- Menu size is J*K at fixed I=64; different aspect ratios and structural branches confound a single product exponent.
- Empirical log-log slopes on the observed range are not asymptotic complexity bounds or extrapolation evidence.
- Large points have final-decision independent validation, without full Python algorithm/trace parity.

Replay: `python scripts/run_instance_scaling.py replay --output benchmarks/instance_scaling_2026-10-14`.
