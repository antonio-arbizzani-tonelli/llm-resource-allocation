# Recorded Stage-2 stress evidence

This is the primary AC restart executed on October 13, 2026: forty workers,
37 accepted sources, 1,850 operational LP attempts. [The results guide](../../docs/STAGE2_RESULTS.md)
explains coverage, recovery, paired costs and numerical rejections. The previous
battery-start attempt is retained locally and excluded from every published metric.

`evidence.zip` preserves 2,027 portable files (40,974,887 uncompressed bytes),
including all 1,970 job files, logs, original execution metadata and the local
post-run audit. Its archive SHA-256 is
`b4f85dee87b6f248180b31a3e7877bab0c2bdbe019dc08908615b2906decf5b7`.
[evidence_manifest.json](evidence_manifest.json) identifies every entry;
[provenance.json](provenance.json) retains original/portable hashes and path
redactions. Scientific numerical observations are unchanged. Symbolic redacted
paths in metadata/logs are historical labels, not executable paths.

`scientific-source-snapshot.zip` contains exact measured scientific sources,
configuration and reviewed runtime scripts. Native binaries and the private
document-structure test are excluded; neither is used by this Stage-2 replay.
The original snapshot manifest retains the historical source/binary identities.

## Solver-free validation replay

From a fresh clone, after installing the base dependencies, extract both archives
into an ignored results directory. This command verifies the archive and all
entry hashes before extraction:

```bash
python -c "import hashlib,json,pathlib,zipfile; d=pathlib.Path('benchmarks/stage2_stress_2026-10-13'); o=pathlib.Path('results/stage2_replay/evidence'); m=json.loads((d/'evidence_manifest.json').read_text()); assert hashlib.sha256((d/'evidence.zip').read_bytes()).hexdigest()==m['archive_sha256']; z=zipfile.ZipFile(d/'evidence.zip'); assert all(hashlib.sha256(z.read(r['path'])).hexdigest()==r['sha256'] for r in m['files']); z.extractall(o); zipfile.ZipFile(d/'scientific-source-snapshot.zip').extractall(o/'snapshot')"
python benchmarks/stage2_stress_2026-10-13/replay_audit.py --campaign results/stage2_replay/evidence --output results/stage2_replay/analysis
```

The replay verifies frozen source/configuration hashes, all forty completed
job inventories and the exact fifty-point grid for each accepted deployment.
It re-evaluates forty Stage-1 constraint reports, 1,850 frozen-routing reports,
850 extracted operational reports and all usable objective/service indicators.
It checks objective disagreement separately and preserves the 204 rejections.
No solver or Gurobi license is needed; no scientific algorithm or decision is
rerun/repaired. The output directory must be separate from the recorded evidence.

The generated analysis reproduces the published quantitative fields. Its audit
timestamp and helper fingerprint identify the new replay and therefore differ
from the original local audit. The public replay checks all supplied frozen
source files and requires all domain/scientific modules and runtime scripts;
it does not rebuild or verify the unused native binaries.

Use [the full campaign guide](../../docs/NIGHTLY_CAMPAIGN.md) to execute new
scientific experiments. A different backend/configuration creates a separate
campaign rather than replacing these observations. Regenerate the three figures
with `python benchmarks/stage2_stress_2026-10-13/plot_results.py` after installing
the optional plotting dependencies.
