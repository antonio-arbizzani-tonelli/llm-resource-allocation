"""Storage-capacity diagnostics for Paper v2 Eq. (8h), under D-0016.

D-0016 closes the paper's free query index with one constraint per query.
The printed sum combines model storage in GB and a data rate in GB/hour;
this unresolved unit mismatch is preserved.
"""

from dataclasses import dataclass
from math import fsum, isfinite

from llm_resource_allocation.domain import ProblemInstance

from .placement import PlacementDecisionState, validate_placement_decision_domains


@dataclass(frozen=True, slots=True)
class QueryStorageCapacityDiagnostic:
    """Record the per-query storage comparison (v2 Eq. 8h, D-0016).

    ``model_storage_usage_gb = sum_(j,k) B_j*z[i,j,k]``;
    ``data_storage_rate_gb_per_hour = sum_(j,k) theta_i*r_i*lambda_i*x[i,j,k]``;
    ``storage_limit_gb = C_s``. ``slack = C_s - printed_storage_lhs`` retains
    the printed comparison despite its GB versus GB/hour mismatch.
    """

    query_id: str
    model_storage_usage_gb: float
    data_storage_rate_gb_per_hour: float
    storage_limit_gb: float

    @property
    def printed_storage_lhs(self) -> float:
        """Return ``model_storage_usage_gb + data_storage_rate_gb_per_hour`` (Eq. 8h)."""

        return self.model_storage_usage_gb + self.data_storage_rate_gb_per_hour

    @property
    def slack(self) -> float:
        """Return ``C_s - printed_storage_lhs`` (v2 Eq. 8h, D-0016)."""

        return self.storage_limit_gb - self.printed_storage_lhs

    @property
    def violation(self) -> float:
        """Return ``max(printed_storage_lhs - C_s, 0)``."""

        return max(-self.slack, 0.0)

    def is_feasible(self, tolerance: float = 0.0) -> bool:
        """Return whether ``slack >= -tolerance`` for Eq. (8h), under D-0016.

        The tolerance uses the numerical scale of the unresolved storage comparison.
        """

        if (
            isinstance(tolerance, bool)
            or not isinstance(tolerance, (int, float))
            or not isfinite(tolerance)
            or tolerance < 0.0
        ):
            raise ValueError("tolerance must be a finite non-negative real number")
        return self.slack >= -tolerance


def compute_model_storage_usage_by_query(
    instance: ProblemInstance,
    state: PlacementDecisionState,
) -> dict[str, float]:
    """Return ``i -> sum_(j,k) B_j*z[i,j,k]`` in GB (v2 Eq. 8h, D-0016).

    ``model.weight_gb`` is B_j; ``state.admission_indicators`` supplies z.
    Each admitted model/tier entry contributes its weight for that query.
    """

    validate_placement_decision_domains(instance, state)
    return _compute_model_storage_usage_by_query(instance, state)


def compute_data_storage_rate_by_query(
    instance: ProblemInstance,
    state: PlacementDecisionState,
) -> dict[str, float]:
    """Return ``i -> sum_(j,k) theta_i*r_i*lambda_i*x[i,j,k]`` (v2 Eq. 8h).

    ``query.storage_gb_per_token`` is theta_i (converted at input under D-0009);
    ``query.total_tokens`` is r_i; ``query.arrival_rate_per_hour`` is lambda_i;
    ``state.routing_fractions`` supplies x. The result is GB/hour, without a horizon.
    """

    validate_placement_decision_domains(instance, state)
    return _compute_data_storage_rate_by_query(instance, state)


def compute_storage_capacity_residuals(
    instance: ProblemInstance,
    state: PlacementDecisionState,
) -> tuple[QueryStorageCapacityDiagnostic, ...]:
    """Return storage-capacity diagnostics per query (v2 Eq. 8h, D-0016).

    Compute ``model_storage_usage_gb = sum_(j,k) B_j*z[i,j,k]`` and
    ``data_storage_rate_gb_per_hour = sum_(j,k) theta_i*r_i*lambda_i*x[i,j,k]``.
    Each diagnostic stores both terms and ``storage_limit_gb = C_s``, deriving
    ``slack = C_s - printed_storage_lhs``. The GB + GB/hour mismatch is preserved.
    """

    validate_placement_decision_domains(instance, state)
    return _compute_storage_capacity_residuals(instance, state)


def _compute_model_storage_usage_by_query(
    instance: ProblemInstance,
    state: PlacementDecisionState,
) -> dict[str, float]:
    """Calculate from instance and decision domains validated by the caller."""
    weight_by_model = {model.id: model.weight_gb for model in instance.models}
    return {
        query_id: fsum(
            weight_by_model[model_id]
            * state.admission_indicators.get(
                (query_id, model_id, tier_id), 0.0
            )
            for model_id in instance.model_ids
            for tier_id in instance.gpu_tier_ids
        )
        for query_id in instance.query_ids
    }


def _compute_data_storage_rate_by_query(
    instance: ProblemInstance,
    state: PlacementDecisionState,
) -> dict[str, float]:
    """Calculate from instance and decision domains validated by the caller."""
    return {
        query.id: fsum(
            query.storage_gb_per_token
            * query.total_tokens
            * query.arrival_rate_per_hour
            * state.routing_fractions.get(
                (query.id, model_id, tier_id), 0.0
            )
            for model_id in instance.model_ids
            for tier_id in instance.gpu_tier_ids
        )
        for query in instance.queries
    }


def _compute_storage_capacity_residuals(
    instance: ProblemInstance,
    state: PlacementDecisionState,
) -> tuple[QueryStorageCapacityDiagnostic, ...]:
    """Calculate from instance and decision domains validated by the caller."""

    model_usage = _compute_model_storage_usage_by_query(instance, state)
    data_rate = _compute_data_storage_rate_by_query(instance, state)
    return tuple(
        QueryStorageCapacityDiagnostic(
            query_id=query_id,
            model_storage_usage_gb=model_usage[query_id],
            data_storage_rate_gb_per_hour=data_rate[query_id],
            storage_limit_gb=instance.storage_capacity_gb,
        )
        for query_id in instance.query_ids
    )
