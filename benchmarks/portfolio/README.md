# Portable indicators and recorded native evidence

`summary.json` and `indicators.csv` are derived from the published Stage-1 CSVs
and `raw/`. Run from the repository root:

```bash
python scripts/summarize_portfolio_results.py
python scripts/summarize_portfolio_results.py --plots
```

The first command needs only the standard library. The second also needs the
optional Matplotlib dependency. These commands verify input hashes and derive
indicators; they do not rerun the historical allocation or timing campaigns.
See [the results report](../../docs/RESULTS.md) for their scientific scope.

`raw/manifest.json` identifies every retained native artifact, its original
relative origin and original SHA-256, its current SHA-256, and any publication
transformation. Numeric observations are unchanged. Absolute host paths are
removed or made relative; address-dependent linked-library listings are
omitted. Paths under `original_origin` identify historical provenance and are
not expected to exist in a fresh clone. Measured source inventories identify
the historical source rather than the current release.

The serial profile hashes the LF numeric transport sent to the child process;
its Windows saved input files used CRLF. The published serial inputs restore
LF to match that recorded transport hash, retaining the original file digest
and this line-ending transformation in the manifest.

The native subset includes serial repeated timings and numeric inputs,
cross-language parity records, full OpenMP warm evidence and compact timed
outputs, exact campaign inputs, and active/passive validator-probe records.
Large probe profiles omit individual observer-call lists and do not ship the
large original timed sample files; they preserve complete warm scientific
states, per-run timings, phase totals and aggregate observer statistics.
Original hashes record the transformation boundary.

The OpenMP manifests use paths relative to the repository root. After building
the native code, their recorded fixed inputs can be replayed from that root:

```bash
cpp/build/release/pacs_campaign --schedule dynamic --threads 8 < benchmarks/portfolio/raw/openmp/inputs/uniform/manifest.txt
```

This is a new replay of current code, distinct from the retained timing. Core
time, complete invocation time, hardware/compiler settings and sample minima
must remain separate when comparing it with the historical observations.
