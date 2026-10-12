"""Build the Stage-2 LP from v1 Eq. (12a)-(12f) and v2 Section 5.2.

Only continuous ``x,u`` are decisions; ``z*,w*,y*`` are fixed coefficients.
Optimize C4+C5; realized C3 is separate reporting evidence. Coherent costs use
realized arrivals and the instance's horizon and data residency.
"""

from collections import defaultdict
from typing import Mapping

from pyomo.environ import (
    ConcreteModel,
    Constraint,
    Expression,
    Objective,
    Set,
    UnitInterval,
    Var,
    minimize,
)

from llm_resource_allocation.domain import ParallelismConfig, QueryType
from llm_resource_allocation.math.latency import compute_configuration_delay_seconds
from llm_resource_allocation.math.objective import (
    compute_delay_penalty,
    compute_unmet_demand_penalty,
)

from .problem_data import ConfigurationKey, ModelTierKey, RouteKey
from .stage2_problem_data import Stage2ProblemData


def _add_sets_and_variables(
    model: ConcreteModel,
    problem_data: Stage2ProblemData,
    query_by_id: Mapping[str, QueryType],
) -> None:
    """Attach ordered Stage-2 sets and continuous x,u with their bounds."""

    lattices = problem_data.pdm_problem_data.variable_lattices

    model.query_ids = Set(initialize=problem_data.unmet_keys, ordered=True)
    model.model_tier_keys = Set(
        dimen=2, initialize=lattices.model_tier_keys, ordered=True
    )
    model.route_keys = Set(
        dimen=3, initialize=problem_data.routing_keys, ordered=True
    )

    model.x = Var(model.route_keys, domain=UnitInterval)
    model.u = Var(
        model.query_ids,
        domain=UnitInterval,
        bounds=lambda _model, query_id: (
            0.0,
            query_by_id[query_id].max_unmet_fraction,
        ),
    )


def _add_delay_expressions(
    model: ConcreteModel,
    problem_data: Stage2ProblemData,
    query_by_id: Mapping[str, QueryType],
    routes_by_query: Mapping[str, list[RouteKey]],
    configurations_by_pair: Mapping[ModelTierKey, list[ConfigurationKey]],
) -> None:
    """Build realized configuration delays and query processing delays."""

    scenario = problem_data.realized_scenario
    fixed = problem_data.fixed_deployment

    # Eq. (12d): fixed w* selects realized D_cfg in seconds.
    def realized_configuration_delay_rule(
        _model: ConcreteModel,
        query_id: str,
        model_id: str,
        tier_id: str,
    ) -> float:
        route_key = (query_id, model_id, tier_id)
        query = query_by_id[query_id]
        return sum(
            fixed.configuration_selectors.get(configuration_key, 0.0)
            * compute_configuration_delay_seconds(
                scenario.compute_delay_seconds_per_token[route_key],
                scenario.communication_delay_seconds_per_token[route_key],
                query,
                ParallelismConfig(configuration_key[2], configuration_key[3]),
            )
            for configuration_key in configurations_by_pair[(model_id, tier_id)]
        )

    model.realized_configuration_delay = Expression(
        model.route_keys, rule=realized_configuration_delay_rule
    )
    model.processing_delay = Expression(
        model.query_ids,
        rule=lambda _model, query_id: sum(
            _model.realized_configuration_delay[route_key]
            * _model.x[route_key]
            for route_key in routes_by_query[query_id]
        ),
    )


def _add_objective_and_reporting(
    model: ConcreteModel,
    problem_data: Stage2ProblemData,
    query_by_id: Mapping[str, QueryType],
) -> None:
    """Optimize versioned C4+C5 and expose realized C3 separately for reporting."""

    instance = problem_data.instance
    scenario = problem_data.realized_scenario

    # Eq. (12a): shared C4 and version-specific C5 formulas.
    model.delay_penalty = Expression(
        expr=compute_delay_penalty(
            instance,
            {
                query_id: model.processing_delay[query_id]
                for query_id in problem_data.unmet_keys
            },
            arrival_rates_per_hour=scenario.arrival_rates_per_hour,
        )
    )
    model.unmet_penalty = Expression(
        expr=compute_unmet_demand_penalty(
            instance,
            {query_id: model.u[query_id] for query_id in problem_data.unmet_keys},
            problem_data.paper_version,
        )
    )
    model.operational_objective = Expression(
        expr=model.delay_penalty + model.unmet_penalty
    )
    model.objective = Objective(expr=model.operational_objective, sense=minimize)

    # D-0067: realized C3 is reported separately from the optimized C4+C5.
    realized_storage_cost = (
        instance.horizon_hours
        * instance.storage_price_usd_per_gb_hour
        * sum(
            query_by_id[query_id].storage_gb_per_token
            * query_by_id[query_id].total_tokens
            * scenario.arrival_rates_per_hour[query_id]
            * model.x[query_id, model_id, tier_id]
            for query_id, model_id, tier_id in problem_data.routing_keys
        )
    )
    model.realized_data_storage_cost = Expression(
        expr=(
            realized_storage_cost * instance.data_residency_hours
            if instance.uses_coherent_units
            else realized_storage_cost
        )
    )


