# Portfolio publication review

## Public baseline

The reference is public default branch `main` at
[`80a9625ab62a3c5c70ede7a9dae97a61158e250a`](https://github.com/antonio-arbizzani-tonelli/llm-resource-allocation/commit/80a9625ab62a3c5c70ede7a9dae97a61158e250a),
verified against GitHub on 15 October 2026. The isolated local publication
checkout matched that commit and was clean before these changes. No intervening
public changes needed integration. The four earlier local documentation
revisions were retained and formed the starting point for this publication.

The numerical extension checkpoint remains
`543ad4e640100a4c2a69febf17fe885bd452861e`. The later reference commit above
contains its numerical payload and the subsequent presentation instructions.
Historical measurements retain their own source hashes and environments.

## Review scope and changes

The review covers the published source, benchmark analyses and archives,
README, results reports, presentation brief and design prompts. The README's
opening benchmark table is shorter; the linked reports retain complete timer
definitions, denominators, intervals and limitations. Python/Pyomo, C++20 and
OpenMP are identified by their implemented roles. The validation report
labels the old overnight-preparation counts as a dated historical checkpoint,
avoiding confusion with the later completed campaigns.

Original Stage-2 results, the retrospective optional-tolerance replay and the
new seeded campaign remain separate. The public standard objective-agreement
default is unchanged. Modeled GPU capacities, latencies and dollar-valued
objectives are distinguished from measured CPU allocation runtime.

The [publication guide](GITHUB_PREPARATION.md) now describes the active
`configs/publication.json` / `prepare_release.py` workflow. Its earlier content
described the historical Stage-1-only exporter. The allowlist adds this review,
that guide and the presentation draft; the new export generates its manifest.

## Presentation assessment

The accessible local English teaching deck has 30 slides and a build manifest
dated 9 October. It presents C++/MPI as future work, Stage 2 as paper theory,
and the older literal unit convention. An earlier Italian HTML draft has a
similar historical scope. They remain local historical material and are not
published as the current project presentation. No existing project PPTX/PDF was
available; the two paper PDFs are scientific sources rather than slide decks.

The [English presentation draft](PRESENTATION_DRAFT.md) rebuilds the narrative
around the allocation problem, model, Python/Pyomo and C++20 implementations,
cross-language verification, runtime benchmarks and OpenMP. It identifies what
to retain from the existing material and provides essential slide text, visual
recommendations, precise sources and a prompt for Claude Design. It leaves the
final slide count and layout open. Detailed Stage-2 comparisons move to optional
appendices, where their policies and cohorts remain distinct.

The publication contains documentation and this draft. At the user's updated
instruction, rendered HTML/PDF work is retained locally outside the commit;
slide creation and modification stopped. The brief and current design prompt
now route to the text draft. Source links retain the reference commit above.

## Verification

- Static code inspection confirms the Pyomo/solver boundary, serial C++20
  GH/AGH, independent-case OpenMP and the distinct timing boundaries. The
  optional Stage-2 relative tolerance retains a default of zero.
- Exact exporter comparison found 3,533 existing scientific, source, test,
  benchmark, example and tooling payloads identical to the public baseline.
  The reviewed numerical claims agree with retained JSON/CSV. Eleven directly
  referenced portfolio hashes match; 15 ZIP archives with 23,978 entries pass
  CRC checks. These are read-only integrity checks, not experimental replays.
- Relative Markdown links are checked from the published destinations, including
  anchors and pinned source-file paths. Proposed charts and numerical claims
  identify retained evidence; the draft does not invent or generate new results.
- The generated export and isolated publication checkout pass
  `python scripts/prepare_release.py --check`. The manifest covers 3,572
  allowlisted files; the manifest itself is delivered separately.
- The commit is limited to documentation, the presentation draft and publication
  metadata. Algorithms, data, benchmark artifacts and experimental settings
  are unchanged. No new benchmark, optimization solve or performance sample
  is produced. Historical test counts are not presented as newly run tests.

The repository's CI runs automatically on publication. Its result is separate
from these documentation and presentation checks and is reported with the
publication commit.

## Scientific limits

These changes add no experimental evidence. The results remain conditional
synthetic CPU studies, with implementation-specific costs and distinct cohorts.
They do not establish GPU inference performance, actual cloud savings,
heuristic optimality, asymptotic scaling or numerical reproduction of the
paper's tables. Author calibration, matched larger Gurobi comparisons,
physical OpenMP cause attribution and optional memory profiling remain open.

Repository description, topics and profile pins are preserved. Publication
uses an ordinary push from the isolated checkout; it does not replace unrelated
development work or rewrite public history.
