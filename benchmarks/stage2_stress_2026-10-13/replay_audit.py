"""Audit recorded AC-restart evidence and replay its independent validators."""
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import datetime, timezone
import gzip
import hashlib
import json
from math import fsum, ulp
from pathlib import Path
from statistics import median
import sys
from types import SimpleNamespace

import argparse

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--campaign", type=Path, required=True, help="extracted evidence directory")
parser.add_argument("--output", type=Path, required=True, help="separate derived replay results")
args = parser.parse_args()
CAMPAIGN = args.campaign.resolve()
SNAPSHOT = CAMPAIGN / "snapshot"
OUTPUT = args.output.resolve()
if OUTPUT == CAMPAIGN or OUTPUT.is_relative_to(CAMPAIGN):
    raise ValueError("Replay output must be outside the recorded evidence")
sys.path.insert(0, str(SNAPSHOT / "scripts"))
sys.path.insert(0, str(SNAPSHOT / "src"))
from run_nightly_campaign import campaign_jobs, configuration_digest, load_configuration, save_json
from run_azure_replay import _plain
from summarize_nightly_campaign import duration_statistics
from llm_resource_allocation.data.scaling_experiment_instances import make_scaling_experiment_case
from llm_resource_allocation.domain import UnitConvention
from llm_resource_allocation.experiments.stress_grid import StressGrid, iter_stress_scenarios, service_observations
from llm_resource_allocation.math.objective import PaperVersion, compute_gpu_rental_cost, compute_model_storage_cost
from llm_resource_allocation.math.parallelism import ParallelismDecisionState
from llm_resource_allocation.math.placement import PlacementDecisionState
from llm_resource_allocation.math.routing import RoutingDecisionState
from llm_resource_allocation.optimization.problem_data import PdmProblemData
from llm_resource_allocation.optimization.stage2_extraction import Stage2Solution, stage2_solution_identity
from llm_resource_allocation.optimization.stage2_problem_data import Stage2FixedDeployment, Stage2ProblemData
from llm_resource_allocation.validation.stage2 import Stage2ValidationTolerances, validate_stage2_solution
from llm_resource_allocation.validation.placement import ValidationTolerances, validate_placement


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_gzip(path):
    return json.loads(gzip.decompress(path.read_bytes()))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def mapping(value):
    if isinstance(value, dict):
        return dict(value)
    result = {tuple(item["key"]): item["value"] for item in value}
    require(len(result) == len(value), "Duplicate serialized scientific mapping key")
    return result


def summarize_rows(rows):
    successful = [row for row in rows if row["successful"]]
    failed_frozen = [row for row in rows if not row["frozen_routing_feasible"]]
    recovered = [row for row in failed_frozen if row["successful"]]
    paired = [row for row in successful if row["frozen_routing_feasible"]]
    baseline = fsum(row["frozen_quality"]["operational_cost_usd"] for row in paired)
    adapted = fsum(row["quality"]["operational_cost_usd"] for row in paired)
    return {
        "attempted_scenarios": len(rows), "accepted_scenarios": len(successful),
        "solver_status_counts": dict(Counter(row["solver_status"] for row in rows)),
        "stage2_status_counts": dict(Counter(row["stage2_status"] for row in rows)),
        "frozen_infeasible_scenarios": len(failed_frozen), "recovered_scenarios": len(recovered),
        "recovery_fraction_of_frozen_failures": len(recovered) / len(failed_frozen) if failed_frozen else None,
        "paired_cost_scenarios": len(paired),
        "paired_frozen_operational_cost_sum_usd": baseline,
        "paired_adapted_operational_cost_sum_usd": adapted,
        "paired_cost_reduction_fraction_of_baseline_sum": (baseline - adapted) / baseline if baseline else None,
        "accepted_demand_weighted_unmet_median": median(row["quality"]["demand_weighted_unmet_fraction"] for row in successful) if successful else None,
        "accepted_changed_assignment_median": median(row["quality"]["mean_changed_assignment_fraction"] for row in successful) if successful else None,
        "stage2_integrated_duration": duration_statistics([row["integrated_seconds"] for row in rows]) if rows else None,
    }


