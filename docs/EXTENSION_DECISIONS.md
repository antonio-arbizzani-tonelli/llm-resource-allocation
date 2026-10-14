# Extension decisions

These explicitly opt-in numerical/experimental choices apply only to the
2026-10-14 extension. Historical results, frozen fixtures and defaults remain
their original evidence. The formulation and GH/AGH are Cheng and Nguyen's.

## D-0105 — Optional scale-aware Stage-2 objective agreement

**Provenance:** user-approved IMPLEMENTATION CHOICE for numerical acceptance;
the nonzero relative coefficient is an explicit ASSUMED numerical policy.
The LP, arithmetic and independent constraint thresholds do not change.

`|a-b| <= max(absolute_tolerance, relative_tolerance * max(|a|, |b|))`.
`absolute_tolerance=1e-8` and `relative_tolerance=0` preserve D-0025's default.
Stage 2 exposes `objective_relative_tolerance` as a keyword-only option;
P_DM keeps its existing default acceptance. Values/decisions are never repaired.

Select `1e-12` for the opt-in campaign: the smallest requested sensitivity
coefficient, above the maximum `3.401745961429846e-16` relative disagreement
in the 204 historical rejection cases. Sweep `1e-12` through `1e-6` explicitly.
This finite roundoff evidence is not a general solver-error guarantee.
An injected relative objective error of at least `1e-6` remains rejected under
the selected policy. Historical classifications are not rewritten.
