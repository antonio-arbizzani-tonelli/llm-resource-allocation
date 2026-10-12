"""Deterministic evaluation and aggregation over explicit Stage-2 scenarios.

This module owns no sampling and no Stage-1 execution.  It preserves caller
order, delegates each supplied realization exactly once to the established
single-scenario integration authority, and aggregates only a wholly successful
batch.  Stage 2 continues to optimize C4+C5; realized C3 is reporting-only
under D-0067.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from math import fsum
from typing import TypeAlias

from llm_resource_allocation.math.objective import (
    PaperVersion,
    compute_gpu_rental_cost,
    compute_model_storage_cost,
)
from llm_resource_allocation.optimization.extraction import (
    SolutionNormalizationTolerances,
)
from llm_resource_allocation.optimization.problem_data import PdmProblemData
from llm_resource_allocation.optimization.solver import SolverConfig
from llm_resource_allocation.optimization.stage2_adapter import Stage1Result
from llm_resource_allocation.optimization.stage2_integration import (
    Stage1Stage2EvaluationResult,
    Stage1Stage2EvaluationStatus,
    _evaluate_prepared_stage2_source,
    _prepare_stage2_source,
)
from llm_resource_allocation.optimization.stage2_problem_data import (
    Stage2FixedDeployment,
    Stage2RealizedScenario,
)
from llm_resource_allocation.optimization.stage2_run import Stage2RunStatus
from llm_resource_allocation.validation.stage2 import (
    Stage2ObjectiveBreakdown,
    Stage2ValidationReport,
    Stage2ValidationTolerances,
)


UNMET_FRACTION_VIOLATION_THRESHOLD = 0.01


class MultiScenarioEvaluationStatus(str, Enum):
    """Classify whether every supplied scenario completed successfully."""

    SUCCESS = "success"
    SCENARIO_EVALUATION_FAILED = "scenario_evaluation_failed"


@dataclass(frozen=True, slots=True)
class PerScenarioEvaluationEvidence:
    """Retain one input scenario and its exact integrated evaluation record."""

    scenario_index: int
    realized_scenario: Stage2RealizedScenario
    evaluation_result: Stage1Stage2EvaluationResult

    @property
    def successful(self) -> bool:
        return self.evaluation_result.successful

    @property
    def integrated_status(self) -> Stage1Stage2EvaluationStatus:
        return self.evaluation_result.status

    @property
    def stage2_status(self) -> Stage2RunStatus | None:
        record = self.evaluation_result.stage2_run_record
        return None if record is None else record.status

    @property
    def objective_breakdown(self) -> Stage2ObjectiveBreakdown | None:
        record = self.evaluation_result.stage2_run_record
        if record is None:
            return None
        return record.scientific_evidence.objective_breakdown

    @property
    def c3(self) -> float | None:
        breakdown = self.objective_breakdown
        return None if breakdown is None else breakdown.realized_data_storage_cost

    @property
    def c4(self) -> float | None:
        breakdown = self.objective_breakdown
        return None if breakdown is None else breakdown.delay_penalty

    @property
    def c5(self) -> float | None:
        breakdown = self.objective_breakdown
        return None if breakdown is None else breakdown.unmet_demand_penalty

    @property
    def operational_cost(self) -> float | None:
        breakdown = self.objective_breakdown
        return None if breakdown is None else breakdown.operational_objective

    @property
    def reporting_contribution(self) -> float | None:
        breakdown = self.objective_breakdown
        return None if breakdown is None else breakdown.reported_variable_cost

    @property
    def unmet_fractions(self) -> Mapping[str, float] | None:
        """Forward the immutable normalized per-query ``u`` mapping, if any."""

        record = self.evaluation_result.stage2_run_record
        if record is None or record.solution is None:
            return None
        return record.solution.unmet_fractions

    @property
    def independent_validation_report(self) -> Stage2ValidationReport | None:
        record = self.evaluation_result.stage2_run_record
        if record is None:
            return None
        return record.scientific_evidence.validation_report

    @property
    def independently_feasible(self) -> bool | None:
        record = self.evaluation_result.stage2_run_record
        return None if record is None else record.independently_feasible

    @property
    def fixed_deployment(self) -> Stage2FixedDeployment | None:
        return self.evaluation_result.fixed_deployment


@dataclass(frozen=True, slots=True)
class MultiScenarioAggregate:
    """Expose deterministic and scenario-mean cost terms without reweighting."""

    deterministic_c1: float
    deterministic_c2: float
    mean_c3: float
    mean_c4: float
    mean_c5: float
    violation_threshold: float
    violation_count: int
    scenario_query_pair_count: int

    def __post_init__(self) -> None:
        if (
            isinstance(self.scenario_query_pair_count, bool)
            or not isinstance(self.scenario_query_pair_count, int)
            or self.scenario_query_pair_count <= 0
        ):
            raise ValueError("scenario_query_pair_count must be positive")
        if (
            isinstance(self.violation_count, bool)
            or not isinstance(self.violation_count, int)
            or not 0 <= self.violation_count <= self.scenario_query_pair_count
        ):
            raise ValueError("violation_count must be within the pair count")

    @property
    def deterministic_stage1_cost(self) -> float:
        return self.deterministic_c1 + self.deterministic_c2

    @property
    def mean_operational_cost(self) -> float:
        """Return mean C4+C5, retaining C4's seconds/milliseconds mismatch."""

        return self.mean_c4 + self.mean_c5

    @property
    def mean_reporting_cost(self) -> float:
        """Return mean C3+C4+C5 with the printed C3/C4 unit ambiguities.

        No implicit unit correction is applied; consistent USD is unresolved.
        """

        return self.mean_c3 + self.mean_operational_cost

    @property
    def expected_total_cost(self) -> float:
        """Return C1+C2+mean(C3+C4+C5) under the printed reporting convention.

        Unit caveat: retain C3's horizon/rate ambiguity and C4's
        seconds/milliseconds mismatch; a consistent USD total is unresolved.
        """

        return self.deterministic_stage1_cost + self.mean_reporting_cost

    @property
    def violation_rate(self) -> float:
        return self.violation_count / self.scenario_query_pair_count

    @property
    def mean_realized_data_storage_cost(self) -> float:
        return self.mean_c3

    @property
    def mean_delay_penalty(self) -> float:
        return self.mean_c4

    @property
    def mean_unmet_demand_penalty(self) -> float:
        return self.mean_c5

    @property
    def mean_realized_c3(self) -> float:
        return self.mean_c3

    @property
    def mean_realized_c4(self) -> float:
        return self.mean_c4

    @property
    def mean_realized_c5(self) -> float:
        return self.mean_c5

    @property
    def mean_realized_operational_cost(self) -> float:
        return self.mean_operational_cost

    @property
    def mean_realized_reporting_cost(self) -> float:
        return self.mean_reporting_cost


