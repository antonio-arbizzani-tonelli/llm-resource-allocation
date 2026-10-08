"""Process every GH Phase-2 query once (v2 Algorithm 1, lines 8-22)."""

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from llm_resource_allocation.algorithms.gh_phase2 import (
    GHPhase2QueryEvaluation,
    GHPhase2State,
    _validate_phase2_state,
)
from llm_resource_allocation.algorithms.gh_phase2_query import (
    GHPhase2QueryProcessResult,
    _process_gh_phase2_query,
)
from llm_resource_allocation.domain import ProblemInstance, validate_problem_instance


class GHPhase2RunCompletionStatus(str, Enum):
    """Record the sole completion condition of the printed outer loop."""

    ALL_QUERIES_PROCESSED = "all_queries_processed"


@dataclass(frozen=True, slots=True)
class GHPhase2QueryTrace:
    """Record one query's entry state, evaluation, traversal, and resulting state."""

    query_position: int
    query_id: str
    arrival_rate_per_hour: float
    state_at_query_entry: GHPhase2State
    query_evaluation: GHPhase2QueryEvaluation
    query_process_result: GHPhase2QueryProcessResult
    state_after_query: GHPhase2State


@dataclass(frozen=True, slots=True)
class GHPhase2RunResult:
    """Store the Phase-2 trace, final state, and per-query residual demand."""

    initial_state: GHPhase2State
    query_traces: tuple[GHPhase2QueryTrace, ...]
    final_state: GHPhase2State
    processed_query_ids: tuple[str, ...]
    residual_demand_by_query: Mapping[str, float]
    completion_status: GHPhase2RunCompletionStatus

    def __post_init__(self) -> None:
        """Freeze caller-supplied containers at the public result boundary."""

        object.__setattr__(self, "query_traces", tuple(self.query_traces))
        object.__setattr__(
            self, "processed_query_ids", tuple(self.processed_query_ids)
        )
        object.__setattr__(
            self,
            "residual_demand_by_query",
            MappingProxyType(dict(self.residual_demand_by_query)),
        )

    @property
    def all_queries_processed(self) -> bool:
        """Return whether the only supported completion status was reached."""

        return (
            self.completion_status
            is GHPhase2RunCompletionStatus.ALL_QUERIES_PROCESSED
        )


def run_gh_phase2(
    instance: ProblemInstance,
    state: GHPhase2State,
    *,
    expected_state_order: tuple[str, ...] | None = None,
) -> GHPhase2RunResult:
    """Process the state's validated query order exactly once (Algorithm 1).

    Evaluate each query at its current entry state, then use the frozen traversal
    and carry its final state into the next query. Routing, deployments, GPU
    counts, query dynamics, and C1-C3 budget persist through commit transitions.
    Residual demand or an empty ranking does not stop later queries (D-0040).
    """

    validate_problem_instance(instance)
    _validate_phase2_state(
        instance, state, expected_state_order=expected_state_order
    )
    return _run_gh_phase2(instance, state)


def _run_gh_phase2(
    instance: ProblemInstance,
    state: GHPhase2State,
) -> GHPhase2RunResult:
    """Process each query once, carrying only internally checked transitions."""

    query_by_id = {query.id: query for query in instance.queries}

    current_state = state
    traces: list[GHPhase2QueryTrace] = []
    for query_position, query_id in enumerate(state.query_order):
        query_entry_state = current_state
        query_result = _process_gh_phase2_query(instance, query_entry_state, query_id)
        query_evaluation = query_result.query_evaluation
        current_state = query_result.final_state
        traces.append(
            GHPhase2QueryTrace(
                query_position=query_position,
                query_id=query_id,
                arrival_rate_per_hour=(
                    query_by_id[query_id].arrival_rate_per_hour
                ),
                state_at_query_entry=query_entry_state,
                query_evaluation=query_evaluation,
                query_process_result=query_result,
                state_after_query=current_state,
            )
        )

    processed_query_ids = tuple(trace.query_id for trace in traces)
    return GHPhase2RunResult(
        initial_state=state,
        query_traces=tuple(traces),
        final_state=current_state,
        processed_query_ids=processed_query_ids,
        residual_demand_by_query=current_state.remaining_demand_by_query,
        completion_status=GHPhase2RunCompletionStatus.ALL_QUERIES_PROCESSED,
    )
