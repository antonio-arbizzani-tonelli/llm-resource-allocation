# Presentation publication review

## Public baseline

The reference is public default branch `main` at
[`0e0609789f9320e099f810c7c288f9ca90372c48`](https://github.com/antonio-arbizzani-tonelli/llm-resource-allocation/commit/0e0609789f9320e099f810c7c288f9ca90372c48),
verified against the live remote on 15 October 2026. The isolated publication
checkout was clean and matched this commit before the update. It includes the
recent shorter README and the supplied presentation with its restored OpenMP
slide 10. The README and earlier English results reports are retained.

The supplied slides identify source commit
[`80a9625ab62a3c5c70ede7a9dae97a61158e250a`](https://github.com/antonio-arbizzani-tonelli/llm-resource-allocation/commit/80a9625ab62a3c5c70ede7a9dae97a61158e250a),
whose scientific source and numerical payload remain unchanged at the baseline
above. The extension numerical checkpoint remains
`543ad4e640100a4c2a69febf17fe885bd452861e`. Historical measurements retain their
own source hashes, environments and verification counts.

A speaker note on slide 20 mentions a separate local 1,126-test run without a
retained artifact. That run is not independently verified here and is not used
as delivery evidence. The documented 1,131-test development checkpoint remains
a separate historical result.

## Delivered material

The supplied [PDF and PowerPoint files](../presentations/README.md) replace
the preceding copies in the project's `presentations/` folder. Their SHA-256
hashes match the newly supplied originals. Both retain 21 content slides/pages,
including the restored OpenMP plot at position 10.

Only the layout of slides 17 and 18 changes: chart counts `1,000` and `850` now
fit on one line. All ordered PowerPoint text runs are identical. The other
19 slide XML files, all notes, media and relationships are byte-identical;
package timestamp metadata is updated. No numerical or scientific content
changes.

PDF text is identical after removing line wrapping. Substantive visual changes
are confined to pages 17 and 18. Pages 2 and 7 have tiny glyph-rendering
differences without visible content or layout changes; the other 17 pages render
identically at the checked scale. The previously reported wrapped-label defects
are resolved in these supplied files, which are published without modification.

The [presentation evidence guide](PRESENTATION_BRIEF.md) and integrity table now
describe this delivery. Preparation-only design instructions and the obsolete
text draft remain absent from the publication. Earlier local HTML/PDF drafts
remain separate historical development material.

## Evidence review

The review compares presentation text, charts, source appendix and speaker notes
with the retained code and artifacts. The main results agree with their recorded
selectors: 63/63 release checks and 3,023 bitwise-identical compared values;
AGH Python/C++ ratios of medians 120.5437 for the core and 99.7005 for complete
invocation; eight-thread OpenMP throughput 4.0223 on the specified 32-case batch;
and native query-scaling slopes 1.6615 (GH) and 1.9402 (AGH). The
[evidence guide](PRESENTATION_BRIEF.md) and
[key numbers](KEY_NUMBERS.md) identify exact artifacts, conditions, intervals
and denominators.

The presentation distinguishes paper formulation, project implementation and
measured CPU evidence. GPU capacities and latencies are modeled coefficients.
Python/Pyomo, serial C++20 and independent-case OpenMP have distinct roles.
Core and complete invocation timing remain separate. Selected OpenMP settings
are exploratory; their intervals do not provide independent confirmation.
Original Stage-2 evaluation, retrospective optional-tolerance replay and the new
campaign occupy separate appendices. MPI and native Stage 2 remain future work.

These checks add no experimental evidence and do not establish GPU-serving
performance, actual cloud savings, heuristic optimality, asymptotic complexity
or numerical replication of the paper's tables. Missing author calibration,
matched larger Gurobi comparisons, physical OpenMP cause attribution and memory
profiling remain separate scientific work.

## Publication checks

- All 21 PDF pages are rendered and compared with the preceding delivery.
  Pages 17 and 18 are visually inspected to verify the corrected count labels;
  unchanged text and small glyph-rendering differences on pages 2 and 7 are
  checked separately. PPTX parts and all slide text are compared. An independent
  PowerPoint application render is not performed.
- Relative Markdown links and anchors are checked from exported destinations;
  pinned repository sources are resolved against Git objects.
- A fresh export and the isolated publication checkout pass the prescribed
  `python -B scripts/prepare_release.py --check`. The regenerated manifest
  covers 3,572 allowlisted files; the manifest itself is delivered separately.
- The complete exported tree is compared with the public baseline. Changes are
  limited to documentation, the two presentation files and publication metadata.
  Algorithms, tests, datasets, benchmark evidence and experimental settings are
  unchanged. No benchmark, optimization solve or performance sample is run.

Publication uses an ordinary push from the isolated checkout. Remote commit and
delivered file hashes are checked after publication; hosted CI is checked
separately and reported with the publication commit. Repository description,
topics, profile pins and unrelated local work are preserved.
