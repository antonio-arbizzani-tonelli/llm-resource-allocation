"""Explicit-policy, reproducible generation of one realized Stage-2 scenario.

The paper protocol remains an audited description.  This module generates one
scenario only after a caller supplies every missing output-sensitive choice in
an :class:`ExecutableScenarioSamplingPolicy`.  It contains no Stage-1 method,
Stage-2 solve, batch loop, or aggregation.
"""

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from math import isfinite
from platform import python_version
from random import Random

from llm_resource_allocation.domain import InstanceValidationError
from llm_resource_allocation.math.objective import PaperVersion
from llm_resource_allocation.math.error import compute_effective_error
from llm_resource_allocation.optimization.problem_data import PdmProblemData, RouteKey
from llm_resource_allocation.optimization.stage2_problem_data import (
    Stage2RealizedScenario,
    validate_stage2_realized_scenario,
)

from .scenario_protocol import (
    PerturbationDirection,
    ProtocolKind,
    ProvenanceClass,
    ScenarioProtocolSpec,
    ScenarioQuantity,
)


SemanticScenarioKey = str | RouteKey


class DistributionFamily(str, Enum):
    """Executable probability families currently needed by synthetic checks."""

    UNIFORM = "uniform"


class SamplingScope(str, Enum):
    """Choose which semantic entries share one relative perturbation draw."""

    GLOBAL = "global"
    PER_QUERY = "per-query"
    PER_ENTRY = "per-entry"


class DelayRealizationTarget(str, Enum):
    """Map the audited delay quantity onto current Stage-2 component fields."""

    COMPUTE_ONLY = "compute-only"
    COMMUNICATION_ONLY = "communication-only"
    BOTH_SHARED = "both-shared-draw"
    BOTH_INDEPENDENT = "both-independent-draws"


class CrossQuantityDependence(str, Enum):
    """Executable dependence relationship between quantity-level RNG streams."""

    INDEPENDENT_STREAMS = "independent-namespaced-streams"


class DomainHandling(str, Enum):
    """Post-draw handling authorized by the executable policy."""

    REJECT_INVALID_NO_CLIPPING = "reject-invalid-no-clipping"


class RngAlgorithm(str, Enum):
    """Local pseudorandom engine selected by the executable policy."""

    PYTHON_MT19937 = "python-random-mt19937"


class SeedDerivation(str, Enum):
    """Stable conversion of seed, identity, and stream namespace to RNG seed."""

    SHA256_NAMESPACED_V1 = "sha256-namespaced-v1"


class ScenarioSamplingPolicyError(ValueError):
    """Base error for incomplete or scientifically inconsistent policy data."""


class IncompleteScenarioSamplingPolicyError(ScenarioSamplingPolicyError):
    """Raised when generation would otherwise need to guess a policy field."""


class GeneratedScenarioDomainError(ScenarioSamplingPolicyError):
    """Raised when an unmodified generated value fails the shared domain check."""


@dataclass(frozen=True, slots=True)
class QuantitySamplingPolicy:
    """Make the draw law, support, direction, scope, and domain rule explicit."""

    quantity: ScenarioQuantity
    distribution_family: DistributionFamily | None
    relative_bounds: tuple[float, float] | None
    direction: PerturbationDirection | None
    sampling_scope: SamplingScope | None
    domain_handling: DomainHandling | None
    provenance: ProvenanceClass
    assumption_note: str

    def __post_init__(self) -> None:
        """Copy a supplied bounds sequence to immutable tuple storage."""

        if self.relative_bounds is not None:
            object.__setattr__(self, "relative_bounds", tuple(self.relative_bounds))


@dataclass(frozen=True, slots=True)
class ExecutableScenarioSamplingPolicy:
    """Contain every caller-owned choice required to generate one scenario.

    Quantity policies may be ``None`` so incomplete configurations can be
    transported and diagnosed.  The generator rejects them; it never fills
    them from unavailable fields in :class:`ScenarioProtocolSpec`.
    """

    policy_id: str
    paper_version: PaperVersion
    protocol_id: str
    provenance: ProvenanceClass
    rng_algorithm: RngAlgorithm | None
    seed_derivation: SeedDerivation | None
    cross_quantity_dependence: CrossQuantityDependence | None
    delay_realization_target: DelayRealizationTarget | None
    arrival: QuantitySamplingPolicy | None
    delay: QuantitySamplingPolicy | None
    effective_error: QuantitySamplingPolicy | None
    assumption_note: str


