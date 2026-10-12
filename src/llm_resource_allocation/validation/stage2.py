"""Independent pure-Python validation for one Stage-2 operational solution."""

from dataclasses import dataclass, field, fields
from enum import Enum
from math import fsum, isfinite
from types import MappingProxyType
from typing import Mapping

from llm_resource_allocation.domain import ParallelismConfig, UnitConvention
from llm_resource_allocation.math.compute_capacity import ComputeCapacityDiagnostic
from llm_resource_allocation.math.routing import (
    DecisionDomainError,
    DemandBalanceDiagnostic,
    RoutingDecisionState,
    _append_real_domain_error,
    _compute_demand_balance_residuals,
)
from llm_resource_allocation.math.processing_delay import DelaySloDiagnostic
from llm_resource_allocation.math.error_slo import ErrorSloDiagnostic
from llm_resource_allocation.math.latency import compute_configuration_delay_seconds
from llm_resource_allocation.math.objective import (
    compute_delay_penalty,
    compute_unmet_demand_penalty,
)
from llm_resource_allocation.optimization.problem_data import ModelTierKey, RouteKey
from llm_resource_allocation.optimization.stage2_extraction import (
    Stage2Solution,
    Stage2SolutionIdentity,
    stage2_solution_identity,
)
from llm_resource_allocation.optimization.stage2_problem_data import (
    Stage2ProblemData,
)
from .tolerances import (
    DEFAULT_FRACTION_ABSOLUTE_TOLERANCE,
    DEFAULT_COMPUTE_ABSOLUTE_TOLERANCE,
    DEFAULT_DELAY_ABSOLUTE_TOLERANCE,
    DEFAULT_ERROR_ABSOLUTE_TOLERANCE,
    DEFAULT_SCALED_RELATIVE_TOLERANCE,
    _record_applied_tolerance,
)


class Stage2ConstraintFamily(str, Enum):
    """Identify independently classified Stage-2 evidence families."""

    FIXED_DEPLOYMENT = "fixed_deployment"
    SOLUTION_IDENTITY = "solution_identity"
    DECISION_DOMAINS = "decision_domains"
    DEMAND_BALANCE = "demand_balance_eq_12b"
    COMPUTE_CAPACITY = "compute_capacity_eq_12c"
    DELAY_SLO = "delay_slo_eq_12d"
    ERROR_SLO = "error_slo_eq_12e"
    ROUTING_MASK = "routing_mask_eq_12f"


_ToleranceKey = tuple[Stage2ConstraintFamily, tuple[str | int, ...]]


@dataclass(frozen=True, slots=True)
class Stage2ValidationTolerances:
    """Use the same absolute/relative policy as placement; domains remain exact.

    ``exact()`` disables both terms for every operational row.
    """

    demand_balance: float = DEFAULT_FRACTION_ABSOLUTE_TOLERANCE
    compute_capacity: float = DEFAULT_COMPUTE_ABSOLUTE_TOLERANCE
    delay_slo: float = DEFAULT_DELAY_ABSOLUTE_TOLERANCE
    error_slo: float = DEFAULT_ERROR_ABSOLUTE_TOLERANCE
    routing_mask: float = DEFAULT_FRACTION_ABSOLUTE_TOLERANCE
    compute_capacity_relative: float = DEFAULT_SCALED_RELATIVE_TOLERANCE
    delay_slo_relative: float = DEFAULT_SCALED_RELATIVE_TOLERANCE
    error_slo_relative: float = DEFAULT_SCALED_RELATIVE_TOLERANCE

    @classmethod
    def exact(cls) -> "Stage2ValidationTolerances":
        """Request exact classification, including zero relative coefficients."""

        return cls(**{descriptor.name: 0.0 for descriptor in fields(cls)})

    def __post_init__(self) -> None:
        for descriptor in fields(self):
            value = getattr(self, descriptor.name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not isfinite(value)
                or value < 0.0
            ):
                raise ValueError(
                    f"{descriptor.name} tolerance must be a finite "
                    "non-negative real number"
                )


@dataclass(frozen=True, slots=True)
class Stage2ValidationDiagnostic:
    """Describe one non-numerical validation boundary."""

    is_valid: bool
    error_type: str | None = None
    message: str | None = None

