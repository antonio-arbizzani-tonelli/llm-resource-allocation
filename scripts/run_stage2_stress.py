"""Evaluate one fixed deployment on a configured deterministic stress grid.

Every attempt is retained. Rejected LPs have diagnostic evidence and no usable
cost/service values. Output is written after every scenario for interruption
recovery; a partial grid has no complete-grid aggregate.
"""

import argparse
from collections import Counter
from dataclasses import replace
import gzip
import hashlib
import json
from pathlib import Path
import platform
from statistics import median
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from llm_resource_allocation.algorithms import GHPhase1Config, run_agh, run_gh
from llm_resource_allocation.data.scaling_experiment_instances import make_scaling_experiment_case
from llm_resource_allocation.domain import UnitConvention
from llm_resource_allocation.experiments.stress_grid import StressGrid, iter_stress_scenarios, service_observations
from llm_resource_allocation.math.objective import compute_gpu_rental_cost, compute_model_storage_cost
from llm_resource_allocation.optimization.extraction import PdmSolutionExtractionError, PdmSolutionNormalizationError
from llm_resource_allocation.optimization.pdm_run import execute_and_record_pdm_run
from llm_resource_allocation.optimization.problem_data import PdmProblemData
from llm_resource_allocation.optimization.solver import NoSolverIncumbentError, SolverBackend, SolverConfig
from llm_resource_allocation.optimization.stage2_adapter import stage2_fixed_deployment_from_stage1
from llm_resource_allocation.optimization.stage2_extraction import Stage2Solution, stage2_solution_identity
from llm_resource_allocation.optimization.stage2_problem_data import Stage2ProblemData
from llm_resource_allocation.optimization.stage2_run import run_stage2
from llm_resource_allocation.validation.stage2 import validate_stage2_solution
from scripts.run_azure_replay import _plain


