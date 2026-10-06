"""Solver-independent placement validation using the mathematical primitives."""

from dataclasses import dataclass, field, fields
from enum import Enum
from math import isfinite
from types import MappingProxyType
from typing import Mapping

from llm_resource_allocation.domain import InstanceValidationError, ProblemInstance
from llm_resource_allocation.math.budget import (
    BudgetDiagnostic,
    compute_budget_residual,
)
from llm_resource_allocation.math.compute_capacity import (
    ComputeCapacityDiagnostic,
    compute_compute_capacity_diagnostics,
)
from llm_resource_allocation.math.parallelism import (
    ConfigurationSelectionDiagnostic,
    GpuCountLinkingDiagnostic,
    compute_configuration_selection_residuals,
    compute_gpu_count_linking_residuals,
)
from llm_resource_allocation.math.routing import (
    DecisionDomainError,
    DemandBalanceDiagnostic,
    RoutingConsistencyDiagnostic,
    compute_demand_balance_residuals,
    compute_routing_consistency_residuals,
)
from llm_resource_allocation.math.processing_delay import (
    DelaySloDiagnostic,
    compute_delay_slo_residuals,
    compute_processing_delays_seconds,
)
from llm_resource_allocation.math.error_slo import (
    ErrorSloDiagnostic,
    compute_error_slo_residuals,
)
from llm_resource_allocation.math.gpu_memory import (
    GpuMemoryDiagnostic,
    compute_gpu_memory_residuals,
)
from llm_resource_allocation.math.placement import (
    McCormickConsistencyDiagnostic,
    PlacementDecisionState,
    compute_mccormick_consistency_diagnostics,
    validate_placement_decision_domains,
)
from llm_resource_allocation.math.objective import (
    ObjectiveBreakdown,
    ObjectiveState,
    PaperVersion,
    compute_objective_breakdown,
)
from llm_resource_allocation.math.storage_capacity import (
    QueryStorageCapacityDiagnostic,
    compute_storage_capacity_residuals,
)


# D-0076: dimensionless residual classification; supplied decisions stay unchanged.
DEFAULT_MCCORMICK_ABSOLUTE_TOLERANCE = 1e-10


class ConstraintFamily(str, Enum):
    """Identify placement constraint families."""

    DECISION_DOMAINS = "decision_domains"
    MCCORMICK = "mccormick_eq_7"
    DEMAND_BALANCE = "demand_balance_eq_8b"
    BUDGET = "budget_eq_8c"
    CONFIGURATION_SELECTION = "configuration_selection_eq_8d"
    GPU_COUNT_LINKING = "gpu_count_linking_eq_8e"
    GPU_MEMORY = "gpu_memory_eq_8f_d_0002"
    COMPUTE_CAPACITY = "compute_capacity_eq_8g"
    STORAGE_CAPACITY = "storage_capacity_eq_8h_d_0016"
    DELAY_SLO = "delay_slo_eq_8i"
    ERROR_SLO = "error_slo_eq_8j"
    ROUTING_CONSISTENCY = "routing_consistency_eq_8k"


@dataclass(frozen=True, slots=True)
class ValidationTolerances:
    """Per-family tolerances in each residual's native unit; domains stay exact."""

    mccormick: float = DEFAULT_MCCORMICK_ABSOLUTE_TOLERANCE
    demand_balance: float = 0.0
    budget: float = 0.0
    configuration_selection: float = 0.0
    gpu_count_linking: float = 0.0
    gpu_memory: float = 0.0
    compute_capacity: float = 0.0
    storage_capacity: float = 0.0
    delay_slo: float = 0.0
    error_slo: float = 0.0
    routing_consistency: float = 0.0

    def __post_init__(self) -> None:
        """Reject non-finite, negative, boolean, or non-numeric tolerances."""

        for field in fields(self):
            value = getattr(self, field.name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not isfinite(value)
                or value < 0.0
            ):
                raise ValueError(
                    f"{field.name} tolerance must be a finite non-negative real number"
                )


@dataclass(frozen=True, slots=True)
class PlacementDomainDiagnostic:
    """Record input/decision domain validity and any error."""

    is_valid: bool
    error_type: str | None = None
    message: str | None = None

    def __post_init__(self) -> None:
        """Require a coherent success flag and error description."""

        if not isinstance(self.is_valid, bool):
            raise TypeError("is_valid must be a bool")
        if self.is_valid:
            if self.error_type is not None or self.message is not None:
                raise ValueError("a valid diagnostic cannot contain an error")
        else:
            if not isinstance(self.error_type, str) or not self.error_type:
                raise ValueError("an invalid diagnostic must name its error type")
            if not isinstance(self.message, str):
                raise ValueError("an invalid diagnostic must contain an error message")


