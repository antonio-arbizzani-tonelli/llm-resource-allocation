# Publishing reviewed changes

The current publication pipeline uses [configs/publication.json](../configs/publication.json)
and [scripts/prepare_release.py](../scripts/prepare_release.py). It exports the
allowlisted Python, C++20, documentation, presentation and benchmark evidence
into a new directory and generates `release-manifest.json`. The older
`prepare_stage1_release.py` pipeline covers a historical Stage-1-only subset.

## Establish the public baseline

Work from the repository root and inspect the live default branch before
preparing a publication:

```bash
git ls-remote --symref origin HEAD
```

Record the branch and full commit SHA in the publication review. Compare the
public commit with the local publication checkout and inspect any intervening
changes before copying files. Keep unrelated development edits in place; use a
separate clean checkout of the intended public branch for the publication
commit. A current baseline is recorded in [PUBLICATION_REVIEW.md](PUBLICATION_REVIEW.md).

## Prepare the reviewed payload

In the development workspace, some allowlist entries have a `source` field:
for example, `docs/public/README.md` exports to `README.md`. Edit that source
and keep any reader mirror consistent. In a public clone, the same configuration
refers directly to the delivered paths. Add each newly published file to the
allowlist explicitly; experimental inputs and settings have their own authority.

Export to a new destination, since the exporter refuses to overwrite an existing
directory or a source directory:

```bash
python scripts/prepare_release.py --output build/publication-review
```

The exporter reads all approved files before writing. Recognized source/documentation text formats outside `benchmarks/`
are normalized to LF; benchmark evidence keeps its original bytes. The generated
manifest records each delivered path, byte count and SHA-256. The exported
configuration removes development-only source mappings, allowing a fresh clone
to verify itself without the private workspace.

Do not edit the generated manifest by hand. If reviewed files change, create a
fresh export so the manifest describes the final payload.

## Verify the actual export

Run the prescribed check inside the exported tree:

```bash
cd build/publication-review
python scripts/prepare_release.py --check
```

Check relative links and anchors from their published destinations, presentation
sources, and any rendered slides. Every numerical claim and chart must retain
an identifiable artifact and case, row or field. Keep original campaigns,
retrospective policy replays and new measurements separate. Historical test
results describe their own source checkpoints.

For documentation-only changes, static source/artifact comparisons, link checks,
visual presentation review and export verification are sufficient. Do not run
new benchmarks to validate prose. Changes to Python behavior require the
repository's regression procedure; this publication pipeline does not replace it.

## Commit from the isolated publication checkout

Copy only the reviewed exported payload into a clean checkout based on the
verified public branch. Inspect the complete diff, including the publication
configuration and generated manifest. Confirm that algorithms, benchmark
artifacts and experimental configuration are unchanged when the scope is
documentation and presentation only.

Stage the exact reviewed paths, rather than the development workspace. In the
publication checkout, use an explicit list suited to that release:

```bash
git diff --check
git diff --stat
git add -- README.md docs/RESULTS.md docs/KEY_NUMBERS.md docs/EXTENSION_REPORT.md
```

Add the other reviewed documentation, presentation and publication metadata
paths explicitly, then inspect the staged diff before committing:

```bash
git diff --cached --check
git diff --cached --stat
python scripts/prepare_release.py --check
git commit -m "Revise portfolio documentation and presentation"
```

Recheck the remote branch before an ordinary push. If it advanced, integrate
those changes and review again; do not force-push over remote work. After
publication, verify the remote SHA, read back changed public files, check their
hashes against the committed export, and inspect the hosted CI status. Record
any unavailable check or unresolved issue separately from successful results.

Repository description, topics and profile pins are independent metadata;
publishing these files does not require changing them.
