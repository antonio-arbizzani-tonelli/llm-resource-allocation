# Acceptance boundaries in the completed Stage-2 campaign

All forty workers finished; this is execution coverage, not forty fully feasible
grids. Thirty-seven Stage-1 sources were accepted and produced 1,850 attempted
LPs. The three rejected sources skipped 150 planned scenarios explicitly.

Of the 1,850 LPs, 646 passed scientific acceptance, 1,000 were reported infeasible
by Gurobi, and 204 had optimal solver status and independently feasible
constraints but failed the separate objective-agreement check. No full grid has
fifty accepted LPs; full-grid mean cost/service metrics are therefore unavailable.

The 204 objective rejections all occur at load 100000. Recorded discrepancies
are one to three floating-point spacings at their objective scale, at most
1.7881393432617188e-7 USD or 3.401745961429846e-16 relative. These magnitudes are
consistent with floating-point evaluation roundoff. The existing absolute
agreement threshold is 1e-8 USD; the campaign retains every rejection and does
not relax that threshold or count those results as usable.

The rejected P_DM sources all have time-limited feasible incumbents rather than
proven optima. Independent replay identifies:

| Source at load 100000 | Independent acceptance evidence |
|---|---|
| 16x4x4 | Error-SLO constraint rejected; objective also differs by 1.4901161193847656e-8 USD. |
| 32x4x4 | Constraints pass; objective differs by 2.9802322387695312e-8 USD. |
| 16x8x8 | Demand-balance constraint rejected; objective agrees exactly. |

The other five P_DM sources are accepted time-limited incumbents. None of the
eight Stage-1 P_DM solves establishes an optimum in this campaign.

Operational adaptation recovers 256 of 1,344 scenarios where frozen routing is
infeasible: 19.047619%. Cost comparison uses only the 390 scenarios where both
decisions are usable. On that paired subset, the reduction in summed C4+C5 is
5.857419%; no cost-saving claim is assigned to an infeasible baseline.
These are deterministic synthetic comparisons, not a real-world recovery
probability or measured cloud-bill saving. Pooled counts include three AGH seeds
and one GH/P_DM source per shape/load and cannot establish a method ranking.

The AC restart is the sole primary evidence. Its forty worker durations sum to
659.5209093 seconds (10.992 minutes), excluding coordinator/reporting overhead.
AC power is observed at launch and all six subsequent power samples. The earlier
battery-start run remains preserved separately and is excluded from these numbers.

Fresh post-run replay verifies forty Stage-1 validation reports, 1,850 frozen
routing reports and all 850 extracted operational reports, including the 204
numerical rejections. All serialized reports and independently recomputed usable
indicators agree exactly; 1,970 job files match the recorded SHA-256 inventory.

Machine-readable evidence: [analysis](analysis.json),
[numerical diagnostics](numerical_diagnostics.json), and the campaign's original
`summary.json`, raw scenario files and logs. A future change to numerical
acceptance would be a separate scientifically approved experiment, with these
original results preserved.
