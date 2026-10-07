"""M1/M2 scientific mechanisms and immutable evaluation evidence."""

from .m1 import (
    M1ConfigurationDiagnostic,
    M1SelectionResult,
    select_minimum_feasible_parallelism,
)

from .m2 import (
    M2CandidateEvaluation,
    M2ConfigurationEvidence,
    M2CoverageLimiter,
    M2EffectiveCoverageDiagnostic,
    M2EvaluationInputs,
    M2MarginalCostDiagnostic,
    M2UnrankableReason,
    compute_m2_effective_coverage,
    compute_m2_marginal_cost,
    evaluate_m2_candidate,
    rank_m2_candidates,
)

__all__ = [
    "M1ConfigurationDiagnostic",
    "M1SelectionResult",
    "select_minimum_feasible_parallelism",
    "M2CandidateEvaluation",
    "M2ConfigurationEvidence",
    "M2CoverageLimiter",
    "M2EffectiveCoverageDiagnostic",
    "M2EvaluationInputs",
    "M2MarginalCostDiagnostic",
    "M2UnrankableReason",
    "compute_m2_effective_coverage",
    "compute_m2_marginal_cost",
    "evaluate_m2_candidate",
    "rank_m2_candidates",
]
