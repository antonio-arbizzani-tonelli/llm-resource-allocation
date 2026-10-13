# Reproducing the experiments

Install the base package from the root README. All supplied workloads are
synthetic unless a workflow explicitly names an external trace. Timings
describe allocation software on a CPU, not deployed LLM serving latency.

## Stage-1 cost and solver evidence

Recorded coherent campaigns live under `benchmarks/reference/` and
`benchmarks/backend_comparison/`. Their manifests, full attempt records,
per-query metrics, plots and archived scientific source identify the measured
configuration. Backend comparisons use identical instances and scientific
source; a solver time limit can leave a feasible incumbent without proving
optimality.

To run the configurable synthetic benchmark:

```bash
python scripts/run_synthetic_benchmark.py --config configs/quick_benchmark.json --output results/synthetic_benchmark
```

Inspect the configuration before running: its solver backend, sizes, seeds,
warmups and time limit determine cost and execution time. Select `highs` for
the base installation. Optional plotting requires
`python -m pip install -e ".[plots]"`. Recorded campaigns have separate
configuration and source snapshots; re-running current source is a new run.

## Stage 2 and uncertainty

```bash
python examples/stage2_quickstart.py
```

The example prints machine-readable accepted routing and cost evidence on a
small coherent scenario. It keeps deployment fixed while checking realized
constraints and costs. Scenario-generation and ordered-batch APIs are in
`experiments/scenario_generation.py` and `experiments/scenario_evaluation.py`;
integration starts in `optimization/stage2_integration.py`.

Protocol comparisons preserve the paper version and sampling policy. Reusing
the same integer seed with different generation rules does not establish
identical scenarios. Historical literal experiment paths remain explicit and
are not converted into coherent measurements after the fact.

## Native performance and parallel campaigns

Build using [the native guide](../cpp/README.md), then:

```bash
python scripts/profile_cpp.py --output results/cpp_serial/profile
python scripts/profile_openmp.py --output results/openmp/profile --repeats 3 --batch-size 16
python scripts/profile_large_instances.py --mode baseline --binary cpp/build/release/pacs_serial --baseline-source-dir cpp --output results/large/profile --build-description 'GCC; C++20; -O2 -g -ffp-contract=off'
```

The runners retain warmups, samples, exact inputs and fingerprints. On Windows
add `--wsl Ubuntu` after building inside that distribution. Serial timing
excludes parsing and output. OpenMP speedup uses the same campaign executable's
serial schedule; complete invocation timing includes process/transport costs.
Cross-language runtime ratios involve different implementations and evidence
work and therefore do not isolate a language effect.

The optional `cpp/experiments/` validator probe is separate from production.
Its controlled comparisons test whether finer parallelism improves the serial
validator. The recorded conclusion is in [RESULTS.md](RESULTS.md).

## Derive the published indicators

```bash
python scripts/summarize_portfolio_results.py
```

This derives the compact portfolio indicators from delivered recorded evidence,
without rerunning optimization or timing. Source hashes and transformation
metadata identify portable copies of local measurements. The public
[results report](RESULTS.md) distinguishes measured values from derived ratios.

## Optional Azure trace-shape workflow

The official [Azure dataset](https://github.com/Azure/AzurePublicDataset/blob/master/AzureLLMInferenceDataset2024.md)
is external. Its raw CSV is not bundled. The downloader checks the official
release digest and records attribution; the historical replay combines trace
shape with synthetic model/GPU coefficients rather than author calibration.

```bash
python scripts/download_azure_trace.py
python scripts/preprocess_azure_trace.py --help
python scripts/run_azure_replay.py --help
```

Review `configs/azure_replay.json` before a replay; it retains a historical
literal fixture and may require optional Gurobi. These tools and their unit
tests are delivered, while a new calibrated Azure experiment is future work.
Dataset licensing and attribution remain those of its original publisher.

## Recorded overnight campaign extension

The [overnight guide](NIGHTLY_CAMPAIGN.md) provides a frozen, resumable 52-job
campaign for larger Python/C++ shapes, independent-case OpenMP scaling and
fixed-deployment Stage-2 sensitivity. The [larger timing study](PERFORMANCE.md)
and [Stage-2 stress study](STAGE2_RESULTS.md) were executed separately on
October 13. Both preserve raw observations, failures and frozen sources.
The [Stage-2 dataset guide](../benchmarks/stage2_stress_2026-10-13/README.md)
provides a solver-free validation replay and numerical-rejection diagnostics.
New optimization runs have their own configuration/environment identities.
