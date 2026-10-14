"""Replay published Stage-2 evidence under an opt-in objective policy.

The archive and its historical classifications remain untouched. No solver is
invoked; all available domain reports and observed objectives are rechecked.
"""

import argparse
from collections import Counter, defaultdict
import csv
from dataclasses import replace
import gzip
import hashlib
import json
from math import fsum, ulp
from pathlib import Path
import platform
from random import Random
import sys
from types import SimpleNamespace
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts.run_azure_replay import _plain
from llm_resource_allocation.data.scaling_experiment_instances import make_scaling_experiment_case
from llm_resource_allocation.domain import UnitConvention
from llm_resource_allocation.experiments.stress_grid import StressGrid, iter_stress_scenarios, service_observations
from llm_resource_allocation.math.objective import PaperVersion
from llm_resource_allocation.math.parallelism import ParallelismDecisionState
from llm_resource_allocation.math.placement import PlacementDecisionState
from llm_resource_allocation.math.routing import RoutingDecisionState
from llm_resource_allocation.optimization.problem_data import PdmProblemData
from llm_resource_allocation.optimization.stage2_extraction import Stage2Solution, stage2_solution_identity
from llm_resource_allocation.optimization.stage2_problem_data import Stage2FixedDeployment, Stage2ProblemData
from llm_resource_allocation.validation.objective_comparison import ObjectiveComparison
from llm_resource_allocation.validation.placement import ValidationTolerances, validate_placement
from llm_resource_allocation.validation.stage2 import Stage2ValidationTolerances, validate_stage2_solution

RELATIVE_SWEEP = (0.0, 1e-12, 1e-11, 1e-10, 1e-9, 1e-8, 1e-7, 1e-6)
SELECTED_RELATIVE = 1e-12


def sha256(value):
    return hashlib.sha256(value).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def mapping(value):
    if isinstance(value, dict):
        return dict(value)
    result = {tuple(item["key"]): item["value"] for item in value}
    require(len(result) == len(value), "duplicate scientific mapping key")
    return result


def saved_placement(value):
    parallel = value["parallelism_decisions"]
    routing = RoutingDecisionState(**{name: mapping(items)
        for name, items in parallel["routing_decisions"].items()})
    return PlacementDecisionState(ParallelismDecisionState(routing,
        mapping(parallel["configuration_selectors"]), mapping(parallel["gpu_counts"])),
        mapping(value["auxiliary_products"]))


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".pending")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def percentile(sorted_values, fraction):
    position = (len(sorted_values)-1)*fraction
    lower = int(position)
    upper = min(lower+1, len(sorted_values)-1)
    return sorted_values[lower] + (position-lower)*(sorted_values[upper]-sorted_values[lower])


def paired_bootstrap(paired, rounds, seed, cluster):
    """Resample corresponding baseline/adapted costs together, using a local RNG."""
    groups = defaultdict(list)
    for index, row in enumerate(paired):
        groups[row["job"] if cluster else index].append(row)
    values = [(fsum(row["frozen_cost_usd"] for row in group),
               fsum(row["adapted_cost_usd"] for row in group)) for group in groups.values()]
    if not values:
        return {"unit": "source_grid" if cluster else "scenario_pair", "units": 0,
                "replicates": rounds, "seed": seed, "ci95": None}
    rng = Random(seed)
    estimates = []
    for _ in range(rounds):
        selected = [values[rng.randrange(len(values))] for _ in values]
        baseline = fsum(value[0] for value in selected)
        adapted = fsum(value[1] for value in selected)
        if baseline:
            estimates.append((baseline-adapted)/baseline)
    estimates.sort()
    return {"unit": "source_grid" if cluster else "scenario_pair", "units": len(values),
            "replicates": rounds, "seed": seed,
            "ci95": [percentile(estimates, 0.025), percentile(estimates, 0.975)] if estimates else None,
            "interpretation": "conditional synthetic sensitivity; no real-world probability inference"}


