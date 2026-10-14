"""Explicit synthetic instance variability, separate from algorithm RNG seeds.

Assumption: independent uniform factors [0.9,1.1] per query for arrival and
token counts, and per route for compute/communication delays. No coefficient is
chosen from an observed algorithm outcome. Original factory/defaults are intact.
"""
from dataclasses import replace
from random import Random
from llm_resource_allocation.data.scaling_experiment_instances import make_scaling_experiment_case
from llm_resource_allocation.domain import UnitConvention, validate_problem_instance


def seeded_instance(shape, load, instance_seed, amplitude=0.1):
    if isinstance(instance_seed, bool) or not isinstance(instance_seed, int):
        raise ValueError("instance_seed must be an integer")
    if not 0 <= amplitude < 1:
        raise ValueError("amplitude must be in [0,1)")
    rng=Random(instance_seed)
    base=make_scaling_experiment_case(*shape,load_multiplier=load).instance
    factor=lambda: rng.uniform(1-amplitude,1+amplitude)
    queries=tuple(replace(q,arrival_rate_per_hour=q.arrival_rate_per_hour*factor(),
         input_tokens=max(1,round(q.input_tokens*factor())),
         output_tokens=max(1,round(q.output_tokens*factor()))) for q in base.queries)
    tables={name:{key:value*factor() for key,value in getattr(base,name).items()}
            for name in ("compute_delay_seconds_per_token","communication_delay_seconds_per_token")}
    result=replace(base,queries=queries,**tables,unit_convention=UnitConvention.COHERENT,
         id=f"extension_{shape[0]}x{shape[1]}x{shape[2]}_load{load:g}_instance{instance_seed}")
    validate_problem_instance(result)
    return result
