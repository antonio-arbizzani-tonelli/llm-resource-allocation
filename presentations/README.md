# Presentation files

**LLM Resource Allocation: A verified reference and CPU performance study**,
by Antonio Arbizzani Tonelli:

- [Read the PDF](llm-resource-allocation.pdf).
- [Download the PowerPoint file](llm-resource-allocation.pptx).
- [Read the evidence guide](../docs/PRESENTATION_BRIEF.md) for implementation
  boundaries, timing definitions and the separate Stage-2 cohorts.

The corrected files were supplied on 15 October 2026 and replace the earlier
delivery at commit
[`26ab90c`](https://github.com/antonio-arbizzani-tonelli/llm-resource-allocation/commit/26ab90ce09ad3c5f011ac92200eb716806a0bc90).
Both now have **21 content slides/pages**: position 10 contains the OpenMP
throughput plot and its experimental conditions. The other 20 PowerPoint slides
and their notes are unchanged; PDF text outside page 10 is unchanged. The supplied
files are published byte for byte, without editing their contents.

In the supplied PDF, chart labels `1,000` on page 17 and `850` on page 18 still
wrap vertically. The [original Stage-2 report](../docs/STAGE2_RESULTS.md) retains
the rejection breakdown; the evidence guide separates the original and replay
denominators.

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
limitations. The wrapped labels remain a delivery issue. The supplied OpenMP
chart uses existing measurements; this replacement adds no experimental result.

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
| `llm-resource-allocation.pdf` | 6,386,280 | `8b9f149d685957503a1f086fb16d0293238bbf8b1759b870807fd646cb1fef73` |
| `llm-resource-allocation.pptx` | 664,797 | `a8b278f9055947649db75e2b7a68827849e559463ce532c4c5b1e9508cdd901f` |

The [publication review](../docs/PUBLICATION_REVIEW.md) records the repository
baseline and delivery checks. The release manifest also identifies both files.