@dataclass(frozen=True, slots=True)
class ValidationViolation:
    """Locate one violation, with slack in the family's native unit.

    Domain errors use ``None`` because they have no numerical magnitude.
    """

    family: ConstraintFamily
    semantic_location: tuple[str | int, ...]
    slack: float | None

    def __post_init__(self) -> None:
        """Own an immutable copy of the semantic location."""

        object.__setattr__(self, "semantic_location", tuple(self.semantic_location))

    @property
    def raw_violation(self) -> float | None:
        return None if self.slack is None else -self.slack


@dataclass(frozen=True, slots=True)
class PlacementValidationReport:
    """Store objective and constraint evidence for v2 Eqs. (7)-(8k).

    Uses D-0002 memory and D-0016 storage interpretations. Invalid domains
    leave the objective and mathematical diagnostics empty.
    """

    paper_version: PaperVersion
    tolerances: ValidationTolerances
    domain_diagnostic: PlacementDomainDiagnostic
    processing_delays_seconds: Mapping[str, float]
    objective_breakdown: ObjectiveBreakdown | None
    mccormick_diagnostics: tuple[McCormickConsistencyDiagnostic, ...]
    demand_balance_diagnostics: tuple[DemandBalanceDiagnostic, ...]
    budget_diagnostic: BudgetDiagnostic | None
    configuration_selection_diagnostics: tuple[ConfigurationSelectionDiagnostic, ...]
    gpu_count_linking_diagnostics: tuple[GpuCountLinkingDiagnostic, ...]
    gpu_memory_diagnostics: tuple[GpuMemoryDiagnostic, ...]
    compute_capacity_diagnostics: tuple[ComputeCapacityDiagnostic, ...]
    storage_capacity_diagnostics: tuple[QueryStorageCapacityDiagnostic, ...]
    delay_slo_diagnostics: tuple[DelaySloDiagnostic, ...]
    error_slo_diagnostics: tuple[ErrorSloDiagnostic, ...]
    routing_consistency_diagnostics: tuple[RoutingConsistencyDiagnostic, ...]

    def __post_init__(self) -> None:
        """Own immutable copies of the mapping and diagnostic sequences."""

        object.__setattr__(
            self,
            "processing_delays_seconds",
            MappingProxyType(dict(self.processing_delays_seconds)),
        )
        for name in (
            "mccormick_diagnostics",
            "demand_balance_diagnostics",
            "configuration_selection_diagnostics",
            "gpu_count_linking_diagnostics",
            "gpu_memory_diagnostics",
            "compute_capacity_diagnostics",
            "storage_capacity_diagnostics",
            "delay_slo_diagnostics",
            "error_slo_diagnostics",
            "routing_consistency_diagnostics",
        ):
            object.__setattr__(self, name, tuple(getattr(self, name)))

    @property
    def violations(self) -> tuple[ValidationViolation, ...]:
        """Collect all violations in deterministic constraint-family order."""

        if not self.domain_diagnostic.is_valid:
            return (
                ValidationViolation(
                    family=ConstraintFamily.DECISION_DOMAINS,
                    semantic_location=(self.domain_diagnostic.error_type,),
                    slack=None,
                ),
            )

        violations = self._mccormick_violations()
        violations.extend(self._demand_balance_violations())
        violations.extend(self._budget_violations())
        violations.extend(self._configuration_violations())
        violations.extend(self._capacity_and_slo_violations())
        violations.extend(self._routing_consistency_violations())
        return tuple(violations)

    def _mccormick_violations(self) -> list[ValidationViolation]:
        """Locate each failed McCormick bound at its full configuration index."""

        violations: list[ValidationViolation] = []
        for diagnostic in self.mccormick_diagnostics:
            slacks = diagnostic.residuals
            location = (
                diagnostic.query_id,
                diagnostic.model_id,
                diagnostic.gpu_tier_id,
                diagnostic.tensor_parallel_degree,
                diagnostic.pipeline_parallel_depth,
            )
            named_slacks = (
                ("x_minus_v", slacks.x_minus_v),
                ("w_minus_v", slacks.w_minus_v),
                ("v_minus_x_minus_w_plus_one", slacks.v_minus_x_minus_w_plus_one),
                ("v_nonnegative", slacks.v_nonnegative),
            )
            for inequality_name, slack in named_slacks:
                if slack < -self.tolerances.mccormick:
                    violations.append(
                        ValidationViolation(
                            ConstraintFamily.MCCORMICK,
                            (*location, inequality_name),
                            slack,
                        )
                    )
        return violations

    def _demand_balance_violations(self) -> list[ValidationViolation]:
        """Locate failed demand-balance equalities by query."""

        violations: list[ValidationViolation] = []
        for diagnostic in self.demand_balance_diagnostics:
            if not diagnostic.is_feasible(self.tolerances.demand_balance):
                violations.append(
                    ValidationViolation(
                        ConstraintFamily.DEMAND_BALANCE,
                        (diagnostic.query_id,),
                        -diagnostic.absolute_violation,
                    )
                )
        return violations

    def _budget_violations(self) -> list[ValidationViolation]:
        """Report the global budget inequality when present and violated."""

        diagnostic = self.budget_diagnostic
        if diagnostic is None or diagnostic.is_feasible(self.tolerances.budget):
            return []
        return [
            ValidationViolation(
                ConstraintFamily.BUDGET,
                ("global",),
                diagnostic.slack,
            )
        ]

    def _configuration_violations(self) -> list[ValidationViolation]:
        """Locate selection and GPU-count equalities by model/GPU pair."""

        violations: list[ValidationViolation] = []
        equality_groups = (
            (
                ConstraintFamily.CONFIGURATION_SELECTION,
                self.configuration_selection_diagnostics,
                self.tolerances.configuration_selection,
            ),
            (
                ConstraintFamily.GPU_COUNT_LINKING,
                self.gpu_count_linking_diagnostics,
                self.tolerances.gpu_count_linking,
            ),
        )
        for family, diagnostics, tolerance in equality_groups:
            for diagnostic in diagnostics:
                if not diagnostic.is_feasible(tolerance):
                    violations.append(
                        ValidationViolation(
                            family,
                            (diagnostic.model_id, diagnostic.gpu_tier_id),
                            -diagnostic.absolute_violation,
                        )
                    )
        return violations

    def _capacity_and_slo_violations(self) -> list[ValidationViolation]:
        """Locate capacity and SLO inequalities by model/GPU pair or query."""

        violations: list[ValidationViolation] = []
        pair_inequality_groups = (
            (
                ConstraintFamily.GPU_MEMORY,
                self.gpu_memory_diagnostics,
                self.tolerances.gpu_memory,
            ),
            (
                ConstraintFamily.COMPUTE_CAPACITY,
                self.compute_capacity_diagnostics,
                self.tolerances.compute_capacity,
            ),
        )
        for family, diagnostics, tolerance in pair_inequality_groups:
            for diagnostic in diagnostics:
                if not diagnostic.is_feasible(tolerance):
                    violations.append(
                        ValidationViolation(
                            family,
                            (diagnostic.model_id, diagnostic.gpu_tier_id),
                            diagnostic.slack,
                        )
                    )

        query_inequality_groups = (
            (
                ConstraintFamily.STORAGE_CAPACITY,
                self.storage_capacity_diagnostics,
                self.tolerances.storage_capacity,
            ),
            (
                ConstraintFamily.DELAY_SLO,
                self.delay_slo_diagnostics,
                self.tolerances.delay_slo,
            ),
            (
                ConstraintFamily.ERROR_SLO,
                self.error_slo_diagnostics,
                self.tolerances.error_slo,
            ),
        )
        for family, diagnostics, tolerance in query_inequality_groups:
            for diagnostic in diagnostics:
                if not diagnostic.is_feasible(tolerance):
                    violations.append(
                        ValidationViolation(
                            family,
                            (diagnostic.query_id,),
                            diagnostic.slack,
                        )
                    )
        return violations

    def _routing_consistency_violations(self) -> list[ValidationViolation]:
        """Locate each failed routing bound at its query/model/GPU index."""

        violations: list[ValidationViolation] = []
        for diagnostic in self.routing_consistency_diagnostics:
            location = (diagnostic.query_id, diagnostic.model_id, diagnostic.gpu_tier_id)
            named_slacks = (
                ("routing_nonnegative_slack", diagnostic.routing_nonnegative_slack),
                ("admission_slack", diagnostic.admission_slack),
                ("deployment_slack", diagnostic.deployment_slack),
            )
            for inequality_name, slack in named_slacks:
                if slack < -self.tolerances.routing_consistency:
                    violations.append(
                        ValidationViolation(
                            ConstraintFamily.ROUTING_CONSISTENCY,
                            (*location, inequality_name),
                            slack,
                        )
                    )

        return violations

    @property
    def is_feasible(self) -> bool:
        """Return true only when domains and every reported family pass."""

        return self.domain_diagnostic.is_valid and not self.violations

    @property
    def violation_count(self) -> int:
        """Return the number of independently located violations."""

        return len(self.violations)

    @property
    def violated_families(self) -> tuple[ConstraintFamily, ...]:
        """Return violated families once each in deterministic report order."""

        return tuple(dict.fromkeys(item.family for item in self.violations))

    @property
    def max_violation_by_family(self) -> Mapping[ConstraintFamily, float]:
        """Return native-unit maxima within families, never across families."""

        maxima: dict[ConstraintFamily, float] = {}
        for violation in self.violations:
            if violation.raw_violation is not None:
                maxima[violation.family] = max(
                    maxima.get(violation.family, 0.0), violation.raw_violation
                )
        return MappingProxyType(maxima)


