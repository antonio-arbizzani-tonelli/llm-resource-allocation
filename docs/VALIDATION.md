# Release verification

Verification establishes the implemented scope through independent equations,
hand-derived examples, solver comparisons and cross-language checks.
Synthetic fixtures are verification inputs, not recovered paper data.

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
