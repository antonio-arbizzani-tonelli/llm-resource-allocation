# WP6 solver-quality plan

Hypothesis: accepted incumbents and the case-specific ordering among Gurobi,
AGH and HiGHS may change when the native limit grows from 20 to 120 to 600 s.
Four fixed synthetic cases use 10x10x10 at loads 1, 200 and 100000, and
6x6x10 at load100000. They vary load, not random instance seeds. Coherent V2,
one-hour residency, GH beta0.8 and AGH seed37 remain explicit assumptions.

Each backend/limit is an independent cold solve, with zero requested MIP gaps;
no warm start or transfer of another method's decisions is allowed. One tiny
warmup per selected solver and heuristic is retained and excluded. Case and
backend order rotates across limits. These quality experiments have one solve
per cell; no repeat-based runtime uncertainty is claimed.

Record native incumbent, bound, normalized gap, status, APPSI call time, complete raw
x/z/q/u/w/y/v, normalized placement, and independent default acceptance.
The normalized gap is abs(incumbent-bound)/abs(incumbent); it is unavailable
without both values or for a zero incumbent with a nonzero absolute gap.
The approved APPSI adapter does not expose a separate backend-native MIPGap;
that observation is explicitly unavailable, never replaced by the normalized gap.
The 1e-8 absolute objective threshold remains the Stage-1 default. Rejected
incumbents remain diagnostic; no rejection enters a ranking, optimum gap,
accepted-objective ratio or bootstrap interval. Heuristic completion alone
is insufficient. Bounds are backend evidence about the constructed model.

Success: replay every usable decision and objective without solving and
report the complete accepted comparison at each limit when it exists.
Negative outcome: preserve timeouts, missing incumbents, numerical rejections
and absent complete cohorts; explicitly leave the ordering question open.
The paired bootstrap across complete cases is descriptive of this four-case
convenience cohort, not a population CI or universal method ranking.

Gate: planned estimated runtime must be at most 3 h. If the gate fails, skip
execution and report why. Resume checks hashes and creates a new attempt
directory for interrupted workers. No campaign run is started by prepare.

Environment: Python>=3.13, i7-13620H, requested WSL Ubuntu where available;
actual Python/platform/solver versions and operator energy/app observations
are retained. GPU delay coefficients are model inputs; timing is CPU allocation
software. This is not numerical replication of Cheng and Nguyen's tables.

Replay: python scripts/extension_solver_quality.py summarize --output
benchmarks/solver_quality_2026-10-14
The replay automatically verifies/unpacks evidence.zip and delegates to the
hashed campaign source snapshot; no solver or current scientific source is used.
Execution: python scripts/extension_solver_quality.py run --output
benchmarks/solver_quality_2026-10-14 --environment-note '<observed state>'

Gurobi execution is skipped: WSL restricted license; academic license incompatible with WSL host. No matched
Gurobi/AGH/HiGHS ordering will be inferred from historical cohorts.
