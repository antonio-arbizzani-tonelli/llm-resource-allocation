"""Budget diagnostics for ``C1 + C2 + C3 <= delta`` (Paper v2 Eq. 8c)."""

from dataclasses import dataclass
from math import isfinite

from fastllm_replication.domain import ProblemInstance

from .objective import (
    compute_data_storage_cost,
    compute_gpu_rental_cost,
    compute_model_storage_cost,
)
from .placement import PlacementDecisionState, validate_placement_decision_domains


@dataclass(frozen=True, slots=True)
class BudgetDiagnostic:
    """Record resource costs and budget ``delta`` (v2 Eq. 8c).

    ``gpu_rental_cost``, ``model_storage_cost``, and ``data_storage_cost`` are
    ``C1``, ``C2``, and ``C3``; ``budget_limit`` is ``delta``.
    ``slack = delta - (C1 + C2 + C3)`` uses the stored monetary scale.
    """

    gpu_rental_cost: float
    model_storage_cost: float
    data_storage_cost: float
    budget_limit: float

    @property
    def total_budget_use(self) -> float:
        """Return ``C1 + C2 + C3``, the resource cost in Eq. (8c)."""

        return self.gpu_rental_cost + self.model_storage_cost + self.data_storage_cost

    @property
    def slack(self) -> float:
        """Return ``delta - (C1 + C2 + C3)`` (v2 Eq. 8c)."""

        return self.budget_limit - self.total_budget_use

    @property
    def violation(self) -> float:
        """Return ``max(C1 + C2 + C3 - delta, 0)``."""

        return max(-self.slack, 0.0)

    def is_feasible(self, tolerance: float = 0.0) -> bool:
        """Return whether ``slack >= -tolerance`` for Eq. (8c).

        ``tolerance`` uses the same monetary scale as ``budget_limit`` (delta).
        """

        if (
            isinstance(tolerance, bool)
            or not isinstance(tolerance, (int, float))
            or not isfinite(tolerance)
            or tolerance < 0.0
        ):
            raise ValueError("tolerance must be a finite non-negative real number")
        return self.slack >= -tolerance


def compute_budget_residual(
    instance: ProblemInstance,
    state: PlacementDecisionState,
) -> BudgetDiagnostic:
    """Compute costs and slack for ``C1 + C2 + C3 <= delta`` (v2 Eq. 8c).

    Reuse the objective terms from ``gpu_counts`` (y), ``admission_indicators``
    (z), and ``routing_fractions`` (x). C4 and C5 are outside this budget.
    """

    validate_placement_decision_domains(instance, state)

    # Keep the objective module authoritative for all three printed cost terms;
    # this diagnostic owns only their budget-specific composition.
    gpu_rental_cost = compute_gpu_rental_cost(instance, state.gpu_counts)
    model_storage_cost = compute_model_storage_cost(
        instance, state.admission_indicators
    )
    data_storage_cost = compute_data_storage_cost(
        instance, state.routing_fractions
    )
    return BudgetDiagnostic(
        gpu_rental_cost=gpu_rental_cost,
        model_storage_cost=model_storage_cost,
        data_storage_cost=data_storage_cost,
        budget_limit=instance.cost_budget_usd,
    )