@dataclass(frozen=True, slots=True)
class QuantityDrawEvidence:
    """Retain the exact local stream and ordered factors used for one field."""

    stream_id: str
    quantity: ScenarioQuantity
    target_field: str
    sampling_scope: SamplingScope
    derived_seed: int
    relative_factors: tuple[tuple[SemanticScenarioKey, float], ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "relative_factors", tuple(self.relative_factors))


@dataclass(frozen=True, slots=True)
class ScenarioGenerationEvidence:
    """Reproducibility metadata without retaining a live RNG object."""

    nominal_problem_data: PdmProblemData
    protocol: ScenarioProtocolSpec
    sampling_policy: ExecutableScenarioSamplingPolicy
    scenario_id: str
    seed: int
    rng_algorithm: RngAlgorithm
    seed_derivation: SeedDerivation
    python_runtime_version: str
    semantic_query_order: tuple[str, ...]
    semantic_route_order: tuple[RouteKey, ...]
    draws: tuple[QuantityDrawEvidence, ...]

    def __post_init__(self) -> None:
        for field_name in (
            "semantic_query_order",
            "semantic_route_order",
            "draws",
        ):
            object.__setattr__(self, field_name, tuple(getattr(self, field_name)))


@dataclass(frozen=True, slots=True)
class GeneratedScenarioRecord:
    """Pair one immutable realized scenario with exact generation evidence."""

    realized_scenario: Stage2RealizedScenario
    evidence: ScenarioGenerationEvidence

def _protocol_quantity(
    protocol: ScenarioProtocolSpec,
    quantity: ScenarioQuantity,
):
    matches = tuple(
        item for item in protocol.perturbations if item.quantity is quantity
    )
    if len(matches) != 1:
        raise ScenarioSamplingPolicyError(
            f"protocol must contain exactly one {quantity.value} specification"
        )
    return matches[0]


def _validate_quantity_policy(
    audited_protocol: ScenarioProtocolSpec,
    executable: QuantitySamplingPolicy | None,
    expected_quantity: ScenarioQuantity,
) -> QuantitySamplingPolicy:
    if executable is None:
        raise IncompleteScenarioSamplingPolicyError(
            f"missing executable {expected_quantity.value} sampling policy"
        )
    if not isinstance(executable, QuantitySamplingPolicy):
        raise ScenarioSamplingPolicyError(
            f"{expected_quantity.value} policy must be QuantitySamplingPolicy"
        )
    if not isinstance(executable.quantity, ScenarioQuantity):
        raise ScenarioSamplingPolicyError("quantity must be ScenarioQuantity")
    if executable.quantity is not expected_quantity:
        raise ScenarioSamplingPolicyError(
            f"expected {expected_quantity.value} policy, got {executable.quantity.value}"
        )
    missing = tuple(
        field_name
        for field_name in (
            "distribution_family",
            "relative_bounds",
            "direction",
            "sampling_scope",
            "domain_handling",
        )
        if getattr(executable, field_name) is None
    )
    if missing:
        raise IncompleteScenarioSamplingPolicyError(
            f"{expected_quantity.value} policy is missing: {', '.join(missing)}"
        )
    if executable.distribution_family is not DistributionFamily.UNIFORM:
        raise ScenarioSamplingPolicyError("unsupported distribution family")
    if not isinstance(executable.sampling_scope, SamplingScope):
        raise ScenarioSamplingPolicyError("sampling_scope must be SamplingScope")
    if executable.domain_handling is not DomainHandling.REJECT_INVALID_NO_CLIPPING:
        raise ScenarioSamplingPolicyError(
            "only explicit reject-invalid/no-clipping domain handling is implemented"
        )
    if executable.provenance not in (
        ProvenanceClass.ASSUMED,
        ProvenanceClass.SCIENTIFIC_INTERPRETATION,
    ):
        raise ScenarioSamplingPolicyError(
            "executable unknown-field choices cannot be classified as paper-specified"
        )
    if (
        not isinstance(executable.assumption_note, str)
        or not executable.assumption_note.strip()
    ):
        raise ScenarioSamplingPolicyError("quantity assumption_note must be non-empty")

    bounds = executable.relative_bounds
    if not isinstance(bounds, tuple) or len(bounds) != 2:
        raise ScenarioSamplingPolicyError("relative_bounds must contain two values")
    lower, upper = bounds
    for value in bounds:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ScenarioSamplingPolicyError("relative bounds must be real numbers")
        if not isfinite(value):
            raise ScenarioSamplingPolicyError("relative bounds must be finite")
    if lower > upper:
        raise ScenarioSamplingPolicyError("relative lower bound must not exceed upper")

    audited = _protocol_quantity(audited_protocol, expected_quantity)
    if executable.direction is not audited.direction:
        raise ScenarioSamplingPolicyError(
            f"{expected_quantity.value} direction contradicts audited protocol"
        )
    if executable.direction is PerturbationDirection.ADVERSE_ONLY and lower < 0.0:
        raise ScenarioSamplingPolicyError(
            f"{expected_quantity.value} adverse-only bounds must be non-negative"
        )
    if executable.direction is PerturbationDirection.SYMMETRIC and not (
        lower <= 0.0 <= upper
    ):
        raise ScenarioSamplingPolicyError(
            f"{expected_quantity.value} symmetric bounds must include zero"
        )
    if audited.executable_relative_bounds is not None:
        audited_lower, audited_upper = audited.executable_relative_bounds
        if lower < audited_lower or upper > audited_upper:
            raise ScenarioSamplingPolicyError(
                f"{expected_quantity.value} bounds exceed audited paper support"
            )
    return executable


