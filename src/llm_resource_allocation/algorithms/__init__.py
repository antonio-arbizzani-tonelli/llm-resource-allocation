"""M1-M3 mechanisms and GH Phase-1 coverage/scoring primitives."""

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

from .m3 import (
    M3ConfigurationDiagnostic,
    M3EvaluationState,
    M3NoUpgradeReason,
    M3UpgradeResult,
    select_m3_parallelism_upgrade,
)

from .phase1 import (
    Phase1ActivationScore,
    Phase1CandidateEvaluation,
    Phase1CommonConfigurationDiagnostic,
    Phase1CommonConfigurationQueryDiagnostic,
    Phase1CoverageResult,
    Phase1QueryExclusionReason,
    Phase1NonRankableReason,
    Phase1QueryCoverageDiagnostic,
    compute_phase1_activation_score,
    compute_phase1_pair_coverage,
    evaluate_phase1_candidate,
    rank_phase1_candidates,
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
    "M3ConfigurationDiagnostic",
    "M3EvaluationState",
    "M3NoUpgradeReason",
    "M3UpgradeResult",
    "select_m3_parallelism_upgrade",
    "Phase1ActivationScore",
    "Phase1CandidateEvaluation",
    "Phase1CommonConfigurationDiagnostic",
    "Phase1CommonConfigurationQueryDiagnostic",
    "Phase1CoverageResult",
    "Phase1QueryExclusionReason",
    "Phase1NonRankableReason",
    "Phase1QueryCoverageDiagnostic",
    "compute_phase1_activation_score",
    "compute_phase1_pair_coverage",
    "evaluate_phase1_candidate",
    "rank_phase1_candidates",
]