def audit():
    status = read_json(CAMPAIGN / "status.json")
    require(status["status"] == "completed", "Campaign must finish before final replay")
    config = load_configuration(SNAPSHOT / "configs/nightly_campaign.json")
    manifest = read_json(CAMPAIGN / "snapshot_manifest.json")
    require(configuration_digest(config) == manifest["configuration_sha256"], "Frozen configuration changed")
    # Every delivered reference file keeps its original measured bytes. The
    # archive deliberately excludes binaries/private tests; Stage 2 uses neither.
    provided = {path.relative_to(SNAPSHOT).as_posix(): digest(path)
                for path in SNAPSHOT.rglob("*") if path.is_file() and "__pycache__" not in path.parts}
    source_files = {name: value for name, value in provided.items() if name != "configs/nightly_campaign.json"}
    require(all(manifest["source_sha256"].get(name) == value for name, value in source_files.items()), "Frozen reference bytes changed")
    required = {name for name in manifest["source_sha256"] if name.startswith("src/")}
    required.update({"scripts/run_stage2_stress.py", "scripts/run_azure_replay.py", "scripts/run_nightly_campaign.py", "scripts/summarize_nightly_campaign.py", "configs/nightly_campaign.json"})
    require(required <= provided.keys(), "Required scientific reference source missing")
    plan = read_json(CAMPAIGN / "plan.json")
    expected_jobs = [job for job in campaign_jobs(config) if job["kind"] == "stress"]
    require(plan["jobs"] == expected_jobs and len(expected_jobs) == 40, "Stress subset changed")
    history = read_json(CAMPAIGN / "jobs.json")
    require(len(history) == 40 and all(job["status"] == "completed" for job in history), "All forty fresh jobs must finish exactly once")
    completed = {job["id"]: job for job in history}
    require(set(completed) == {job["id"] for job in expected_jobs}, "Job coverage mismatch")
    grid = StressGrid(tuple(config["arrival_factors"]), tuple(config["stress_factors"]))
    all_rows, source_rows, methods, shapes = [], [], defaultdict(list), defaultdict(list)
    verified_files = revalidated_operational = revalidated_frozen = revalidated_sources = 0
    rejected_sources = []
    objective_rejections = []
    stage1_solver_statuses = Counter()
    for job in expected_jobs:
        entry = completed[job["id"]]
        directory = (CAMPAIGN / entry["output"]).resolve()
        require(directory.is_relative_to((CAMPAIGN / "jobs").resolve()), "Evidence escapes campaign")
        inventory = {p.relative_to(directory).as_posix(): digest(p) for p in sorted(directory.rglob("*")) if p.is_file()}
        require(inventory == entry["evidence_sha256"], f"Changed evidence tree: {job['id']}")
        verified_files += len(inventory)
        result = read_json(directory / "result.json")
        require(result["complete"] and result["planned_scenario_count"] == 50, "Incomplete worker")
        require(result["shape"] == job["shape"] and result["method"] == job["method"] and result["load_multiplier"] == job["load"], "Worker identity changed")
        require(result["backend"] == config["backend"] and result["unit_convention"] == "coherent", "Scientific convention changed")
        require(digest(directory / "instance.json.gz") == result["instance_sha256"], "Input pointer changed")
        shape = tuple(job["shape"])
        case = make_scaling_experiment_case(*shape, load_multiplier=job["load"])
        instance = replace(case.instance, unit_convention=UnitConvention.COHERENT,
                           data_residency_hours=config["data_residency_hours"],
                           id=f"extended_{shape[0]}x{shape[1]}x{shape[2]}_load{job['load']:g}")
        require(_plain(instance) == read_gzip(directory / "instance.json.gz"), "Frozen input reconstruction differs")
        if (directory / "stage1.json.gz").exists():
            require(digest(directory / "stage1.json.gz") == result["stage1_evidence_sha256"], "Source pointer changed")
            saved_source = read_gzip(directory / "stage1.json.gz")
            saved_parallelism = saved_source["placement"]["parallelism_decisions"]
            saved_routing = RoutingDecisionState(**{key: mapping(value) for key, value in saved_parallelism["routing_decisions"].items()})
            source_state = PlacementDecisionState(
                ParallelismDecisionState(saved_routing, mapping(saved_parallelism["configuration_selectors"]), mapping(saved_parallelism["gpu_counts"])),
                mapping(saved_source["placement"]["auxiliary_products"]))
            source_report = validate_placement(instance, source_state, PaperVersion.V2, tolerances=ValidationTolerances(**saved_source["validation"]["tolerances"]))
            revalidated_sources += 1
            require(_plain(source_report) == saved_source["validation"], "Source validation replay differs")
            if saved_source["solver"] is not None:
                stage1_solver_statuses[saved_source["solver"]["result"]["status"]] += 1
            if not result["stage1_accepted"]:
                solver_result = saved_source["solver"]["result"] if saved_source["solver"] is not None else None
                independent_total = source_report.objective_breakdown.total if source_report.objective_breakdown is not None else None
                solver_total = solver_result["objective_value"] if solver_result else None
                rejected_sources.append({
                    "job": job["id"], "constraints_independently_feasible": source_report.is_feasible,
                    "violated_families": _plain(source_report.violated_families),
                    "solver_status": solver_result["status"] if solver_result else None,
                    "termination_condition": solver_result["termination_condition"] if solver_result else None,
                    "solver_objective": solver_total, "independent_objective": independent_total,
                    "objective_absolute_difference": abs(solver_total - independent_total) if solver_total is not None and independent_total is not None else None,
                })
        if not result["stage1_accepted"]:
            require(not result["attempts"] and result["aggregate"] is None and result["skipped_scenario_count"] == 50,
                    "Rejected source has operational metrics")
            source_rows.append({"job": job["id"], "source_accepted": False, "skipped_scenarios": 50})
            continue
        require(digest(directory / "stage1.json.gz") == result["stage1_evidence_sha256"], "Source pointer changed")
        source = read_gzip(directory / "stage1.json.gz")
        require(source["accepted"] is True, "Source acceptance differs")
        parallelism = source["placement"]["parallelism_decisions"]
        routing = parallelism["routing_decisions"]
        fixed = Stage2FixedDeployment(mapping(routing["admission_indicators"]),
                                      mapping(parallelism["configuration_selectors"]), mapping(parallelism["gpu_counts"]))
        nominal = SimpleNamespace(routing_fractions=mapping(routing["routing_fractions"]),
                                  unmet_fractions=mapping(routing["unmet_fractions"]))
        fixed_cost = compute_gpu_rental_cost(instance, fixed.gpu_counts) + compute_model_storage_cost(instance, fixed.admission_indicators)
        require(fixed_cost == result["fixed_cost_usd"], "Fixed objective changed")
        problem = PdmProblemData(instance)
        expected_scenarios = list(iter_stress_scenarios(instance, grid))
        require(len(result["attempts"]) == len(expected_scenarios) == 50, "Grid coverage mismatch")
        for index, (row, (arrival, stress, scenario)) in enumerate(zip(result["attempts"], expected_scenarios, strict=True)):
            require((row["index"], row["scenario_id"], row["arrival_factor"], row["stress_factor"]) ==
                    (index, scenario.id, arrival, stress), "Grid sequence changed")
            path = (directory / row["evidence"]).resolve()
            require(path.is_relative_to(directory) and digest(path) == row["evidence_sha256"], "Scenario pointer changed")
            evidence = read_gzip(path)
            require(evidence["realization"] == _plain(scenario), "Realized scientific coefficients changed")
            data = Stage2ProblemData(problem, fixed, scenario)
            run = evidence["operational_run"]
            fixed_evidence = {**_plain(fixed), "derived_deployment_indicators": _plain(data.derived_deployment_indicators)}
            require(run["fixed_deployment"] == fixed_evidence, "Operational deployment changed")
            require(run["status"] == row["stage2_status"] and row["successful"] == (run["status"] == "success"), "Success status differs")
            require(run["solver_evidence"]["result"]["status"] == row["solver_status"], "Solver status differs")
            require(run["solver_evidence"]["config"]["backend"] == config["backend"] and
                    run["solver_evidence"]["config"]["time_limit_seconds"] == config["stage2_solver_limit_seconds"], "Solver configuration changed")
            frozen = Stage2Solution(stage2_solution_identity(data), nominal.routing_fractions, nominal.unmet_fractions)
            frozen_report = validate_stage2_solution(data, frozen)
            revalidated_frozen += 1
            require(_plain(frozen_report) == evidence["frozen_routing_validation"] and
                    frozen_report.is_feasible == row["frozen_routing_feasible"], "Frozen validation replay differs")
            require((row["frozen_quality"] is not None) == frozen_report.is_feasible, "Invalid frozen cost usability")
            if frozen_report.is_feasible:
                costs = frozen_report.objective_breakdown
                expected = {**service_observations(instance, scenario, frozen, nominal),
                            "operational_cost_usd": costs.operational_objective,
                            "reporting_cost_usd": fixed_cost + costs.reported_variable_cost}
                require(expected == row["frozen_quality"], "Frozen indicators differ")
            if run["solution"] is not None and run["scientific_evidence"]["validation_report"] is not None:
                scientific = run["scientific_evidence"]
                raw = run["solution"]
                require(raw["identity"] == _plain(stage2_solution_identity(data)), "Solution identity changed")
                solution = Stage2Solution(stage2_solution_identity(data), mapping(raw["routing_fractions"]), mapping(raw["unmet_fractions"]))
                tolerances = Stage2ValidationTolerances(**scientific["validation_tolerances"])
                report = validate_stage2_solution(data, solution, tolerances)
                revalidated_operational += 1
                require(_plain(report) == scientific["validation_report"] and report.is_feasible == row["independently_feasible"], "Operational validation replay differs")
                costs = report.objective_breakdown
                comparison = scientific["objective_comparison"]
                difference = abs(comparison["solver_objective"] - comparison["independent_objective"])
                agreement = difference <= comparison["absolute_tolerance"]
                require(comparison["independent_objective"] == costs.operational_objective and agreement == row["objective_agrees"], "Objective evidence replay differs")
                if run["status"] == "objective_inconsistent":
                    require(report.is_feasible and not agreement and row["quality"] is None, "Numerical rejection classification differs")
                    objective_rejections.append({
                        "job": job["id"], "scenario_index": index, "absolute_difference": difference,
                        "relative_difference": difference / abs(comparison["independent_objective"]),
                        "ulp_difference_at_independent_scale": difference / ulp(comparison["independent_objective"]),
                        "absolute_tolerance": comparison["absolute_tolerance"],
                    })
            if row["successful"]:
                require(row["objective_agrees"] and row["independently_feasible"], "Accepted row lacks independent evidence")
                expected = {**service_observations(instance, scenario, solution, nominal),
                            "c3_usd": costs.realized_data_storage_cost, "c4_usd": costs.delay_penalty,
                            "c5_usd": costs.unmet_demand_penalty, "operational_cost_usd": costs.operational_objective,
                            "reporting_cost_usd": fixed_cost + costs.reported_variable_cost}
                require(row["quality"] == expected, "Operational indicators differ")
            else:
                require(row["quality"] is None, "Rejected LP has usable quality metrics")
            require(row["integrated_seconds"] >= 0, "Negative duration")
            all_rows.append(row)
            methods[job["method"]].append(row)
            shapes[("x".join(map(str, shape)), job["load"], job["method"])].append(row)
        accepted = [row for row in result["attempts"] if row["successful"]]
        require(result["accepted_scenario_count"] == len(accepted), "Accepted count differs")
        require(result["status_counts"] == dict(Counter(row["stage2_status"] for row in result["attempts"])), "Status counts differ")
        require((result["aggregate"] is not None) == (len(accepted) == 50), "Invalid full-grid mean")
        if len(accepted) == 50:
            expected_mean = {key: fsum(row["quality"][key] for row in accepted) / 50
                             for key in accepted[0]["quality"] if accepted[0]["quality"][key] is not None}
            require(result["aggregate"] == expected_mean, "Full-grid aggregate differs")
        source_rows.append({"job": job["id"], "source_accepted": True, "stage1_seconds": result["stage1_seconds"],
                            "job_wall_seconds": entry["wall_seconds"], "full_grid_accepted": len(accepted) == 50,
                            **summarize_rows(result["attempts"])})
    environment = read_json(CAMPAIGN / "environment.json")
    observations = read_json(CAMPAIGN / "power_observations.json")
    require(environment["ac_line_status"] == 1 and all(row["ac_line_status"] == 1 for row in observations), "AC context differs")
    report = {
        "audited_utc": datetime.now(timezone.utc).isoformat(), "audit_status": "passed",
        "configuration_sha256": read_json(CAMPAIGN / "snapshot_manifest.json")["configuration_sha256"],
        "analysis_helper_sha256": digest(Path(__file__)), "completed_jobs": 40,
        "accepted_sources": sum(row["source_accepted"] for row in source_rows),
        "full_grids_accepted": sum(row.get("full_grid_accepted", False) for row in source_rows),
        "stage1_solver_status_counts": dict(stage1_solver_statuses),
        "verified_job_files": verified_files, "fresh_frozen_validation_replays": revalidated_frozen,
        "fresh_operational_validation_replays": revalidated_operational,
        "fresh_stage1_validation_replays": revalidated_sources, "rejected_source_diagnostics": rejected_sources,
        "objective_rejection_diagnostics": objective_rejections,
        "job_wall_seconds_sum": fsum(row["wall_seconds"] for row in history),
        "overall": summarize_rows(all_rows),
        "methods": {key: summarize_rows(rows) for key, rows in sorted(methods.items())},
        "groups": [{"shape": key[0], "load": key[1], "method": key[2], **summarize_rows(rows)} for key, rows in sorted(shapes.items())],
        "sources": source_rows, "environment": environment, "power_observations": observations,
        "limitations": [
            "Deterministic synthetic sensitivity grid, not paper numerical replication or a real-world probability model.",
            "Only the clean AC restart enters this analysis; the superseded first attempt is preserved separately.",
            "Recorded Stage-1 and Stage-2/frozen constraint validation and indicators are replayed without solver reruns or decision repair.",
            "Published frozen scientific files are hash-checked; unused native binaries/private tests are excluded from this replay.",
            "Costs are paired only where frozen and adapted decisions are both usable; infeasible baselines receive no cost saving.",
            "Pooled counts include three AGH seeds and one GH/P_DM source per shape/load; pooled method costs are not a matched method ranking.",
            "Accepted-only service summaries are conditional on feasibility; an entire-grid mean requires fifty accepted LPs.",
            "Integrated LP duration excludes frozen validation, gzip/checkpoint I/O and worker startup.",
        ],
    }
    analysis = OUTPUT
    save_json(analysis / "analysis.json", report)
    shutil_source = Path(__file__)
    (analysis / "audit_helper.py").write_bytes(shutil_source.read_bytes())
    totals = report["overall"]
    lines = ["# Stage-2 deterministic stress campaign", "",
             f"Completed workers: **40/40**; accepted sources: **{report['accepted_sources']}/40**.",
             f"Attempted LPs: **{totals['attempted_scenarios']}**; accepted LPs: **{totals['accepted_scenarios']}**; fully accepted grids: **{report['full_grids_accepted']}/40**.",
             f"Worker wall durations total **{report['job_wall_seconds_sum'] / 60:.2f} minutes**. Fresh AC restart only.", "",
             f"Frozen routing fails in {totals['frozen_infeasible_scenarios']} scenarios; operational adaptation recovers {totals['recovered_scenarios']}",
             f"({100 * totals['recovery_fraction_of_frozen_failures']:.2f}% of those frozen failures).", "",
             "| Method | Attempted | Accepted | Frozen failures | Recovered | Paired costs | Paired reduction |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for method, row in report["methods"].items():
        reduction = row["paired_cost_reduction_fraction_of_baseline_sum"]
        label = f"{100 * reduction:.4f}%" if reduction is not None else "unavailable"
        lines.append(f"| {method} | {row['attempted_scenarios']} | {row['accepted_scenarios']} | {row['frozen_infeasible_scenarios']} | {row['recovered_scenarios']} | {row['paired_cost_scenarios']} | {label} |")
    lines += ["", "Paired reduction is (sum frozen C4+C5 − sum adapted C4+C5) / sum frozen C4+C5 on the same usable scenarios.",
              "", f"Fresh validation replay: {revalidated_sources} Stage-1 sources, {revalidated_frozen} frozen decisions and {revalidated_operational} extracted operational decisions (including numerical rejections); {verified_files} hashed job files verified.", "",
              "Recorded statuses: `" + json.dumps(totals["solver_status_counts"], sort_keys=True) + "`.", "",
              *["- " + item for item in report["limitations"]], ""]
    (analysis / "report.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(json.dumps({key: report[key] for key in ("audit_status", "completed_jobs", "accepted_sources", "full_grids_accepted", "fresh_operational_validation_replays", "job_wall_seconds_sum")}))
    print(json.dumps(totals))


if __name__ == "__main__":
    audit()