@dataclass(frozen=True, slots=True)
class MultiScenarioEvaluationFailure:
    """Identify one supplied scenario whose integrated evaluation failed."""

    scenario_index: int
    realized_scenario: Stage2RealizedScenario
    evaluation_result: Stage1Stage2EvaluationResult

@dataclass(frozen=True, slots=True)
class MultiScenarioEvaluationResult:
    """Retain a complete ordered batch and either its aggregate or failures."""

    source_result: Stage1Result
    pdm_problem_data: PdmProblemData
    realized_scenarios: tuple[Stage2RealizedScenario, ...]
    paper_version: PaperVersion
    status: MultiScenarioEvaluationStatus
    per_scenario: tuple[PerScenarioEvaluationEvidence, ...]
    aggregate: MultiScenarioAggregate | None = None
    failures: tuple[MultiScenarioEvaluationFailure, ...] = ()

    def __post_init__(self) -> None:
        """Freeze batch evidence without replaying the evaluator's traversal."""

        object.__setattr__(self, "realized_scenarios", tuple(self.realized_scenarios))
        object.__setattr__(self, "per_scenario", tuple(self.per_scenario))
        object.__setattr__(self, "failures", tuple(self.failures))

    @property
    def successful(self) -> bool:
        return self.status is MultiScenarioEvaluationStatus.SUCCESS


_ScenarioCosts: TypeAlias = tuple[float, float, float]


def is_unmet_fraction_violation(unmet_fraction: float) -> bool:
    """Apply the paper protocol's strict ``u_i > 0.01`` classification."""

    return unmet_fraction > UNMET_FRACTION_VIOLATION_THRESHOLD


def _explicit_scenario_tuple(
    realized_scenarios: Sequence[Stage2RealizedScenario],
) -> tuple[Stage2RealizedScenario, ...]:
    if isinstance(realized_scenarios, (str, bytes)) or not isinstance(
        realized_scenarios, Sequence
    ):
        raise TypeError("realized_scenarios must be an ordered sequence")
    scenarios = tuple(realized_scenarios)
    if not scenarios:
        raise ValueError("realized_scenarios must be non-empty")
    if not all(isinstance(item, Stage2RealizedScenario) for item in scenarios):
        raise TypeError("every item must be a Stage2RealizedScenario")
    return scenarios


