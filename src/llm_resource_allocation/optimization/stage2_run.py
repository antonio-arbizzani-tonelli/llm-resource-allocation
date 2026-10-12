"""Solve and independently validate one fixed-deployment Stage-2 LP.

Build -> solve -> extract -> normalize -> validate -> compare objectives.
The optimized objective is C4 plus versioned C5; reported cost also includes C3
(v1 Eq. 12a, v2 Section 5.2, D-0067). Returned evidence is detached from Pyomo.
"""

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from llm_resource_allocation.math.objective import PaperVersion
from llm_resource_allocation.validation.objective_comparison import (
    ObjectiveComparison,
)
from llm_resource_allocation.validation.stage2 import (
    Stage2ObjectiveBreakdown,
    Stage2ValidationReport,
    Stage2ValidationTolerances,
    validate_stage2_solution,
)

from .extraction import SolutionNormalizationTolerances
from .problem_data import ConfigurationKey, ModelTierKey, RouteKey
from .pyomo_stage2 import build_stage2_pyomo_model
from .solver import (
    NoSolverIncumbentError,
    SolverConfig,
    SolverResult,
    require_solver_incumbent,
    solve_pyomo_model,
)
from .stage2_extraction import (
    RawStage2Solution,
    Stage2Solution,
    Stage2SolutionExtractionError,
    Stage2SolutionNormalizationError,
    extract_raw_stage2_solution_from_pyomo,
    normalize_raw_stage2_solution,
)
from .stage2_problem_data import Stage2ProblemData


class Stage2RunStatus(str, Enum):
    """Classify success or the failed Stage-2 execution boundary."""

    SUCCESS = "success"
    SOLVER_NO_USABLE_SOLUTION = "solver_no_usable_solution"
    EXTRACTION_FAILED = "extraction_failed"
    NORMALIZATION_FAILED = "normalization_failed"
    VALIDATION_FAILED = "validation_failed"
    OBJECTIVE_INCONSISTENT = "objective_inconsistent"


class Stage2RunError(RuntimeError):
    """Base error for typed Stage-2 run diagnostics."""


class Stage2UnusableSolverResultError(Stage2RunError):
    """Report a solver incumbent without an objective value."""


class Stage2IndependentValidationError(Stage2RunError):
    """Report a normalized solution rejected by the independent validator."""


class Stage2ObjectiveConsistencyError(Stage2RunError):
    """Report disagreement between solver and independent C4+C5 values."""


@dataclass(frozen=True, slots=True)
class Stage2RunIdentity:
    """Snapshot instance, scenario, version, and ordered decision lattices."""

    instance_id: str
    scenario_id: str
    paper_version: PaperVersion
    query_ids: tuple[str, ...]
    model_ids: tuple[str, ...]
    tier_ids: tuple[str, ...]
    route_keys: tuple[RouteKey, ...]
    unmet_keys: tuple[str, ...]

    def __post_init__(self) -> None:
        """Freeze the problem data's ordered identity and lattice sequences."""

        for field_name in (
            "query_ids",
            "model_ids",
            "tier_ids",
            "route_keys",
            "unmet_keys",
        ):
            object.__setattr__(self, field_name, tuple(getattr(self, field_name)))


@dataclass(frozen=True, slots=True)
class Stage2FixedDeploymentEvidence:
    """Snapshot fixed ``z*,w*,y*`` and ``q[j,k] = sum_(n,m) w*[j,k,n,m]``."""

    admission_indicators: Mapping[RouteKey, float]
    configuration_selectors: Mapping[ConfigurationKey, float]
    gpu_counts: Mapping[ModelTierKey, float]
    derived_deployment_indicators: Mapping[ModelTierKey, float]

    def __post_init__(self) -> None:
        """Copy fixed mappings into read-only views."""

        for field_name in (
            "admission_indicators",
            "configuration_selectors",
            "gpu_counts",
            "derived_deployment_indicators",
        ):
            object.__setattr__(
                self,
                field_name,
                MappingProxyType(dict(getattr(self, field_name))),
            )


@dataclass(frozen=True, slots=True)
class Stage2SolverEvidence:
    """Retain solver configuration and result metadata from the same backend."""

    config: SolverConfig
    result: SolverResult

@dataclass(frozen=True, slots=True)
class Stage2ScientificEvidence:
    """Retain transport tolerances and completed independent validation evidence.

    The breakdown comes from validation; comparison uses its C4+C5 objective.
    """

    normalization_tolerances: SolutionNormalizationTolerances
    validation_tolerances: Stage2ValidationTolerances
    validation_report: Stage2ValidationReport | None = None
    objective_comparison: ObjectiveComparison | None = None

    @property
    def objective_breakdown(self) -> Stage2ObjectiveBreakdown | None:
        """Return the report's costs, or None before independent validation."""

        return (
            None
            if self.validation_report is None
            else self.validation_report.objective_breakdown
        )

