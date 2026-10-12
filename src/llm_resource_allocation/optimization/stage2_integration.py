"""Evaluate an accepted Stage-1 result under one supplied Stage-2 scenario.

Adapter -> problem data -> Stage-2 run, with shared objects retained by identity.
The requested paper version must match Stage 1, preserving versioned C5 (D-0003).
"""

from dataclasses import dataclass
from enum import Enum

from llm_resource_allocation.math.objective import PaperVersion
from llm_resource_allocation.math.placement import PlacementDecisionState
from llm_resource_allocation.validation.stage2 import Stage2ValidationTolerances

from .extraction import SolutionNormalizationTolerances
from .problem_data import PdmProblemData
from .solver import SolverConfig
from .stage2_adapter import (
    Stage1Method,
    Stage1Result,
    Stage1ToStage2AdapterError,
    Stage1ToStage2DeploymentEvidence,
    Stage1ToStage2FailureReason,
    stage2_fixed_deployment_from_stage1,
)
from .stage2_problem_data import (
    Stage2FixedDeployment,
    Stage2ProblemData,
    Stage2RealizedScenario,
)
from .stage2_run import Stage2RunFailure, Stage2RunRecord, run_stage2


class Stage1Stage2EvaluationStatus(str, Enum):
    """Classify success or the failed integration boundary."""

    SUCCESS = "success"
    STAGE1_SOURCE_REJECTED = "stage1_source_rejected"
    ADAPTER_FAILED = "adapter_failed"
    PROBLEM_DATA_CONSTRUCTION_FAILED = "problem_data_construction_failed"
    STAGE2_RUN_FAILED = "stage2_run_failed"


@dataclass(frozen=True, slots=True)
class Stage1Stage2EvaluationFailure:
    """Retain an adapter or problem-data construction failure."""

    status: Stage1Stage2EvaluationStatus
    error_type: str
    message: str
    adapter_reason: Stage1ToStage2FailureReason | None = None

    def __post_init__(self) -> None:
        """Require an upstream failure status; the producer retains its reason."""

        if self.status not in (
            Stage1Stage2EvaluationStatus.STAGE1_SOURCE_REJECTED,
            Stage1Stage2EvaluationStatus.ADAPTER_FAILED,
            Stage1Stage2EvaluationStatus.PROBLEM_DATA_CONSTRUCTION_FAILED,
        ):
            raise ValueError("integration failure has an invalid upstream status")


IntegratedFailure = Stage1Stage2EvaluationFailure | Stage2RunFailure


@dataclass(frozen=True, slots=True)
class Stage1Stage2EvaluationResult:
    """Retain the completed boundaries of one Stage-1/Stage-2 evaluation.

    Shared source, problem, deployment, and scenario objects retain identity.
    Versions and lattices match throughout; failures retain upstream evidence.
    """

    source_result: Stage1Result
    pdm_problem_data: PdmProblemData
    realized_scenario: Stage2RealizedScenario
    paper_version: PaperVersion
    status: Stage1Stage2EvaluationStatus
    adapter_evidence: Stage1ToStage2DeploymentEvidence | None = None
    stage2_problem_data: Stage2ProblemData | None = None
    stage2_run_record: Stage2RunRecord | None = None
    failure: IntegratedFailure | None = None

    @property
    def successful(self) -> bool:
        """Check whether the integrated status is SUCCESS."""

        return self.status is Stage1Stage2EvaluationStatus.SUCCESS

    @property
    def stage1_method(self) -> Stage1Method | None:
        """Return the accepted source method, or None before conversion."""

        if self.adapter_evidence is None:
            return None
        return self.adapter_evidence.method

    @property
    def source_final_placement(self) -> PlacementDecisionState | None:
        """Return the accepted placement by reference, or None before conversion."""

        if self.adapter_evidence is None:
            return None
        return self.adapter_evidence.source_final_placement

    @property
    def fixed_deployment(self) -> Stage2FixedDeployment | None:
        """Return the adapter's fixed deployment, or None before conversion."""

        if self.adapter_evidence is None:
            return None
        return self.adapter_evidence.fixed_deployment


_SOURCE_REJECTION_REASONS = frozenset(
    {
        Stage1ToStage2FailureReason.UNSUPPORTED_RESULT_TYPE,
        Stage1ToStage2FailureReason.STAGE1_RESULT_NOT_ACCEPTED,
        Stage1ToStage2FailureReason.NO_VALID_AGH_INCUMBENT,
        Stage1ToStage2FailureReason.SOURCE_VERSION_MISMATCH,
    }
)


def _adapter_failure_result(
    stage1_result: Stage1Result,
    pdm_problem_data: PdmProblemData,
    realized_scenario: Stage2RealizedScenario,
    paper_version: PaperVersion,
    error: Stage1ToStage2AdapterError,
) -> Stage1Stage2EvaluationResult:
    """Classify source rejection or adapter failure and retain its reason."""

    status = (
        Stage1Stage2EvaluationStatus.STAGE1_SOURCE_REJECTED
        if error.reason in _SOURCE_REJECTION_REASONS
        else Stage1Stage2EvaluationStatus.ADAPTER_FAILED
    )
    return Stage1Stage2EvaluationResult(
        source_result=stage1_result,
        pdm_problem_data=pdm_problem_data,
        realized_scenario=realized_scenario,
        paper_version=paper_version,
        status=status,
        failure=Stage1Stage2EvaluationFailure(
            status=status,
            error_type=type(error).__name__,
            message=str(error),
            adapter_reason=error.reason,
        ),
    )


