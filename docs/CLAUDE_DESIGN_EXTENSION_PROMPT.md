# Claude Design prompt — results extension

Copy the block below into Claude Design, or attach this Markdown file together
with the repository sources it identifies. It develops the existing
[presentation brief](PRESENTATION_BRIEF.md) and
[original prompt](CLAUDE_DESIGN_PROMPT.md), replacing the main experimental
story with the controlled results extension. The older presentation remains a
historical source; its figures must keep their original campaign labels.

Numerical authority is fixed to commit
`543ad4e640100a4c2a69febf17fe885bd452861e`. This prompt is added after that
commit and does not pretend to be contained in its own source snapshot.

```text
Create a complete, editable presentation in Italian about my project
“LLM Resource Allocation”. Use Italian for slides and speaker notes, including
technical captions. Keep code symbols, file names and commands unchanged.

Author: Antonio Arbizzani Tonelli.
Audience: scientific-computing faculty, C++ developers and GitHub portfolio
reviewers. Duration: 10–12 minutes. Format: 12 main slides, 16:9, with technical
appendices outside the spoken time. Write speaker notes that fit that duration.

Suggested title:
“LLM Resource Allocation: decisioni verificate, prestazioni misurate”

SOURCE CONTRACT

Repository:
https://github.com/antonio-arbizzani-tonelli/llm-resource-allocation

Use this exact numerical source commit:
543ad4e640100a4c2a69febf17fe885bd452861e

Raw file base, followed by the repository-relative paths below:
https://raw.githubusercontent.com/antonio-arbizzani-tonelli/llm-resource-allocation/543ad4e640100a4c2a69febf17fe885bd452861e/

Read first:
- docs/KEY_NUMBERS.md: values, denominators, timer boundaries and replay.
- docs/EXTENSION_REPORT.md: hypotheses, results, limitations and deviations.
- docs/EXTENSION_ENVIRONMENT.md: machine and measurement conditions.
- docs/extension_numbers.json: final machine-readable aggregate.
- docs/PRESENTATION_BRIEF.md and docs/CLAUDE_DESIGN_PROMPT.md: inherited story.
- docs/MODEL.md, docs/ARCHITECTURE.md and docs/VALIDATION.md: foundations.
- docs/STAGE2_OBJECTIVE_POLICY.md: opt-in numerical policy.

The inherited prompt pins 8a11e7d533e929009ef5e1cae2dde6bdb18d217b. Treat that
as historical context, not the authority for new extension numbers. Do not
combine the largest ratios, different timers or different accepted cohorts
from separate campaigns. Use the supplied final aggregate, not the retained
initial aggregate that certifies only an earlier supplemental analysis.

If sources are inaccessible, report the missing paths and request the files.
Do not invent missing values, plots, solver outcomes or confidence intervals.
Some raw evidence is delivered in ZIP archives or multipart ZIP archives.
The retained analysis JSON/CSV and published plots are sufficient for the
presentation; inspect or unpack the archives only when deeper evidence is
needed. Never replace an unavailable record with a plausible reconstruction.

ATTRIBUTION AND SCOPE

Attribute the mathematical formulation and GH/AGH algorithms to Cheng and
Nguyen, arXiv:2604.07472, with v2 as the main scientific specification and v1
as a secondary source. Attribute the independent implementation, unit
conventions, validation, C++ port, measurements and experiments to this project.

All new experiments use synthetic project inputs. Runtimes measure CPU
allocation software; GPU capabilities and delays are modeled coefficients.
This is engineering and scientific verification evidence, without a numerical
replication claim for the authors’ tables or a real GPU-serving deployment.

CORE STORY

Begin with the allocation problem, then show why a trustworthy decision needs
an independently checked scientific state. Explain how the Python reference
and C++20 implementation support that check. The extension then asks four
practical questions: how much faster is the existing native implementation
under matched conditions; how does runtime grow; what does parallelism buy;
and when do adaptation and longer exact-solver budgets improve accepted results?

Make one claim per slide. Select a few strong figures rather than filling
slides with every measured number. Keep technical caveats beside their claims
in a short caption and explain their consequences in the notes.

PROPOSED TWELVE-SLIDE SEQUENCE

1. “Una scelta economica deve rispettare il servizio”
   Present the author and the question: assign heterogeneous models/resources
   while respecting demand, cost and SLO constraints. Visual: workload →
   allocator → modeled model/GPU alternatives. Attribute the source paper.

2. “Due stadi separano deployment e adattamento”
   Stage 1 selects deployment and routing; Stage 2 holds deployment fixed and
   adapts routing and unmet demand. Show what is fixed and what changes.
   Put “software su CPU; risorse GPU modellate” visibly on the slide.

3. “Un risultato è utilizzabile dopo una verifica indipendente”
   Show input → algorithm/solver → plain decision → independent validator.
   Separate completion, constraint feasibility, objective agreement and solver
   termination. Unit conversions have explicit boundaries. Status “optimal”
   describes the constructed solver model and cannot replace these checks.

4. “Il confronto controllato conferma il vantaggio del codice nativo”
   Highlight AGH 16×4×4, load 200, ten paired rounds in the same WSL environment:
   core ratio of medians Python/C++ = 120.54×, 95% CI [109.75, 131.22];
   complete-invocation ratio = 99.70×, CI [93.26, 107.26]. Use a compact paired
   comparison with separate core and invocation panels, not one unlabeled ratio.
   Core medians: Python 8.425024 s, C++ 0.069892 s. Invocation medians:
   Python 9.883960 s, C++ 0.099137 s. The campaign verifies 480/480 worker calls.
   Explain in notes: core includes a complete fresh-result public solve with
   traces and validation, excluding startup/parsing/projection/output/destruction;
   invocation is one Linux subprocess from startup through exit. Core excludes
   same-process warmup; invocation has no in-process warmup. Python internally
   validates input/builds PdmProblemData inside its core call, whereas C++ receives
   a prepared lattice before its timer. This compares the existing complete
   implementations and is not an equal-operation or pure-language speedup.

5. “La crescita delle istanze costa più ad AGH”
   Use the new native query-scaling chart: I = 16, 32, 64, 128, 256, 384 at J=K=4;
   five input seeds per size and three native core samples per method/instance.
   Empirical log-log exponents: GH 1.6615, CI [1.6402, 1.6798], R² 0.9903;
   AGH 1.9402, CI [1.9254, 1.9600], R² 0.9975. Display “pendenze empiriche
   nell’intervallo misurato”. Do not write GH = O(I^1.66) or AGH = O(I²).
   In notes: fit the median of three samples for each instance; intervals
   resample five entire seed grids, holding those medians fixed. The menu
   experiment is a separate dimension and belongs in the appendix.

6. “Otto thread accelerano il batch, con efficienza parziale”
   New OpenMP evidence: 32 mixed GH/AGH cases, 30 paired core rounds,
   cores/close/dynamic/chunk1, unsorted, default allocator. Eight-thread
   speedup = 4.0223×, CI [3.7636, 4.4243]; efficiency = 50.28%.
   Plot the same-setting team-size series against its own one-thread control.
   Mention that sixteen threads further reduce observed elapsed time but
   offer lower efficiency. Explain that independent cases run in parallel;
   the individual scientific solve remains serial.
   Notes: 6,030/6,030 observations cover 201 factor-separable settings. These
   are exploratory comparisons; physical P/E-core, cache, SMT and throttling
   causes are unresolved in WSL. Avoid a causal explanation based on wall-idle
   proxies or an Amdahl-equivalent fitted fraction.

7. “Più tempo al solver cambia alcuni confronti di costo”
   Use one accepted same-input example, 10×10×10/load 1: AGH 1,150.055 USD;
   HiGHS 20 s incumbent 1,274.759 USD; HiGHS 120 and 600 s incumbents
   915.549 USD. Label the values “costo modellato per orizzonte sintetico”.
   This is a local ordering reversal, not proof that either method dominates.
   Put “incumbent al limite; ottimalità non dimostrata” visibly beside the chart.
   Notes: all four inputs receive fresh, independent cold solves at 20/120/600 s,
   with no incumbent transfer. 20/20 measured jobs complete, 18/20 pass
   scientific acceptance. Derived normalized gaps remain approximately
   98.67–100%, so the bounds certify little about distance to the optimum.
   Gurobi is unavailable on the WSL host; no new three-way ranking is supported.
   Keep the full solver table and rejected rows in an appendix.

8. “I rifiuti numerici sono distinti dalle infeasibilità”
   Retain the historical Stage-2 denominator: 1,850 attempted LPs from 37
   accepted fixed-deployment sources. Original policy: 646 usable results,
   1,000 infeasible, 204 objective-only rejections. Another 150 scenarios are
   skipped after three rejected Stage-1 sources and lie outside 1,850.
   Use three clearly labeled categories. A completed job is not a usable LP.

9. “Una politica esplicita recupera i soli rifiuti da arrotondamento osservati”
   The extension independently replays the same retained decisions, with no
   new solve or decision repair. Optional Stage-2 objective agreement:
   |a-b| ≤ max(abs_tol, rel_tol × max(|a|,|b|)), selected rel_tol = 1e-12.
   Existing defaults remain abs_tol = 1e-8 USD, rel_tol = 0; constraint
   tolerances and Stage-1 acceptance are unchanged.
   The optional policy recovers 204/204 objective-only rejections: usable
   attempts become 850/1,850, while all 1,000 infeasible attempts stay rejected.
   Adaptation recovers 344/1,344 infeasible frozen baselines = 25.5952%.
   On 506 usable frozen/adapted pairs, summed C4+C5 reduction is 5.957974%,
   95% cluster-bootstrap CI [5.745418%, 6.063490%]. Use 25.6% as the main
   number; keep cost and the 37 source-grid bootstrap units in the notes.
   An injected relative objective error around 2e-6 remains rejected. This
   validates observed cases, not universal solver precision. The new 506-pair
   cohort differs from the original 390-pair cohort; do not present their
   pooled cost difference as a causal benefit of changing the policy.

10. “Il beneficio di Stage 2 si osserva anche ai carichi intermedi”
    Show the new per-load figure for 200, 2,000, 20,000 and 100,000.
    Conditional recovery spans 22.22–32.79%; conditional paired summed C4+C5
    reductions span 4.9235–5.4335%, with their published intervals.
    Notes must identify 144/144 sources completed, 136 accepted, 6,800 LPs
    attempted, 3,246 usable and 400 skipped after eight objective-only
    Stage-1 rejections. Those Stage-1 results remain rejected. Shared seeded
    inputs are matched across GH/AGH/P_DM, but the accepted three-method
    intersection is 40/48 and operating cohorts/denominators differ.
    These per-load pooled figures support no general method ranking. No
    savings are credited to infeasible frozen baselines; a modeled cost
    reduction can accompany greater unmet demand. It is not a cloud bill.

11. “L’evidenza resta delimitata e riproducibile”
    A compact evidence map: same-input comparisons, independent checks,
    retained failures, frozen source/input hashes and numerical replay.
    Beside it, state the remaining limits: synthetic calibration, modeled
    GPU coefficients, weak MILP bounds, unavailable WSL Gurobi comparison,
    unresolved physical causes of OpenMP scaling and limited Python parity
    on large instances. This should explain what a reader may conclude.

12. “Il contributo è una base verificabile per il lavoro successivo”
    Summarize the contribution as implementation + verification + native
    engineering + controlled experiments. Show the GitHub URL and an editable
    clickable link. Future work: author-data calibration/paper comparisons,
    native Stage 2 and solver integration, memory profiling and then a validated
    MPI decomposition. Optional memory WP7 was not performed; claim no new
    memory improvement, lean-trace implementation or MPI result.

APPENDICES

A. Timer and statistics contract: separate ratio of medians from median of
   paired ratios. The latter values at the highlighted runtime point are
   117.8295 core and 102.4151 invocation, with their own reported intervals.
   Keep them labeled; do not substitute them for 120.5437 and 99.7005.

B. Verification boundaries: the historical campaign has sixteen complete
   Python/C++ comparisons and 185,832 bit-identical numeric values. Its two
   AGH MemoryError endpoints have final-decision checks without full algorithm
   parity. Separately, new scaling has 90/90 method/instance points and 270/270
   native samples, with full Python parity only for the 20 I=16/32 points;
   the other 70 have independent final-decision validation. Never invent a
   Python timing or speedup for a failed historical run.

C. Native menu scaling: I=64, J×K = 4×4, 8×4, 8×8, 12×12; five input seeds.
   Empirical exponents GH 0.9455 [0.9185, 0.9707], R² 0.9928; AGH 1.4461
   [1.4065, 1.4998], R² 0.9694. Different aspect ratios and structural branches
   confound a single menu-product exponent. Do not extrapolate.

D. OpenMP selection: the fastest selected sorted sixteen-thread setting has
   median 0.220359 s and speedup 4.7871 [4.5179, 5.2513] against its OWN sorted
   one-thread control. Sorting effect at sixteen threads is only 1.0053
   [0.9592, 1.1998], so an ordering benefit is unestablished. The unsorted
   sixteen-thread baseline is 4.5536×, efficiency 28.46%. Selection among 201
   settings lacks held-out confirmation. The earlier 4.20×/52.5% eight-thread
   campaign used 18 rounds and retains its historical scope; do not splice it
   with the new 30-round figures. Timed compact fingerprints are not rich-trace
   parity. The full 585-setting interaction grid was skipped under the budget.

E. Solver quality: reproduce all four same-input rows with accepted/rejected
   status. At 20 s AGH has lower cost in 3/4 accepted pairs; at 120 and 600 s
   HiGHS has lower cost in each of the three accepted pairs. The latter cohorts
   reject different cases, so aggregate ratios are conditional: median
   AGH/HiGHS = 0.845329, 2.103171, 2.103171; denominators 4/4, 3/4, 3/4.
   Intervals use 5,000 accepted-case resamples, seed 113, describing four
   convenience inputs without population inference. Reject 10×10×10/load200/
   120 s and 6×6×10/load100,000/600 s for independent constraint violations;
   their diagnostic native costs must not enter accepted rankings. All twelve
   HiGHS MILPs report feasible/maxTimeLimit, not an optimum. Native MIPGap is
   unavailable. Normalized gap is separately derived as
   |incumbent-bound|/|incumbent| with documented missing/zero rules; range
   0.986719115–0.999999981 includes diagnostic rejected incumbents.

F. Stage-2 accounting: give per-load denominators/intervals and distinguish
   attempted, accepted, skipped and independently infeasible frozen baselines.
   Historical infeasibility has sufficient certificates for 1,000/1,000
   cases: 940 error-SLO and 120 compute-capacity, with 60 overlapping. These
   are nonexclusive certificates, not unique IIS or proof of a sole cause.

FIGURE SOURCES

Use the published PNG/SVG files, or redraw from retained JSON/CSV while
preserving all values, axes, units, intervals and scientific status markers:
- benchmarks/matched_runtime_2026-10-14/analysis/core_ratios.png
- benchmarks/matched_runtime_2026-10-14/analysis/invocation_ratios.png
- benchmarks/instance_scaling_2026-10-14/analysis/query_scaling.png
- benchmarks/instance_scaling_2026-10-14/analysis/menu_scaling.png
- benchmarks/openmp_diagnostics_2026-10-14/plots/speedup.png
- benchmarks/stage2_policy_2026-10-14/plots/policy_comparison.png
- benchmarks/stage2_robustness_2026-10-14/plots/per_load.png
- benchmarks/solver_quality_2026-10-14/solver_quality.png

For a selected example, recreate a simple chart from the cited values rather
than shrinking a dense all-cases plot. Do not crop away status markers or
confidence intervals that qualify the displayed claim. Keep full diagnostic
plots in appendices when needed. Source filenames stay fixed in the notes.

VISUAL DIRECTION AND DELIVERY

Use a light background, a clear typographic hierarchy, readable chart labels
and a restrained consistent palette: Python/reference, native code, parallel
execution and accepted Stage-2 adaptation need distinguishable roles. Use
real project plots and simple allocation/validation diagrams. Avoid decorative
GPU-cluster photos or visuals that imply measured GPU inference.

Place “dati sintetici del progetto; software di allocazione su CPU” on
experimental slides. Keep modeled USD costs distinct from runtime in seconds.
Use “rapporto delle mediane”, “intervallo al 95%” and explicit denominators.
Make source citations discreet but legible. Do not claim universal speedup,
cloud savings, heuristic optimality, complete large-point Python parity,
asymptotic complexity or numerical reproduction of the paper.

Deliver the editable 12-slide presentation, timed Italian speaker notes,
technical appendices and a claim-to-source table. Verify readability,
overlap, arithmetic, status labels, campaign dates, timer boundaries and
scientific attribution before delivery. The main deck should work as a spoken
research narrative; the appendix and source table should support questions.
```