def _successful_costs(
    evidence: PerScenarioEvaluationEvidence,
) -> _ScenarioCosts:
    breakdown = evidence.objective_breakdown
    return (
        breakdown.realized_data_storage_cost,
        breakdown.delay_penalty,
        breakdown.unmet_demand_penalty,
    )


def _aggregate_successes(
    pdm_problem_data: PdmProblemData,
    per_scenario: tuple[PerScenarioEvaluationEvidence, ...],
) -> MultiScenarioAggregate:
    first_fixed = per_scenario[0].fixed_deployment
    c1 = compute_gpu_rental_cost(
        pdm_problem_data.instance,
        first_fixed.gpu_counts,
    )
    c2 = compute_model_storage_cost(
        pdm_problem_data.instance,
        first_fixed.admission_indicators,
    )
    scenario_costs = tuple(_successful_costs(item) for item in per_scenario)
    scenario_count = len(scenario_costs)
    mean_c3 = fsum(item[0] for item in scenario_costs) / scenario_count
    mean_c4 = fsum(item[1] for item in scenario_costs) / scenario_count
    mean_c5 = fsum(item[2] for item in scenario_costs) / scenario_count

    unmet_values = tuple(
        unmet
        for item in per_scenario
        for unmet in (
            () if item.unmet_fractions is None else item.unmet_fractions.values()
        )
    )
    pair_count = len(unmet_values)
    violation_count = sum(is_unmet_fraction_violation(item) for item in unmet_values)
    return MultiScenarioAggregate(
        deterministic_c1=c1,
        deterministic_c2=c2,
        mean_c3=mean_c3,
        mean_c4=mean_c4,
        mean_c5=mean_c5,
        violation_threshold=UNMET_FRACTION_VIOLATION_THRESHOLD,
        violation_count=violation_count,
        scenario_query_pair_count=pair_count,
    )


def evaluate_stage1_result_over_scenarios(
    stage1_result: Stage1Result,
    pdm_problem_data: PdmProblemData,
    realized_scenarios: Sequence[Stage2RealizedScenario],
    *,
    paper_version: PaperVersion = PaperVersion.V2,
    solver_config: SolverConfig | None = None,
    normalization_tolerances: SolutionNormalizationTolerances | None = None,
    validation_tolerances: Stage2ValidationTolerances | None = None,
) -> MultiScenarioEvaluationResult:
    """Evaluate one fixed accepted Stage-1 result over explicit scenarios.

    Every input scenario is evaluated exactly once in caller order.  A failed
    scenario does not suppress evaluation evidence for later supplied scenarios,
    but any failure suppresses the whole-batch aggregate.
    """

    if not isinstance(pdm_problem_data, PdmProblemData):
        raise TypeError("pdm_problem_data must be a PdmProblemData")
    if not isinstance(paper_version, PaperVersion):
        raise TypeError("paper_version must be PaperVersion.V1 or V2")
    scenarios = _explicit_scenario_tuple(realized_scenarios)
    prepared = _prepare_stage2_source(stage1_result, pdm_problem_data, paper_version)

    evidence_items: list[PerScenarioEvaluationEvidence] = []
    failures: list[MultiScenarioEvaluationFailure] = []
    for index, scenario in enumerate(scenarios):
        evaluation = _evaluate_prepared_stage2_source(
            prepared,
            scenario,
            solver_config=solver_config,
            normalization_tolerances=normalization_tolerances,
            validation_tolerances=validation_tolerances,
        )
        evidence = PerScenarioEvaluationEvidence(index, scenario, evaluation)
        evidence_items.append(evidence)
        if not evaluation.successful:
            failures.append(
                MultiScenarioEvaluationFailure(index, scenario, evaluation)
            )

    per_scenario = tuple(evidence_items)
    if failures:
        return MultiScenarioEvaluationResult(
            source_result=stage1_result,
            pdm_problem_data=pdm_problem_data,
            realized_scenarios=scenarios,
            paper_version=paper_version,
            status=MultiScenarioEvaluationStatus.SCENARIO_EVALUATION_FAILED,
            per_scenario=per_scenario,
            failures=tuple(failures),
        )

    return MultiScenarioEvaluationResult(
        source_result=stage1_result,
        pdm_problem_data=pdm_problem_data,
        realized_scenarios=scenarios,
        paper_version=paper_version,
        status=MultiScenarioEvaluationStatus.SUCCESS,
        per_scenario=per_scenario,
        aggregate=_aggregate_successes(pdm_problem_data, per_scenario),
    )