@dataclass(frozen=True, slots=True)
class Stage2RoutingMaskDiagnostic:
    """Diagnose ``0 <= x[i,j,k] <= z*[i,j,k]`` for one route."""

    query_id: str
    model_id: str
    gpu_tier_id: str
    routing_fraction: float
    fixed_admission_indicator: float

    @property
    def slack(self) -> float:
        """Return fixed admission minus routed fraction."""

        return self.fixed_admission_indicator - self.routing_fraction

    @property
    def violation(self) -> float:
        return max(-self.slack, 0.0)

    def is_feasible(self, tolerance: float = 0.0) -> bool:
        _validate_tolerance(tolerance)
        return self.slack >= -tolerance


@dataclass(frozen=True, slots=True)
class Stage2ObjectiveBreakdown:
    """Separate optimized C4+C5 from reported realized C3.

    Coherent inputs produce USD costs; literal inputs retain their historical
    C3/C4 arithmetic. The validation report identifies the convention.
    """

    delay_penalty: float
    unmet_demand_penalty: float
    realized_data_storage_cost: float

    @property
    def operational_objective(self) -> float:
        """Return Stage-2 Eq. (12a)'s component set C4+C5."""

        return self.delay_penalty + self.unmet_demand_penalty

    @property
    def reported_variable_cost(self) -> float:
        """Return C3+C4+C5 for later expected-total-cost reporting."""

        return self.realized_data_storage_cost + self.operational_objective


@dataclass(frozen=True, slots=True)
class Stage2ValidationViolation:
    """Locate one failed Stage-2 boundary or equation."""

    family: Stage2ConstraintFamily
    semantic_location: tuple[str, ...]
    slack: float | None

    def __post_init__(self) -> None:
        """Own an immutable copy of the semantic location."""

        object.__setattr__(self, "semantic_location", tuple(self.semantic_location))

    @property
    def raw_violation(self) -> float | None:
        return None if self.slack is None else -self.slack


