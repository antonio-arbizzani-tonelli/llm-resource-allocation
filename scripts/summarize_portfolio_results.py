"""Recompute portfolio indicators from the shipped historical observations.

The default command uses only the standard library. It verifies retained file
hashes and never reruns a scientific method or changes a recorded observation.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from statistics import median


ROOT = Path(__file__).resolve().parents[1]


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_recorded_files(root: Path) -> list[dict]:
    """Check publication inputs against their retained integrity manifests."""
    records = read_json(root / "benchmarks/portfolio/raw/manifest.json")["files"]
    for record in records:
        if sha256(root / record["path"]) != record["sha256"]:
            raise ValueError(f"retained observation hash mismatch: {record['path']}")
    native = root / "benchmarks/portfolio/raw"
    for directory in ("serial", "validation/baseline"):
        profile = read_json(native / directory / "profile.json")
        for case in profile["cases"]:
            path = native / directory / "inputs" / f"{case['case']}.txt"
            if sha256(path) != case["input_sha256"]:
                raise ValueError(f"measured native transport hash mismatch: {case['case']}")
    for campaign in ("reference", "gurobi"):
        directory = root / "benchmarks" / campaign
        manifest = read_json(directory / "manifest.json")
        for name in ("runs.csv", "summary.csv", "query_metrics.csv"):
            expected = manifest["publication"]["files"][name]["sha256"]
            if sha256(directory / name) != expected:
                raise ValueError(f"recorded campaign hash mismatch: {campaign}/{name}")
    comparison = read_json(root / "benchmarks/backend_comparison/manifest.json")
    for role, campaign in (("reference", "reference"), ("candidate", "gurobi")):
        for name, field in (("runs.csv", "runs_sha256"), ("manifest.json", "manifest_sha256")):
            if sha256(root / "benchmarks" / campaign / name) != comparison["inputs"][role][field]:
                raise ValueError(f"matched backend input hash mismatch: {campaign}/{name}")
    return records


def percentage_reduction(baseline: float, candidate: float) -> float | None:
    return 100.0 * (baseline - candidate) / baseline if baseline else None


def accepted_median(rows: list[dict], field: str) -> float | None:
    values = [float(row[field]) for row in rows if row["accepted"] == "True" and row[field]]
    return median(values) if values else None


def summarize_stage1(root: Path) -> dict:
    campaigns = {}
    for campaign in ("reference", "gurobi"):
        rows = [row for row in read_csv(root / f"benchmarks/{campaign}/runs.csv")
                if row["is_warmup"] == "False"]
        summaries = []
        for case in dict.fromkeys(row["case_id"] for row in rows):
            for method in ("P_DM", "GH", "AGH"):
                group = [row for row in rows if row["case_id"] == case and row["method"] == method]
                summaries.append({
                    "case": case, "method": method, "attempted": len(group),
                    "accepted": sum(row["accepted"] == "True" for row in group),
                    "independently_feasible": sum(row["independently_feasible"] == "True" for row in group),
                    "optimal": sum(row["optimal"] == "True" for row in group),
                    "time_median_seconds": median(float(row["time_seconds"]) for row in group),
                    "objective_median_usd": accepted_median(group, "objective_total"),
                    "cost_component_medians_usd": {key: accepted_median(group, key)
                                                    for key in ("c1", "c2", "c3", "c4", "c5")},
                    "mean_unmet_fraction": accepted_median(group, "mean_unmet_fraction"),
                })
        campaigns[campaign] = {
            "measured_attempts": len(rows),
            "accepted": sum(row["accepted"] == "True" for row in rows),
            "independently_feasible": sum(row["independently_feasible"] == "True" for row in rows),
            "accepted_optima": sum(row["accepted"] == "True" and row["optimal"] == "True" for row in rows),
            "accepted_pdm_feasible_nonoptimal": sum(row["accepted"] == "True" and row["method"] == "P_DM"
                                                    and row["optimal"] == "False" for row in rows),
            "objective_disagreement_rejections": sum(row["accepted"] == "False"
                                                     and row["objective_agrees"] == "False" for row in rows),
            "summaries": summaries,
        }
    savings = []
    reference = campaigns["reference"]["summaries"]
    for case in dict.fromkeys(row["case"] for row in reference):
        group = {row["method"]: row for row in reference if row["case"] == case}
        gh, agh = group["GH"], group["AGH"]
        rental_gh, rental_agh = (row["cost_component_medians_usd"]["c1"] for row in (gh, agh))
        savings.append({
            "case": case, "gh_rental_usd": rental_gh, "agh_rental_usd": rental_agh,
            "rental_saving_usd": rental_gh - rental_agh,
            "rental_reduction_percent": percentage_reduction(rental_gh, rental_agh),
            "total_score_reduction_percent": percentage_reduction(
                gh["objective_median_usd"], agh["objective_median_usd"]),
            "other_component_differences_usd": {key: gh["cost_component_medians_usd"][key]
                                               - agh["cost_component_medians_usd"][key]
                                               for key in ("c2", "c3", "c4", "c5")},
            "gh_mean_unmet_fraction": gh["mean_unmet_fraction"],
            "agh_mean_unmet_fraction": agh["mean_unmet_fraction"],
        })
    backend_comparisons = []
    for case in dict.fromkeys(row["case"] for row in reference):
        values = {campaign: next(row["objective_median_usd"] for row in data["summaries"]
                                 if row["case"] == case and row["method"] == "P_DM")
                  for campaign, data in campaigns.items()}
        baseline, candidate = values["reference"], values["gurobi"]
        backend_comparisons.append({"case": case, "highs_accepted_median_usd": baseline,
                                    "gurobi_accepted_median_usd": candidate,
                                    "gurobi_reduction_percent": percentage_reduction(baseline, candidate)
                                    if baseline is not None and candidate is not None else None,
                                    "scope": "matched accepted P_DM objectives; large-case optimum unproven"})
    return {"scope": "coherent synthetic Stage-1 planning; three measured rounds, one excluded warmup",
            "campaigns": campaigns, "gh_to_agh": savings, "backend_comparisons": backend_comparisons}


def summarize_stage2(root: Path) -> dict:
    evidence = read_json(root / "benchmarks/stage2/reference.json")
    return {
        "evidence_kind": evidence["evidence_kind"],
        "scope": "hand-checkable coherent functionality example; no robustness or cost-saving campaign",
        "deployment_unchanged": evidence["deployment_unchanged"],
        "scenarios": [{
            "scenario": row["scenario_id"], "gpu_count": row["gpu_count"],
            "offered_requests_per_hour": row["realized_arrivals_per_hour"],
            "served_requests_per_hour": row["realized_arrivals_per_hour"] * row["routing_fraction"],
            "unmet_requests_per_hour": row["realized_arrivals_per_hour"] * row["unmet_fraction"],
            "routing_fraction": row["routing_fraction"], "unmet_fraction": row["unmet_fraction"],
            "independently_feasible": row["independently_feasible"],
            "solver_objective_agrees": row["solver_objective_agrees"],
            "total_reporting_cost_usd": row["costs_usd"]["total_reporting_cost"],
        } for row in evidence["scenarios"]],
    }


def summarize_serial(root: Path) -> list[dict]:
    profile = read_json(root / "benchmarks/portfolio/raw/serial/profile.json")
    results = []
    for case in profile["cases"]:
        python_min = min(value for sample in case["samples"] for value in sample["python_repeat_seconds"])
        cpp_min = min(value for sample in case["samples"] for value in sample["cpp_repeat_seconds"])
        results.append({"case": case["case"], "dimensions": case["dimensions"],
                        "python_min_seconds": python_min, "cpp_core_min_seconds": cpp_min,
                        "python_over_cpp_core_ratio": python_min / cpp_min,
                        "scope": "Windows Python public call / WSL C++ prepared-input core; different evidence costs"})
    return results


def summarize_openmp(root: Path) -> list[dict]:
    profile = read_json(root / "benchmarks/portfolio/raw/openmp/profile.json")
    results = []
    for workload in profile["workloads"]:
        serial = next(row for row in workload["scaling"] if row["schedule"] == "serial")
        serial_core = min(value for sample in serial["samples"] for value in sample["repeat_seconds"])
        serial_process = min(sample["process_wall_seconds"] for sample in serial["samples"])
        for setting in workload["scaling"]:
            teams = {team for sample in setting["samples"] for team in sample["repeat_threads"]}
            if len(teams) != 1:
                raise ValueError("the observed team changed within a recorded setting")
            team = teams.pop()
            core = min(value for sample in setting["samples"] for value in sample["repeat_seconds"])
            process = min(sample["process_wall_seconds"] for sample in setting["samples"])
            results.append({
                "workload": workload["workload"], "jobs": workload["job_count"],
                "schedule": setting["schedule"], "requested_threads": setting["requested_threads"],
                "actual_threads": team, "core_min_seconds": core,
                "core_speedup": serial_core / core, "core_efficiency_percent": 100.0 * serial_core / core / team,
                "core_batch_throughput_solves_per_second": workload["job_count"] / core,
                "process_min_seconds": process, "process_speedup": serial_process / process,
                "scope": "fixed independent-case batch; core includes team creation; parent process includes WSL/startup/transport",
            })
    return results


def summarize_validation(root: Path) -> list[dict]:
    results = []
    for policy in ("active", "passive"):
        profile = read_json(root / f"benchmarks/portfolio/raw/validation/{policy}/profile.json")
        for case in profile["cases"]:
            slots = next(row for row in case["variants"] if row["variant"] == "slots")
            slots_min = min(value for sample in slots["samples"] for value in sample["cpp_repeat_seconds"])
            for variant in case["variants"]:
                durations = [value for sample in variant["samples"] for value in sample["cpp_repeat_seconds"]]
                results.append({
                    "wait_policy": policy, "case": case["case"], "method": case["method"],
                    "queries": case["dimensions"][0], "variant": variant["variant"],
                    "core_min_seconds": min(durations), "core_median_seconds": median(durations),
                    "speedup_vs_serial_slots": slots_min / min(durations),
                    "scope": "experimental validator execution; rotated samples; production remains serial",
                })
    return results


def summarize_parity(root: Path) -> dict:
    serial = read_json(root / "benchmarks/portfolio/raw/serial/parity.json")
    placements = [case for case in serial["cases"] if case["method"] != "rng"]
    larger = read_json(root / "benchmarks/portfolio/raw/validation/baseline/profile.json")
    validation = read_json(root / "benchmarks/portfolio/raw/validation/verification.json")
    return {
        "serial_cases_passed": sum(case["passed"] for case in serial["cases"]),
        "serial_cases_total": len(serial["cases"]),
        "serial_placement_cases": len(placements),
        "serial_rng_cases": len(serial["cases"]) - len(placements),
        "serial_compared_final_numeric_values": sum(case["compared_numeric_values"] for case in placements),
        "serial_bitwise_difference_count": sum(case["bitwise_difference_count"] for case in placements),
        "larger_cases": len(larger["cases"]),
        "larger_compared_final_numeric_values": sum(case["python_parity"]["compared_numeric_values"] for case in larger["cases"]),
        "larger_bitwise_difference_count": sum(case["python_parity"]["bitwise_difference_count"] for case in larger["cases"]),
        "experimental_release_complete_comparisons": validation["release_full_scientific_comparisons"],
        "experimental_sanitizer_complete_comparisons": validation["sanitizer_full_scientific_comparisons"],
        "scope": "recorded bounded Python/C++ parity and experimental replay; case sets reported separately",
    }


def metric_rows(summary: dict) -> list[dict]:
    rows = []
    def add(section, case, metric, value, unit, scope, source):
        rows.append(dict(section=section, case=case, metric=metric, value=value,
                         unit=unit, scope=scope, source=source))
    for record in summary["stage1"]["gh_to_agh"]:
        for metric, unit in (("rental_saving_usd", "USD/horizon"),
                             ("rental_reduction_percent", "%"), ("total_score_reduction_percent", "%")):
            add("stage1", record["case"], metric, record[metric], unit,
                summary["stage1"]["scope"], "benchmarks/reference/runs.csv")
    for campaign, record in summary["stage1"]["campaigns"].items():
        for metric in ("measured_attempts", "accepted", "independently_feasible", "accepted_optima",
                       "accepted_pdm_feasible_nonoptimal", "objective_disagreement_rejections"):
            add("stage1", campaign, metric, record[metric], "count", summary["stage1"]["scope"],
                f"benchmarks/{campaign}/runs.csv")
    for record in summary["stage1"]["backend_comparisons"]:
        add("backend", record["case"], "gurobi_reduction_percent", record["gurobi_reduction_percent"], "%",
            record["scope"], "benchmarks/reference/runs.csv;benchmarks/gurobi/runs.csv")
    for record in summary["stage2"]["scenarios"]:
        for metric, unit in (("served_requests_per_hour", "requests/h"), ("unmet_requests_per_hour", "requests/h"),
                             ("total_reporting_cost_usd", "USD/horizon")):
            add("stage2_example", record["scenario"], metric, record[metric], unit,
                summary["stage2"]["scope"], "benchmarks/stage2/reference.json")
    for record in summary["serial_implementation"]:
        for metric, unit in (("python_min_seconds", "s"), ("cpp_core_min_seconds", "s"),
                             ("python_over_cpp_core_ratio", "ratio")):
            add("serial", record["case"], metric, record[metric], unit,
                record["scope"], "benchmarks/portfolio/raw/serial/profile.json")
    for record in summary["openmp"]:
        case = f"{record['workload']}/{record['schedule']}/{record['actual_threads']}"
        for metric, unit in (("core_min_seconds", "s"), ("core_speedup", "ratio"),
                             ("core_efficiency_percent", "%"), ("process_min_seconds", "s"),
                             ("process_speedup", "ratio"), ("core_batch_throughput_solves_per_second", "solves/s")):
            add("openmp", case, metric, record[metric], unit,
                record["scope"], "benchmarks/portfolio/raw/openmp/profile.json")
    for record in summary["validation_experiment"]:
        case = f"{record['wait_policy']}/{record['case']}/{record['variant']}"
        for metric, unit in (("core_min_seconds", "s"), ("core_median_seconds", "s"),
                             ("speedup_vs_serial_slots", "ratio")):
            add("validator", case, metric, record[metric], unit, record["scope"],
                f"benchmarks/portfolio/raw/validation/{record['wait_policy']}/profile.json")
    for metric, value in summary["parity"].items():
        if metric != "scope":
            add("parity", "recorded_campaigns", metric, value, "count", summary["parity"]["scope"],
                "benchmarks/portfolio/raw/serial/parity.json;benchmarks/portfolio/raw/validation/baseline/profile.json")
    return rows


def plot_results(summary: dict, output: Path) -> None:
    """Optional scientific figures, generated only from the derived tables."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "svg.hashsalt": "llm-resource-allocation-portfolio"})
    plots = output / "plots"
    plots.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.2), layout="constrained")
    for workload, color in (("uniform", "#2563a8"), ("mixed", "#ba4d20")):
        records = [row for row in summary["openmp"]
                   if row["workload"] == workload and row["schedule"] == "dynamic"]
        records.sort(key=lambda row: row["actual_threads"])
        label = "16 large AGH" if workload == "uniform" else "8 large AGH + 4 medium AGH + 4 GH"
        for ax, field in zip(axes, ("core_speedup", "process_speedup")):
            ax.plot([row["actual_threads"] for row in records], [row[field] for row in records],
                    marker="o", linewidth=2, color=color, label=label)
    axes[0].plot([1, 2, 4, 8], [1, 2, 4, 8], "--", color="#9aa0a6", label="Ideal strong scaling")
    for ax in axes:
        ax.set_xticks([1, 2, 4, 8]); ax.set_xlabel("Observed threads (dynamic scheduling)")
        ax.set_ylabel("Serial / parallel time"); ax.grid(axis="y", alpha=.2)
    axes[0].set_title("Campaign core: up to 5.16×")
    axes[1].set_title("Complete process: overhead and variability")
    axes[0].legend(fontsize=8, loc="upper left")
    axes[1].legend(fontsize=8, loc="upper left")
    fig.suptitle("Fixed synthetic allocation batches — repeated minima on Intel i7-13620H / WSL")
    for suffix in ("png", "svg"):
        fig.savefig(plots / f"openmp_scaling.{suffix}", dpi=180,
                    metadata={"Date": None} if suffix == "svg" else None)
    plt.close(fig)
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.0), layout="constrained")
    variants = ["slots", "omp2", "omp4", "omp8"]
    for ax, queries in zip(axes, (32, 64)):
        records = {row["variant"]: row for row in summary["validation_experiment"]
                   if row["wait_policy"] == "active" and row["method"] == "agh" and row["queries"] == queries}
        values = [records[variant]["core_min_seconds"] for variant in variants]
        ax.bar(["Serial slots", "OMP 2", "OMP 4", "OMP 8"], values,
               color=["#2563a8", "#bcc9d6", "#bcc9d6", "#bcc9d6"])
        ax.set_title(f"AGH: {queries} queries, 4 models, 4 tiers")
        ax.set_ylabel("Whole algorithm core minimum [s]"); ax.grid(axis="y", alpha=.2)
        for index, value in enumerate(values):
            ax.text(index, value, f"{value:.3f}", ha="center", va="bottom", fontsize=9)
        ax.set_ylim(0, max(values)*1.17)
    fig.suptitle("Finer parallelism was not promoted — active wait policy, rotated fixed-input runs")
    for suffix in ("png", "svg"):
        fig.savefig(plots / f"validation_grain.{suffix}", dpi=180,
                    metadata={"Date": None} if suffix == "svg" else None)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="published repository root")
    parser.add_argument("--output", type=Path, help="derived output directory; default benchmarks/portfolio")
    parser.add_argument("--plots", action="store_true", help="also render figures with optional Matplotlib")
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output.resolve() if args.output else root / "benchmarks/portfolio"
    retained = verify_recorded_files(root)
    sources = ["benchmarks/reference/runs.csv", "benchmarks/gurobi/runs.csv", "benchmarks/stage2/reference.json",
               "benchmarks/portfolio/raw/manifest.json",
               "benchmarks/portfolio/raw/serial/profile.json", "benchmarks/portfolio/raw/serial/parity.json",
               "benchmarks/portfolio/raw/openmp/profile.json",
               "benchmarks/portfolio/raw/validation/baseline/profile.json",
               "benchmarks/portfolio/raw/validation/verification.json",
               "benchmarks/portfolio/raw/validation/active/profile.json",
               "benchmarks/portfolio/raw/validation/passive/profile.json"]
    summary = {
        "schema_version": 1,
        "classification": "derived indicators from retained historical synthetic observations; not a new run",
        "measurement_dates": {"stage1_and_native_campaigns": "2026-10-11/12"},
        "source_sha256": {name: sha256(root / name) for name in sources},
        "verified_retained_file_count": len(retained),
        "formulas": {"reduction_percent": "100*(baseline-candidate)/baseline",
                     "speedup": "serial_min_seconds/parallel_min_seconds",
                     "efficiency_percent": "100*speedup/observed_threads",
                     "batch_throughput": "fixed_job_count/core_min_seconds"},
        "stage1": summarize_stage1(root), "stage2": summarize_stage2(root), "serial_implementation": summarize_serial(root),
        "openmp": summarize_openmp(root), "parity": summarize_parity(root),
        "validation_experiment": summarize_validation(root),
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False)+"\n", encoding="utf-8", newline="\n")
    rows = metric_rows(summary)
    with (output / "indicators.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)
    if args.plots:
        plot_results(summary, output)
    print(f"Verified {len(retained)} retained files; wrote {len(rows)} derived indicators.")


if __name__ == "__main__":
    main()
