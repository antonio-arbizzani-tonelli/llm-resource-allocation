"""Immutable fixed deployment and realized coefficients for the Stage-2 LP.

Paper v1 Eq. (12a)-(12f) and v2 Section 5.2 fix ``z*,w*,y*``.
Only ``x,u`` are re-optimized; these data are independent of Pyomo and solvers.
"""

from dataclasses import dataclass, field
from math import isfinite
from types import MappingProxyType
from typing import Mapping

from llm_resource_allocation.domain import InstanceValidationError, ProblemInstance
from llm_resource_allocation.math.objective import PaperVersion
from llm_resource_allocation.math.parallelism import (
    ParallelismDecisionState,
    _compute_gpu_count_linking_residuals,
    _validate_parallelism_configuration_domains,
)
from llm_resource_allocation.math.routing import (
    DecisionDomainError,
    RoutingDecisionState,
    _compute_routing_consistency_residuals,
    _validate_deployment_indicator_domains,
    _validate_routing_decision_domains,
)

from .problem_data import (
    ConfigurationKey,
    ModelTierKey,
    PdmProblemData,
    RouteKey,
)


@dataclass(frozen=True, slots=True)
class Stage2FixedDeployment:
    """Store read-only sparse ``z*,w*,y*``; omitted known entries are zero.

    ``q[j,k] = sum_(n,m) w*[j,k,n,m]`` is derived during validation.
    Operational decisions ``x,u`` are absent from this fixed boundary.
    """

    admission_indicators: Mapping[RouteKey, float]
    configuration_selectors: Mapping[ConfigurationKey, float]
    gpu_counts: Mapping[ModelTierKey, float]

    def __post_init__(self) -> None:
        """Copy all caller-owned fixed-decision mappings."""

        for field_name in (
            "admission_indicators",
            "configuration_selectors",
            "gpu_counts",
        ):
            object.__setattr__(
                self,
                field_name,
                MappingProxyType(dict(getattr(self, field_name))),
            )


@dataclass(frozen=True, slots=True)
class Stage2RealizedScenario:
    """Store one realization in canonical units.

    ``arrival_rates_per_hour`` is ``lambda_tilde`` in queries/hour.
    Realized ``d_comp,d_comm`` maps are in seconds/token; effective errors are
    dimensionless with no upper bound. ``Stage2ProblemData`` requires complete
    coverage and finite non-negative values, without clipping.
    """

    id: str
    arrival_rates_per_hour: Mapping[str, float]
    compute_delay_seconds_per_token: Mapping[RouteKey, float]
    communication_delay_seconds_per_token: Mapping[RouteKey, float]
    effective_errors: Mapping[RouteKey, float]

    def __post_init__(self) -> None:
        """Copy all caller-owned realized-coefficient mappings."""

        for field_name in (
            "arrival_rates_per_hour",
            "compute_delay_seconds_per_token",
            "communication_delay_seconds_per_token",
            "effective_errors",
        ):
            object.__setattr__(
                self,
                field_name,
                MappingProxyType(dict(getattr(self, field_name))),
            )


