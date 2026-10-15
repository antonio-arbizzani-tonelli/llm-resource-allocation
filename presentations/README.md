# Presentation files

**LLM Resource Allocation: A verified reference and CPU performance study**,
by Antonio Arbizzani Tonelli:

- [Read the PDF](llm-resource-allocation.pdf).
- [Download the PowerPoint file](llm-resource-allocation.pptx).
- [Read the evidence guide](../docs/PRESENTATION_BRIEF.md) for implementation
  boundaries, timing definitions and the separate Stage-2 cohorts.

Both files were supplied on 15 October 2026 and are published byte for byte,
without editing the slides. Each has 21 positions, including **a blank slide/page
10**, leaving 20 content pages. It falls between native scaling and OpenMP
diagnostics; the [extension report](../docs/EXTENSION_REPORT.md) retains the
complete OpenMP throughput evidence. In the supplied PDF, chart labels `1,000`
on page 17 and `850` on page 18 wrap vertically. The
[original Stage-2 report](../docs/STAGE2_RESULTS.md) retains the rejection
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
The numerical payload is unchanged in this publication. The source table still
lists position 10, whose supplied slide is blank. Current
[key numbers](../docs/KEY_NUMBERS.md), [results](../docs/RESULTS.md) and
[extension report](../docs/EXTENSION_REPORT.md) provide the full evidence and
limitations. The blank slide and wrapped labels remain delivery issues; this
publication does not add or reconstruct any chart.

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
| `llm-resource-allocation.pdf` | 5,943,311 | `39da177f5445202a2b0b47848078ab8940e44ee920fca3369195ff9878ff5e75` |
| `llm-resource-allocation.pptx` | 450,558 | `888cd876eaacad279ff7842924b513517e6bc6bcb99caaa7ddb58eb85498d1e8` |

The [publication review](../docs/PUBLICATION_REVIEW.md) records the repository
baseline and delivery checks. The release manifest also identifies both files.