def summarize(rows, relative, bootstrap_rounds, seed):
    usable = [row for row in rows if row["independently_feasible"] and
              row["solver_objective"] is not None and ObjectiveComparison(
                  row["solver_objective"], row["independent_objective"],
                  row["absolute_tolerance"], relative).agrees]
    frozen_failed = [row for row in rows if not row["frozen_feasible"]]
    recovered = [row for row in usable if not row["frozen_feasible"]]
    paired = [row for row in usable if row["frozen_feasible"]]
    baseline = fsum(row["frozen_cost_usd"] for row in paired)
    adapted = fsum(row["adapted_cost_usd"] for row in paired)
    result = {"relative_tolerance": relative, "attempted": len(rows), "usable": len(usable),
              "newly_usable": sum(not row["old_usable"] for row in usable),
              "frozen_failures": len(frozen_failed), "recovered": len(recovered),
              "recovery_fraction": len(recovered)/len(frozen_failed) if frozen_failed else None,
              "paired_scenarios": len(paired), "paired_source_grids": len({row["job"] for row in paired}),
              "paired_baseline_cost_sum_usd": baseline, "paired_adapted_cost_sum_usd": adapted,
              "paired_reduction_fraction": (baseline-adapted)/baseline if baseline else None}
    if bootstrap_rounds:
        result["source_cluster_bootstrap"] = paired_bootstrap(paired, bootstrap_rounds, seed, True)
        result["scenario_pair_bootstrap_sensitivity"] = paired_bootstrap(paired, bootstrap_rounds, seed, False)
    return result


class EvidenceArchive:
    """Verify all portable bytes before providing read-only scientific evidence."""

    def __init__(self, directory):
        self.directory = directory
        self.manifest = json.loads((directory/"evidence_manifest.json").read_text(encoding="utf-8"))
        self.path = directory/"evidence.zip"
        require(sha256(self.path.read_bytes()) == self.manifest["archive_sha256"], "archive hash mismatch")
        self.archive = zipfile.ZipFile(self.path)
        files = self.manifest["files"]
        require(set(self.archive.namelist()) == {entry["path"] for entry in files}, "archive membership mismatch")
        for entry in files:
            value = self.archive.read(entry["path"])
            require(len(value) == entry["bytes"] and sha256(value) == entry["sha256"], "entry hash mismatch: "+entry["path"])
        self.source_path = directory/"scientific-source-snapshot.zip"
        self.sources = zipfile.ZipFile(self.source_path)
        snapshot_manifest = self.read("snapshot_manifest.json")
        self.verified_source_files = 0
        for name in self.sources.namelist():
            if name == "configs/nightly_campaign.json":
                continue
            require(sha256(self.sources.read(name)) == snapshot_manifest["source_sha256"].get(name),
                    "frozen source hash mismatch: "+name)
            self.verified_source_files += 1

    def read(self, name):
        value = self.sources.read(name.removeprefix("snapshot/")) if name.startswith("snapshot/") else self.archive.read(name)
        return json.loads(gzip.decompress(value) if name.endswith(".gz") else value)

    def close(self):
        self.archive.close()
        self.sources.close()


