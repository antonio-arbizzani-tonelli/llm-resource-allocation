"""Explicit deterministic sensitivity scenarios and served-demand observations.

This is a project experiment, not a recovered paper sampler. Both delay
components and effective errors share the configured stress factor. Other
instance coefficients, unmet caps and the operational formulation stay fixed.
"""

from dataclasses import dataclass
from math import fsum, isfinite

from llm_resource_allocation.domain import ProblemInstance
from llm_resource_allocation.math.error import compute_effective_error
from llm_resource_allocation.math.placement import PlacementDecisionState
from llm_resource_allocation.optimization.stage2_extraction import Stage2Solution
from llm_resource_allocation.optimization.stage2_problem_data import Stage2RealizedScenario


@dataclass(frozen=True, slots=True)
class StressGrid:
    """Own unique, ordered arrival and adverse delay/error factor levels."""

    arrival_factors: tuple[float, ...]
    stress_factors: tuple[float, ...]

    def __post_init__(self):
        for name, lower in (("arrival_factors", 0.0), ("stress_factors", 1.0)):
            values = tuple(getattr(self, name))
            if not values or len(set(values)) != len(values):
                raise ValueError(f"{name} must be nonempty and unique")
            if any(isinstance(value, bool) or not isinstance(value, (int, float))
                   or not isfinite(value) or value < lower for value in values):
                raise ValueError(f"{name} must contain finite factors >= {lower}")
            object.__setattr__(self, name, values)

    @property
    def scenario_count(self):
        return len(self.arrival_factors) * len(self.stress_factors)


def make_stress_scenario(instance: ProblemInstance, arrival_factor: float,
                         stress_factor: float, scenario_id: str) -> Stage2RealizedScenario:
    """Map one validated grid point onto nominal physical coefficients."""
    tiers = {tier.id: tier for tier in instance.gpu_tiers}
    return Stage2RealizedScenario(
        id=scenario_id,
        arrival_rates_per_hour={query.id: query.arrival_rate_per_hour * arrival_factor
                                for query in instance.queries},
        compute_delay_seconds_per_token={key: value * stress_factor
                                         for key, value in instance.compute_delay_seconds_per_token.items()},
        communication_delay_seconds_per_token={key: value * stress_factor
                                               for key, value in instance.communication_delay_seconds_per_token.items()},
        effective_errors={key: compute_effective_error(instance.base_error_rate[key[:2]],
                                                       tiers[key[2]].quantization_error_multiplier) * stress_factor
                          for key in instance.compute_delay_seconds_per_token},
    )


def iter_stress_scenarios(instance: ProblemInstance, grid: StressGrid):
    """Yield all points in arrival-major order without sampling or RNG state."""
    for arrival_index, arrival in enumerate(grid.arrival_factors):
        for stress_index, stress in enumerate(grid.stress_factors):
            identifier = f"arrival_{arrival_index:02d}_stress_{stress_index:02d}"
            yield arrival, stress, make_stress_scenario(instance, arrival, stress, identifier)


def service_observations(instance: ProblemInstance, scenario: Stage2RealizedScenario,
                         solution: Stage2Solution, nominal: PlacementDecisionState) -> dict:
    """Describe an already independently accepted operational decision.

    The caller owns scientific acceptance. Rates use realized arrivals;
    the strict u>0.01 indicator follows the existing reporting convention.
    Changed fractions include transitions to or from unmet demand.
    """
    ids = instance.query_ids
    arrivals = scenario.arrival_rates_per_hour
    unmet = solution.unmet_fractions
    offered = fsum(arrivals[i] for i in ids)
    unserved = fsum(arrivals[i] * unmet.get(i, 0.0) for i in ids)
    changed = fsum(
        abs(solution.routing_fractions.get(key, 0.0) - nominal.routing_fractions.get(key, 0.0))
        for key in ((i, j, k) for i in ids for j in instance.model_ids for k in instance.gpu_tier_ids)
    ) + fsum(abs(unmet.get(i, 0.0) - nominal.unmet_fractions.get(i, 0.0)) for i in ids)
    return {
        "offered_requests_per_hour": offered,
        "served_requests_per_hour": offered - unserved,
        "mean_unmet_fraction": fsum(unmet.get(i, 0.0) for i in ids) / len(ids),
        "demand_weighted_unmet_fraction": unserved / offered if offered else None,
        "unmet_over_1pct_query_fraction": sum(unmet.get(i, 0.0) > 0.01 for i in ids) / len(ids),
        "mean_changed_assignment_fraction": 0.5 * changed / len(ids),
    }
