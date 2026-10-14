# Release verification

Verification establishes the implemented scope through independent equations,
hand-derived examples, solver comparisons and cross-language checks.
Synthetic fixtures are verification inputs, not recovered paper data.

## Larger-instance performance verification

The [October 13 study](PERFORMANCE.md) retains 18 native method/shape points,
90 individual timings and 54 OpenMP setting/workload combinations. Sixteen
complete Python reference comparisons check 185,832 numeric values without
bitwise differences. Two separate native points pass Python independent
final-decision validation and bitwise objective agreement after the full AGH
reference failed with MemoryError. Their full algorithm parity is not claimed.

The OpenMP protocol checks 4,032 ordered case outputs in full warm comparisons
and 72,576 status/feasibility/objective outputs in measured compact invocations.
Actual teams and source/binary/input hashes are retained. Every complete
timing job's evidence is hashed; finished methods from stopped workers also
verify all their retained input/golden/native/sample pointers.

Final development regression: **1,046 tests pass**, no skips, **11.850 s**,
Python 3.14.3, stable source hashes. The exact base export runs **1,031 tests**:
**1,027 pass, four optional skips**, **7.471 s**, stable sources; its
[regression record](../benchmarks/release_checks/larger_performance_base_regression.json)
identifies the tested Python files. Eleven new checks cover analysis, archive
portability, partial finished methods, native final-decision validation and
explicit deferral without false completion. Four figures have PNG/SVG outputs
and were visually inspected. The verified evidence archive retains all
1,689 files with original/portable hashes and exact byte checks.
Extracting the delivered ZIP in the actual base export and rerunning analysis
reproduces all derived observations exactly; [the replay record](../benchmarks/release_checks/larger_performance_replay.json)
also confirms that existing scientific source files are unchanged.

## Historical overnight preparation checkpoint, 12 October

The prepared [overnight extension](NIGHTLY_CAMPAIGN.md) passes a complete
development regression of **1,035 tests**, no skips, **13.053 s** on Python
3.14.3. The exact base publication runs **1,020 tests**, with **1,016 passes and
four optional skips**, **13.950 s**; [its source-hash record](../benchmarks/release_checks/nightly_preparation_base_regression.json)
identifies the tested Python files. Fifteen new tests cover hand-derived stress
mapping/service indicators, configuration boundaries, snapshot tampering,
resume, timeout, interruption and failure reporting.

Fresh release binaries pass core/GH/AGH and OpenMP campaign tests. Five separate
minimal worker checks exercise GH, AGH and P_DM Stage 2 (two scenarios each),
paired Python/C++ profiling and OpenMP profiling/reporting. The PowerShell
wrapper passes syntax parsing. These verify preparation and execution plumbing;
at that preparation checkpoint, **0/52** declared overnight jobs had executed.
The later performance and Stage-2 campaigns are reported separately;
this historical preparation result does not describe their final execution state.

The checks below are the retained original release checkpoint.

## Checks performed before publication

- Complete development regression: **1,020 tests pass**, no skips, 11.793 s
  on Python 3.14.3. The public tree omits only the development-document
  structure test module, which checks private continuity logs and local PDFs.
- Fresh base installation of the actual publication: **1,005 tests run**,
  **1,001 pass and four optional checks skip**, 7.112 s, without Gurobi or
  plotting packages. Source hashes stay stable during both regressions.
  [The base regression record](../benchmarks/release_checks/base_regression.json)
  retains the exact counts, skipped checks and tested source hashes.
- Coherent Stage 2: **103 focused tests pass**, including seven new
  hand-derived checks for realized-arrival costs, horizon/residency factors,
  zero arrivals, historical compatibility and accepted source integration.
- Both public quickstarts run with HiGHS and accept their independent checks.
  Stage 2's nominal/doubled-demand observations are retained in
  [reference.json](../benchmarks/stage2/reference.json).
- Fresh GCC 13.3.0 C++20 release and AddressSanitizer/UndefinedBehaviorSanitizer
  builds pass core, GH/AGH, OpenMP campaign and optional validator-probe tests
  without warnings or sanitizer findings.
- Fresh [exported-source parity](../benchmarks/release_checks/cpp_parity.json)
  passes **63/63** with 3,023 final bitwise-identical values.
  [Exported campaign verification](../benchmarks/release_checks/openmp_verification.json)
  passes **90 complete ordered comparisons** across nine settings, observing
  1/2/4/8 threads. Historical larger cases separately retain 20,494 identical
  numeric values.
- The documented bounded HiGHS benchmark accepts **12/12** measured attempts
  in a fresh base installation; both public quickstarts and manifest checks pass.
- The indicator summarizer verifies retained observation hashes before
  deriving ratios. [The results report](RESULTS.md) defines their denominators
  and numerical scope.

Package/backend environment: Python 3.14.3, Pyomo 6.10.0, highspy 1.14.0;
optional licensed Gurobi checks use gurobipy 13.0.3. The papers' historical
software versions remain source metadata rather than this release's runtime.

The workflow tests Python 3.13/3.14 with HiGHS and builds/tests the native
implementation separately. Gurobi and plotting checks skip when optional
dependencies are absent. Hosted workflow results must be read from the
repository's Actions page; this document records local checks.

## Recheck a clone

The completed [Stage-2 stress campaign](STAGE2_RESULTS.md) also verifies **1,970
job-file hashes**, then replays **40 Stage-1**, **1,850 frozen-routing** and **850
extracted operational** validation reports and usable indicators. The latter
includes 204 feasible decisions rejected for objective disagreement; only 646
are scientifically usable. Forty completed workers do not imply 2,000 accepted
LPs: three sources skip 150 scenarios, and no fifty-point grid is wholly accepted.
The [portable evidence and replay](../benchmarks/stage2_stress_2026-10-13/README.md)
retain this distinction. The delivered ZIP was extracted and its replay passed;
all quantitative fields match the original audit, recorded in
[stage2_portable_replay.json](../benchmarks/release_checks/stage2_portable_replay.json).
The actual publication export also passes **1,031 tests: 1,027 pass and four
optional skips**, with stable Python source hashes, in a base environment without
Gurobi. [The regression record](../benchmarks/release_checks/stage2_publication_base_regression.json)
identifies the tested source files. Its standalone manifest check passes.
Source data, mathematical code and tolerances remain
unchanged by the documentation/evidence publication.

```bash
python -m pip install -e .
python -m unittest discover -s tests -q
python examples/stage1_quickstart.py
python examples/stage2_quickstart.py
python scripts/prepare_release.py --check
```

On Linux/WSL with GCC and GNU Make:

```bash
make -C cpp -j4 all test openmp campaign-test
make -C cpp -j4 MODE=sanitize test campaign-test
python scripts/check_cpp_parity.py --frozen
python scripts/check_openmp_campaign.py --output results/openmp/check
```

The generated [release manifest](../release-manifest.json) records every
delivered file and SHA256. A newly generated measurement is a new experiment;
historical source/input fingerprints describe the original recorded run.
Passing tests alone do not prove calibration or numerical replication of the
paper's complete experiments.
