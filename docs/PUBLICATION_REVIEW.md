# Presentation publication review

## Public baseline

The reference is public default branch `main` at
[`5ab0cfe7db63ec9782de7a21b6c55a6625c55cc3`](https://github.com/antonio-arbizzani-tonelli/llm-resource-allocation/commit/5ab0cfe7db63ec9782de7a21b6c55a6625c55cc3),
verified against the live remote on 15 October 2026. The isolated publication
checkout was clean and matched this commit before the update. It includes the
recent shorter README; that revision and the earlier English results reports
are retained.

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

The supplied [PDF and PowerPoint files](../presentations/README.md) are copied
unchanged into `presentations/`. Their recorded SHA-256 hashes match the supplied
originals. Both have 21 positions, including a blank slide/page 10, leaving 20
content pages. The blank position interrupts the OpenMP narrative; the source
appendix still refers to it. The PDF also wraps chart counts `1,000` and `850`
vertically on pages 17 and 18. These supplied layout issues are documented and
remain unresolved; no chart or slide has been reconstructed.

The README now links the actual files. The former brief becomes a
[presentation evidence guide](PRESENTATION_BRIEF.md). Preparation-only design
instructions and the obsolete text draft are removed from the publication.
Earlier local HTML/PDF drafts remain separate historical development material.

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

- All PDF pages are rendered and visually inspected. The PPTX package and
  slide text are inspected; its 20 nonblank slides agree with PDF text.
  An independent PowerPoint application render is not performed.
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
