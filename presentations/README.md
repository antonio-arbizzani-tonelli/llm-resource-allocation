# Presentation files

**LLM Resource Allocation: A verified reference and CPU performance study**,
by Antonio Arbizzani Tonelli:

- [Read the PDF](llm-resource-allocation.pdf).
- [Download the PowerPoint file](llm-resource-allocation.pptx).
- [Read the evidence guide](../docs/PRESENTATION_BRIEF.md) for implementation
  boundaries, timing definitions and the separate Stage-2 cohorts.

The current files were supplied on 15 October 2026 and replace the delivery at
commit
[`0e06097`](https://github.com/antonio-arbizzani-tonelli/llm-resource-allocation/commit/0e0609789f9320e099f810c7c288f9ca90372c48).
Both have **21 content slides/pages**. The latest revision improves the layout of
slides 17 and 18: chart counts `1,000` and `850` now appear on one line. All text
and numerical values are unchanged. The other 19 PowerPoint slides, all notes
and media are byte-identical to the preceding delivery; PDF text is unchanged
apart from line wrapping. The files are published byte for byte, without editing
the supplied originals.

The [original Stage-2 report](../docs/STAGE2_RESULTS.md) retains the rejection
breakdown; the evidence guide separates the original and replay denominators.

## Scope and sources

The presentation covers the allocation problem, two-stage model, Python/Pyomo
reference, serial C++20 GH/AGH, cross-language checks and CPU benchmarks.
OpenMP schedules independent experimental cases. GPU capacities and serving
latencies are modeled inputs; the experiments measure allocation software on
CPUs. Core runtime and complete invocation remain separate measurements.
MPI and native Stage 2 remain future work.

Appendix A8 and PowerPoint speaker notes identify artifacts, selectors and public
source commit
[`80a9625ab62a3c5c70ede7a9dae97a61158e250a`](https://github.com/antonio-arbizzani-tonelli/llm-resource-allocation/commit/80a9625ab62a3c5c70ede7a9dae97a61158e250a).
The numerical payload is unchanged in this publication. Position 10 now matches
the OpenMP entry in the source table. Current
[key numbers](../docs/KEY_NUMBERS.md), [results](../docs/RESULTS.md) and
[extension report](../docs/EXTENSION_REPORT.md) provide the full evidence and
limitations. The supplied charts use existing measurements; this layout
replacement adds no experimental result.

The deck's 3,572-file manifest count describes its pinned source publication;
the regenerated manifest describes this delivery. A slide-20 note cites an
unarchived local test run; it is not independently verified by this delivery.

Original Stage-2 solves, the retrospective optional-tolerance replay and the new
seeded campaign occupy separate appendices. Selected OpenMP settings retain
their exploratory status. The results establish neither measured GPU inference
performance, real cloud savings, heuristic optimality nor numerical replication
of the paper's tables.

## File integrity

| File | Bytes | SHA-256 |
|---|---:|---|
| `llm-resource-allocation.pdf` | 6,396,217 | `772ffdd8c84f64c337558bc6e93595051e8aad351c0832338b484d5585cc576c` |
| `llm-resource-allocation.pptx` | 664,705 | `8546a2ae56880af925f2dce871406ad27a5d792d06df0db2240db60ca00aa6a1` |

The [publication review](../docs/PUBLICATION_REVIEW.md) records the repository
baseline and delivery checks. The release manifest also identifies both files.
