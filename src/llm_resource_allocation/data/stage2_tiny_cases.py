"""Hand-checkable synthetic Stage-2 cases; no paper data or replication evidence."""

from dataclasses import replace

from llm_resource_allocation.domain import FoundationModel, ProblemInstance
from llm_resource_allocation.math.objective import PaperVersion
from llm_resource_allocation.math.error import compute_effective_error
from llm_resource_allocation.optimization.problem_data import PdmProblemData
from llm_resource_allocation.optimization.stage2_problem_data import (
    Stage2FixedDeployment,
    Stage2ProblemData,
    Stage2RealizedScenario,
)

from .tiny_instances import make_minimal_tiny_instance


def _single_route_fixed(data) -> Stage2FixedDeployment:
    """Admit the first route, select its first configuration, and set y=TP*PP."""

    route = data.variable_lattices.route_keys[0]
    configuration = data.variable_lattices.configuration_keys[0]
    return Stage2FixedDeployment(
        admission_indicators={route: 1.0},
        configuration_selectors={configuration: 1.0},
        gpu_counts={configuration[:2]: configuration[2] * configuration[3]},
    )


def _scenario_from_instance(
    instance: ProblemInstance,
    scenario_id: str,
    *,
    arrival_rates_per_hour: dict[str, float] | None = None,
    compute_delay_seconds_per_token: dict[tuple[str, str, str], float] | None = None,
    communication_delay_seconds_per_token: dict[
        tuple[str, str, str], float
    ]
    | None = None,
) -> Stage2RealizedScenario:
    """Build a scenario with optional arrival/delay overrides and effective errors."""

    tier_by_id = {tier.id: tier for tier in instance.gpu_tiers}
    return Stage2RealizedScenario(
        id=scenario_id,
        arrival_rates_per_hour=(
            arrival_rates_per_hour
            if arrival_rates_per_hour is not None
            else {
                query.id: query.arrival_rate_per_hour for query in instance.queries
            }
        ),
        compute_delay_seconds_per_token=(
            compute_delay_seconds_per_token
            if compute_delay_seconds_per_token is not None
            else dict(instance.compute_delay_seconds_per_token)
        ),
        communication_delay_seconds_per_token=(
            communication_delay_seconds_per_token
            if communication_delay_seconds_per_token is not None
            else dict(instance.communication_delay_seconds_per_token)
        ),
        effective_errors={
            key: compute_effective_error(
                instance.base_error_rate[key[:2]],
                tier_by_id[key[2]].quantization_error_multiplier,
            )
            for key in instance.compute_delay_seconds_per_token
        },
    )


def make_stage2_fully_served_case(
    paper_version: PaperVersion = PaperVersion.V2,
) -> Stage2ProblemData:
    """Return a one-route case with optimum ``x=1,u=0``.

    ``D_cfg=0.31`` seconds; ``C4=0.01*0.31=0.0031`` and ``C5=0``.
    """

    instance = make_minimal_tiny_instance()
    pdm_data = PdmProblemData(instance)
    return Stage2ProblemData(
        pdm_data,
        _single_route_fixed(pdm_data),
        _scenario_from_instance(instance, "fully_served"),
        paper_version,
    )


def make_stage2_capacity_limited_case(
    paper_version: PaperVersion = PaperVersion.V2,
) -> Stage2ProblemData:
    """Return a compute-limited case with optimum ``x=0.8,u=0.2``.

    ``40500*x <= 32400`` TFLOP/hour; v2 ``C4+C5=1.00248``.
    """

    instance = make_minimal_tiny_instance()
    pdm_data = PdmProblemData(instance)
    scenario = _scenario_from_instance(
        instance,
        "capacity_limited",
        arrival_rates_per_hour={"q_text": 13_500_000.0},
    )
    return Stage2ProblemData(
        pdm_data, _single_route_fixed(pdm_data), scenario, paper_version
    )


