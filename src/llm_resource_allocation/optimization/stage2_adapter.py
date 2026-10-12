"""Copy accepted Stage-1 ``z*, w*, y*`` into a Stage-2 fixed deployment.

Paper v2 Section 5.2 and v1 Eq. (12) fix these decisions and re-optimize ``x,u``.
The adapter preserves source identity and checks the shared deployment lattices.
"""

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import TYPE_CHECKING, Mapping, TypeAlias

from llm_resource_allocation.math.placement import PlacementDecisionState

from .pdm_run import PdmRunIdentity, PdmRunRecord
from .problem_data import ModelTierKey, PdmProblemData
from .stage2_problem_data import (
    Stage2FixedDeployment,
    validate_stage2_fixed_deployment,
)

if TYPE_CHECKING:
    from llm_resource_allocation.algorithms.agh import AGHResult
    from llm_resource_allocation.algorithms.gh import GHResult, GHRunIdentity

    Stage1Result: TypeAlias = PdmRunRecord | GHResult | AGHResult
    Stage1ResultIdentity: TypeAlias = PdmRunIdentity | GHRunIdentity
else:
    Stage1Result: TypeAlias = object
    Stage1ResultIdentity: TypeAlias = object


class Stage1Method(str, Enum):
    """Identify the Stage-1 method that supplied the accepted placement."""

    P_DM = "p_dm"
    GH = "gh"
    AGH = "agh"


class Stage1ToStage2FailureReason(str, Enum):
    """Classify rejected sources and fixed-deployment conversion failures."""

    UNSUPPORTED_RESULT_TYPE = "unsupported_result_type"
    STAGE1_RESULT_NOT_ACCEPTED = "stage1_result_not_accepted"
    NO_VALID_AGH_INCUMBENT = "no_valid_agh_incumbent"
    SOURCE_VERSION_MISMATCH = "source_version_mismatch"
    SOURCE_IDENTITY_MISMATCH = "source_identity_mismatch"
    STRUCTURALLY_INCOMPATIBLE_RESULT = "structurally_incompatible_result"
    INVALID_FIXED_DEPLOYMENT = "invalid_fixed_deployment"


class Stage1ToStage2AdapterError(ValueError):
    """Report a conversion failure with its typed reason."""

    def __init__(
        self,
        reason: Stage1ToStage2FailureReason,
        message: str,
    ) -> None:
        """Require a typed failure reason and retain it with the message."""

        if not isinstance(reason, Stage1ToStage2FailureReason):
            raise TypeError("reason must be a Stage1ToStage2FailureReason")
        self.reason = reason
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class Stage1ToStage2DeploymentEvidence:
    """Retain the accepted source and copied fixed deployment.

    Problem data, source result, identity, and placement are held by reference;
    ``Stage2FixedDeployment`` copies only ``z*,w*,y*``.
    """

    method: Stage1Method
    pdm_problem_data: PdmProblemData
    source_result: Stage1Result
    fixed_deployment: Stage2FixedDeployment
    _derived_deployment_indicators: Mapping[ModelTierKey, float] = field(
        init=False, repr=False, compare=False
    )

    @property
    def source_identity(self) -> Stage1ResultIdentity:
        """Return the retained accepted result's identity without revalidation."""

        if self.method is Stage1Method.AGH:
            return self.source_result.final_incumbent.gh_result.identity
        return self.source_result.identity

    @property
    def source_final_placement(self) -> PlacementDecisionState:
        """Return the retained accepted result's exact final placement."""

        if self.method is Stage1Method.P_DM:
            return self.source_result.solution
        if self.method is Stage1Method.GH:
            return self.source_result.placement_decisions
        return self.source_result.final_placement

    def __post_init__(self) -> None:
        """Own the validated fixed-deployment context reused by Stage 2."""

        object.__setattr__(
            self,
            "_derived_deployment_indicators",
            MappingProxyType(validate_stage2_fixed_deployment(
                self.pdm_problem_data, self.fixed_deployment
            )),
        )


