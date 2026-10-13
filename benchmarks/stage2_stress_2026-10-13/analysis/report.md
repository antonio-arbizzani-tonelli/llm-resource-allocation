# Stage-2 deterministic stress campaign

Completed workers: **40/40**; accepted sources: **37/40**.
Attempted LPs: **1850**; accepted LPs: **646**; fully accepted grids: **0/40**.
Worker wall durations total **10.99 minutes**. Fresh AC restart only.

Frozen routing fails in 1344 scenarios; operational adaptation recovers 256
(19.05% of those frozen failures).

| Method | Attempted | Accepted | Frozen failures | Recovered | Paired costs | Paired reduction |
|---|---:|---:|---:|---:|---:|---:|
| agh | 1200 | 378 | 858 | 123 | 255 | 6.0991% |
| gh | 400 | 126 | 286 | 41 | 85 | 6.0991% |
| p_dm | 250 | 142 | 200 | 92 | 50 | 0.0000% |

Paired reduction is (sum frozen C4+C5 − sum adapted C4+C5) / sum frozen C4+C5 on the same usable scenarios.

Fresh validation replay: 40 Stage-1 sources, 1850 frozen decisions and 850 extracted operational decisions (including numerical rejections); 1970 hashed job files verified.

Recorded statuses: `{"infeasible": 1000, "optimal": 850}`.

- Deterministic synthetic sensitivity grid, not paper numerical replication or a real-world probability model.
- Only the clean AC restart enters this analysis; the superseded first attempt is preserved separately.
- Recorded Stage-1 and Stage-2/frozen constraint validation and indicators are replayed without solver reruns or decision repair.
- Costs are paired only where frozen and adapted decisions are both usable; infeasible baselines receive no cost saving.
- Pooled counts include three AGH seeds and one GH/P_DM source per shape/load; pooled method costs are not a matched method ranking.
- Accepted-only service summaries are conditional on feasibility; an entire-grid mean requires fifty accepted LPs.
- Integrated LP duration excludes frozen validation, gzip/checkpoint I/O and worker startup.
