"""Controlled synthetic v1-v2 comparison and cause-decomposition evidence.

This module performs comparison bookkeeping only. It consumes successful
results from existing generation, Stage-2 evaluation, and bounded-experiment
authorities; it does not generate scenarios, solve a model, recompute a
scientific objective, or aggregate scenario costs.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from math import isfinite
from types import MappingProxyType
from typing import TypeAlias

from llm_resource_allocation.math.objective import PaperVersion
from llm_resource_allocation.optimization.stage2_integration import (
    Stage1Stage2EvaluationResult,
)
from llm_resource_allocation.optimization.stage2_problem_data import (
    Stage2FixedDeployment,
)

from .bounded_experiment import BoundedScenarioExperimentRecord
from .scenario_evaluation import MultiScenarioEvaluationResult
from .scenario_generation import (
    ExecutableScenarioSamplingPolicy,
    GeneratedScenarioRecord,
    QuantityDrawEvidence,
    QuantitySamplingPolicy,
)
from .scenario_protocol import (
    PerturbationDirection,
    PerturbationSpecification,
    ScenarioProtocolSpec,
    ScenarioQuantity,
)


class VersionComparisonAxis(str, Enum):
    """Name the controlled dimension intended by one comparison."""

    OBJECTIVE_SEMANTICS = "objective-semantics-only"
    PROTOCOL_SEMANTICS = "protocol-semantics-only"
    COMBINED_END_TO_END = "combined-end-to-end-version-paths"


class DifferenceCause(str, Enum):
    """Classify only causes established by the retained controls."""

    OBJECTIVE_SEMANTICS = "objective-semantics"
    SCENARIO_REALIZATION = "scenario-realization"
    PROTOCOL_SUPPORT_DIRECTION = "protocol-support-direction"
    FIXED_DEPLOYMENT = "fixed-deployment"
    COMBINED_NOT_ISOLATED = "combined-not-isolated"


@dataclass(frozen=True, slots=True)
class ScalarVersionComparison:
    """Expose both raw scalar values before their unsigned absolute delta."""

    v1_value: float
    v2_value: float

    @property
    def absolute_delta(self) -> float:
        """Return the absolute difference between the retained scalar values."""

        return abs(self.v2_value - self.v1_value)

    def __post_init__(self) -> None:
        for name in ("v1_value", "v2_value", "absolute_delta"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be a real number")
            if not isfinite(value):
                raise ValueError(f"{name} must be finite")


def _scalar(v1_value: float, v2_value: float) -> ScalarVersionComparison:
    return ScalarVersionComparison(
        v1_value,
        v2_value,
    )


@dataclass(frozen=True, slots=True)
class ScenarioDecisionSnapshot:
    """Retain raw operational outputs from one authoritative Stage-2 run."""

    scenario_id: str
    routing_fractions: Mapping[tuple[str, str, str], float]
    unmet_fractions: Mapping[str, float]
    independently_feasible: bool

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "routing_fractions",
            MappingProxyType(dict(self.routing_fractions)),
        )
        object.__setattr__(
            self,
            "unmet_fractions",
            MappingProxyType(dict(self.unmet_fractions)),
        )


@dataclass(frozen=True, slots=True)
class Stage2MetricComparison:
    """Compare one pair of successful independently validated Stage-2 runs."""

    c3: ScalarVersionComparison
    c4: ScalarVersionComparison
    c5: ScalarVersionComparison
    operational_objective: ScalarVersionComparison
    reporting_total: ScalarVersionComparison
    v1_decision: ScenarioDecisionSnapshot
    v2_decision: ScenarioDecisionSnapshot


@dataclass(frozen=True, slots=True)
class AggregateMetricComparison:
    """Compare authoritative aggregate values without recomputing them."""

    expected_total_cost: ScalarVersionComparison
    mean_c3: ScalarVersionComparison
    mean_c4: ScalarVersionComparison
    mean_c5: ScalarVersionComparison
    mean_operational_cost: ScalarVersionComparison
    mean_reporting_cost: ScalarVersionComparison
    violation_rate: ScalarVersionComparison
    v1_decisions: tuple[ScenarioDecisionSnapshot, ...]
    v2_decisions: tuple[ScenarioDecisionSnapshot, ...]

    @property
    def v1_scenario_count(self) -> int:
        """Return the number of retained v1 scenario decisions."""

        return len(self.v1_decisions)

    @property
    def v2_scenario_count(self) -> int:
        """Return the number of retained v2 scenario decisions."""

        return len(self.v2_decisions)

    def __post_init__(self) -> None:
        object.__setattr__(self, "v1_decisions", tuple(self.v1_decisions))
        object.__setattr__(self, "v2_decisions", tuple(self.v2_decisions))
        if not self.v1_decisions or not self.v2_decisions:
            raise ValueError("both versions require non-empty scenario decisions")


@dataclass(frozen=True, slots=True)
class ProtocolQuantityComparison:
    """Expose audited direction, executable support, and realized factors."""

    quantity: ScenarioQuantity
    v1_direction: PerturbationDirection
    v2_direction: PerturbationDirection
    v1_executable_support: tuple[float, float]
    v2_executable_support: tuple[float, float]
    v1_realized_factors: tuple[float, ...]
    v2_realized_factors: tuple[float, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "v1_executable_support", tuple(self.v1_executable_support)
        )
        object.__setattr__(
            self, "v2_executable_support", tuple(self.v2_executable_support)
        )
        object.__setattr__(
            self, "v1_realized_factors", tuple(self.v1_realized_factors)
        )
        object.__setattr__(
            self, "v2_realized_factors", tuple(self.v2_realized_factors)
        )


@dataclass(frozen=True, slots=True)
class ProtocolComparisonEvidence:
    """Retain exact generated records and explicit policy provenance."""

    v1_protocol: ScenarioProtocolSpec
    v2_protocol: ScenarioProtocolSpec
    v1_policy: ExecutableScenarioSamplingPolicy
    v2_policy: ExecutableScenarioSamplingPolicy
    v1_generated_records: tuple[GeneratedScenarioRecord, ...]
    v2_generated_records: tuple[GeneratedScenarioRecord, ...]
    quantity_comparisons: tuple[ProtocolQuantityComparison, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "v1_generated_records", tuple(self.v1_generated_records)
        )
        object.__setattr__(
            self, "v2_generated_records", tuple(self.v2_generated_records)
        )
        object.__setattr__(
            self, "quantity_comparisons", tuple(self.quantity_comparisons)
        )

@dataclass(frozen=True, slots=True)
class ComparisonControls:
    """State which possible causes were actually held fixed."""

    nominal_problem_same_identity: bool
    fixed_deployment_equivalent: bool
    realized_scenarios_same_identity: bool
    common_stage2_objective_version: PaperVersion | None
    description: str

ComparisonEvidence: TypeAlias = (
    Stage1Stage2EvaluationResult
    | MultiScenarioEvaluationResult
    | BoundedScenarioExperimentRecord
)


@dataclass(frozen=True, slots=True)
class VersionComparisonRecord:
    """Package raw versioned evidence, controls, metrics, and justified causes."""

    axis: VersionComparisonAxis
    v1_evidence: ComparisonEvidence
    v2_evidence: ComparisonEvidence
    controls: ComparisonControls
    causes: tuple[DifferenceCause, ...]
    stage2_metrics: Stage2MetricComparison | None = None
    aggregate_metrics: AggregateMetricComparison | None = None
    protocol_evidence: ProtocolComparisonEvidence | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "causes", tuple(self.causes))

def _require_successful_stage2(
    result: Stage1Stage2EvaluationResult,
    expected_version: PaperVersion | None = None,
) -> None:
    if not isinstance(result, Stage1Stage2EvaluationResult):
        raise TypeError("comparison input must be Stage1Stage2EvaluationResult")
    if not result.successful or result.stage2_run_record is None:
        raise ValueError("comparison requires a successful Stage-2 evaluation")
    if expected_version is not None and result.paper_version is not expected_version:
        raise ValueError("Stage-2 evaluation has the wrong paper version")


def _decision_snapshot(
    result: Stage1Stage2EvaluationResult,
) -> ScenarioDecisionSnapshot:
    record = result.stage2_run_record
    solution = record.solution
    return ScenarioDecisionSnapshot(
        result.realized_scenario.id,
        solution.routing_fractions,
        solution.unmet_fractions,
        True,
    )


def _stage2_metric_comparison(
    v1: Stage1Stage2EvaluationResult,
    v2: Stage1Stage2EvaluationResult,
) -> Stage2MetricComparison:
    left = v1.stage2_run_record.scientific_evidence.objective_breakdown
    right = v2.stage2_run_record.scientific_evidence.objective_breakdown
    return Stage2MetricComparison(
        c3=_scalar(left.realized_data_storage_cost, right.realized_data_storage_cost),
        c4=_scalar(left.delay_penalty, right.delay_penalty),
        c5=_scalar(left.unmet_demand_penalty, right.unmet_demand_penalty),
        operational_objective=_scalar(
            left.operational_objective, right.operational_objective
        ),
        reporting_total=_scalar(
            left.reported_variable_cost, right.reported_variable_cost
        ),
        v1_decision=_decision_snapshot(v1),
        v2_decision=_decision_snapshot(v2),
    )


def _require_successful_batch(result: MultiScenarioEvaluationResult) -> None:
    if not isinstance(result, MultiScenarioEvaluationResult):
        raise TypeError("comparison input must be MultiScenarioEvaluationResult")
    if not result.successful or result.aggregate is None:
        raise ValueError("comparison requires a successful complete batch")


def _batch_decisions(
    result: MultiScenarioEvaluationResult,
) -> tuple[ScenarioDecisionSnapshot, ...]:
    return tuple(_decision_snapshot(item.evaluation_result) for item in result.per_scenario)


def _aggregate_metric_comparison(
    v1: MultiScenarioEvaluationResult,
    v2: MultiScenarioEvaluationResult,
) -> AggregateMetricComparison:
    left = v1.aggregate
    right = v2.aggregate
    return AggregateMetricComparison(
        _scalar(left.expected_total_cost, right.expected_total_cost),
        _scalar(left.mean_c3, right.mean_c3),
        _scalar(left.mean_c4, right.mean_c4),
        _scalar(left.mean_c5, right.mean_c5),
        _scalar(left.mean_operational_cost, right.mean_operational_cost),
        _scalar(left.mean_reporting_cost, right.mean_reporting_cost),
        _scalar(left.violation_rate, right.violation_rate),
        _batch_decisions(v1),
        _batch_decisions(v2),
    )


def _protocol_quantity(
    protocol: ScenarioProtocolSpec,
    quantity: ScenarioQuantity,
) -> PerturbationSpecification:
    matches = tuple(item for item in protocol.perturbations if item.quantity is quantity)
    if len(matches) != 1:
        raise ValueError(f"protocol must contain one {quantity.value} item")
    return matches[0]


def _policy_quantity(
    policy: ExecutableScenarioSamplingPolicy,
    quantity: ScenarioQuantity,
) -> QuantitySamplingPolicy:
    item = {
        ScenarioQuantity.ARRIVAL_RATE: policy.arrival,
        ScenarioQuantity.DELAY_COEFFICIENT: policy.delay,
        ScenarioQuantity.EFFECTIVE_ERROR: policy.effective_error,
    }[quantity]
    if item is None or item.relative_bounds is None or item.direction is None:
        raise ValueError("comparison requires complete executable quantity policies")
    return item


def _realized_factors(
    records: tuple[GeneratedScenarioRecord, ...],
    quantity: ScenarioQuantity,
) -> tuple[float, ...]:
    draws: tuple[QuantityDrawEvidence, ...] = tuple(
        draw
        for record in records
        for draw in record.evidence.draws
        if draw.quantity is quantity
    )
    if not draws:
        raise ValueError(f"generated evidence has no {quantity.value} draws")
    return tuple(value for draw in draws for _, value in draw.relative_factors)


def _explicit_records(
    records: Sequence[GeneratedScenarioRecord],
) -> tuple[GeneratedScenarioRecord, ...]:
    if isinstance(records, (str, bytes)) or not isinstance(records, Sequence):
        raise TypeError("generated records must be an ordered sequence")
    result = tuple(records)
    if not result or any(not isinstance(item, GeneratedScenarioRecord) for item in result):
        raise ValueError("generated records must be non-empty and complete")
    return result


def _protocol_comparison_evidence(
    v1_records: Sequence[GeneratedScenarioRecord],
    v2_records: Sequence[GeneratedScenarioRecord],
) -> ProtocolComparisonEvidence:
    left = _explicit_records(v1_records)
    right = _explicit_records(v2_records)
    v1_protocol = left[0].evidence.protocol
    v2_protocol = right[0].evidence.protocol
    v1_policy = left[0].evidence.sampling_policy
    v2_policy = right[0].evidence.sampling_policy
    for records, protocol, policy, version in (
        (left, v1_protocol, v1_policy, PaperVersion.V1),
        (right, v2_protocol, v2_policy, PaperVersion.V2),
    ):
        if protocol.paper_version is not version or policy.paper_version is not version:
            raise ValueError(f"{version.value} protocol and policy must retain their version")
        if any(
            record.evidence.protocol is not protocol
            or record.evidence.sampling_policy is not policy
            for record in records
        ):
            raise ValueError("generated records must retain one exact protocol and policy")
    quantities = tuple(
        ProtocolQuantityComparison(
            quantity,
            _protocol_quantity(v1_protocol, quantity).direction,
            _protocol_quantity(v2_protocol, quantity).direction,
            _policy_quantity(v1_policy, quantity).relative_bounds,
            _policy_quantity(v2_policy, quantity).relative_bounds,
            _realized_factors(left, quantity),
            _realized_factors(right, quantity),
        )
        for quantity in ScenarioQuantity
    )
    return ProtocolComparisonEvidence(
        v1_protocol,
        v2_protocol,
        v1_policy,
        v2_policy,
        left,
        right,
        quantities,
    )


def _fixed_from_batch(result: MultiScenarioEvaluationResult) -> Stage2FixedDeployment:
    _require_successful_batch(result)
    return result.per_scenario[0].fixed_deployment


def _require_generated_batch_chain(
    records: tuple[GeneratedScenarioRecord, ...],
    batch: MultiScenarioEvaluationResult,
) -> None:
    if len(records) != len(batch.realized_scenarios) or any(
        record.realized_scenario is not scenario
        for record, scenario in zip(records, batch.realized_scenarios, strict=True)
    ):
        raise ValueError("batch must evaluate the exact generated scenario sequence")


def compare_objective_semantics(
    v1_evaluation: Stage1Stage2EvaluationResult,
    v2_evaluation: Stage1Stage2EvaluationResult,
) -> VersionComparisonRecord:
    """Isolate versioned objective semantics under identical scientific inputs."""

    _require_successful_stage2(v1_evaluation, PaperVersion.V1)
    _require_successful_stage2(v2_evaluation, PaperVersion.V2)
    if v1_evaluation.pdm_problem_data is not v2_evaluation.pdm_problem_data:
        raise ValueError("objective-only comparison requires identical nominal data")
    if v1_evaluation.realized_scenario is not v2_evaluation.realized_scenario:
        raise ValueError("objective-only comparison requires the identical scenario object")
    if v1_evaluation.fixed_deployment != v2_evaluation.fixed_deployment:
        raise ValueError("objective-only comparison requires equivalent fixed deployment")
    return VersionComparisonRecord(
        VersionComparisonAxis.OBJECTIVE_SEMANTICS,
        v1_evaluation,
        v2_evaluation,
        ComparisonControls(
            True,
            True,
            True,
            None,
            (
                "Nominal data, explicit realized scenario, and fixed deployment "
                "content are controlled; only versioned objective semantics differ."
            ),
        ),
        (DifferenceCause.OBJECTIVE_SEMANTICS,),
        stage2_metrics=_stage2_metric_comparison(v1_evaluation, v2_evaluation),
    )


def compare_protocol_semantics(
    v1_generated_records: Sequence[GeneratedScenarioRecord],
    v2_generated_records: Sequence[GeneratedScenarioRecord],
    v1_control_evaluation: MultiScenarioEvaluationResult,
    v2_control_evaluation: MultiScenarioEvaluationResult,
) -> VersionComparisonRecord:
    """Isolate generated-scenario effects under one common objective/source."""

    protocol = _protocol_comparison_evidence(
        v1_generated_records, v2_generated_records
    )
    by_quantity = {
        item.quantity: item for item in protocol.quantity_comparisons
    }
    for quantity in (
        ScenarioQuantity.DELAY_COEFFICIENT,
        ScenarioQuantity.EFFECTIVE_ERROR,
    ):
        item = by_quantity[quantity]
        if (
            item.v1_direction is not PerturbationDirection.SYMMETRIC
            or item.v2_direction is not PerturbationDirection.ADVERSE_ONLY
        ):
            raise ValueError(
                "protocol comparison requires the audited v1/v2 direction difference"
            )
    left = protocol.v1_generated_records
    right = protocol.v2_generated_records
    _require_successful_batch(v1_control_evaluation)
    _require_successful_batch(v2_control_evaluation)
    _require_generated_batch_chain(left, v1_control_evaluation)
    _require_generated_batch_chain(right, v2_control_evaluation)
    if v1_control_evaluation.pdm_problem_data is not v2_control_evaluation.pdm_problem_data:
        raise ValueError("protocol comparison requires identical nominal data")
    if v1_control_evaluation.source_result is not v2_control_evaluation.source_result:
        raise ValueError("protocol comparison requires one common Stage-1 source")
    if v1_control_evaluation.paper_version is not v2_control_evaluation.paper_version:
        raise ValueError("protocol comparison requires one common objective version")
    fixed_equal = _fixed_from_batch(v1_control_evaluation) == _fixed_from_batch(
        v2_control_evaluation
    )
    if not fixed_equal:
        raise ValueError("protocol comparison requires equivalent fixed deployment")
    if any(
        record.evidence.nominal_problem_data
        is not v1_control_evaluation.pdm_problem_data
        for record in left + right
    ):
        raise ValueError("generation and evaluation must share nominal data identity")
    scenarios_same_identity = len(left) == len(right) and all(
        a.realized_scenario is b.realized_scenario
        for a, b in zip(left, right, strict=True)
    )
    scenarios_same_value = len(left) == len(right) and all(
        a.realized_scenario == b.realized_scenario
        for a, b in zip(left, right, strict=True)
    )
    causes = [DifferenceCause.PROTOCOL_SUPPORT_DIRECTION]
    if not scenarios_same_value:
        causes.append(DifferenceCause.SCENARIO_REALIZATION)
    return VersionComparisonRecord(
        VersionComparisonAxis.PROTOCOL_SEMANTICS,
        v1_control_evaluation,
        v2_control_evaluation,
        ComparisonControls(
            True,
            True,
            scenarios_same_identity,
            v1_control_evaluation.paper_version,
            (
                "Both generated sequences are evaluated with the same accepted "
                "Stage-1 source and Stage-2 objective version; seed equality is "
                "not used as a matching criterion."
            ),
        ),
        tuple(causes),
        aggregate_metrics=_aggregate_metric_comparison(
            v1_control_evaluation, v2_control_evaluation
        ),
        protocol_evidence=protocol,
    )


def compare_bounded_version_paths(
    v1_record: BoundedScenarioExperimentRecord,
    v2_record: BoundedScenarioExperimentRecord,
) -> VersionComparisonRecord:
    """Compare native bounded paths while marking their deltas non-isolated."""

    if not isinstance(v1_record, BoundedScenarioExperimentRecord) or not isinstance(
        v2_record, BoundedScenarioExperimentRecord
    ):
        raise TypeError("bounded comparison requires bounded experiment records")
    if not v1_record.successful or v1_record.evaluation_result is None:
        raise ValueError("v1 bounded record must be successful")
    if not v2_record.successful or v2_record.evaluation_result is None:
        raise ValueError("v2 bounded record must be successful")
    if v1_record.paper_version is not PaperVersion.V1:
        raise ValueError("left bounded path must be v1")
    if v2_record.paper_version is not PaperVersion.V2:
        raise ValueError("right bounded path must be v2")
    if v1_record.nominal_problem_data is not v2_record.nominal_problem_data:
        raise ValueError("end-to-end comparison requires identical nominal data")
    protocol = _protocol_comparison_evidence(
        v1_record.generated_records,
        v2_record.generated_records,
    )
    left = v1_record.evaluation_result
    right = v2_record.evaluation_result
    fixed_equal = _fixed_from_batch(left) == _fixed_from_batch(right)
    scenarios_same_identity = (
        len(left.realized_scenarios) == len(right.realized_scenarios)
        and all(
            a is b
            for a, b in zip(
                left.realized_scenarios,
                right.realized_scenarios,
                strict=True,
            )
        )
    )
    scenarios_same_value = (
        len(left.realized_scenarios) == len(right.realized_scenarios)
        and all(
            a == b
            for a, b in zip(
                left.realized_scenarios,
                right.realized_scenarios,
                strict=True,
            )
        )
    )
    causes = [
        DifferenceCause.OBJECTIVE_SEMANTICS,
        DifferenceCause.PROTOCOL_SUPPORT_DIRECTION,
    ]
    if not scenarios_same_value:
        causes.append(DifferenceCause.SCENARIO_REALIZATION)
    if not fixed_equal:
        causes.append(DifferenceCause.FIXED_DEPLOYMENT)
    causes.append(DifferenceCause.COMBINED_NOT_ISOLATED)
    return VersionComparisonRecord(
        VersionComparisonAxis.COMBINED_END_TO_END,
        v1_record,
        v2_record,
        ComparisonControls(
            True,
            fixed_equal,
            scenarios_same_identity,
            None,
            (
                "Each bounded path retains its native protocol, policy, accepted "
                "Stage-1 source, and objective version; resulting metric deltas "
                "combine every changed dimension listed in causes."
            ),
        ),
        tuple(causes),
        aggregate_metrics=_aggregate_metric_comparison(left, right),
        protocol_evidence=protocol,
    )
