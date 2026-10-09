"""Build, solve, normalize, and independently validate one ``P_DM`` run.

Records retain plain immutable evidence, including objective agreement (D-0029).
"""

from dataclasses import dataclass

from llm_resource_allocation.math.objective import (
    ObjectiveBreakdown,
    PaperVersion,
)
from llm_resource_allocation.math.placement import PlacementDecisionState
from llm_resource_allocation.validation.objective_comparison import (
    ObjectiveComparison,
)
from llm_resource_allocation.validation.placement import (
    PlacementValidationReport,
    ValidationTolerances,
    validate_placement,
)

from .extraction import (
    SolutionNormalizationTolerances,
    extract_raw_pdm_solution_from_pyomo,
    normalize_raw_pdm_solution,
)
from .problem_data import (
    PdmConstraintCounts,
    PdmProblemData,
    PdmVariableCounts,
)
from .pyomo_pdm import build_pdm_pyomo_model
from .solver import (
    SolverConfig,
    SolverResult,
    require_solver_incumbent,
    solve_pyomo_model,
)


@dataclass(frozen=True, slots=True)
class PdmRunIdentity:
    """Snapshot instance/paper identity, ordered IDs, and unpresolved counts."""

    instance_id: str
    paper_version: PaperVersion
    query_ids: tuple[str, ...]
    model_ids: tuple[str, ...]
    tier_ids: tuple[str, ...]
    variable_counts: PdmVariableCounts
    constraint_counts: PdmConstraintCounts

    def __post_init__(self) -> None:
        """Freeze sequence inputs and reject malformed identity metadata."""

        if not isinstance(self.instance_id, str) or not self.instance_id:
            raise ValueError("instance_id must be a non-empty string")
        if not isinstance(self.paper_version, PaperVersion):
            raise ValueError("paper_version must be PaperVersion.V1 or V2")
        for field_name in ("query_ids", "model_ids", "tier_ids"):
            values = tuple(getattr(self, field_name))
            if not values or any(not isinstance(value, str) or not value for value in values):
                raise ValueError(f"{field_name} must contain non-empty strings")
            object.__setattr__(self, field_name, values)
        if not isinstance(self.variable_counts, PdmVariableCounts):
            raise TypeError("variable_counts must be PdmVariableCounts")
        if not isinstance(self.constraint_counts, PdmConstraintCounts):
            raise TypeError("constraint_counts must be PdmConstraintCounts")


@dataclass(frozen=True, slots=True)
class PdmScientificEvidence:
    """Store independent validation results and normalization tolerances.

    Retain C1-C5 costs computed from problem data and normalized decisions,
    together with their total's comparison to the solver objective.
    """

    validation_report: PlacementValidationReport
    objective_breakdown: ObjectiveBreakdown
    objective_comparison: ObjectiveComparison
    normalization_tolerances: SolutionNormalizationTolerances

    def __post_init__(self) -> None:
        """Require stored objective values to match the validation report."""

        if not isinstance(self.validation_report, PlacementValidationReport):
            raise TypeError("validation_report must be PlacementValidationReport")
        if not isinstance(self.objective_breakdown, ObjectiveBreakdown):
            raise TypeError("objective_breakdown must be ObjectiveBreakdown")
        if not isinstance(self.objective_comparison, ObjectiveComparison):
            raise TypeError("objective_comparison must be ObjectiveComparison")
        if not isinstance(
            self.normalization_tolerances, SolutionNormalizationTolerances
        ):
            raise TypeError(
                "normalization_tolerances must be SolutionNormalizationTolerances"
            )
        if self.validation_report.objective_breakdown != self.objective_breakdown:
            raise ValueError(
                "objective_breakdown must equal the independent validation result"
            )
        if (
            self.objective_comparison.independent_objective
            != self.objective_breakdown.total
        ):
            raise ValueError(
                "objective comparison must use the stored independent C1-C5 total"
            )


@dataclass(frozen=True, slots=True)
class PdmSolverEvidence:
    """Store solver configuration and result metadata together."""

    config: SolverConfig
    result: SolverResult

    def __post_init__(self) -> None:
        """Require matching configuration and result backends."""

        if not isinstance(self.config, SolverConfig):
            raise TypeError("config must be SolverConfig")
        if not isinstance(self.result, SolverResult):
            raise TypeError("result must be SolverResult")
        if self.config.backend is not self.result.backend:
            raise ValueError("solver config and result backends must match")