def evaluate_stage1_result_under_scenario(
    stage1_result: Stage1Result,
    pdm_problem_data: PdmProblemData,
    realized_scenario: Stage2RealizedScenario,
    *,
    paper_version: PaperVersion = PaperVersion.V2,
    solver_config: SolverConfig | None = None,
    normalization_tolerances: SolutionNormalizationTolerances | None = None,
    validation_tolerances: Stage2ValidationTolerances | None = None,
) -> Stage1Stage2EvaluationResult:
    """Convert Stage 1, build scenario problem data, and execute Stage 2 once.

    A source-version mismatch stops before problem construction. Failed boundaries
    retain completed upstream evidence and typed failure diagnostics.
    """

    if not isinstance(pdm_problem_data, PdmProblemData):
        raise TypeError("pdm_problem_data must be a PdmProblemData")
    if not isinstance(realized_scenario, Stage2RealizedScenario):
        raise TypeError("realized_scenario must be a Stage2RealizedScenario")
    if not isinstance(paper_version, PaperVersion):
        raise TypeError("paper_version must be PaperVersion.V1 or V2")

    prepared = _prepare_stage2_source(stage1_result, pdm_problem_data, paper_version)
    return _evaluate_prepared_stage2_source(
        prepared,
        realized_scenario,
        solver_config=solver_config,
        normalization_tolerances=normalization_tolerances,
        validation_tolerances=validation_tolerances,
    )


@dataclass(frozen=True, slots=True)
class _PreparedStage2Source:
    """Retain one accepted conversion, or its failure, for a local scenario batch."""

    source_result: Stage1Result
    pdm_problem_data: PdmProblemData
    paper_version: PaperVersion
    adapter_evidence: Stage1ToStage2DeploymentEvidence | None = None
    adapter_error: Stage1ToStage2AdapterError | None = None


def _prepare_stage2_source(
    stage1_result: Stage1Result,
    pdm_problem_data: PdmProblemData,
    paper_version: PaperVersion,
) -> _PreparedStage2Source:
    """Convert a source once, retaining typed rejection for every scenario."""

    try:
        adapter_evidence = stage2_fixed_deployment_from_stage1(
            stage1_result,
            pdm_problem_data,
        )
    except Stage1ToStage2AdapterError as error:
        return _PreparedStage2Source(
            stage1_result, pdm_problem_data, paper_version, adapter_error=error
        )

    if adapter_evidence.source_identity.paper_version is not paper_version:
        return _PreparedStage2Source(
            stage1_result,
            pdm_problem_data,
            paper_version,
            adapter_error=Stage1ToStage2AdapterError(
                Stage1ToStage2FailureReason.SOURCE_VERSION_MISMATCH,
                "accepted Stage-1 source and requested Stage-2 paper versions differ",
            ),
        )

    return _PreparedStage2Source(
        stage1_result, pdm_problem_data, paper_version, adapter_evidence
    )


def _evaluate_prepared_stage2_source(
    prepared: _PreparedStage2Source,
    realized_scenario: Stage2RealizedScenario,
    *,
    solver_config: SolverConfig | None = None,
    normalization_tolerances: SolutionNormalizationTolerances | None = None,
    validation_tolerances: Stage2ValidationTolerances | None = None,
) -> Stage1Stage2EvaluationResult:
    """Build and independently validate one scenario for the prepared source."""

    stage1_result = prepared.source_result
    pdm_problem_data = prepared.pdm_problem_data
    paper_version = prepared.paper_version
    if prepared.adapter_error is not None:
        return _adapter_failure_result(
            stage1_result, pdm_problem_data, realized_scenario,
            paper_version, prepared.adapter_error,
        )
    adapter_evidence = prepared.adapter_evidence

    try:
        stage2_data = Stage2ProblemData._from_validated_deployment(
            pdm_problem_data,
            adapter_evidence.fixed_deployment,
            adapter_evidence._derived_deployment_indicators,
            realized_scenario,
            paper_version,
        )
    except (TypeError, ValueError) as error:
        status = Stage1Stage2EvaluationStatus.PROBLEM_DATA_CONSTRUCTION_FAILED
        return Stage1Stage2EvaluationResult(
            source_result=stage1_result,
            pdm_problem_data=pdm_problem_data,
            realized_scenario=realized_scenario,
            paper_version=paper_version,
            status=status,
            adapter_evidence=adapter_evidence,
            failure=Stage1Stage2EvaluationFailure(
                status=status,
                error_type=type(error).__name__,
                message=str(error),
            ),
        )

    stage2_record = run_stage2(
        stage2_data,
        solver_config=solver_config,
        normalization_tolerances=normalization_tolerances,
        validation_tolerances=validation_tolerances,
    )
    status = (
        Stage1Stage2EvaluationStatus.SUCCESS
        if stage2_record.successful
        else Stage1Stage2EvaluationStatus.STAGE2_RUN_FAILED
    )
    return Stage1Stage2EvaluationResult(
        source_result=stage1_result,
        pdm_problem_data=pdm_problem_data,
        realized_scenario=realized_scenario,
        paper_version=paper_version,
        status=status,
        adapter_evidence=adapter_evidence,
        stage2_problem_data=stage2_data,
        stage2_run_record=stage2_record,
        failure=None if stage2_record.successful else stage2_record.failure,
    )
