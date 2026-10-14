# Matched synthetic Stage-2 extension

Completed sources: 144/144; accepted: 136/144. Attempted LPs: 6800.

| Nominal load | Usable / attempted | Recovery / frozen failures | Paired scenarios | C4+C5 paired reduction | 95% shared-input cluster bootstrap |
|---|---:|---:|---:|---:|---|
| 200.0 | 870/1800 | 330/1260 | 540 | 4.945490% | [0.04640838272063797, 0.051770306464910466] |
| 2000.0 | 820/1800 | 280/1260 | 540 | 4.923512% | [0.04628602848205589, 0.05146725078776872] |
| 20000.0 | 930/1750 | 400/1220 | 530 | 5.156249% | [0.04726027206906497, 0.05526150021129388] |
| 100000.0 | 626/1450 | 311/1135 | 315 | 5.433509% | [0.049830662945300745, 0.05865710056327765] |

Accepted-source intersection: 40/48 prepared input identities. All methods share exact input hashes; acceptance can still differ.

Bootstrap interval endpoints in the table are proportions; multiply by 100 for percentages.

No infeasible baseline receives cost savings. Pooled by_load summaries can include unmatched accepted inputs; only by_method_on_matched_inputs uses the accepted-source intersection. Bootstrap resamples contributing shared-input clusters of usable pairs, preserving available shared-method dependence. Report each paired-source-grid count as the contributing input-cluster count. A one-cluster interval is degenerate and supports no precision claim. These are conditional synthetic intervals, not real-world probabilities or rankings.

The historical diagnosis records sufficient contradiction certificates and their supporting demand caps/balance; overlaps are permitted and unresolved cases stay explicit. No unique IIS is claimed.

Raw failures and decisions are retained in the ZIP archive(s) listed in evidence_manifest.json, with exact membership and per-entry/per-part hashes. The measured producer and scientific sources remain frozen in scientific-source-snapshot.zip; multipart archive transport and this report wording are separate post-processing, with the helper fingerprint recorded in the evidence manifest. Scientific observations, decisions and numerical arithmetic are unchanged. Replay: `python scripts/run_stage2_extension.py --output benchmarks/stage2_robustness_2026-10-14 --replay`.