def _validate_policy(
    protocol: ScenarioProtocolSpec,
    policy: ExecutableScenarioSamplingPolicy,
) -> tuple[QuantitySamplingPolicy, QuantitySamplingPolicy, QuantitySamplingPolicy]:
    if protocol.kind is not ProtocolKind.PRIMARY_UNCERTAINTY:
        raise ScenarioSamplingPolicyError(
            "single-scenario generator requires a primary uncertainty protocol"
        )
    if not isinstance(policy.paper_version, PaperVersion):
        raise ScenarioSamplingPolicyError("policy paper_version must be PaperVersion")
    if policy.paper_version is not protocol.paper_version:
        raise ScenarioSamplingPolicyError("policy and protocol paper versions differ")
    if not isinstance(policy.protocol_id, str) or policy.protocol_id != protocol.protocol_id:
        raise ScenarioSamplingPolicyError("policy does not identify this protocol")
    if (
        not isinstance(policy.policy_id, str)
        or not policy.policy_id.strip()
        or not isinstance(policy.assumption_note, str)
        or not policy.assumption_note.strip()
    ):
        raise ScenarioSamplingPolicyError(
            "policy_id and assumption_note must be non-empty"
        )
    if policy.provenance not in (
        ProvenanceClass.ASSUMED,
        ProvenanceClass.SCIENTIFIC_INTERPRETATION,
    ):
        raise ScenarioSamplingPolicyError(
            "executable sampling policy cannot claim paper-specified provenance"
        )
    missing = tuple(
        field_name
        for field_name in (
            "rng_algorithm",
            "seed_derivation",
            "cross_quantity_dependence",
            "delay_realization_target",
        )
        if getattr(policy, field_name) is None
    )
    if missing:
        raise IncompleteScenarioSamplingPolicyError(
            "executable policy is missing: " + ", ".join(missing)
        )
    if policy.rng_algorithm is not RngAlgorithm.PYTHON_MT19937:
        raise ScenarioSamplingPolicyError("unsupported RNG algorithm")
    if policy.seed_derivation is not SeedDerivation.SHA256_NAMESPACED_V1:
        raise ScenarioSamplingPolicyError("unsupported seed derivation")
    if (
        policy.cross_quantity_dependence
        is not CrossQuantityDependence.INDEPENDENT_STREAMS
    ):
        raise ScenarioSamplingPolicyError(
            "only explicit independent namespaced streams are implemented"
        )
    if not isinstance(policy.delay_realization_target, DelayRealizationTarget):
        raise ScenarioSamplingPolicyError(
            "delay_realization_target must be DelayRealizationTarget"
        )
    return (
        _validate_quantity_policy(
            protocol, policy.arrival, ScenarioQuantity.ARRIVAL_RATE
        ),
        _validate_quantity_policy(
            protocol, policy.delay, ScenarioQuantity.DELAY_COEFFICIENT
        ),
        _validate_quantity_policy(
            protocol, policy.effective_error, ScenarioQuantity.EFFECTIVE_ERROR
        ),
    )


def _derived_seed(
    seed: int,
    scenario_id: str,
    policy_id: str,
    stream_id: str,
) -> int:
    """Derive a stable integer seed without Python's process-randomized hash."""

    payload = (
        f"fastllm-scenario-v1|{seed}|{len(scenario_id)}:{scenario_id}|"
        f"{len(policy_id)}:{policy_id}|{len(stream_id)}:{stream_id}"
    ).encode("utf-8")
    return int.from_bytes(sha256(payload).digest(), "big")