def _two_route_instance() -> ProblemInstance:
    """Add a faster model with D_cfg=0.06 seconds and a compute limit of x=0.6."""

    base = make_minimal_tiny_instance()
    second_model = FoundationModel(
        id="m_fast",
        weight_gb=1.0,
        kv_cache_gb_per_token=base.models[0].kv_cache_gb_per_token,
    )
    tier_id = base.gpu_tiers[0].id
    query_id = base.queries[0].id
    return replace(
        base,
        id="tiny_stage2_two_route",
        models=(base.models[0], second_model),
        base_error_rate={
            (query_id, base.models[0].id): 0.05,
            (query_id, second_model.id): 0.04,
        },
        compute_delay_seconds_per_token={
            (query_id, base.models[0].id, tier_id): 0.10,
            (query_id, second_model.id, tier_id): 0.02,
        },
        communication_delay_seconds_per_token={
            (query_id, base.models[0].id, tier_id): 0.01,
            (query_id, second_model.id, tier_id): 0.0,
        },
        compute_gflop_per_token={
            (query_id, base.models[0].id, tier_id): 1.0,
            # lambda=10, r=3: 54000*x <= 32400 TFLOP/hour gives x <= 0.6.
            (query_id, second_model.id, tier_id): 1_800_000.0,
        },
        kv_cache_residency_seconds={
            (query_id, base.models[0].id, tier_id): 1.0,
            (query_id, second_model.id, tier_id): 1.0,
        },
    )


def make_stage2_two_route_case(
    *,
    mask_fast_route: bool = False,
    paper_version: PaperVersion = PaperVersion.V2,
) -> Stage2ProblemData:
    """Return a two-route case, optionally masking the faster route.

    Optimum: ``x_fast=0.6,x_slow=0.4,u=0``; ``C4+C5=0.0016``.
    Masking sets ``z_fast*=0``, forcing ``x_fast=0`` (v1 Eq. 12f);
    then ``x_slow=1,u=0`` and ``C4+C5=0.0031``.
    """

    instance = _two_route_instance()
    pdm_data = PdmProblemData(instance)
    routes = pdm_data.variable_lattices.route_keys
    configurations = pdm_data.variable_lattices.configuration_keys
    fixed = Stage2FixedDeployment(
        admission_indicators={
            routes[0]: 1.0,
            routes[1]: 0.0 if mask_fast_route else 1.0,
        },
        configuration_selectors={
            configurations[0]: 1.0,
            configurations[2]: 1.0,
        },
        gpu_counts={
            configurations[0][:2]: 1.0,
            configurations[2][:2]: 1.0,
        },
    )
    return Stage2ProblemData(
        pdm_data,
        fixed,
        _scenario_from_instance(instance, "two_route_mask" if mask_fast_route else "two_route"),
        paper_version,
    )


def make_stage2_delay_stress_pair() -> tuple[Stage2ProblemData, Stage2ProblemData]:
    """Return nominal/stressed scenarios sharing one fixed deployment.

    ``Delta=0.25`` seconds and ``u <= 0.5``. Nominal ``D_cfg=0.25`` gives
    ``x=1,u=0``; stressed ``D_cfg=0.50`` gives ``x=0.5,u=0.5``.
    """

    base = make_minimal_tiny_instance()
    query = replace(
        base.queries[0], delay_slo_seconds=0.25, max_unmet_fraction=0.5
    )
    route = (query.id, base.models[0].id, base.gpu_tiers[0].id)
    instance = replace(
        base,
        id="tiny_stage2_delay_stress",
        queries=(query,),
        compute_delay_seconds_per_token={route: 0.08},
    )
    pdm_data = PdmProblemData(instance)
    fixed = _single_route_fixed(pdm_data)
    nominal = Stage2ProblemData(
        pdm_data,
        fixed,
        _scenario_from_instance(instance, "delay_nominal"),
    )
    stressed = Stage2ProblemData(
        pdm_data,
        fixed,
        _scenario_from_instance(
            instance,
            "delay_stressed",
            compute_delay_seconds_per_token={route: 0.16},
            communication_delay_seconds_per_token={route: 0.02},
        ),
    )
    return nominal, stressed