## Traceability for the recommended claims

Paths below refer to the pinned numerical source commit. Replay commands run
from a repository checkout with its documented dependencies. Numerical replay
uses retained evidence; it is outside the measured timings.

| Claim / placement | Authoritative source | Boundary or denominator | Replay |
|---|---|---|---|
| Matched AGH core 120.5437× / invocation 99.7005×; slide 4 | [WP1 analysis](../benchmarks/matched_runtime_2026-10-14/analysis/analysis.json), [key numbers](KEY_NUMBERS.md) | AGH 16×4×4/load200; ten same-WSL pairs per separate timer; ratio of medians; implementation costs differ | `python scripts/run_matched_runtime.py replay --output benchmarks/matched_runtime_2026-10-14` |
| Matched coverage 480/480; slide 4 notes | [WP1 status](../benchmarks/matched_runtime_2026-10-14/status.json) | 12 method/configuration points × two timer boundaries × two runtimes × ten rounds | Same WP1 replay |
| Empirical query GH 1.6615 / AGH 1.9402 and R²; slide 5 | [WP5 analysis](../benchmarks/instance_scaling_2026-10-14/analysis/analysis.json), [fit report](../benchmarks/instance_scaling_2026-10-14/analysis/report.md) | Six query sizes, five input seeds, 30 instances per method; median of three core samples; five seed bootstrap clusters | `python scripts/run_instance_scaling.py replay --output benchmarks/instance_scaling_2026-10-14` |
| Menu slopes / new parity coverage; appendices B–C | [WP5 fit report](../benchmarks/instance_scaling_2026-10-14/analysis/report.md), [final replay](../benchmarks/instance_scaling_2026-10-14/final_replay_verification.json) | Four menus at I=64; 20 instances per method; 90 total method/instance points, 20 full Python parity points | Same WP5 replay |
| Eight-thread 4.0223× / 50.28%; slide 6 | [WP2 analysis](../benchmarks/openmp_diagnostics_2026-10-14/analysis/extension.json) | 32 fixed cases, 30 paired core rounds; same-setting one-thread control; cores/close/dynamic/chunk1, unsorted/default allocator | `python scripts/analyze_openmp_extension.py --output benchmarks/openmp_diagnostics_2026-10-14` |
| Selected 16-thread setting / unestablished sorting benefit; appendix D | [WP2 controls](../benchmarks/openmp_diagnostics_2026-10-14/analysis/same_team_controls.csv), [analysis](../benchmarks/openmp_diagnostics_2026-10-14/analysis/extension.json) | Selected among 201 settings; own sorted one-thread control for speedup; same-team unsorted control for sorting effect | Same WP2 analysis replay |
| HiGHS longer-limit example / acceptance / weak bounds; slide 7 and appendix E | [WP6 all rows](../benchmarks/solver_quality_2026-10-14/REPORT.md), [analysis](../benchmarks/solver_quality_2026-10-14/analysis.json) | Four fixed inputs; fresh cold solves at 20/120/600 s; 20 measured jobs, 18 accepted; accepted-only comparisons | `python scripts/extension_solver_quality.py summarize --output benchmarks/solver_quality_2026-10-14` |
| Historical 646 usable / 1,000 infeasible / 204 rejected; slide 8 | [Original Stage-2 analysis](../benchmarks/stage2_stress_2026-10-13/analysis/analysis.json), [historical report](STAGE2_RESULTS.md) | 1,850 LP attempts from 37 accepted sources; 150 skipped outside that denominator; original absolute-only policy | `python scripts/replay_stage2_policy.py --output benchmarks/stage2_policy_2026-10-14` verifies its archived historical inputs as well as the separate policy evidence |
| 204/204 rescued; 850/1,850; 344/1,344; slide 9 | [WP3 analysis](../benchmarks/stage2_policy_2026-10-14/analysis.json), [policy](STAGE2_OBJECTIVE_POLICY.md) | Retrospective same-decision replay, opt-in relative 1e-12; defaults unchanged; no decision repair/new solve | Same WP3 replay |
| C4+C5 reduction 5.957974%, interval; slide 9 notes | [WP3 selected policy](../benchmarks/stage2_policy_2026-10-14/analysis.json) | 506 usable pairs; ratio of cost sums; 37 source-grid bootstrap clusters; cohort differs from historical 390 | Same WP3 replay |
| Intermediate-load recovery 22.22–32.79% / reduction 4.9235–5.4335%; slide 10 | [WP4 analysis](../benchmarks/stage2_robustness_2026-10-14/analysis.json), [source results](../benchmarks/stage2_robustness_2026-10-14/source_results.json) | Load-specific frozen failures / usable pairs; 144 sources, 136 accepted, 6,800 attempted LPs; pooled cohorts include unmatched inputs | `python scripts/run_stage2_extension.py --output benchmarks/stage2_robustness_2026-10-14 --replay` |
| Historical 1,000 infeasibility certificates; appendix F | [WP4 diagnosis](../benchmarks/stage2_robustness_2026-10-14/historical_infeasibility.json) | 940 error-SLO / 120 capacity certificates; 60 overlap; sufficient nonexclusive certificates | Same WP4 replay |
| Historical 16 comparisons / 185,832 bit-identical values / MemoryError scope; appendix B | [Historical performance report](PERFORMANCE.md), [original presentation brief](PRESENTATION_BRIEF.md) | Original campaign, separate from new 20-point full Python parity; failed Python endpoints have no measured speedup | `python scripts/check_cpp_parity.py --frozen` checks retained scientific parity; original benchmark evidence remains separately identified in `PERFORMANCE.md` |

The formulation and algorithms remain attributed to Cheng and Nguyen:
[v2](https://arxiv.org/abs/2604.07472v2),
[v1](https://arxiv.org/abs/2604.07472v1). Those links identify the scientific
work; extension statistics come from this repository's synthetic campaigns.