@dataclass(frozen=True, slots=True)
class Stage2RunFailure:
    """Retain the failed boundary, error type, and diagnostic message."""

    status: Stage2RunStatus
    error_type: str
    message: str

    def __post_init__(self) -> None:
        """Require a failure status; retain diagnostic text exactly as observed."""

        if not isinstance(self.status, Stage2RunStatus):
            raise TypeError("status must be a Stage2RunStatus")
        if self.status is Stage2RunStatus.SUCCESS:
            raise ValueError("failure status cannot be SUCCESS")


@dataclass(frozen=True, slots=True)
class Stage2RunRecord:
    """Retain progressive evidence for one successful or failed Stage-2 run.

    Success requires an incumbent, transported solution, independent feasibility,
    and solver/reference C4+C5 agreement; it does not imply proven optimality.
    """

    identity: Stage2RunIdentity
    fixed_deployment: Stage2FixedDeploymentEvidence
    solver_evidence: Stage2SolverEvidence
    scientific_evidence: Stage2ScientificEvidence
    status: Stage2RunStatus
    raw_solution: RawStage2Solution | None = None
    solution: Stage2Solution | None = None
    failure: Stage2RunFailure | None = None

    @property
    def successful(self) -> bool:
        """Check whether the run status is SUCCESS."""

        return self.status is Stage2RunStatus.SUCCESS

    @property
    def independently_feasible(self) -> bool:
        """Check whether the retained independent report is feasible."""

        report = self.scientific_evidence.validation_report
        return report is not None and report.is_feasible

    @property
    def objective_agrees(self) -> bool:
        """Check whether the retained solver/reference comparison agrees."""

        comparison = self.scientific_evidence.objective_comparison
        return comparison is not None and comparison.agrees

    @property
    def operational_objective(self) -> float | None:
        """Return independently recomputed C4+C5, or None if unavailable."""

        breakdown = self.scientific_evidence.objective_breakdown
        return None if breakdown is None else breakdown.operational_objective

    @property
    def realized_data_storage_cost(self) -> float | None:
        """Return independently recomputed realized C3, or None if unavailable."""

        breakdown = self.scientific_evidence.objective_breakdown
        return None if breakdown is None else breakdown.realized_data_storage_cost

    @property
    def reported_variable_cost(self) -> float | None:
        """Return independently recomputed C3+C4+C5, or None if unavailable."""

        breakdown = self.scientific_evidence.objective_breakdown
        return None if breakdown is None else breakdown.reported_variable_cost


def _run_identity(problem_data: Stage2ProblemData) -> Stage2RunIdentity:
    """Snapshot the scenario identity and ordered ``x,u`` lattices from problem data."""

    indices = problem_data.pdm_problem_data.index_sets
    return Stage2RunIdentity(
        instance_id=problem_data.instance.id,
        scenario_id=problem_data.realized_scenario.id,
        paper_version=problem_data.paper_version,
        query_ids=indices.query_ids,
        model_ids=indices.model_ids,
        tier_ids=indices.tier_ids,
        route_keys=problem_data.routing_keys,
        unmet_keys=problem_data.unmet_keys,
    )


def _fixed_evidence(problem_data: Stage2ProblemData) -> Stage2FixedDeploymentEvidence:
    """Copy fixed ``z*,w*,y*`` and derived ``q`` into run evidence."""

    fixed = problem_data.fixed_deployment
    return Stage2FixedDeploymentEvidence(
        admission_indicators=fixed.admission_indicators,
        configuration_selectors=fixed.configuration_selectors,
        gpu_counts=fixed.gpu_counts,
        derived_deployment_indicators=problem_data.derived_deployment_indicators,
    )


@dataclass(frozen=True, slots=True)
class _Stage2RunContext:
    """Share immutable run metadata across status-specific record construction."""

    identity: Stage2RunIdentity
    fixed_deployment: Stage2FixedDeploymentEvidence
    solver_config: SolverConfig
    solver_result: SolverResult
    normalization_tolerances: SolutionNormalizationTolerances
    validation_tolerances: Stage2ValidationTolerances


def _record(
    context: _Stage2RunContext,
    *,
    status: Stage2RunStatus,
    raw_solution: RawStage2Solution | None = None,
    solution: Stage2Solution | None = None,
    validation_report: Stage2ValidationReport | None = None,
    objective_comparison: ObjectiveComparison | None = None,
    failure: Stage2RunFailure | None = None,
) -> Stage2RunRecord:
    """Assemble the evidence retained by the completed execution boundaries."""

    return Stage2RunRecord(
        identity=context.identity,
        fixed_deployment=context.fixed_deployment,
        solver_evidence=Stage2SolverEvidence(
            context.solver_config, context.solver_result
        ),
        scientific_evidence=Stage2ScientificEvidence(
            normalization_tolerances=context.normalization_tolerances,
            validation_tolerances=context.validation_tolerances,
            validation_report=validation_report,
            objective_comparison=objective_comparison,
        ),
        status=status,
        raw_solution=raw_solution,
        solution=solution,
        failure=failure,
    )