@dataclass(frozen=True, slots=True)
class Stage2ProblemData:
    """Pair the shared instance/lattices with fixed deployment and a realization.

    ``routing_keys`` and ``unmet_keys`` define continuous decisions ``x,u``.
    Internal ``q=sum(w*)`` is derived solely to check fixed deployment linkage.
    """

    pdm_problem_data: PdmProblemData
    fixed_deployment: Stage2FixedDeployment
    realized_scenario: Stage2RealizedScenario
    paper_version: PaperVersion = PaperVersion.V2
    derived_deployment_indicators: Mapping[ModelTierKey, float] = field(
        init=False
    )

    def __post_init__(self) -> None:
        """Validate the fixed/realized boundary against the shared lattices."""

        if not isinstance(self.pdm_problem_data, PdmProblemData):
            raise TypeError("pdm_problem_data must be a PdmProblemData")
        if not isinstance(self.fixed_deployment, Stage2FixedDeployment):
            raise TypeError("fixed_deployment must be a Stage2FixedDeployment")
        if not isinstance(self.realized_scenario, Stage2RealizedScenario):
            raise TypeError("realized_scenario must be a Stage2RealizedScenario")
        if not isinstance(self.paper_version, PaperVersion):
            raise ValueError("paper_version must be PaperVersion.V1 or PaperVersion.V2")
        if self.instance.uses_coherent_units and self.paper_version is PaperVersion.V1:
            raise ValueError("coherent units require PaperVersion.V2; v1 uses LITERAL_PAPER")

        derived_q = validate_stage2_fixed_deployment(
            self.pdm_problem_data, self.fixed_deployment
        )
        validate_stage2_realized_scenario(
            self.pdm_problem_data, self.realized_scenario
        )
        object.__setattr__(
            self,
            "derived_deployment_indicators",
            MappingProxyType(derived_q),
        )

    @classmethod
    def _from_validated_deployment(
        cls,
        pdm_problem_data: PdmProblemData,
        fixed_deployment: Stage2FixedDeployment,
        derived_deployment_indicators: Mapping[ModelTierKey, float],
        realized_scenario: Stage2RealizedScenario,
        paper_version: PaperVersion,
    ) -> "Stage2ProblemData":
        """Attach a new scenario to the adapter's already checked deployment.

        The private integration path supplies the exact immutable adapter objects.
        Public construction continues to validate both fixed and realized inputs.
        """

        if pdm_problem_data.instance.uses_coherent_units and paper_version is PaperVersion.V1:
            raise ValueError("coherent units require PaperVersion.V2; v1 uses LITERAL_PAPER")
        validate_stage2_realized_scenario(pdm_problem_data, realized_scenario)
        result = object.__new__(cls)
        for name, value in (
            ("pdm_problem_data", pdm_problem_data),
            ("fixed_deployment", fixed_deployment),
            ("realized_scenario", realized_scenario),
            ("paper_version", paper_version),
            ("derived_deployment_indicators", derived_deployment_indicators),
        ):
            object.__setattr__(result, name, value)
        return result

    @property
    def instance(self) -> ProblemInstance:
        """Return the exact shared scientific instance by identity."""

        return self.pdm_problem_data.instance

    @property
    def routing_keys(self) -> tuple[RouteKey, ...]:
        """Return the exact ``x`` lattice owned by ``PdmProblemData``."""

        return self.pdm_problem_data.variable_lattices.route_keys

    @property
    def unmet_keys(self) -> tuple[str, ...]:
        """Return the exact ``u`` lattice owned by ``PdmProblemData``."""

        return self.pdm_problem_data.variable_lattices.unmet_keys