def _extract_accepted_source(
    stage1_result: Stage1Result,
) -> tuple[Stage1Method, Stage1ResultIdentity, PlacementDecisionState]:
    """Select the accepted P_DM, GH, or completed AGH final placement."""

    # Lazy imports prevent a cycle between optimization and algorithm packages.
    from llm_resource_allocation.algorithms.agh import (
        AGHCompletionStatus,
        AGHResult,
    )
    from llm_resource_allocation.algorithms.gh import GHResult

    if isinstance(stage1_result, PdmRunRecord):
        if not stage1_result.accepted_run:
            raise Stage1ToStage2AdapterError(
                Stage1ToStage2FailureReason.STAGE1_RESULT_NOT_ACCEPTED,
                "P_DM result is not an accepted incumbent-bearing run",
            )
        return Stage1Method.P_DM, stage1_result.identity, stage1_result.solution

    if isinstance(stage1_result, GHResult):
        if not (
            stage1_result.algorithm_completed
            and stage1_result.canonicalization_completed
            and stage1_result.independently_feasible
            and stage1_result.objective_breakdown is not None
        ):
            raise Stage1ToStage2AdapterError(
                Stage1ToStage2FailureReason.STAGE1_RESULT_NOT_ACCEPTED,
                "GH result has no complete independently feasible final placement",
            )
        return (
            Stage1Method.GH,
            stage1_result.identity,
            stage1_result.placement_decisions,
        )

    if isinstance(stage1_result, AGHResult):
        if (
            stage1_result.completion_status
            is AGHCompletionStatus.NO_FEASIBLE_INCUMBENT
        ):
            raise Stage1ToStage2AdapterError(
                Stage1ToStage2FailureReason.NO_VALID_AGH_INCUMBENT,
                "AGH result has no valid incumbent",
            )
        if not stage1_result.completed:
            raise Stage1ToStage2AdapterError(
                Stage1ToStage2FailureReason.STAGE1_RESULT_NOT_ACCEPTED,
                "AGH result did not close with consistent final evidence",
            )
        incumbent = stage1_result.final_incumbent
        placement = stage1_result.final_placement
        if incumbent is None or placement is None:
            raise Stage1ToStage2AdapterError(
                Stage1ToStage2FailureReason.STRUCTURALLY_INCOMPATIBLE_RESULT,
                "completed AGH result is missing its authoritative final placement",
            )
        return Stage1Method.AGH, incumbent.gh_result.identity, placement

    raise Stage1ToStage2AdapterError(
        Stage1ToStage2FailureReason.UNSUPPORTED_RESULT_TYPE,
        "stage1_result must be PdmRunRecord, GHResult, or AGHResult",
    )


def _require_shared_identity(
    pdm_problem_data: PdmProblemData,
    source_identity: Stage1ResultIdentity,
) -> None:
    """Require matching instance/entity identities and P_DM model dimensions."""

    indices = pdm_problem_data.index_sets
    expected = (
        pdm_problem_data.instance.id,
        indices.query_ids,
        indices.model_ids,
        indices.tier_ids,
    )
    actual = tuple(
        getattr(source_identity, field_name, None)
        for field_name in ("instance_id", "query_ids", "model_ids", "tier_ids")
    )
    if actual != expected:
        raise Stage1ToStage2AdapterError(
            Stage1ToStage2FailureReason.SOURCE_IDENTITY_MISMATCH,
            "Stage-1 result identity does not match the supplied PdmProblemData",
        )
    if isinstance(source_identity, PdmRunIdentity) and (
        source_identity.variable_counts != pdm_problem_data.variable_counts
        or source_identity.constraint_counts != pdm_problem_data.constraint_counts
    ):
        raise Stage1ToStage2AdapterError(
            Stage1ToStage2FailureReason.SOURCE_IDENTITY_MISMATCH,
            "P_DM result dimensions do not match the supplied PdmProblemData",
        )


def _require_exact_deployment_lattices(
    pdm_problem_data: PdmProblemData,
    placement: PlacementDecisionState,
) -> None:
    """Require exact ordered ``z*,w*,y*`` lattices from problem data."""

    lattices = pdm_problem_data.variable_lattices
    for label, actual, expected in (
        (
            "admission_indicators",
            tuple(placement.admission_indicators),
            lattices.route_keys,
        ),
        (
            "configuration_selectors",
            tuple(placement.configuration_selectors),
            lattices.configuration_keys,
        ),
        ("gpu_counts", tuple(placement.gpu_counts), lattices.model_tier_keys),
    ):
        if actual != expected:
            raise Stage1ToStage2AdapterError(
                Stage1ToStage2FailureReason.STRUCTURALLY_INCOMPATIBLE_RESULT,
                f"Stage-1 {label} does not preserve the exact shared lattice",
            )


def stage2_fixed_deployment_from_stage1(
    stage1_result: Stage1Result,
    pdm_problem_data: PdmProblemData,
) -> Stage1ToStage2DeploymentEvidence:
    """Convert an accepted Stage-1 placement into validated fixed ``z*,w*,y*``.

    ``pdm_problem_data`` supplies the shared identity and ordered key lattices.
    Fixed-deployment validation checks structure; Stage-1 acceptance is separate.
    """

    if not isinstance(pdm_problem_data, PdmProblemData):
        raise TypeError("pdm_problem_data must be a PdmProblemData")
    method, source_identity, placement = _extract_accepted_source(stage1_result)
    _require_shared_identity(pdm_problem_data, source_identity)
    _require_exact_deployment_lattices(pdm_problem_data, placement)

    fixed = Stage2FixedDeployment(
        admission_indicators=placement.admission_indicators,
        configuration_selectors=placement.configuration_selectors,
        gpu_counts=placement.gpu_counts,
    )
    try:
        return Stage1ToStage2DeploymentEvidence(
            method=method,
            pdm_problem_data=pdm_problem_data,
            source_result=stage1_result,
            fixed_deployment=fixed,
        )
    except (TypeError, ValueError) as error:
        raise Stage1ToStage2AdapterError(
            Stage1ToStage2FailureReason.INVALID_FIXED_DEPLOYMENT,
            "accepted Stage-1 placement is invalid at the Stage-2 fixed boundary",
        ) from error