def _failure(status: Stage2RunStatus, error: Exception) -> Stage2RunFailure:
    """Retain the boundary status and the original error type/message."""

    return Stage2RunFailure(status, type(error).__name__, str(error))


def run_stage2(
    problem_data: Stage2ProblemData,
    solver_config: SolverConfig | None = None,
    normalization_tolerances: SolutionNormalizationTolerances | None = None,
    validation_tolerances: Stage2ValidationTolerances | None = None,
) -> Stage2RunRecord:
    """Build, solve, transport, validate, and compare one Stage-2 LP result.

    Compare solver and independently recomputed C4+C5 using the separate
    objective-comparison tolerance (D-0025); retain typed post-solve failures.
    """

    if not isinstance(problem_data, Stage2ProblemData):
        raise TypeError("problem_data must be a Stage2ProblemData")
    selected_solver_config = SolverConfig() if solver_config is None else solver_config
    if not isinstance(selected_solver_config, SolverConfig):
        raise TypeError("solver_config must be SolverConfig or None")
    selected_normalization = (
        SolutionNormalizationTolerances()
        if normalization_tolerances is None
        else normalization_tolerances
    )
    if not isinstance(selected_normalization, SolutionNormalizationTolerances):
        raise TypeError(
            "normalization_tolerances must be SolutionNormalizationTolerances or None"
        )
    selected_validation = (
        Stage2ValidationTolerances()
        if validation_tolerances is None
        else validation_tolerances
    )
    if not isinstance(selected_validation, Stage2ValidationTolerances):
        raise TypeError(
            "validation_tolerances must be Stage2ValidationTolerances or None"
        )

    identity = _run_identity(problem_data)
    fixed = _fixed_evidence(problem_data)
    model = build_stage2_pyomo_model(problem_data)
    solver_result = solve_pyomo_model(model, selected_solver_config)
    context = _Stage2RunContext(
        identity=identity,
        fixed_deployment=fixed,
        solver_config=selected_solver_config,
        solver_result=solver_result,
        normalization_tolerances=selected_normalization,
        validation_tolerances=selected_validation,
    )

    try:
        require_solver_incumbent(solver_result)
        if solver_result.objective_value is None:
            raise Stage2UnusableSolverResultError(
                "Stage-2 solver result has an incumbent but no objective value"
            )
    except (NoSolverIncumbentError, Stage2UnusableSolverResultError) as error:
        status = Stage2RunStatus.SOLVER_NO_USABLE_SOLUTION
        return _record(
            context,
            status=status,
            failure=_failure(status, error),
        )

    try:
        raw_solution = extract_raw_stage2_solution_from_pyomo(model, problem_data)
    except Stage2SolutionExtractionError as error:
        status = Stage2RunStatus.EXTRACTION_FAILED
        return _record(
            context,
            status=status,
            failure=_failure(status, error),
        )

    try:
        solution = normalize_raw_stage2_solution(
            raw_solution,
            problem_data,
            selected_normalization,
        )
    except Stage2SolutionNormalizationError as error:
        status = Stage2RunStatus.NORMALIZATION_FAILED
        return _record(
            context,
            status=status,
            raw_solution=raw_solution,
            failure=_failure(status, error),
        )

    validation_report = validate_stage2_solution(
        problem_data,
        solution,
        selected_validation,
    )
    if not validation_report.is_feasible:
        status = Stage2RunStatus.VALIDATION_FAILED
        families = ", ".join(
            family.value for family in validation_report.violated_families
        )
        error = Stage2IndependentValidationError(
            f"independent Stage-2 validation failed: {families}"
        )
        return _record(
            context,
            status=status,
            raw_solution=raw_solution,
            solution=solution,
            validation_report=validation_report,
            failure=_failure(status, error),
        )

    breakdown = validation_report.objective_breakdown
    if breakdown is None:
        raise RuntimeError("feasible Stage-2 validation produced no objective")
    objective_comparison = ObjectiveComparison(
        solver_result.objective_value,
        breakdown.operational_objective,
    )
    if not objective_comparison.agrees:
        status = Stage2RunStatus.OBJECTIVE_INCONSISTENT
        error = Stage2ObjectiveConsistencyError(
            "solver Stage-2 objective does not agree with independent C4+C5: "
            f"solver={objective_comparison.solver_objective!r}, "
            f"independent={objective_comparison.independent_objective!r}, "
            f"difference={objective_comparison.absolute_difference!r}"
        )
        return _record(
            context,
            status=status,
            raw_solution=raw_solution,
            solution=solution,
            validation_report=validation_report,
            objective_comparison=objective_comparison,
            failure=_failure(status, error),
        )

    return _record(
        context,
        status=Stage2RunStatus.SUCCESS,
        raw_solution=raw_solution,
        solution=solution,
        validation_report=validation_report,
        objective_comparison=objective_comparison,
    )