def validate_stage2_fixed_deployment(
    pdm_data: PdmProblemData,
    fixed: Stage2FixedDeployment,
) -> dict[ModelTierKey, float]:
    """Check fixed ``z*,w*,y*`` domains/linkage and derive ``q=sum(w*)``.

    Require ``y*=sum(n*m*w*)`` and ``z*<=q`` on the shared lattices.
    This structural check does not recertify the complete Stage-1 placement.
    """

    if not isinstance(pdm_data, PdmProblemData):
        raise TypeError("pdm_data must be a PdmProblemData")
    if not isinstance(fixed, Stage2FixedDeployment):
        raise TypeError("fixed must be a Stage2FixedDeployment")
    lattices = pdm_data.variable_lattices
    expected_routes = set(lattices.route_keys)
    expected_configurations = set(lattices.configuration_keys)
    expected_pairs = set(lattices.model_tier_keys)
    structural_errors: list[str] = []
    for label, values, expected in (
        ("admission_indicators", fixed.admission_indicators, expected_routes),
        (
            "configuration_selectors",
            fixed.configuration_selectors,
            expected_configurations,
        ),
        ("gpu_counts", fixed.gpu_counts, expected_pairs),
    ):
        unknown = set(values) - expected
        if unknown:
            structural_errors.append(
                f"{label} has unknown semantic IDs: "
                f"{sorted(unknown, key=repr)!r}"
            )
    if structural_errors:
        raise DecisionDomainError(
            "Invalid Stage-2 fixed deployment:\n- "
            + "\n- ".join(structural_errors)
        )

    derived_q = {
        pair: sum(
            fixed.configuration_selectors.get(configuration, 0.0)
            for configuration in lattices.configuration_keys
            if configuration[:2] == pair
        )
        for pair in lattices.model_tier_keys
    }
    routing_state = RoutingDecisionState(
        routing_fractions={},
        admission_indicators=fixed.admission_indicators,
        deployment_indicators=derived_q,
        unmet_fractions={},
    )
    parallelism_state = ParallelismDecisionState(
        routing_decisions=routing_state,
        configuration_selectors=fixed.configuration_selectors,
        gpu_counts=fixed.gpu_counts,
    )

    # Fixed decisions retain the Stage-1 exact domains.
    # PdmProblemData already owns instance validation; check only new decisions.
    _validate_deployment_indicator_domains(pdm_data.instance, derived_q)
    _validate_parallelism_configuration_domains(pdm_data.instance, parallelism_state)
    _validate_routing_decision_domains(pdm_data.instance, routing_state)

    consistency_errors: list[str] = []
    for residual in _compute_gpu_count_linking_residuals(
        pdm_data.instance, parallelism_state
    ):
        if residual.absolute_violation != 0.0:
            consistency_errors.append(
                "fixed y* does not equal sum(n*m*w*) for "
                f"({residual.model_id!r}, {residual.gpu_tier_id!r})"
            )
    for residual in _compute_routing_consistency_residuals(
        pdm_data.instance, routing_state
    ):
        if residual.deployment_slack < 0.0:
            consistency_errors.append(
                "fixed z* exceeds q derived from w* for "
                f"({residual.query_id!r}, {residual.model_id!r}, "
                f"{residual.gpu_tier_id!r})"
            )
    if consistency_errors:
        raise DecisionDomainError(
            "Invalid Stage-2 fixed deployment:\n- "
            + "\n- ".join(consistency_errors)
        )
    return derived_q


def validate_stage2_realized_scenario(
    pdm_data: PdmProblemData,
    scenario: Stage2RealizedScenario,
) -> None:
    """Require complete coefficient lattices and finite non-negative values.

    Effective errors have no upper bound. No coefficient is clipped or repaired.
    """

    if not isinstance(pdm_data, PdmProblemData):
        raise TypeError("pdm_data must be a PdmProblemData")
    if not isinstance(scenario, Stage2RealizedScenario):
        raise TypeError("scenario must be a Stage2RealizedScenario")

    errors: list[str] = []
    if not isinstance(scenario.id, str) or not scenario.id:
        errors.append(f"scenario ID must be a non-empty string; got {scenario.id!r}")

    expected_queries = set(pdm_data.variable_lattices.unmet_keys)
    expected_routes = set(pdm_data.variable_lattices.route_keys)
    for label, values, expected in (
        ("arrival_rates_per_hour", scenario.arrival_rates_per_hour, expected_queries),
        (
            "compute_delay_seconds_per_token",
            scenario.compute_delay_seconds_per_token,
            expected_routes,
        ),
        (
            "communication_delay_seconds_per_token",
            scenario.communication_delay_seconds_per_token,
            expected_routes,
        ),
        ("effective_errors", scenario.effective_errors, expected_routes),
    ):
        actual = set(values)
        missing = expected - actual
        extra = actual - expected
        if missing:
            errors.append(f"{label} is missing keys: {sorted(missing, key=repr)!r}")
        if extra:
            errors.append(f"{label} has unexpected keys: {sorted(extra, key=repr)!r}")
        for key, value in values.items():
            value_label = f"{label}[{key!r}]"
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                errors.append(f"{value_label} must be a real number; got {value!r}")
            elif not isfinite(value):
                errors.append(f"{value_label} must be finite; got {value!r}")
            elif value < 0.0:
                errors.append(f"{value_label} must be >= 0.0; got {value!r}")

    if errors:
        raise InstanceValidationError(
            "Invalid Stage-2 realized scenario:\n- " + "\n- ".join(errors)
        )
