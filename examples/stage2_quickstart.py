"""Run a hand-checkable coherent Stage-2 demand shock with the CPU HiGHS solver.

This synthetic example doubles demand; it does not use the paper's sampler or
measure LLM serving performance. Run from the repository after installing it:
``python examples/stage2_quickstart.py``. Standard output is a JSON result.
"""

from dataclasses import replace
import json
import platform

from llm_resource_allocation.algorithms import GHPhase1Config, run_gh
from llm_resource_allocation.data import make_coherent_tiny_instance
from llm_resource_allocation.math.objective import (
    compute_gpu_rental_cost, compute_model_storage_cost,
)
from llm_resource_allocation.optimization.problem_data import PdmProblemData
from llm_resource_allocation.optimization.solver import SolverBackend, SolverConfig
from llm_resource_allocation.optimization.stage2_integration import (
    evaluate_stage1_result_under_scenario,
)
from llm_resource_allocation.optimization.stage2_problem_data import (
    Stage2RealizedScenario,
)


def build_example_problem() -> PdmProblemData:
    """Prepare one GPU whose hourly compute capacity is exactly 600 TFLOP."""

    base = make_coherent_tiny_instance()
    route = (base.queries[0].id, base.models[0].id, base.gpu_tiers[0].id)
    query = replace(
        base.queries[0], arrival_rate_per_hour=6.0,
        input_tokens=60.0, output_tokens=40.0,
        storage_gb_per_token=0.002, delay_slo_seconds=0.1,
        delay_penalty_usd_per_millisecond_query=0.02,
        unmet_penalty_usd_per_hour=100.0, max_unmet_fraction=0.5,
    )
    instance = replace(
        base, id="stage2_synthetic_demand_shock", queries=(query,),
        models=(replace(base.models[0], weight_gb=4.0),),
        gpu_tiers=(replace(base.gpu_tiers[0],
                           compute_throughput_tflops=5.0 / 27.0,
                           tensor_parallel_degrees=(1,)),),
        compute_gflop_per_token={route: 1000.0},
        compute_delay_seconds_per_token={route: 0.001},
        communication_delay_seconds_per_token={route: 0.0},
        horizon_hours=3.0, data_residency_hours=2.0,
        storage_price_usd_per_gb_hour=0.25, cost_budget_usd=200.0,
    )
    return PdmProblemData(instance)


def main() -> None:
    problem = build_example_problem()
    instance = problem.instance
    route = problem.variable_lattices.route_keys[0]
    query_id = route[0]
    source = run_gh(instance, GHPhase1Config(budget_fraction=0.8))
    if not (source.algorithm_completed and source.independently_feasible):
        raise RuntimeError("the Stage-1 example did not pass independent acceptance")

    solver_config = SolverConfig(backend=SolverBackend.HIGHS)
    records = []
    for scenario_id, arrivals in (("nominal", 6.0), ("demand_doubled", 12.0)):
        scenario = Stage2RealizedScenario(
            scenario_id, {query_id: arrivals},
            instance.compute_delay_seconds_per_token,
            instance.communication_delay_seconds_per_token,
            {route: 0.05},
        )
        evaluation = evaluate_stage1_result_under_scenario(
            source, problem, scenario, solver_config=solver_config,
        )
        if not evaluation.successful:
            raise RuntimeError(f"Stage-2 {scenario_id} failed: {evaluation.failure}")
        run = evaluation.stage2_run_record
        report = run.scientific_evidence.validation_report
        costs = report.objective_breakdown
        fixed = evaluation.fixed_deployment
        fixed_cost = (
            compute_gpu_rental_cost(instance, fixed.gpu_counts)
            + compute_model_storage_cost(instance, fixed.admission_indicators)
        )
        records.append({
            "scenario_id": scenario_id,
            "realized_arrivals_per_hour": arrivals,
            "routing_fraction": run.solution.routing_fractions[route],
            "unmet_fraction": run.solution.unmet_fractions[query_id],
            "processing_delay_seconds": report.processing_delays_seconds[query_id],
            "gpu_count": fixed.gpu_counts[route[1:]],
            "independently_feasible": run.independently_feasible,
            "solver_objective_agrees": run.objective_agrees,
            "solver_status": run.solver_evidence.result.status.value,
            "solver_version": run.solver_evidence.result.raw_status_metadata["solver_version"],
            "costs_usd": {
                "fixed_gpu_and_model_storage": fixed_cost,
                "realized_data_storage": costs.realized_data_storage_cost,
                "delay": costs.delay_penalty,
                "unmet": costs.unmet_demand_penalty,
                "operational_objective": costs.operational_objective,
                "total_reporting_cost": fixed_cost + costs.reported_variable_cost,
            },
        })

    print(json.dumps({
        "evidence_kind": "hand_checkable_synthetic_example",
        "paper_replication": False,
        "scenario_policy": "explicit nominal and doubled demand; no random sampler",
        "python_version": platform.python_version(),
        "solver_backend": solver_config.backend.value,
        "unit_convention": instance.unit_convention.value,
        "horizon_hours": instance.horizon_hours,
        "data_residency_hours": instance.data_residency_hours,
        "stage1_method": "GH",
        "stage1_routing_fraction": source.placement_decisions.routing_fractions[route],
        "stage1_unmet_fraction": source.placement_decisions.unmet_fractions[query_id],
        "deployment_unchanged": records[0]["gpu_count"] == records[1]["gpu_count"],
        "scenarios": records,
    }, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
