# Overnight allocation experiments

The declared 52-job campaign was prepared separately from earlier measurements.
The [12-job timing subset](PERFORMANCE.md) was executed on October 13, retaining
its resource-limited Python references. The separate [forty-worker Stage-2
study](STAGE2_RESULTS.md) is now complete: 37 accepted sources, 1,850 attempted
LPs, 646 usable decisions, 1,000 infeasible LPs and 204 objective rejections.
This guide defines the experiment and commands for new runs; the two reports
retain the exact observed coverage. It evaluates CPU allocation software,
with native timing workers under WSL; it does not run GPU inference or measure
cloud bills. Stage-2 workers use the recorded Windows Python/Gurobi environment.

## Prepare and start

Install the project dependencies and the optional Gurobi backend as described in
the [main README](../README.md). On Windows, Ubuntu in WSL must provide `make`
and `g++` with OpenMP support. Gurobi needs a working license. HiGHS is an explicit
alternative; it produces a distinct configuration and result set.

Inspect the plan without running anything:

```powershell
python scripts/run_nightly_campaign.py --plan
```

Freeze the configuration, sources and freshly tested native binaries. This step
does not execute experimental jobs:

```powershell
python scripts/run_nightly_campaign.py --prepare-only --wsl Ubuntu --output results/nightly_campaign
```

At night, from the repository directory, start the prepared snapshot:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run_nightly_campaign.ps1 -OutputPath results/nightly_campaign -Resume
```

This execution-policy setting applies to the launched PowerShell process. The
wrapper prevents automatic system sleep while running, restores its request on
exit and leaves the global power plan unchanged. Keep the laptop plugged in and
the lid open. The screen can turn off. Avoid other CPU-heavy tasks when measuring
timings. No shutdown, automatic scheduling or application closing is performed.

On Linux, prepare and resume with `python scripts/run_nightly_campaign.py`,
omitting `--wsl`. Linux sleep prevention is managed by the user.

For a HiGHS campaign, add `--backend highs` at preparation. The Windows wrapper
reads the frozen configuration on resume. Do not switch backend within an
existing result directory; prepare another directory instead.

## Declared protocol

The [configuration](../configs/nightly_campaign.json) defines 52 jobs:

| Component | Scope |
|---|---|
| Stage 2 | 40 source deployments: four shapes, two loads; GH, P_DM and AGH seeds 37/41/43. Up to 50 scenarios per accepted deployment. |
| Python/C++ | Nine shapes, through 256 queries at 4 models/4 tiers; separate menu growth through 128x8x8. Five individual native repeats and one Python reference check per method/shape. |
| OpenMP | Batches of 32, 64 and 128 independent cases; serial plus static/dynamic schedules at requested teams 1/2/4/8; 18 rounds with rotated/reversed order. |

Shapes denote **queries x model alternatives x GPU-tier alternatives**. The
added model/tier values interpolate the existing synthetic fixture and are not
additional measured hardware products. Query-only and menu-growth controls help
separate workload growth from growth of the search space.

Stage 2 keeps the independently accepted Stage-1 deployment fixed. A deterministic
Cartesian grid combines arrivals at 0.8, 0.85, 0.9, 0.95, 1, 1.025, 1.05, 1.1,
1.15 and 1.2 times nominal with adverse factors 1, 1.1, 1.2, 1.35 and 1.5. One
shared adverse factor multiplies both delay components and effective error.
Source unmet caps, coefficients, LP constraints and numerical acceptance remain
fixed. Loads 200 and 100000 are declared synthetic assumptions; no post-result
input tuning is applied.

This grid is a project sensitivity experiment. It is neither the paper's sampled
500-scenario protocol nor its separate 2% unmet-cap stress experiment. No missing
paper distribution is inferred. Coherent period costs use the published project
[unit contract](UNITS.md); the operational objective remains C4+C5.

## Evidence and indicators

Each attempted scenario retains the actual realization, solver status,
independent validation, objective agreement and validation of frozen nominal
routing. Failed Stage-1 sources skip Stage 2 explicitly. Rejected LPs have no
usable cost/service metrics. A full-grid mean is present only when all 50 LP
attempts are independently accepted.

The prepared summary derives these indicators from observations:

- Feasibility recovery: how many attempted scenarios rejected frozen routing but
  accepted operational adaptation, with the number of frozen failures as the
  explicit denominator. A partial run remains labeled partial.
- Realized served requests/hour, demand-weighted unmet fraction, strict query
  fraction with `u > 0.01`, and changed assignment fraction (including unmet demand).
- Operational C4+C5 and reporting C1+C2+C3+C4+C5 in USD per configured horizon.
  Frozen-route costs are supplied only when that baseline is independently feasible.
- Minimum, median and inclusive interquartile range of native durations; OpenMP
  core speedup, observed-team efficiency, median speedup and separate process speedup.

The Python/C++ ratio compares one Python reference check (including projection
and validation) with C++ core duration. It is an implementation comparison with
different scopes, not an isolated language effect. Scenario-integrated Stage-2
timing includes model construction, solve, extraction and independent validation;
its median spans different grid scenarios rather than repeated identical solves.

## Logs, limits and recovery

`status.json` shows the current job; `logs/` contains build and per-attempt logs.
`jobs.json` preserves completion, timeout and interruption history.
`snapshot_manifest.json` hashes sources, configuration and binaries. Resume
checks that snapshot and all completed job outputs before reusing them.
Each invocation records environment metadata in `environment_history.json`.

The default execution budget is **four hours per invocation**, with a **30-minute
limit per job** and **20-second limits for each MILP/LP solve**. Preparation and
final reporting are additional. These are limits, not a promise that all jobs
finish. Timeouts preserve partial outputs and continue; unexpected worker errors
stop the campaign for inspection. Resume retries unfinished jobs in new attempt
directories, preserving old evidence; a partial stress job restarts its grid.

`report.md`, `summary.json` and the observed-data CSV files are generated on exit.
The preparation report explicitly says that no experimental measurements exist.
To rebuild a report without running experiments:

```powershell
python scripts/summarize_nightly_campaign.py --output results/nightly_campaign
```

The runtime outputs stay under ignored `results/`. New portfolio claims and
presentation figures should be selected only after reviewing the completed
coverage, failures, raw evidence and timing scopes.
