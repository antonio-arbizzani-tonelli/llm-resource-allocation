# C++20 allocation planner

The native implementation runs the Stage-1 greedy heuristic (GH), adaptive
greedy heuristic (AGH), their local search, and independent feasibility checks.
An OpenMP runner executes independent planning cases concurrently. The exact
Stage-1 mixed-integer model and Stage-2 operational LP are implemented in
Python. See the [project overview](../README.md),
[architecture](../docs/ARCHITECTURE.md), and
[measured results](../docs/RESULTS.md).

## Build and run

Use Linux or WSL, GNU Make, and GCC with C++20 support. The verified native
environment is Ubuntu 24.04 under WSL with GCC 13.3.0. Production executables
need no Python installation or optimization solver. The campaign executable
also needs the compiler's OpenMP runtime.

Run these commands from the repository root in a Linux or WSL shell:

```bash
make -C cpp -j4 all test openmp campaign-test
make -C cpp -j4 MODE=sanitize test campaign-test
cpp/build/release/pacs_serial gh < cpp/tests/fixtures/minimal_coherent_gh.txt
cpp/build/release/pacs_serial agh < cpp/tests/fixtures/minimal_coherent_agh.txt
```

Build modes are `release` (`-O2 -g`), `debug` (`-O0 -g`), `profile` (adds
`-pg`), and `sanitize` (AddressSanitizer and UndefinedBehaviorSanitizer).
All use `-std=c++20 -Wall -Wextra -Wpedantic -ffp-contract=off`, without
fast-math. Files are generated under `cpp/build/MODE/`. Ordinary serial
builds have no OpenMP runtime dependency.

The serial CLI reads numeric input from standard input and writes JSON.
`status` describes algorithm completion; `feasible` reports independent
acceptance. A completed GH run may be infeasible. `objective` contains the
five cost components C1–C5, and full output retains decisions, constraint
residuals, and selected trace evidence. `--summary` reduces serialization;
the algorithms and scientific checks still execute in full.

Supported modes are `gh`, `agh`, `relocate`, `consolidate`, `validate`, and
`rng`. The three placement-processing modes require a supplied state.
`--repeat N` repeats identical prepared input and records each duration.

Numeric transport begins with `PACS_GH_AGH 1` and contains ordered problem
data, options, a decimal integer seed, and an optional dense placement.
The [Python serializer](../scripts/check_cpp_parity.py) and
[input adapter](src/io.cpp) define the format; the committed fixtures provide
complete examples. External coefficients, dimensions, and configuration grids
are checked before a solve begins.

## Algorithms and ownership

| Code authority | Role |
|---|---|
| [core.hpp](include/pacs/core.hpp), [core.cpp](src/core.cpp) | `Problem`, `Placement`, cost arithmetic, numerical policy, and independent `validate`. |
| [gh.hpp](include/pacs/gh.hpp), [gh.cpp](src/gh.cpp) | M1–M3, deployment selection, demand allocation, and `run_gh`. |
| [agh.hpp](include/pacs/agh.hpp), [agh.cpp](src/agh.cpp) | Seeded orderings, relocate, consolidation, ordered multi-start, and `run_agh`. |
| [io.cpp](src/io.cpp) | Numeric transport and shared JSON projection. |
| [campaign.cpp](src/campaign.cpp) | Serial, static, and dynamic schedules for independent cases. |

M1 screens configurations by model weight and query delay, selecting the
smallest eligible GPU count. M2 computes coverage under remaining demand and
cumulative error/delay limits, then ranks marginal cost per covered fraction.
M3 selects an eligible higher-GPU configuration when an active deployment
needs a delay upgrade. Candidate commits additionally check resources and
budget; the final placement passes the complete independent validator.

AGH evaluates deterministic and seeded query orderings. Relocate moves a whole
route to an active destination with strict objective improvement. Consolidation
attempts to redistribute traffic before deactivating a deployment, accepting
the final transaction only if feasible and strictly cheaper. Multi-start
incumbents and early stopping are evaluated in their specified order.

