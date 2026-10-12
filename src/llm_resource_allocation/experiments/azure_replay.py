"""Replay real diurnal multipliers on an explicitly synthetic instance (D-0089).

The unchanged reference algorithms and Stage-2 LP remain the scientific
authorities. EWMA timing and keep-best comparison are declared project choices,
not recovered Azure-paper calibration. Costs retain the instance's horizon and
are model scores, not 24-hour billing estimates.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from enum import Enum
from math import fsum, isfinite
from numbers import Real
from time import perf_counter

from llm_resource_allocation.algorithms.agh import AGHResult, run_agh
from llm_resource_allocation.algorithms.gh import GHResult, run_gh
from llm_resource_allocation.algorithms.gh_phase1 import GHPhase1Config
from llm_resource_allocation.data.tiny_instances import make_heterogeneous_tiny_instance
from llm_resource_allocation.domain import ProblemInstance
from llm_resource_allocation.experiments.scenario_evaluation import is_unmet_fraction_violation
from llm_resource_allocation.math.error import compute_effective_error
from llm_resource_allocation.math.objective import (
    PaperVersion, compute_gpu_rental_cost, compute_model_storage_cost,
)
from llm_resource_allocation.optimization.pdm_run import (
    PdmRunRecord, execute_and_record_pdm_run,
)
from llm_resource_allocation.optimization.problem_data import PdmProblemData
from llm_resource_allocation.optimization.solver import SolverConfig
from llm_resource_allocation.optimization.stage2_adapter import (
    Stage1Method, Stage1ToStage2DeploymentEvidence,
    stage2_fixed_deployment_from_stage1,
)
from llm_resource_allocation.optimization.stage2_integration import (
    Stage1Stage2EvaluationResult, _PreparedStage2Source,
    _evaluate_prepared_stage2_source,
)
from llm_resource_allocation.optimization.stage2_problem_data import Stage2RealizedScenario


class AzureReplayVariant(str, Enum):
    """Select a mean-demand static source or causal rolling keep-best sources."""

    STATIC = "static"
    ROLLING = "rolling"


class ReplaySelection(str, Enum):
    """Retain the reason a source was kept, replaced, or unavailable."""

    STATIC_SOURCE = "static_source"
    INITIAL_CANDIDATE = "initial_candidate"
    STRICT_IMPROVEMENT = "strict_improvement"
    INCUMBENT_FORECAST_FAILED = "incumbent_forecast_failed"
    KEEP_INCUMBENT = "keep_incumbent"
    NO_ACCEPTED_SOURCE = "no_accepted_source"


def _nonnegative_real(value: float, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, Real) or not isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a finite non-negative real number")


@dataclass(frozen=True, slots=True)
class AzureReplayWindow:
    """Carry one explicit real-trace multiplier and its original day-bin index."""

    window_index: int
    realized_multiplier: float
    request_count: int | None = None

    def __post_init__(self) -> None:
        if (isinstance(self.window_index, bool) or not isinstance(self.window_index, int)
                or not 0 <= self.window_index < 288):
            raise ValueError("window_index must be an integer in [0, 288)")
        _nonnegative_real(self.realized_multiplier, "realized_multiplier")
        if self.request_count is not None and (
            isinstance(self.request_count, bool) or not isinstance(self.request_count, int)
            or self.request_count < 0
        ):
            raise ValueError("request_count must be a non-negative integer or None")


@dataclass(frozen=True, slots=True)
class AzureReplayConfig:
    """Explicit assumed replay policy; every solver/scientific input is retained.

    AGH uses the same local seed for every construction, isolating forecast
    changes from changing random starts. The causal EWMA observes supplied
    windows only; a subset therefore remains an explicitly partial pilot.
    """

    method: Stage1Method
    variant: AzureReplayVariant
    ewma_alpha: float = 0.2
    initial_forecast_multiplier: float = 1.0
    random_seed: int = 37
    gh_budget_fraction: float = 0.8
    solver_config: SolverConfig = SolverConfig()
    paper_version: PaperVersion = PaperVersion.V2

    def __post_init__(self) -> None:
        if not isinstance(self.method, Stage1Method):
            raise TypeError("method must be a Stage1Method")
        if not isinstance(self.variant, AzureReplayVariant):
            raise TypeError("variant must be an AzureReplayVariant")
        _nonnegative_real(self.ewma_alpha, "ewma_alpha")
        if not 0 < self.ewma_alpha <= 1:
            raise ValueError("ewma_alpha must be in (0, 1]")
        _nonnegative_real(self.initial_forecast_multiplier, "initial_forecast_multiplier")
        if isinstance(self.random_seed, bool) or not isinstance(self.random_seed, int):
            raise ValueError("random_seed must be an integer")
        GHPhase1Config(self.gh_budget_fraction)
        if not isinstance(self.solver_config, SolverConfig):
            raise TypeError("solver_config must be a SolverConfig")
        if not isinstance(self.paper_version, PaperVersion):
            raise TypeError("paper_version must be a PaperVersion")


@dataclass(frozen=True, slots=True)
class AzureReplayFailure:
    """Preserve an experiment-boundary failure without guessing a cost."""

    boundary: str
    error_type: str
    message: str


@dataclass(frozen=True, slots=True)
class ReplayStage1Attempt:
    """Retain construction evidence and elapsed boundary time in seconds.

    Timing covers scaling, problem-data construction, the public runner and
    source-acceptance validation, including rejected outcomes.
    """

    construction_problem_data: PdmProblemData
    forecast_multiplier: float
    random_seed: int
    source_result: PdmRunRecord | GHResult | AGHResult | None
    failure: AzureReplayFailure | None = None
    elapsed_seconds: float = 0.0
    _adapter_evidence: Stage1ToStage2DeploymentEvidence | None = field(
        default=None, repr=False, compare=False
    )
    _fixed_model_cost: float | None = field(init=False, repr=False, compare=False)

    @property
    def accepted(self) -> bool:
        """Report whether source acceptance produced deployment evidence."""

        return self._adapter_evidence is not None

    def __post_init__(self) -> None:
        _nonnegative_real(self.elapsed_seconds, "elapsed_seconds")
        evidence = self._adapter_evidence
        fixed_cost = None
        if self.accepted:
            instance = self.construction_problem_data.instance
            fixed = evidence.fixed_deployment
            fixed_cost = (
                compute_gpu_rental_cost(instance, fixed.gpu_counts)
                + compute_model_storage_cost(instance, fixed.admission_indicators)
            )
        object.__setattr__(self, "_fixed_model_cost", fixed_cost)


@dataclass(frozen=True, slots=True)
class ReplaySourceEvaluation:
    """Retain Stage-2 integration, validation and elapsed boundary time.

    The elapsed seconds include unsuccessful integrated results and raised
    execution failures. Solver-only timing remains separate nested evidence.
    """

    source: ReplayStage1Attempt
    scenario: Stage2RealizedScenario
    evaluation_result: Stage1Stage2EvaluationResult | None
    failure: AzureReplayFailure | None = None
    elapsed_seconds: float = 0.0

    def __post_init__(self) -> None:
        _nonnegative_real(self.elapsed_seconds, "elapsed_seconds")

    @property
    def successful(self) -> bool:
        return self.evaluation_result is not None and self.evaluation_result.successful

    @property
    def full_model_cost(self) -> float | None:
        """Use independent C3-C5 and the existing fixed C1/C2 authorities."""

        if not self.successful:
            return None
        result = self.evaluation_result
        breakdown = result.stage2_run_record.scientific_evidence.objective_breakdown
        return self.source._fixed_model_cost + breakdown.reported_variable_cost


@dataclass(frozen=True, slots=True)
class ReplayQueryMetrics:
    """Report accepted operational fractions and the strict u>0.01 convention."""

    query_id: str
    arrival_rate_per_hour: float
    unmet_fraction: float

    @property
    def served_fraction(self) -> float:
        """Return the complement of the retained unmet fraction."""

        return 1.0 - self.unmet_fraction

    @property
    def violation(self) -> bool:
        """Classify the retained unmet fraction with the strict u>0.01 policy."""

        return is_unmet_fraction_violation(self.unmet_fraction)


@dataclass(frozen=True, slots=True)
class AzureReplayWindowResult:
    """Retain candidate/incumbent comparison and the exact operational record."""

    window: AzureReplayWindow
    forecast_multiplier: float
    next_forecast_multiplier: float
    forecast_scenario: Stage2RealizedScenario
    realized_scenario: Stage2RealizedScenario
    candidate: ReplayStage1Attempt | None
    incumbent_before: ReplayStage1Attempt | None
    candidate_forecast_evaluation: ReplaySourceEvaluation | None
    incumbent_forecast_evaluation: ReplaySourceEvaluation | None
    selected_source: ReplayStage1Attempt | None
    selection: ReplaySelection
    operation: ReplaySourceEvaluation | None
    query_metrics: tuple[ReplayQueryMetrics, ...]
    failure: AzureReplayFailure | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "query_metrics", tuple(self.query_metrics))

    @property
    def successful(self) -> bool:
        return self.operation is not None and self.operation.successful

    @property
    def model_cost(self) -> float | None:
        return None if self.operation is None else self.operation.full_model_cost


@dataclass(frozen=True, slots=True)
class AzureReplayAggregate:
    """Suppress every aggregate metric if any operational window failed."""

    window_count: int
    successful_window_count: int
    full_day: bool
    sum_window_model_cost: float | None
    scenario_query_pair_count: int | None
    violation_count: int | None

    @property
    def mean_window_model_cost(self) -> float | None:
        """Return the mean retained model score, or None for a failed batch."""

        if self.sum_window_model_cost is None:
            return None
        return self.sum_window_model_cost / self.window_count

    @property
    def violation_rate(self) -> float | None:
        """Return the fraction of scenario/query pairs violating the policy."""

        if self.violation_count is None or self.scenario_query_pair_count is None:
            return None
        return self.violation_count / self.scenario_query_pair_count


@dataclass(frozen=True, slots=True)
class AzureReplayResult:
    """Retain the synthetic base, declared configuration and ordered evidence."""

    nominal_problem_data: PdmProblemData
    config: AzureReplayConfig
    static_source: ReplayStage1Attempt | None
    windows: tuple[AzureReplayWindowResult, ...]
    aggregate: AzureReplayAggregate
    classification: str = "REAL_AZURE_TRACE_SYNTHETIC_INSTANCE_REPLAY"

    def __post_init__(self) -> None:
        object.__setattr__(self, "windows", tuple(self.windows))

    @property
    def successful(self) -> bool:
        return self.aggregate.successful_window_count == self.aggregate.window_count


def update_ewma_forecast(prior: float, observed: float, alpha: float) -> float:
    """Update after operation: next=alpha*observed+(1-alpha)*prior."""

    _nonnegative_real(prior, "prior")
    _nonnegative_real(observed, "observed")
    _nonnegative_real(alpha, "alpha")
    if not 0 < alpha <= 1:
        raise ValueError("alpha must be in (0, 1]")
    return alpha * observed + (1.0 - alpha) * prior


def scale_instance_arrivals(
    instance: ProblemInstance, multiplier: float, *, instance_id: str,
) -> ProblemInstance:
    """Copy only arrivals and identity; preserve tokens, coefficients and caps."""

    _nonnegative_real(multiplier, "multiplier")
    return replace(instance, id=instance_id, queries=tuple(
        replace(query, arrival_rate_per_hour=query.arrival_rate_per_hour * multiplier)
        for query in instance.queries
    ))


def make_replay_scenario(
    nominal_data: PdmProblemData, multiplier: float, scenario_id: str,
) -> Stage2RealizedScenario:
    """Scale every nominal arrival while retaining nominal delay/effective error."""

    _nonnegative_real(multiplier, "multiplier")
    instance = nominal_data.instance
    tiers = {tier.id: tier for tier in instance.gpu_tiers}
    return Stage2RealizedScenario(
        scenario_id,
        {query.id: query.arrival_rate_per_hour * multiplier for query in instance.queries},
        instance.compute_delay_seconds_per_token,
        instance.communication_delay_seconds_per_token,
        {key: compute_effective_error(instance.base_error_rate[key[:2]],
                                      tiers[key[2]].quantization_error_multiplier)
         for key in nominal_data.variable_lattices.route_keys},
    )


def should_replace_incumbent(
    candidate_score: float | None, incumbent_score: float | None,
) -> bool:
    """Replace on a successful strict improvement or failed incumbent forecast.

    None denotes an unsuccessful forecast evaluation. Exact ties preserve the
    incumbent. Neither tolerance classification nor rounding affects scores.
    """

    for name, score in (("candidate_score", candidate_score), ("incumbent_score", incumbent_score)):
        if score is not None:
            _nonnegative_real(score, name)
    return (candidate_score is not None
            and (incumbent_score is None or candidate_score < incumbent_score))


def _construct_source(
    nominal_data: PdmProblemData, multiplier: float, window_index: int,
    config: AzureReplayConfig,
) -> ReplayStage1Attempt:
    started = perf_counter()
    instance = scale_instance_arrivals(
        nominal_data.instance, multiplier,
        instance_id=f"{nominal_data.instance.id}.azure.{config.variant.value}.{window_index}",
    )
    data = PdmProblemData(instance)
    source = None
    try:
        if config.method is Stage1Method.P_DM:
            source = execute_and_record_pdm_run(data, config.solver_config, config.paper_version)
        elif config.method is Stage1Method.GH:
            source = run_gh(instance, GHPhase1Config(config.gh_budget_fraction),
                            paper_version=config.paper_version)
        else:
            source = run_agh(instance, GHPhase1Config(config.gh_budget_fraction),
                             random_seed=config.random_seed, paper_version=config.paper_version)
        adapter_evidence = stage2_fixed_deployment_from_stage1(source, data)
    except Exception as error:
        return ReplayStage1Attempt(data, multiplier, config.random_seed, source,
                                   AzureReplayFailure("stage1", type(error).__name__, str(error)),
                                   elapsed_seconds=perf_counter() - started)
    return ReplayStage1Attempt(data, multiplier, config.random_seed, source,
                               elapsed_seconds=perf_counter() - started,
                               _adapter_evidence=adapter_evidence)


def _evaluate_source(
    source: ReplayStage1Attempt, scenario: Stage2RealizedScenario, config: AzureReplayConfig,
) -> ReplaySourceEvaluation:
    started = perf_counter()
    try:
        prepared = _PreparedStage2Source(
            source.source_result, source.construction_problem_data,
            config.paper_version, source._adapter_evidence,
        )
        result = _evaluate_prepared_stage2_source(
            prepared, scenario, solver_config=config.solver_config,
        )
    except Exception as error:
        return ReplaySourceEvaluation(source, scenario, None,
                                      AzureReplayFailure("stage2", type(error).__name__, str(error)),
                                      elapsed_seconds=perf_counter() - started)
    failure = None if result.successful else AzureReplayFailure(
        "stage2", result.failure.error_type,
        f"{result.status.value}: {result.failure}",
    )
    return ReplaySourceEvaluation(source, scenario, result, failure,
                                  elapsed_seconds=perf_counter() - started)


def aggregate_replay_windows(
    windows: Sequence[AzureReplayWindowResult],
) -> AzureReplayAggregate:
    """Sum model scores only for wholly successful supplied windows."""

    if not windows:
        raise ValueError("at least one window is required")
    successful_count = sum(window.successful for window in windows)
    full_day = tuple(window.window.window_index for window in windows) == tuple(range(288))
    if successful_count != len(windows):
        return AzureReplayAggregate(len(windows), successful_count, full_day,
                                    None, None, None)
    total = fsum(window.model_cost for window in windows)
    pairs = sum(len(window.query_metrics) for window in windows)
    violations = sum(metric.violation for window in windows for metric in window.query_metrics)
    return AzureReplayAggregate(len(windows), successful_count, full_day,
                                total, pairs, violations)


def _query_metrics(operation: ReplaySourceEvaluation | None) -> tuple[ReplayQueryMetrics, ...]:
    if operation is None or not operation.successful:
        return ()
    solution = operation.evaluation_result.stage2_run_record.solution
    return tuple(ReplayQueryMetrics(
        query_id, operation.scenario.arrival_rates_per_hour[query_id],
        fraction,
    ) for query_id, fraction in solution.unmet_fractions.items())


def run_azure_replay(
    windows: Sequence[AzureReplayWindow], config: AzureReplayConfig, *,
    instance: ProblemInstance | None = None, progress: Callable[[str], None] | None = None,
) -> AzureReplayResult:
    """Run ordered real-trace windows on an explicit synthetic reference.

    Static construction uses multiplier one. Rolling construction uses only
    the EWMA of earlier supplied observations. Both sources are scored on the
    exact same forecast scenario using their own retained construction data;
    the old placement is not recertified under a new P_DM forecast. Operational
    failure never silently changes the selected source or fabricates metrics.
    """

    if not isinstance(config, AzureReplayConfig):
        raise TypeError("config must be an AzureReplayConfig")
    ordered = tuple(windows)
    if not ordered or any(not isinstance(window, AzureReplayWindow) for window in ordered):
        raise ValueError("windows must contain non-empty AzureReplayWindow records")
    indices = tuple(window.window_index for window in ordered)
    if indices != tuple(sorted(set(indices))):
        raise ValueError("window indices must be unique and increasing")
    nominal = PdmProblemData(make_heterogeneous_tiny_instance() if instance is None else instance)
    static_source = (_construct_source(nominal, 1.0, -1, config)
                     if config.variant is AzureReplayVariant.STATIC else None)
    incumbent = static_source if static_source is not None and static_source.accepted else None
    forecast = config.initial_forecast_multiplier
    records = []
    for window in ordered:
        if progress is not None:
            progress(f"{config.method.value}/{config.variant.value}: window {window.window_index}")
        current_forecast = 1.0 if config.variant is AzureReplayVariant.STATIC else forecast
        forecast_scenario = make_replay_scenario(nominal, current_forecast,
                                                f"azure-forecast-{window.window_index}")
        realized = make_replay_scenario(nominal, window.realized_multiplier,
                                       f"azure-realized-{window.window_index}")
        before = incumbent
        candidate = candidate_evaluation = incumbent_evaluation = None
        selection = ReplaySelection.STATIC_SOURCE
        if config.variant is AzureReplayVariant.ROLLING:
            candidate = _construct_source(nominal, current_forecast, window.window_index, config)
            if candidate.accepted:
                candidate_evaluation = _evaluate_source(candidate, forecast_scenario, config)
            if incumbent is not None:
                incumbent_evaluation = _evaluate_source(incumbent, forecast_scenario, config)
            candidate_score = None if candidate_evaluation is None else candidate_evaluation.full_model_cost
            incumbent_score = None if incumbent_evaluation is None else incumbent_evaluation.full_model_cost
            if should_replace_incumbent(candidate_score, incumbent_score):
                incumbent = candidate
                selection = (ReplaySelection.INITIAL_CANDIDATE if before is None
                             else ReplaySelection.INCUMBENT_FORECAST_FAILED if incumbent_score is None
                             else ReplaySelection.STRICT_IMPROVEMENT)
            else:
                selection = (ReplaySelection.KEEP_INCUMBENT if incumbent is not None
                             else ReplaySelection.NO_ACCEPTED_SOURCE)
        operation = None if incumbent is None else _evaluate_source(incumbent, realized, config)
        failure = None
        if incumbent is None:
            selection = ReplaySelection.NO_ACCEPTED_SOURCE
            failure = AzureReplayFailure("selection", "NoAcceptedSource", "no accepted operational source")
        elif not operation.successful:
            nested = operation.evaluation_result
            failure = (operation.failure if operation.failure is not None else
                       AzureReplayFailure("operation", nested.status.value, str(nested.failure)))
        next_forecast = (1.0 if config.variant is AzureReplayVariant.STATIC else
                         update_ewma_forecast(forecast, window.realized_multiplier, config.ewma_alpha))
        records.append(AzureReplayWindowResult(
            window, current_forecast, next_forecast, forecast_scenario, realized,
            candidate, before, candidate_evaluation, incumbent_evaluation,
            incumbent, selection, operation, _query_metrics(operation), failure,
        ))
        forecast = next_forecast
    result_windows = tuple(records)
    return AzureReplayResult(nominal, config, static_source, result_windows,
                             aggregate_replay_windows(result_windows))