def _empty_report(
    paper_version: PaperVersion,
    tolerances: ValidationTolerances,
    domain_diagnostic: PlacementDomainDiagnostic,
) -> PlacementValidationReport:
    """Return a domain-invalid report with no mathematical results."""

    return PlacementValidationReport(
        paper_version=paper_version,
        tolerances=tolerances,
        domain_diagnostic=domain_diagnostic,
        processing_delays_seconds={},
        objective_breakdown=None,
        mccormick_diagnostics=(),
        demand_balance_diagnostics=(),
        budget_diagnostic=None,
        configuration_selection_diagnostics=(),
        gpu_count_linking_diagnostics=(),
        gpu_memory_diagnostics=(),
        compute_capacity_diagnostics=(),
        storage_capacity_diagnostics=(),
        delay_slo_diagnostics=(),
        error_slo_diagnostics=(),
        routing_consistency_diagnostics=(),
    )


@dataclass(frozen=True, slots=True)
class PlacementValidator:
    """Validate supplied placements with one immutable configuration."""

    instance: ProblemInstance
    paper_version: PaperVersion
    tolerances: ValidationTolerances = field(default_factory=ValidationTolerances)

    def __post_init__(self) -> None:
        """Reject invalid API configuration before scientific validation."""

        if not isinstance(self.paper_version, PaperVersion):
            raise ValueError("paper_version must be PaperVersion.V1 or PaperVersion.V2")
        if not isinstance(self.tolerances, ValidationTolerances):
            raise TypeError("tolerances must be a ValidationTolerances")

    def validate(self, state: PlacementDecisionState) -> PlacementValidationReport:
        """Check domains, then recompute objective and constraint diagnostics.

        Invalid domains return an empty report; all constraint failures remain
        visible. Objective: v2 Eq. (8a) / v1 Eq. (5a).
        """

        instance = self.instance
        paper_version = self.paper_version
        selected_tolerances = self.tolerances

        try:
            validate_placement_decision_domains(instance, state)
        except (InstanceValidationError, DecisionDomainError) as error:
            return _empty_report(
                paper_version,
                selected_tolerances,
                PlacementDomainDiagnostic(
                    is_valid=False,
                    error_type=type(error).__name__,
                    message=str(error),
                ),
            )

        # Derive D_proc from supplied v (v2 Eq. 6), without replacing it with x*w.
        processing_delays = compute_processing_delays_seconds(instance, state)
        objective = compute_objective_breakdown(
            instance,
            ObjectiveState(
                gpu_counts=state.gpu_counts,
                admission_indicators=state.admission_indicators,
                routing_fractions=state.routing_fractions,
                unmet_fractions=state.unmet_fractions,
                processing_delays_seconds=processing_delays,
            ),
            paper_version,
        )

        return PlacementValidationReport(
            paper_version=paper_version,
            tolerances=selected_tolerances,
            domain_diagnostic=PlacementDomainDiagnostic(is_valid=True),
            processing_delays_seconds=processing_delays,
            objective_breakdown=objective,
            mccormick_diagnostics=compute_mccormick_consistency_diagnostics(
                instance, state
            ),
            demand_balance_diagnostics=compute_demand_balance_residuals(
                instance, state.routing_decisions
            ),
            budget_diagnostic=compute_budget_residual(instance, state),
            configuration_selection_diagnostics=(
                compute_configuration_selection_residuals(
                    instance, state.parallelism_decisions
                )
            ),
            gpu_count_linking_diagnostics=compute_gpu_count_linking_residuals(
                instance, state.parallelism_decisions
            ),
            gpu_memory_diagnostics=compute_gpu_memory_residuals(instance, state),
            compute_capacity_diagnostics=compute_compute_capacity_diagnostics(
                instance, state.parallelism_decisions
            ),
            storage_capacity_diagnostics=compute_storage_capacity_residuals(
                instance, state
            ),
            delay_slo_diagnostics=compute_delay_slo_residuals(instance, state),
            error_slo_diagnostics=compute_error_slo_residuals(
                instance, state.routing_decisions
            ),
            routing_consistency_diagnostics=compute_routing_consistency_residuals(
                instance, state.routing_decisions
            ),
        )


def validate_placement(
    instance: ProblemInstance,
    state: PlacementDecisionState,
    paper_version: PaperVersion,
    tolerances: ValidationTolerances | None = None,
) -> PlacementValidationReport:
    """Validate one placement through the configured independent authority."""

    selected_tolerances = ValidationTolerances() if tolerances is None else tolerances
    return PlacementValidator(instance, paper_version, selected_tolerances).validate(state)