@dataclass(frozen=True, slots=True)
class Stage2ValidationReport:
    """Retain complete independent evidence for Eq. (12a)-(12f)."""

    tolerances: Stage2ValidationTolerances
    unit_convention: UnitConvention
    data_residency_hours: float
    fixed_deployment_diagnostic: Stage2ValidationDiagnostic
    identity_diagnostic: Stage2ValidationDiagnostic
    decision_domain_diagnostic: Stage2ValidationDiagnostic
    processing_delays_seconds: Mapping[str, float]
    objective_breakdown: Stage2ObjectiveBreakdown | None
    demand_balance_diagnostics: tuple[DemandBalanceDiagnostic, ...]
    compute_capacity_diagnostics: tuple[ComputeCapacityDiagnostic, ...]
    delay_slo_diagnostics: tuple[DelaySloDiagnostic, ...]
    error_slo_diagnostics: tuple[ErrorSloDiagnostic, ...]
    routing_mask_diagnostics: tuple[Stage2RoutingMaskDiagnostic, ...]
    _violations: tuple[Stage2ValidationViolation, ...] = field(
        init=False, repr=False, compare=False
    )
    applied_tolerances: Mapping[_ToleranceKey, float] = field(
        init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        """Own immutable copies of the mapping and diagnostic sequences."""

        object.__setattr__(
            self,
            "processing_delays_seconds",
            MappingProxyType(dict(self.processing_delays_seconds)),
        )
        for name in (
            "demand_balance_diagnostics",
            "compute_capacity_diagnostics",
            "delay_slo_diagnostics",
            "error_slo_diagnostics",
            "routing_mask_diagnostics",
        ):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        thresholds: dict[_ToleranceKey, float] = {}
        object.__setattr__(self, "_violations", self._compute_violations(thresholds))
        object.__setattr__(self, "applied_tolerances", MappingProxyType(thresholds))

    @property
    def violations(self) -> tuple[Stage2ValidationViolation, ...]:
        """Return every failed classification in equation order."""

        return self._violations

    def _compute_violations(
        self, thresholds: dict[_ToleranceKey, float]
    ) -> tuple[Stage2ValidationViolation, ...]:
        """Classify immutable diagnostic evidence once during construction."""

        for family, diagnostic in (
            (Stage2ConstraintFamily.FIXED_DEPLOYMENT, self.fixed_deployment_diagnostic),
            (Stage2ConstraintFamily.SOLUTION_IDENTITY, self.identity_diagnostic),
            (Stage2ConstraintFamily.DECISION_DOMAINS, self.decision_domain_diagnostic),
        ):
            if not diagnostic.is_valid:
                return (
                    Stage2ValidationViolation(
                        family,
                        (diagnostic.error_type or "validation_error",),
                        None,
                    ),
                )

        violations: list[Stage2ValidationViolation] = []
        for diagnostic in self.demand_balance_diagnostics:
            tolerance = _record_applied_tolerance(
                thresholds, Stage2ConstraintFamily.DEMAND_BALANCE,
                (diagnostic.query_id,), self.tolerances.demand_balance,
            )
            if not diagnostic.is_feasible(tolerance):
                violations.append(
                    Stage2ValidationViolation(
                        Stage2ConstraintFamily.DEMAND_BALANCE,
                        (diagnostic.query_id,),
                        -diagnostic.absolute_violation,
                    )
                )
        for diagnostic in self.compute_capacity_diagnostics:
            tolerance = _record_applied_tolerance(
                thresholds, Stage2ConstraintFamily.COMPUTE_CAPACITY,
                (diagnostic.model_id, diagnostic.gpu_tier_id),
                self.tolerances.compute_capacity, self.tolerances.compute_capacity_relative,
                diagnostic.required_compute, diagnostic.available_compute,
            )
            if not diagnostic.is_feasible(tolerance):
                violations.append(
                    Stage2ValidationViolation(
                        Stage2ConstraintFamily.COMPUTE_CAPACITY,
                        (diagnostic.model_id, diagnostic.gpu_tier_id),
                        diagnostic.slack,
                    )
                )
        for family, diagnostics, absolute, relative, lhs_name, rhs_name in (
            (
                Stage2ConstraintFamily.DELAY_SLO,
                self.delay_slo_diagnostics,
                self.tolerances.delay_slo,
                self.tolerances.delay_slo_relative,
                "processing_delay", "delay_limit",
            ),
            (
                Stage2ConstraintFamily.ERROR_SLO,
                self.error_slo_diagnostics,
                self.tolerances.error_slo,
                self.tolerances.error_slo_relative,
                "weighted_error", "error_limit",
            ),
        ):
            for diagnostic in diagnostics:
                tolerance = _record_applied_tolerance(
                    thresholds, family, (diagnostic.query_id,), absolute, relative,
                    getattr(diagnostic, lhs_name), getattr(diagnostic, rhs_name),
                )
                if not diagnostic.is_feasible(tolerance):
                    violations.append(
                        Stage2ValidationViolation(
                            family,
                            (diagnostic.query_id,),
                            diagnostic.slack,
                        )
                    )
        for diagnostic in self.routing_mask_diagnostics:
            tolerance = _record_applied_tolerance(
                thresholds, Stage2ConstraintFamily.ROUTING_MASK,
                (diagnostic.query_id, diagnostic.model_id, diagnostic.gpu_tier_id),
                self.tolerances.routing_mask,
            )
            if not diagnostic.is_feasible(tolerance):
                violations.append(
                    Stage2ValidationViolation(
                        Stage2ConstraintFamily.ROUTING_MASK,
                        (
                            diagnostic.query_id,
                            diagnostic.model_id,
                            diagnostic.gpu_tier_id,
                        ),
                        diagnostic.slack,
                    )
                )
        return tuple(violations)

    @property
    def is_feasible(self) -> bool:
        return not self.violations

    @property
    def violated_families(self) -> tuple[Stage2ConstraintFamily, ...]:
        return tuple(dict.fromkeys(item.family for item in self.violations))


def _validate_tolerance(tolerance: float) -> None:
    if (
        isinstance(tolerance, bool)
        or not isinstance(tolerance, (int, float))
        or not isfinite(tolerance)
        or tolerance < 0.0
    ):
        raise ValueError("tolerance must be a finite non-negative real number")


def _empty_report(
    problem_data: Stage2ProblemData,
    tolerances: Stage2ValidationTolerances,
    fixed: Stage2ValidationDiagnostic,
    identity: Stage2ValidationDiagnostic,
    domains: Stage2ValidationDiagnostic,
) -> Stage2ValidationReport:
    return Stage2ValidationReport(
        tolerances=tolerances,
        unit_convention=problem_data.instance.unit_convention,
        data_residency_hours=problem_data.instance.data_residency_hours,
        fixed_deployment_diagnostic=fixed,
        identity_diagnostic=identity,
        decision_domain_diagnostic=domains,
        processing_delays_seconds={},
        objective_breakdown=None,
        demand_balance_diagnostics=(),
        compute_capacity_diagnostics=(),
        delay_slo_diagnostics=(),
        error_slo_diagnostics=(),
        routing_mask_diagnostics=(),
    )


def _check_identity(
    expected: Stage2SolutionIdentity,
    solution: Stage2Solution,
) -> Stage2ValidationDiagnostic:
    if solution.identity != expected:
        return Stage2ValidationDiagnostic(
            False,
            "Stage2SolutionIdentityMismatch",
            f"expected {expected!r}; got {solution.identity!r}",
        )
    return Stage2ValidationDiagnostic(is_valid=True)


def _routing_state(
    problem_data: Stage2ProblemData,
    solution: Stage2Solution,
) -> RoutingDecisionState:
    return RoutingDecisionState(
        routing_fractions=solution.routing_fractions,
        admission_indicators=problem_data.fixed_deployment.admission_indicators,
        deployment_indicators=problem_data.derived_deployment_indicators,
        unmet_fractions=solution.unmet_fractions,
    )


def _check_solution_domains(
    problem_data: Stage2ProblemData,
    solution: Stage2Solution,
) -> Stage2ValidationDiagnostic:
    expected_x = problem_data.routing_keys
    expected_u = problem_data.unmet_keys
    if tuple(solution.routing_fractions) != expected_x:
        return Stage2ValidationDiagnostic(
            False,
            "Stage2SolutionLatticeMismatch",
            f"x keys must equal {expected_x!r}",
        )
    if tuple(solution.unmet_fractions) != expected_u:
        return Stage2ValidationDiagnostic(
            False,
            "Stage2SolutionLatticeMismatch",
            f"u keys must equal {expected_u!r}",
        )
    errors: list[str] = []
    for key, value in solution.routing_fractions.items():
        _append_real_domain_error(
            value, f"routing_fractions[{key!r}]", errors, maximum=1.0
        )
    max_unmet = {
        query.id: query.max_unmet_fraction for query in problem_data.instance.queries
    }
    for query_id, value in solution.unmet_fractions.items():
        _append_real_domain_error(
            value, f"unmet_fractions[{query_id!r}]", errors,
            maximum=max_unmet[query_id],
        )
    if errors:
        error = DecisionDomainError(
            "Invalid routing decision state:\n- " + "\n- ".join(errors)
        )
        return Stage2ValidationDiagnostic(False, type(error).__name__, str(error))
    return Stage2ValidationDiagnostic(is_valid=True)


def _realized_configuration_delays(
    problem_data: Stage2ProblemData,
) -> dict[RouteKey, float]:
    instance = problem_data.instance
    scenario = problem_data.realized_scenario
    fixed = problem_data.fixed_deployment
    query_by_id = {query.id: query for query in instance.queries}
    configurations_by_pair: dict[ModelTierKey, list[tuple[str, str, int, int]]] = {}
    for pair in problem_data.pdm_problem_data.variable_lattices.model_tier_keys:
        configurations_by_pair[pair] = [
            key
            for key in problem_data.pdm_problem_data.variable_lattices.configuration_keys
            if key[:2] == pair
        ]
    return {
        route_key: fsum(
            fixed.configuration_selectors.get(configuration_key, 0.0)
            * compute_configuration_delay_seconds(
                scenario.compute_delay_seconds_per_token[route_key],
                scenario.communication_delay_seconds_per_token[route_key],
                query_by_id[route_key[0]],
                ParallelismConfig(configuration_key[2], configuration_key[3]),
            )
            for configuration_key in configurations_by_pair[route_key[1:]]
        )
        for route_key in problem_data.routing_keys
    }


def _compute_capacity_diagnostics(
    problem_data: Stage2ProblemData,
    solution: Stage2Solution,
) -> tuple[ComputeCapacityDiagnostic, ...]:
    """Recompute realized load and fixed capacity in TFLOP/hour (v1 Eq. 12c)."""

    instance = problem_data.instance
    scenario = problem_data.realized_scenario
    fixed = problem_data.fixed_deployment
    query_by_id = {query.id: query for query in instance.queries}
    tier_by_id = {tier.id: tier for tier in instance.gpu_tiers}
    compute_diagnostics: list[ComputeCapacityDiagnostic] = []
    for model_id, tier_id in problem_data.pdm_problem_data.variable_lattices.model_tier_keys:
        required = fsum(
            instance.compute_gflop_per_token[(query_id, model_id, tier_id)]
            * query_by_id[query_id].total_tokens
            * scenario.arrival_rates_per_hour[query_id]
            * solution.routing_fractions[(query_id, model_id, tier_id)]
            / 1000.0
            for query_id in problem_data.unmet_keys
        )
        available = (
            instance.compute_utilization
            * instance.seconds_per_hour
            * tier_by_id[tier_id].compute_throughput_tflops
            * fixed.gpu_counts.get((model_id, tier_id), 0.0)
        )
        compute_diagnostics.append(
            ComputeCapacityDiagnostic(
                model_id, tier_id, required, available
            )
        )
    return tuple(compute_diagnostics)


def _compute_slo_diagnostics(
    problem_data: Stage2ProblemData,
    solution: Stage2Solution,
    delay_by_route: Mapping[RouteKey, float],
) -> tuple[
    dict[str, float],
    tuple[DelaySloDiagnostic, ...],
    tuple[ErrorSloDiagnostic, ...],
]:
    """Return processing delays and delay/error evidence (v1 Eqs. 12d-12e)."""

    scenario = problem_data.realized_scenario
    query_by_id = {query.id: query for query in problem_data.instance.queries}
    processing_delays = {
        query_id: fsum(
            delay_by_route[(query_id, model_id, tier_id)]
            * solution.routing_fractions[(query_id, model_id, tier_id)]
            for model_id in problem_data.pdm_problem_data.index_sets.model_ids
            for tier_id in problem_data.pdm_problem_data.index_sets.tier_ids
        )
        for query_id in problem_data.unmet_keys
    }
    delay_diagnostics = tuple(
        DelaySloDiagnostic(
            query_id,
            processing_delays[query_id],
            query_by_id[query_id].delay_slo_seconds,
        )
        for query_id in problem_data.unmet_keys
    )
    error_diagnostics = tuple(
        ErrorSloDiagnostic(
            query_id,
            fsum(
                scenario.effective_errors[(query_id, model_id, tier_id)]
                * solution.routing_fractions[(query_id, model_id, tier_id)]
                for model_id in problem_data.pdm_problem_data.index_sets.model_ids
                for tier_id in problem_data.pdm_problem_data.index_sets.tier_ids
            ),
            query_by_id[query_id].error_slo,
        )
        for query_id in problem_data.unmet_keys
    )
    return processing_delays, delay_diagnostics, error_diagnostics


def _compute_objective_breakdown(
    problem_data: Stage2ProblemData,
    solution: Stage2Solution,
    processing_delays: Mapping[str, float],
) -> Stage2ObjectiveBreakdown:
    """Recompute C4+C5 and separate C3 under the recorded unit convention."""

    instance = problem_data.instance
    scenario = problem_data.realized_scenario
    query_by_id = {query.id: query for query in instance.queries}
    delay_penalty = compute_delay_penalty(
        instance, processing_delays,
        arrival_rates_per_hour=scenario.arrival_rates_per_hour,
    )
    unmet_penalty = compute_unmet_demand_penalty(
        instance, solution.unmet_fractions, problem_data.paper_version
    )
    realized_c3 = instance.horizon_hours * instance.storage_price_usd_per_gb_hour * fsum(
        query_by_id[query_id].storage_gb_per_token
        * query_by_id[query_id].total_tokens
        * scenario.arrival_rates_per_hour[query_id]
        * solution.routing_fractions[(query_id, model_id, tier_id)]
        for query_id, model_id, tier_id in problem_data.routing_keys
    )
    if instance.uses_coherent_units:
        realized_c3 *= instance.data_residency_hours
    return Stage2ObjectiveBreakdown(
        delay_penalty=delay_penalty,
        unmet_demand_penalty=unmet_penalty,
        realized_data_storage_cost=realized_c3,
    )


@dataclass(frozen=True, slots=True)
class Stage2Validator:
    """Validate solutions against one immutable operational problem and policy.

    Problem data owns fixed-deployment and scenario validation. Prepare their
    static coefficients once; check every new solution independently.
    """

    problem_data: Stage2ProblemData
    tolerances: Stage2ValidationTolerances = field(
        default_factory=Stage2ValidationTolerances
    )
    _solution_identity: Stage2SolutionIdentity = field(
        init=False, repr=False, compare=False
    )
    _configuration_delays: Mapping[RouteKey, float] = field(
        init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        """Reject invalid API configuration before scientific validation."""

        if not isinstance(self.problem_data, Stage2ProblemData):
            raise TypeError("problem_data must be a Stage2ProblemData")
        if not isinstance(self.tolerances, Stage2ValidationTolerances):
            raise TypeError("tolerances must be a Stage2ValidationTolerances")
        object.__setattr__(
            self, "_solution_identity", stage2_solution_identity(self.problem_data)
        )
        object.__setattr__(
            self, "_configuration_delays",
            MappingProxyType(_realized_configuration_delays(self.problem_data)),
        )

    def validate(self, solution: Stage2Solution) -> Stage2ValidationReport:
        """Recompute Eq. (12a)-(12f) without Pyomo or solver evidence."""

        if not isinstance(solution, Stage2Solution):
            raise TypeError("solution must be a Stage2Solution")
        problem_data = self.problem_data
        selected_tolerances = self.tolerances

        fixed_diagnostic = Stage2ValidationDiagnostic(is_valid=True)
        identity_diagnostic = _check_identity(self._solution_identity, solution)
        if not identity_diagnostic.is_valid:
            return _empty_report(
                problem_data,
                selected_tolerances,
                fixed_diagnostic,
                identity_diagnostic,
                Stage2ValidationDiagnostic(is_valid=True),
            )
        domain_diagnostic = _check_solution_domains(problem_data, solution)
        if not domain_diagnostic.is_valid:
            return _empty_report(
                problem_data,
                selected_tolerances,
                fixed_diagnostic,
                identity_diagnostic,
                domain_diagnostic,
            )

        instance = problem_data.instance
        fixed = problem_data.fixed_deployment
        routing_state = _routing_state(problem_data, solution)
        demand_diagnostics = _compute_demand_balance_residuals(instance, routing_state)
        compute_diagnostics = _compute_capacity_diagnostics(problem_data, solution)
        processing_delays, delay_diagnostics, error_diagnostics = (
            _compute_slo_diagnostics(problem_data, solution, self._configuration_delays)
        )

        mask_diagnostics = tuple(
            Stage2RoutingMaskDiagnostic(
                route_key[0],
                route_key[1],
                route_key[2],
                solution.routing_fractions[route_key],
                fixed.admission_indicators.get(route_key, 0.0),
            )
            for route_key in problem_data.routing_keys
        )

        objective = _compute_objective_breakdown(
            problem_data, solution, processing_delays
        )
        return Stage2ValidationReport(
            tolerances=selected_tolerances,
            unit_convention=instance.unit_convention,
            data_residency_hours=instance.data_residency_hours,
            fixed_deployment_diagnostic=fixed_diagnostic,
            identity_diagnostic=identity_diagnostic,
            decision_domain_diagnostic=domain_diagnostic,
            processing_delays_seconds=processing_delays,
            objective_breakdown=objective,
            demand_balance_diagnostics=demand_diagnostics,
            compute_capacity_diagnostics=compute_diagnostics,
            delay_slo_diagnostics=delay_diagnostics,
            error_slo_diagnostics=error_diagnostics,
            routing_mask_diagnostics=mask_diagnostics,
        )


def validate_stage2_solution(
    problem_data: Stage2ProblemData,
    solution: Stage2Solution,
    tolerances: Stage2ValidationTolerances | None = None,
) -> Stage2ValidationReport:
    """Validate one solution through the configured independent authority."""

    selected_tolerances = (
        Stage2ValidationTolerances() if tolerances is None else tolerances
    )
    return Stage2Validator(problem_data, selected_tolerances).validate(solution)