def replay(directory):
    evidence = EvidenceArchive(directory)
    try:
        config = evidence.read("snapshot/configs/nightly_campaign.json")
        jobs = evidence.read("jobs.json")
        grid = StressGrid(tuple(config["arrival_factors"]), tuple(config["stress_factors"]))
        rows, rejected_sources = [], []
        counts = Counter()
        counts["frozen_source_files"] = evidence.verified_source_files
        for job in jobs:
            require(job["status"] == "completed", "historical job incomplete")
            base = job["output"].replace("\\", "/")
            result = evidence.read(base+"/result.json")
            shape, load = result["shape"], result["load_multiplier"]
            instance = replace(make_scaling_experiment_case(*shape, load_multiplier=load).instance,
                unit_convention=UnitConvention.COHERENT, data_residency_hours=config["data_residency_hours"],
                id=f"extended_{shape[0]}x{shape[1]}x{shape[2]}_load{load:g}")
            require(_plain(instance) == evidence.read(base+"/instance.json.gz"), "instance reconstruction changed")
            source = evidence.read(base+"/stage1.json.gz")
            nominal = saved_placement(source["placement"])
            source_report = validate_placement(instance, nominal, PaperVersion.V2,
                tolerances=ValidationTolerances(**source["validation"]["tolerances"]))
            require(_plain(source_report) == source["validation"], "source report replay changed")
            counts["stage1_reports"] += 1
            if not result["stage1_accepted"]:
                require(not result["attempts"] and result["aggregate"] is None, "rejected source has scenarios")
                rejected_sources.append({"job": job["id"], "shape": shape, "load": load,
                    "violated_families": _plain(source_report.violated_families), "skipped_scenarios": 50})
                continue
            counts["accepted_sources"] += 1
            require(source_report.is_feasible, "accepted source failed independent replay")
            fixed = Stage2FixedDeployment(nominal.admission_indicators,
                nominal.configuration_selectors, nominal.gpu_counts)
            problem = PdmProblemData(instance)
            scenarios = tuple(iter_stress_scenarios(instance, grid))
            require(len(result["attempts"]) == len(scenarios) == 50, "historical grid changed")
            for old, (arrival, stress, scenario) in zip(result["attempts"], scenarios, strict=True):
                saved = evidence.read(base+"/"+old["evidence"])
                require(saved["realization"] == _plain(scenario), "scenario coefficients changed")
                data = Stage2ProblemData(problem, fixed, scenario)
                frozen = Stage2Solution(stage2_solution_identity(data), nominal.routing_fractions, nominal.unmet_fractions)
                frozen_report = validate_stage2_solution(data, frozen)
                require(_plain(frozen_report) == saved["frozen_routing_validation"], "frozen report changed")
                counts["frozen_reports"] += 1
                run = saved["operational_run"]
                feasible = False
                solver_value = independent = adapted = None
                absolute = 1e-8
                quality = None
                comparison = run["scientific_evidence"]["objective_comparison"]
                if run["solution"] is not None:
                    raw = run["solution"]
                    solution = Stage2Solution(stage2_solution_identity(data), mapping(raw["routing_fractions"]), mapping(raw["unmet_fractions"]))
                    report = validate_stage2_solution(data, solution,
                        Stage2ValidationTolerances(**run["scientific_evidence"]["validation_tolerances"]))
                    require(_plain(report) == run["scientific_evidence"]["validation_report"], "operational report changed")
                    counts["operational_reports"] += 1
                    feasible = report.is_feasible
                    if comparison is not None:
                        solver_value = comparison["solver_objective"]
                        independent = report.objective_breakdown.operational_objective
                        absolute = comparison["absolute_tolerance"]
                        require(comparison["independent_objective"] == independent, "saved objective changed")
                        require(ObjectiveComparison(solver_value, independent, absolute).agrees == old["objective_agrees"], "old agreement changed")
                        adapted = independent
                        costs = report.objective_breakdown
                        quality = {**service_observations(instance, scenario, solution, nominal),
                            "c3_usd": costs.realized_data_storage_cost, "c4_usd": costs.delay_penalty,
                            "c5_usd": costs.unmet_demand_penalty, "operational_cost_usd": independent}
                require(old["successful"] == (feasible and comparison is not None and ObjectiveComparison(
                    solver_value, independent, absolute).agrees), "old usability changed")
                require(old["independently_feasible"] == feasible, "old feasibility changed")
                new_usable = feasible and comparison is not None and ObjectiveComparison(
                    solver_value, independent, absolute, SELECTED_RELATIVE).agrees
                rows.append({"job": job["id"], "method": result["method"], "shape": "x".join(map(str,shape)),
                    "load": load, "index": old["index"], "arrival_factor": arrival, "stress_factor": stress,
                    "historical_stage2_status": old["stage2_status"], "solver_status": old["solver_status"],
                    "old_usable": old["successful"], "new_usable": new_usable, "independently_feasible": feasible,
                    "frozen_feasible": frozen_report.is_feasible, "solver_objective": solver_value,
                    "independent_objective": independent, "absolute_tolerance": absolute,
                    "absolute_difference": abs(solver_value-independent) if comparison is not None else None,
                    "relative_difference": abs(solver_value-independent)/max(abs(solver_value),abs(independent)) if comparison is not None and max(abs(solver_value),abs(independent)) else None,
                    "ulp_difference": abs(solver_value-independent)/ulp(independent) if comparison is not None else None,
                    "frozen_cost_usd": frozen_report.objective_breakdown.operational_objective if frozen_report.is_feasible else None,
                    "adapted_cost_usd": adapted, "replayed_quality": quality if new_usable else None,
                    "evidence": base+"/"+old["evidence"], "evidence_sha256": old["evidence_sha256"]})
        require(len(rows) == 1850 and counts["operational_reports"] == 850, "historical replay denominator changed")
        require(sum(row["historical_stage2_status"] == "objective_inconsistent" for row in rows) == 204, "objective rejection count changed")
        return rows, rejected_sources, dict(counts), evidence.manifest["archive_sha256"]
    finally:
        evidence.close()