`Problem::prepare()` validates external input and establishes contiguous
configuration indices. Algorithms borrow the prepared problem through
`const Problem&`. Results own their decision arrays and trace snapshots;
candidate moves operate on copies and transfer ownership only when accepted.
Nullable placement and incumbent accessors borrow from a live result owner.
The owner must remain alive and unchanged while those pointers are used;
temporary-owner calls are rejected by the API.

The local RNG reproduces Python's integer-seeded shuffle stream, including
negative and large integer seeds. Floating summation preserves the reference's
distinct `sum` and `fsum` conventions. These choices make cross-language
verification sensitive to arithmetic, ordering, and stopping behavior.

## Independent-case OpenMP execution

Save the following as `campaign.txt` in the repository root:

```text
PACS_CAMPAIGN 1
2
gh "first GH case" "cpp/tests/fixtures/minimal_coherent_gh.txt"
agh "second AGH case" "cpp/tests/fixtures/minimal_coherent_agh.txt"
```

Run it with:

```bash
cpp/build/release/pacs_campaign --schedule dynamic --threads 4 --repeat 3 < campaign.txt
```

Paths resolve from the process working directory. Names and paths use C++
`std::quoted` syntax: escape backslashes and double quotes, and retain UTF-8
characters. Schedules are `serial`, `static`, and `dynamic`; dynamic assigns
one case at a time. Each case owns its input, options, seed, and result.
Workers write separate preallocated slots, and the coordinator emits results
in manifest order. Exceptions are retained per case and rethrown in input
order after joining. Thread requests apply to this region, and output records
the observed teams for every repeat.

Parallelism improves batch throughput while each individual GH/AGH solve keeps
the same serial scientific routines. The project contains no MPI runner or
C++ LP solver. The [results report](../docs/RESULTS.md) gives measured
speedup, efficiency, workload definitions, and hardware.

## Verify and profile

Install the Python package as described in the root README. From the repository
root, run:

```bash
python scripts/check_cpp_parity.py --frozen
python scripts/check_openmp_campaign.py --output results/openmp_check
```

The parity check compares decisions, costs, independent feasibility, and
projected GH/AGH transitions. Four committed input/reference pairs under
[tests/fixtures](tests/fixtures/README.md) can also be replayed with
`python scripts/check_cpp_parity.py --frozen-only`. Frozen expectations are
read without regeneration. On Windows Python, add `--wsl Ubuntu` to run
Linux executables through WSL.

For repeatable measurements:

```bash
make -C cpp -j4 MODE=profile all
python scripts/profile_cpp.py --output results/serial_profile \
  --build-description 'GCC; C++20; -O2 -g -ffp-contract=off; gprof adds -pg'
python scripts/profile_openmp.py --output results/openmp_profile \
  --repeats 3 --batch-size 16 \
  --build-description 'GCC; C++20; -O2 -g -ffp-contract=off -fopenmp'
```

Serial `algorithm_seconds` covers the algorithm and result construction on
prepared input. Campaign `campaign_seconds` includes scheduling, allocation,
full computation/evidence, validation, ordered result assembly, and initial
team creation. Parsing, JSON output, and process startup lie outside these
timers. Measurement scripts also retain complete invocation wall times,
individual samples, observed teams, and source/input/binary fingerprints.
Python/native ratios compare implementations with different input-validation,
trace, and runtime costs; they do not isolate a language effect.

## Optional internal-validation experiment

An opt-in probe compares the original residual append loop, serial fixed
slots, and OpenMP fixed slots. It is separate from production executables.
Building it requires Python 3 for the checked source generator:

```bash
make -C cpp -j4 validation-probe validation-probe-test
OMP_DYNAMIC=FALSE OMP_PROC_BIND=close OMP_PLACES=cores OMP_WAIT_POLICY=ACTIVE \
  cpp/build/release/pacs_validation_probe agh \
  --validation-mode omp --validation-threads 4 --validation-min-rows 0 \
  < cpp/tests/fixtures/minimal_coherent_agh.txt
```

The generator verifies the production core's expected source hash before
creating experimental code. The probe keeps arithmetic and residual order,
uses private query slots, and avoids parallel floating-point reductions.
Measured internal parallelism did not show a stable benefit over the serial
slot control on the tested workloads, so production validation remains serial.
This experiment documents an optimization decision and its evidence.