def save_json(path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic replacement prevents an interrupted write from erasing a checkpoint.
    temporary = path.with_suffix(path.suffix + ".pending")
    temporary.write_text(json.dumps(record, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    temporary.replace(path)


def save_scientific_evidence(path, record):
    encoded = (json.dumps(_plain(record), separators=(",", ":"), allow_nan=False) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(encoded, mtime=0))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_details(source, method):
    if method == "p_dm":
        return source.accepted_run, source.solution, source.scientific_evidence.validation_report, source.solver_evidence
    if method == "gh":
        return source.algorithm_completed and source.independently_feasible, source.placement_decisions, source.validation_report, None
    return source.completed and source.final_validation is not None and source.final_validation.is_feasible, source.final_placement, source.final_validation, None


def run_stress_case(config, shape, load, method, seed, output):
    case = make_scaling_experiment_case(*shape, load_multiplier=load)
    instance = replace(case.instance, unit_convention=UnitConvention.COHERENT,
                       data_residency_hours=config["data_residency_hours"],
                       id=f"extended_{shape[0]}x{shape[1]}x{shape[2]}_load{load:g}")
    problem = PdmProblemData(instance)
    grid = StressGrid(tuple(config["arrival_factors"]), tuple(config["stress_factors"]))
    backend = SolverBackend(config["backend"])
    result = {"classification": config["classification"], "complete": False,
              "shape": list(shape), "load_multiplier": load, "method": method,
              "seed": seed if method == "agh" else None, "backend": backend.value,
              "python_version": platform.python_version(), "unit_convention": "coherent",
              "horizon_hours": instance.horizon_hours, "data_residency_hours": instance.data_residency_hours,
              "sampling": "deterministic Cartesian grid; no random draws",
              "stress_mapping": config["stress_mapping"], "source_unmet_caps_retained": True,
              "planned_scenario_count": grid.scenario_count, "attempts": [], "aggregate": None}
    input_path = output / "instance.json.gz"
    result["instance_sha256"] = save_scientific_evidence(input_path, instance)
    save_json(output / "result.json", result)
    start = perf_counter()
    try:
        if method == "p_dm":
            source = execute_and_record_pdm_run(problem, SolverConfig(
                backend=backend, time_limit_seconds=config["stage1_solver_limit_seconds"],
                relative_mip_gap=0.0, absolute_mip_gap=0.0))
        elif method == "gh":
            source = run_gh(instance, GHPhase1Config(config["gh_budget_fraction"]))
        else:
            source = run_agh(instance, GHPhase1Config(config["gh_budget_fraction"]), random_seed=seed)
    except (NoSolverIncumbentError, PdmSolutionExtractionError, PdmSolutionNormalizationError) as error:
        result.update(complete=True, stage1_accepted=False, stage1_seconds=perf_counter() - start,
                      stage1_failure={"type": type(error).__name__, "message": str(error)},
                      skipped_scenario_count=grid.scenario_count)
        save_json(output / "result.json", result)
        return result
    result["stage1_seconds"] = perf_counter() - start
    accepted, nominal, validation, solver = source_details(source, method)
    result["stage1_accepted"] = accepted
    result["stage1_evidence_sha256"] = save_scientific_evidence(output / "stage1.json.gz", {
        "accepted": accepted, "placement": nominal, "validation": validation, "solver": solver,
        "completion": source.completion_status if method != "p_dm" else None})
    if not accepted:
        result.update(complete=True, skipped_scenario_count=grid.scenario_count)
        save_json(output / "result.json", result)
        return result
    adapter = stage2_fixed_deployment_from_stage1(source, problem)
    fixed = adapter.fixed_deployment
    fixed_cost = compute_gpu_rental_cost(instance, fixed.gpu_counts) + compute_model_storage_cost(instance, fixed.admission_indicators)
    result["fixed_cost_usd"] = fixed_cost
    solver_config = SolverConfig(backend=backend, time_limit_seconds=config["stage2_solver_limit_seconds"])
    for index, (arrival, stress, scenario) in enumerate(iter_stress_scenarios(instance, grid)):
        start = perf_counter()
        data = Stage2ProblemData(problem, fixed, scenario)
        record = run_stage2(data, solver_config=solver_config)
        elapsed = perf_counter() - start
        frozen_solution = Stage2Solution(stage2_solution_identity(data), nominal.routing_fractions, nominal.unmet_fractions)
        frozen_validation = validate_stage2_solution(data, frozen_solution)
        evidence_path = output / "scenarios" / f"{index:03d}.json.gz"
        digest = save_scientific_evidence(evidence_path, {
            "realization": scenario, "operational_run": record,
            "frozen_routing_validation": frozen_validation})
        observation = {"index": index, "scenario_id": scenario.id, "arrival_factor": arrival,
                       "stress_factor": stress, "successful": record.successful,
                       "stage2_status": record.status.value, "solver_status": record.solver_evidence.result.status.value,
                       "objective_agrees": record.objective_agrees, "independently_feasible": record.independently_feasible,
                       "frozen_routing_feasible": frozen_validation.is_feasible,
                       "integrated_seconds": elapsed, "evidence": evidence_path.relative_to(output).as_posix(),
                       "evidence_sha256": digest, "quality": None, "frozen_quality": None}
        if frozen_validation.is_feasible:
            frozen_costs = frozen_validation.objective_breakdown
            observation["frozen_quality"] = {
                **service_observations(instance, scenario, frozen_solution, nominal),
                "operational_cost_usd": frozen_costs.operational_objective,
                "reporting_cost_usd": fixed_cost + frozen_costs.reported_variable_cost}
        if record.successful:
            costs = record.scientific_evidence.objective_breakdown
            observation["quality"] = {
                **service_observations(instance, scenario, record.solution, nominal),
                "c3_usd": costs.realized_data_storage_cost, "c4_usd": costs.delay_penalty,
                "c5_usd": costs.unmet_demand_penalty, "operational_cost_usd": costs.operational_objective,
                "reporting_cost_usd": fixed_cost + costs.reported_variable_cost}
        result["attempts"].append(observation)
        save_json(output / "result.json", result)
        if index % 10 == 0 or index + 1 == grid.scenario_count:
            print(f"{method} {shape}: {index + 1}/{grid.scenario_count}; {record.status.value}", flush=True)
    accepted_attempts = [attempt for attempt in result["attempts"] if attempt["successful"]]
    result.update(complete=True, accepted_scenario_count=len(accepted_attempts),
                  status_counts=dict(Counter(attempt["stage2_status"] for attempt in result["attempts"])))
    # Full-grid cost/service means are intentionally unavailable if any LP failed.
    if len(accepted_attempts) == grid.scenario_count:
        from math import fsum
        result["aggregate"] = {
            key: fsum(attempt["quality"][key] for attempt in accepted_attempts) / grid.scenario_count
            for key in accepted_attempts[0]["quality"]
            if accepted_attempts[0]["quality"][key] is not None}
    result["scenario_integrated_median_seconds"] = median(attempt["integrated_seconds"] for attempt in result["attempts"])
    save_json(output / "result.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--shape", type=int, nargs=3, required=True)
    parser.add_argument("--load", type=float, required=True)
    parser.add_argument("--method", choices=("gh", "agh", "p_dm"), required=True)
    parser.add_argument("--seed", type=int, default=37)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    from run_nightly_campaign import load_configuration
    run_stress_case(load_configuration(args.config), tuple(args.shape), args.load,
                    args.method, args.seed, args.output)


if __name__ == "__main__":
    main()