@dataclass(frozen=True, slots=True)
class PdmRunRecord:
    """Store a completed ``P_DM`` incumbent with separate scientific evidence.

    Record construction follows successful normalization. Acceptance also
    requires independent feasibility and objective agreement (D-0029).
    """

    identity: PdmRunIdentity
    solution: PlacementDecisionState
    scientific_evidence: PdmScientificEvidence
    solver_evidence: PdmSolverEvidence

    def __post_init__(self) -> None:
        """Reject cross-section mismatches in a manually constructed record."""

        if not isinstance(self.identity, PdmRunIdentity):
            raise TypeError("identity must be PdmRunIdentity")
        if not isinstance(self.solution, PlacementDecisionState):
            raise TypeError("solution must be PlacementDecisionState")
        if not isinstance(self.scientific_evidence, PdmScientificEvidence):
            raise TypeError("scientific_evidence must be PdmScientificEvidence")
        if not isinstance(self.solver_evidence, PdmSolverEvidence):
            raise TypeError("solver_evidence must be PdmSolverEvidence")
        report = self.scientific_evidence.validation_report
        comparison = self.scientific_evidence.objective_comparison
        solver_result = self.solver_evidence.result
        if self.identity.paper_version is not report.paper_version:
            raise ValueError("identity and validation paper versions must match")
        if not solver_result.has_incumbent:
            raise ValueError("a completed PdmRunRecord requires a solver incumbent")
        if solver_result.objective_value != comparison.solver_objective:
            raise ValueError(
                "objective comparison must use the nested solver result objective"
            )

    @property
    def has_incumbent(self) -> bool:
        """Return incumbent presence from the solver result."""

        return self.solver_evidence.result.has_incumbent

    @property
    def independently_feasible(self) -> bool:
        """Return the independent placement-feasibility classification."""

        return self.scientific_evidence.validation_report.is_feasible

    @property
    def objective_agrees(self) -> bool:
        """Return solver/independent objective agreement."""

        return self.scientific_evidence.objective_comparison.agrees

    @property
    def accepted_run(self) -> bool:
        """Require incumbent, independent feasibility, and objective agreement.

        Successful normalization precedes record construction (D-0029).
        """

        return (
            self.has_incumbent
            and self.independently_feasible
            and self.objective_agrees
        )


def execute_and_record_pdm_run(
    problem_data: PdmProblemData,
    solver_config: SolverConfig,
    paper_version: PaperVersion = PaperVersion.V2,
    normalization_tolerances: SolutionNormalizationTolerances | None = None,
    *,
    validation_tolerances: ValidationTolerances | None = None,
) -> PdmRunRecord:
    """Execute the ``P_DM`` pipeline and snapshot decisions and evidence.

    No incumbent raises ``NoSolverIncumbentError`` before extraction (D-0030).
    Validation failures and objective discrepancies remain in rejected records.
    ``validation_tolerances`` controls only independent residual acceptance;
    ``ValidationTolerances.exact()`` disables absolute and relative terms.
    """

    if not isinstance(problem_data, PdmProblemData):
        raise TypeError("problem_data must be PdmProblemData")
    if not isinstance(solver_config, SolverConfig):
        raise TypeError("solver_config must be SolverConfig")
    if not isinstance(paper_version, PaperVersion):
        raise ValueError("paper_version must be PaperVersion.V1 or V2")
    selected_validation = (
        ValidationTolerances() if validation_tolerances is None else validation_tolerances
    )
    if not isinstance(selected_validation, ValidationTolerances):
        raise TypeError("validation_tolerances must be ValidationTolerances or None")
    selected_tolerances = (
        normalization_tolerances or SolutionNormalizationTolerances()
    )
    if not isinstance(selected_tolerances, SolutionNormalizationTolerances):
        raise TypeError(
            "normalization_tolerances must be SolutionNormalizationTolerances or None"
        )

    model = build_pdm_pyomo_model(problem_data, paper_version)
    solver_result = solve_pyomo_model(model, solver_config)
    require_solver_incumbent(solver_result)
    raw_solution = extract_raw_pdm_solution_from_pyomo(model, problem_data)
    solution = normalize_raw_pdm_solution(
        raw_solution,
        problem_data,
        selected_tolerances,
    )
    validation_report = validate_placement(
        problem_data.instance,
        solution,
        paper_version,
        selected_validation,
    )
    objective_breakdown = validation_report.objective_breakdown
    if objective_breakdown is None:
        raise RuntimeError(
            "normalized solution produced no independent objective breakdown"
        )
    # Guard the optional value for static typing and manually built results.
    if solver_result.objective_value is None:
        raise RuntimeError("incumbent-bearing solver result has no objective")
    objective_comparison = ObjectiveComparison(
        solver_result.objective_value,
        objective_breakdown.total,
    )

    indices = problem_data.index_sets
    return PdmRunRecord(
        identity=PdmRunIdentity(
            instance_id=problem_data.instance.id,
            paper_version=paper_version,
            query_ids=indices.query_ids,
            model_ids=indices.model_ids,
            tier_ids=indices.tier_ids,
            variable_counts=problem_data.variable_counts,
            constraint_counts=problem_data.constraint_counts,
        ),
        solution=solution,
        scientific_evidence=PdmScientificEvidence(
            validation_report=validation_report,
            objective_breakdown=objective_breakdown,
            objective_comparison=objective_comparison,
            normalization_tolerances=selected_tolerances,
        ),
        solver_evidence=PdmSolverEvidence(
            config=solver_config,
            result=solver_result,
        ),
    )