def plots(output, summary):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(10, 4), layout="constrained")
    labels = ["Absolute default", "Opt-in relative 1e-12"]
    policies = (summary["old_policy"], summary["selected_policy"])
    axes[0].bar(labels, [value["usable"] for value in policies], color=("#777777", "#245b9c"))
    axes[0].set_ylabel("Usable operational attempts / 1,850")
    for i,value in enumerate(policies):
        axes[0].text(i,value["usable"],str(value["usable"]),ha="center",va="bottom")
    axes[0].set_ylim(0,1000)
    for i,value in enumerate(policies):
        reduction = value["paired_reduction_fraction"]*100
        interval = value["source_cluster_bootstrap"]["ci95"]
        axes[1].errorbar(i,reduction,yerr=[[reduction-interval[0]*100], [interval[1]*100-reduction]],
                        fmt="o", capsize=5, color=("#777777", "#245b9c")[i])
    axes[1].set_xticks((0,1),labels)
    axes[1].set_ylabel("Paired C4+C5 reduction (%)")
    axes[1].set_title("95% source-grid bootstrap; conditional pairs")
    for suffix in ("png", "svg"):
        fig.savefig(output/"plots"/f"policy_comparison.{suffix}", dpi=180)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=ROOT/"benchmarks/stage2_stress_2026-10-13")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bootstrap-rounds", type=int, default=10000)
    parser.add_argument("--bootstrap-seed", type=int, default=20261014)
    args = parser.parse_args()
    require(args.bootstrap_rounds > 0, "bootstrap rounds must be positive")
    output = args.output.resolve()
    require(output != args.archive.resolve() and not output.is_relative_to(args.archive.resolve()), "derived output must be separate")
    require((output/"PLAN.md").is_file(), "write PLAN.md before replay")
    rows, rejected, verification, digest = replay(args.archive)
    summary = {"classification": "SYNTHETIC_SOLVER_FREE_POLICY_REPLAY", "python": platform.python_version(),
        "historical_archive_sha256": digest, "historical_archive_entry_count": 2027,
        "replay_verification": verification, "stage1_rejected_sources_unchanged": rejected,
        "absolute_tolerance_default_unchanged": 1e-8, "relative_tolerance_default_unchanged": 0.0,
        "selected_relative_tolerance": SELECTED_RELATIVE,
        "cohort_limit": "three AGH seeds, one GH/P_DM source; no matched method ranking",
        "old_policy": summarize(rows, 0.0, args.bootstrap_rounds, args.bootstrap_seed),
        "selected_policy": summarize(rows, SELECTED_RELATIVE, args.bootstrap_rounds, args.bootstrap_seed),
        "sensitivity": [summarize(rows, relative, 0, args.bootstrap_seed) for relative in RELATIVE_SWEEP],
        "by_load": {str(load): {"old": summarize([r for r in rows if r["load"]==load], 0.0,args.bootstrap_rounds,args.bootstrap_seed),
                                "new": summarize([r for r in rows if r["load"]==load], SELECTED_RELATIVE,args.bootstrap_rounds,args.bootstrap_seed)}
                    for load in sorted({row["load"] for row in rows})},
        "source_hashes": {path.relative_to(ROOT).as_posix():sha256(path.read_bytes()) for path in
            (Path(__file__), ROOT/"src/llm_resource_allocation/validation/objective_comparison.py",
             ROOT/"src/llm_resource_allocation/optimization/stage2_run.py")}}
    summary["maximum_all_extracted_relative_difference"] = max(row["relative_difference"] or 0 for row in rows)
    summary["maximum_rejected_relative_difference"] = max(row["relative_difference"] or 0 for row in rows
        if row["historical_stage2_status"] == "objective_inconsistent")
    summary["mutation_check"] = {"relative_error": abs(1e8*(1+2e-6)-1e8)/abs(1e8*(1+2e-6)),
        "selected_policy_rejects": not ObjectiveComparison(1e8*(1+2e-6),1e8,relative_tolerance=SELECTED_RELATIVE).agrees}
    require(summary["mutation_check"]["selected_policy_rejects"], "mutation accepted")
    save_json(output/"analysis.json",summary)
    save_json(output/"replayed_attempts.json",rows)
    csv_fields = [name for name in rows[0] if name != "replayed_quality"]
    with (output/"attempts.csv").open("w",newline="",encoding="utf-8") as stream:
        writer = csv.DictWriter(stream,fieldnames=csv_fields)
        writer.writeheader()
        writer.writerows({name:row[name] for name in csv_fields} for row in rows)
    (output/"plots").mkdir(exist_ok=True)
    plots(output,summary)
    old,new = summary["old_policy"],summary["selected_policy"]
    report = f"""# Stage-2 opt-in objective policy replay

All 2,027 archive entries pass SHA-256 verification. Independent replay verifies
40 Stage-1 reports, 1,850 frozen-routing reports and 850 extracted Stage-2 reports.
The original archive and its classifications remain unchanged; no LP was solved.

| Policy | Usable / attempted | New usable / objective rejections | Recovered / frozen failures | Paired cost scenarios | Paired C4+C5 reduction |
|---|---:|---:|---:|---:|---:|
| Absolute 1e-8 default | {old['usable']}/1850 | 0/204 | {old['recovered']}/{old['frozen_failures']} | {old['paired_scenarios']} | {old['paired_reduction_fraction']:.6%} |
| Opt-in relative 1e-12 | {new['usable']}/1850 | {new['newly_usable']}/204 | {new['recovered']}/{new['frozen_failures']} | {new['paired_scenarios']} | {new['paired_reduction_fraction']:.6%} |

The pooled paired figure divides the difference of cost sums by the frozen cost
sum over the same usable pairs. Frozen-infeasible decisions receive no baseline
cost savings. The selected-policy source-grid bootstrap 95% interval is
{new['source_cluster_bootstrap']['ci95']}; the paired denominator is
{new['paired_scenarios']} scenarios in {new['paired_source_grids']} contributing
source grids. Resampling unit, seed and 10,000 replicates are recorded in JSON.
Scenario-pair intervals are separately labeled sensitivity because grid points
within one deployment are dependent. Neither interval estimates a real-world
probability from this deterministic synthetic design.

All seven requested nonzero sensitivity coefficients recover the same objective
rejections. A 2e-6 injected relative error remains rejected under the selected
1e-12 policy. Recorded maximum relative disagreement is
{summary['maximum_rejected_relative_difference']:.17g} among the 204 rejections;
the all-extracted maximum is separately recorded in JSON. Raw values remain intact.
No general solver-precision guarantee follows from this finite evidence.

All 1,000 solver-infeasible attempts remain unusable. Three rejected Stage-1
sources still skip 150 scenarios. Method cohorts remain unmatched and are not
ranked. Per-load denominators and paired bootstrap intervals are in analysis.json.

Replay: `python scripts/replay_stage2_policy.py --output benchmarks/stage2_policy_2026-10-14`.
Historical raw evidence: `../stage2_stress_2026-10-13/evidence.zip`; each new row
retains its original archive entry and SHA-256. The opt-in rule is
`|a-b| <= max(abs_tol, rel_tol * max(|a|,|b|))`; relative zero preserves defaults.
"""
    (output/"README.md").write_text(report,encoding="utf-8")
    inventory={path.relative_to(output).as_posix():sha256(path.read_bytes())
        for path in sorted(output.rglob("*")) if path.is_file() and path.name!="artifact_hashes.json"}
    save_json(output/"artifact_hashes.json",inventory)
    print(json.dumps({"usable_old":old["usable"],"usable_new":new["usable"],
                      "newly_usable":new["newly_usable"],"verified":verification}))


if __name__ == "__main__":
    main()
