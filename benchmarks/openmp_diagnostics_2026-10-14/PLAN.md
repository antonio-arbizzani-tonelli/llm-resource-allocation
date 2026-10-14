# WP2 plan — independent-case OpenMP diagnostics

Synthetic mixed 32-case workload from the established `campaign_workloads(32)`.
Scientific arithmetic, acceptance and native production sources stay unchanged.
Only an opt-in wrapper times each job and records worker busy time and observed CPU.

Test teams 1..16 (confirm `lscpu`), cores/threads × close/spread, static/dynamic/guided
with chunks 1/2/4; 30 rounds, deterministic rotated configuration order, excluded
warmup. Additional descending-cost and `MALLOC_ARENA_MAX=1` interventions at
1/8/16 threads test workload ordering and allocator sensitivity independently.
Warmup job times determine one frozen cost ordering before measurement, never decisions.
The ordered intervention uses that manifest with exactly the control's warmup policy.

Metrics: core median/IQR, paired-round bootstrap 95% speedup CI, per-worker busy
and idle fraction `1-busy/core`, and serial-equivalent Amdahl fraction. Approximate
decomposition uses measured imbalance `(max busy-mean busy)/core`; remainder is
explicitly not uniquely attributable to cache, allocation or scheduling.
Success: bootstrap lower bound above 1 for an intervention relative to matched
configuration. Retain negative/no-improvement outcomes and every error.

Estimate before launch using measured one-team pilot and sum of inverse teams,
including warmups, subprocess/serialization overhead; skip full sweep above 3h.
Checkpoint every configuration/round; completed measurements never overwritten.
Input and source/binary hashes are required. `perf stat` and frequency/governor
availability are probed and failures retained. WSL virtual topology does not
identify physical P/E cores; affinity is guest affinity, not a physical-core test.
Unobservable hypotheses remain unresolved. Other CPU-heavy campaigns run serially.
Replay: `python scripts/run_openmp_diagnostics.py --analyze`.

## Pilot-driven revision before measured rounds

The excluded pilot observes 1.662651337 s one-team core and 4.319610153 s
complete invocation with full warmup and evidence. The full 585-setting grid
is estimated at 6.94 h and is skipped under the requested three-hour limit.
The revised default is a factor-separable 201-setting design: all 16 teams
crossed with every schedule/chunk at cores/close, all 16 teams crossed with
every placement/binding at dynamic/chunk1, plus nine sort/allocator interventions.
This covers every requested factor level without claiming every interaction.
Estimate the revised design again before launch; retain both forecasts.

Before measured rounds, the wrapper is bounded further: retain full serial
goldens once, independently decode/validate their decisions in Python, and
compare final-decision/objective/feasibility fingerprints in every timed
invocation. Repeated serialization of trace and all residuals is unnecessary
for the decision-preservation test and is excluded from the core timer.
A separate excluded pilot with measurement-sized output estimates invocation
overhead. Forecast parallel work at 50% efficiency, capped at the serial time,
and stop/checkpoint at three hours. No serial algorithm/validator code changes.