def _draw_relative_factors(
    keys: tuple[SemanticScenarioKey, ...],
    query_order: tuple[str, ...],
    policy: QuantitySamplingPolicy,
    rng: Random,
) -> tuple[tuple[SemanticScenarioKey, float], ...]:
    lower, upper = policy.relative_bounds  # type: ignore[misc]

    def draw() -> float:
        return lower + (upper - lower) * rng.random()

    if policy.sampling_scope is SamplingScope.GLOBAL:
        shared = draw()
        return tuple((key, shared) for key in keys)
    if policy.sampling_scope is SamplingScope.PER_QUERY:
        by_query = {query_id: draw() for query_id in query_order}
        return tuple(
            (key, by_query[key if isinstance(key, str) else key[0]]) for key in keys
        )
    if policy.sampling_scope is SamplingScope.PER_ENTRY:
        return tuple((key, draw()) for key in keys)
    raise ScenarioSamplingPolicyError("unsupported sampling scope")


def _draw_evidence(
    *,
    seed: int,
    scenario_id: str,
    policy_id: str,
    stream_id: str,
    target_field: str,
    keys: tuple[SemanticScenarioKey, ...],
    query_order: tuple[str, ...],
    quantity_policy: QuantitySamplingPolicy,
) -> QuantityDrawEvidence:
    derived_seed = _derived_seed(seed, scenario_id, policy_id, stream_id)
    factors = _draw_relative_factors(
        keys,
        query_order,
        quantity_policy,
        Random(derived_seed),
    )
    return QuantityDrawEvidence(
        stream_id,
        quantity_policy.quantity,
        target_field,
        quantity_policy.sampling_scope,  # type: ignore[arg-type]
        derived_seed,
        factors,
    )


def _factor_mapping(draw: QuantityDrawEvidence) -> dict[SemanticScenarioKey, float]:
    return dict(draw.relative_factors)


def _realize_delays(
    nominal_problem_data: PdmProblemData,
    delay_policy: QuantitySamplingPolicy,
    delay_target: DelayRealizationTarget,
    *,
    seed: int,
    scenario_id: str,
    policy_id: str,
) -> tuple[
    dict[RouteKey, float],
    dict[RouteKey, float],
    tuple[QuantityDrawEvidence, ...],
]:
    """Realize both delay components and retain their exact ordered draws."""

    query_order = nominal_problem_data.variable_lattices.unmet_keys
    route_order = nominal_problem_data.variable_lattices.route_keys
    instance = nominal_problem_data.instance
    draws: list[QuantityDrawEvidence] = []
    compute_factors: dict[SemanticScenarioKey, float] = {
        key: 0.0 for key in route_order
    }
    communication_factors: dict[SemanticScenarioKey, float] = {
        key: 0.0 for key in route_order
    }
    if delay_target is DelayRealizationTarget.BOTH_INDEPENDENT:
        compute_draw = _draw_evidence(
            seed=seed,
            scenario_id=scenario_id,
            policy_id=policy_id,
            stream_id="delay-compute",
            target_field="compute_delay_seconds_per_token",
            keys=route_order,
            query_order=query_order,
            quantity_policy=delay_policy,
        )
        communication_draw = _draw_evidence(
            seed=seed,
            scenario_id=scenario_id,
            policy_id=policy_id,
            stream_id="delay-communication",
            target_field="communication_delay_seconds_per_token",
            keys=route_order,
            query_order=query_order,
            quantity_policy=delay_policy,
        )
        draws.extend((compute_draw, communication_draw))
        compute_factors = _factor_mapping(compute_draw)
        communication_factors = _factor_mapping(communication_draw)
    else:
        target_field = {
            DelayRealizationTarget.COMPUTE_ONLY: "compute_delay_seconds_per_token",
            DelayRealizationTarget.COMMUNICATION_ONLY: (
                "communication_delay_seconds_per_token"
            ),
            DelayRealizationTarget.BOTH_SHARED: (
                "compute_and_communication_delay_seconds_per_token"
            ),
        }[delay_target]
        delay_draw = _draw_evidence(
            seed=seed,
            scenario_id=scenario_id,
            policy_id=policy_id,
            stream_id="delay-shared",
            target_field=target_field,
            keys=route_order,
            query_order=query_order,
            quantity_policy=delay_policy,
        )
        draws.append(delay_draw)
        factor = _factor_mapping(delay_draw)
        if delay_target in (
            DelayRealizationTarget.COMPUTE_ONLY,
            DelayRealizationTarget.BOTH_SHARED,
        ):
            compute_factors = factor
        if delay_target in (
            DelayRealizationTarget.COMMUNICATION_ONLY,
            DelayRealizationTarget.BOTH_SHARED,
        ):
            communication_factors = factor

    compute_delays = {
        key: instance.compute_delay_seconds_per_token[key]
        * (1.0 + compute_factors[key])
        for key in route_order
    }
    communication_delays = {
        key: instance.communication_delay_seconds_per_token[key]
        * (1.0 + communication_factors[key])
        for key in route_order
    }
    return compute_delays, communication_delays, tuple(draws)