def _add_compute_and_error_expressions(
    model: ConcreteModel,
    problem_data: Stage2ProblemData,
    query_by_id: Mapping[str, QueryType],
    routes_by_query: Mapping[str, list[RouteKey]],
    routes_by_pair: Mapping[ModelTierKey, list[RouteKey]],
) -> None:
    """Build realized compute demand, fixed compute supply, and effective errors."""

    instance = problem_data.instance
    scenario = problem_data.realized_scenario
    fixed = problem_data.fixed_deployment
    tier_by_id = {tier.id: tier for tier in instance.gpu_tiers}

    # Eq. (12c): GFLOP/hour divided by 1000 gives TFLOP/hour (D-0015).
    model.required_compute = Expression(
        model.model_tier_keys,
        rule=lambda _model, model_id, tier_id: sum(
            instance.compute_gflop_per_token[route_key]
            * query_by_id[route_key[0]].total_tokens
            * scenario.arrival_rates_per_hour[route_key[0]]
            * _model.x[route_key]
            / 1000.0
            for route_key in routes_by_pair[(model_id, tier_id)]
        ),
    )
    # Fixed y* supplies the available compute, also in TFLOP/hour.
    model.available_compute = Expression(
        model.model_tier_keys,
        rule=lambda _model, model_id, tier_id: (
            instance.compute_utilization
            * instance.seconds_per_hour
            * tier_by_id[tier_id].compute_throughput_tflops
            * fixed.gpu_counts.get((model_id, tier_id), 0.0)
        ),
    )
    # Eq. (12e): realized effective errors and the SLO are dimensionless.
    model.weighted_error = Expression(
        model.query_ids,
        rule=lambda _model, query_id: sum(
            scenario.effective_errors[route_key] * _model.x[route_key]
            for route_key in routes_by_query[query_id]
        ),
    )


def _add_operational_constraints(
    model: ConcreteModel,
    problem_data: Stage2ProblemData,
    query_by_id: Mapping[str, QueryType],
    routes_by_query: Mapping[str, list[RouteKey]],
) -> None:
    """Attach demand, compute, SLO, and fixed routing-mask constraints."""

    fixed = problem_data.fixed_deployment

    # Eq. (12b): sum_(j,k) x[i,j,k] + u[i] = 1.
    model.demand_balance = Constraint(
        model.query_ids,
        rule=lambda _model, query_id: (
            sum(_model.x[route_key] for route_key in routes_by_query[query_id])
            + _model.u[query_id]
            == 1.0
        ),
    )
    model.compute_capacity = Constraint(
        model.model_tier_keys,
        rule=lambda _model, model_id, tier_id: (
            _model.required_compute[model_id, tier_id]
            <= _model.available_compute[model_id, tier_id]
        ),
    )
    model.delay_slo = Constraint(
        model.query_ids,
        rule=lambda _model, query_id: (
            _model.processing_delay[query_id]
            <= query_by_id[query_id].delay_slo_seconds
        ),
    )
    model.error_slo = Constraint(
        model.query_ids,
        rule=lambda _model, query_id: (
            _model.weighted_error[query_id]
            <= query_by_id[query_id].error_slo
        ),
    )
    # Eq. (12f): 0 <= x <= z*; non-negativity is the variable domain.
    model.routing_mask = Constraint(
        model.route_keys,
        rule=lambda _model, query_id, model_id, tier_id: (
            _model.x[query_id, model_id, tier_id]
            <= fixed.admission_indicators.get(
                (query_id, model_id, tier_id), 0.0
            )
        ),
    )


def build_stage2_pyomo_model(problem_data: Stage2ProblemData) -> ConcreteModel:
    """Build an unsolved LP for one realized scenario and fixed deployment.

    Enforce demand, compute, delay, error, and ``x<=z*`` (D-0004).
    C5 follows the selected paper version (D-0003).
    """

    if not isinstance(problem_data, Stage2ProblemData):
        raise TypeError("problem_data must be a Stage2ProblemData")

    instance = problem_data.instance
    scenario = problem_data.realized_scenario
    lattices = problem_data.pdm_problem_data.variable_lattices
    query_by_id = {query.id: query for query in instance.queries}

    routes_by_query: dict[str, list[RouteKey]] = defaultdict(list)
    routes_by_pair: dict[ModelTierKey, list[RouteKey]] = defaultdict(list)
    configurations_by_pair: dict[ModelTierKey, list[ConfigurationKey]] = (
        defaultdict(list)
    )
    for route_key in lattices.route_keys:
        query_id, model_id, tier_id = route_key
        routes_by_query[query_id].append(route_key)
        routes_by_pair[(model_id, tier_id)].append(route_key)
    for configuration_key in lattices.configuration_keys:
        configurations_by_pair[configuration_key[:2]].append(configuration_key)

    model = ConcreteModel(
        name=(
            f"Stage2[{instance.id},{scenario.id},"
            f"{problem_data.paper_version.value}]"
        )
    )
    _add_sets_and_variables(model, problem_data, query_by_id)
    _add_delay_expressions(
        model, problem_data, query_by_id, routes_by_query, configurations_by_pair
    )
    _add_objective_and_reporting(model, problem_data, query_by_id)
    _add_compute_and_error_expressions(
        model, problem_data, query_by_id, routes_by_query, routes_by_pair
    )
    _add_operational_constraints(model, problem_data, query_by_id, routes_by_query)
    return model