def generate_realized_scenario(
    nominal_problem_data: PdmProblemData,
    protocol: ScenarioProtocolSpec,
    sampling_policy: ExecutableScenarioSamplingPolicy,
    *,
    seed: int,
    scenario_id: str,
) -> GeneratedScenarioRecord:
    """Generate exactly one reproducible scenario from an explicit policy.

    ``scenario_id`` participates in deterministic seed derivation; it is not
    merely a label.  Every RNG is local and namespaced by quantity/component.
    The returned evidence retains seeds and ordered factors, never live RNG
    state.  Invalid realized values are rejected by the same public authority
    used by :class:`Stage2ProblemData`.
    """

    if not isinstance(nominal_problem_data, PdmProblemData):
        raise TypeError("nominal_problem_data must be a PdmProblemData")
    if not isinstance(protocol, ScenarioProtocolSpec):
        raise TypeError("protocol must be a ScenarioProtocolSpec")
    if not isinstance(sampling_policy, ExecutableScenarioSamplingPolicy):
        raise TypeError(
            "sampling_policy must be an ExecutableScenarioSamplingPolicy"
        )
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TypeError("seed must be an integer")
    if not isinstance(scenario_id, str) or not scenario_id:
        raise ValueError("scenario_id must be a non-empty string")

    arrival_policy, delay_policy, error_policy = _validate_policy(
        protocol, sampling_policy
    )
    query_order = nominal_problem_data.variable_lattices.unmet_keys
    route_order = nominal_problem_data.variable_lattices.route_keys
    instance = nominal_problem_data.instance
    tier_by_id = {tier.id: tier for tier in instance.gpu_tiers}

    arrival_draw = _draw_evidence(
        seed=seed,
        scenario_id=scenario_id,
        policy_id=sampling_policy.policy_id,
        stream_id="arrival",
        target_field="arrival_rates_per_hour",
        keys=query_order,
        query_order=query_order,
        quantity_policy=arrival_policy,
    )
    arrival_factor = _factor_mapping(arrival_draw)
    query_by_id = {query.id: query for query in instance.queries}
    arrivals = {
        query_id: query_by_id[query_id].arrival_rate_per_hour
        * (1.0 + arrival_factor[query_id])
        for query_id in query_order
    }

    compute_delays, communication_delays, delay_draws = _realize_delays(
        nominal_problem_data,
        delay_policy,
        sampling_policy.delay_realization_target,  # type: ignore[arg-type]
        seed=seed,
        scenario_id=scenario_id,
        policy_id=sampling_policy.policy_id,
    )
    draws: list[QuantityDrawEvidence] = [arrival_draw, *delay_draws]

    error_draw = _draw_evidence(
        seed=seed,
        scenario_id=scenario_id,
        policy_id=sampling_policy.policy_id,
        stream_id="effective-error",
        target_field="effective_errors",
        keys=route_order,
        query_order=query_order,
        quantity_policy=error_policy,
    )
    draws.append(error_draw)
    error_factors = _factor_mapping(error_draw)
    effective_errors = {
        key: compute_effective_error(
            instance.base_error_rate[key[:2]],
            tier_by_id[key[2]].quantization_error_multiplier,
        )
        * (1.0 + error_factors[key])
        for key in route_order
    }

    scenario = Stage2RealizedScenario(
        scenario_id,
        arrivals,
        compute_delays,
        communication_delays,
        effective_errors,
    )
    try:
        validate_stage2_realized_scenario(nominal_problem_data, scenario)
    except InstanceValidationError as exc:
        raise GeneratedScenarioDomainError(str(exc)) from exc

    evidence = ScenarioGenerationEvidence(
        nominal_problem_data,
        protocol,
        sampling_policy,
        scenario_id,
        seed,
        sampling_policy.rng_algorithm,  # type: ignore[arg-type]
        sampling_policy.seed_derivation,  # type: ignore[arg-type]
        python_version(),
        query_order,
        route_order,
        tuple(draws),
    )
    return GeneratedScenarioRecord(scenario, evidence)
