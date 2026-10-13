"""Verify timing evidence and derive comparable statistics and paired costs.

Works with the local campaign or its portable recorded copy. No scientific
algorithm is rerun; all ratios identify the actual baseline and timer scope.
"""

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from statistics import median

from summarize_nightly_campaign import duration_statistics


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reduction_fraction(baseline, candidate):
    return (baseline - candidate) / baseline if baseline != 0 else None


def total_objective_cost(components):
    """Keep the reference breakdown's left-to-right C1..C5 addition order."""
    total = components[0]
    for component in components[1:]:
        total += component
    return total


def verify_finished_case(root, case):
    """Verify all retained pointers for a finished method in a stopped worker."""
    pointers = [(case[key], case[key + "_sha256"])
                for key in ("input", "python_golden", "full_cpp_evidence")]
    pointers += [(sample["evidence"], sample["evidence_sha256"]) for sample in case["samples"]]
    for relative, expected in pointers:
        path = (root / relative).resolve()
        if not path.is_relative_to(root.resolve()) or digest(path) != expected:
            raise ValueError("finished method evidence changed")


def analyze(directory):
    """Accept completed hashed jobs; retain incomplete coverage separately."""
    plan = read_json(directory / "plan.json")
    attempts = read_json(directory / "jobs.json") if (directory / "jobs.json").exists() else []
    completed = {item["id"]: item for item in attempts if item["status"] == "completed"}
    latest = {item["id"]: item for item in attempts}
    latest.update(completed)
    closed = (directory / "status.json").exists() and read_json(directory / "status.json")["status"] in ("completed", "incomplete", "interrupted")
    serial, parallel, costs = [], [], []
    verified_files = 0
    for job in plan["jobs"]:
        attempt = latest.get(job["id"])
        if attempt is None:
            continue
        partial_serial = job["kind"] == "serial" and closed and attempt["status"] in ("timeout", "worker_error", "interrupted")
        if attempt["status"] != "completed" and not partial_serial:
            continue
        root = (directory / attempt["output"]).resolve()
        if not root.is_relative_to((directory / "jobs").resolve()):
            raise ValueError("job evidence escapes recorded campaign")
        actual = {path.relative_to(root).as_posix(): digest(path)
                  for path in sorted(root.rglob("*")) if path.is_file()}
        if attempt["status"] == "completed" and actual != attempt["evidence_sha256"]:
            raise ValueError(f"recorded evidence changed: {job['id']}")
        verified_files += len(actual)
        if not (root / "profile.json").exists():
            continue
        profile = read_json(root / "profile.json")
        if job["kind"] == "serial":
            if not partial_serial and (not profile["complete"] or not profile["fingerprints_verified_unchanged"]):
                raise ValueError("serial profile is not completely verified")
            for case in profile["cases"]:
                if partial_serial:
                    verify_finished_case(root, case)
                if case["python_parity"]["bitwise_difference_count"] != 0:
                    raise ValueError("Python/C++ decisions differ bitwise")
                seconds = [value for sample in case["samples"] for value in sample["cpp_repeat_seconds"]]
                stats = duration_statistics(seconds)
                process = duration_statistics([sample["process_wall_seconds"] for sample in case["samples"]])
                serial.append({"job": job["id"], "method": case["method"], "shape": case["dimensions"],
                               "job_status": attempt["status"],
                               "verification_mode": "full_python_reference",
                               "feasible": case["feasible"], "input_sha256": case["input_sha256"],
                               "compared_numeric_values": case["python_parity"]["compared_numeric_values"],
                               "cpp_core": stats, "process_wall": process,
                               "python_reference_seconds": case["python_reference_check_seconds"],
                               "python_reference_to_cpp_median_ratio": case["python_reference_check_seconds"] / stats["median_seconds"],
                               "objective_components_usd": case["objective"]})
            by_method = {case["method"]: case for case in profile["cases"]}
            if "gh" in by_method and "agh" in by_method:
                gh, agh = by_method["gh"], by_method["agh"]
                if gh["input_sha256"] != agh["input_sha256"]:
                    raise ValueError("quality comparison requires the identical instance transport")
                if gh["feasible"] and agh["feasible"]:
                    gh_total, agh_total = total_objective_cost(gh["objective"]), total_objective_cost(agh["objective"])
                    costs.append({"shape": gh["dimensions"], "input_sha256": gh["input_sha256"],
                                  "gh_rental_usd": gh["objective"][0], "agh_rental_usd": agh["objective"][0],
                                  "rental_reduction_fraction": reduction_fraction(gh["objective"][0], agh["objective"][0]),
                                  "gh_total_usd": gh_total, "agh_total_usd": agh_total,
                                  "total_reduction_fraction": reduction_fraction(gh_total, agh_total)})
        elif job["kind"] == "openmp":
            if not profile["metadata"]["fingerprints_verified_unchanged"]:
                raise ValueError("OpenMP sources/binaries changed during measurement")
            for workload in profile["workloads"]:
                baseline = next(record for record in workload["scaling"] if record["schedule"] == "serial")
                base_core = median(sample["campaign_seconds"] for sample in baseline["samples"])
                base_process = median(sample["process_wall_seconds"] for sample in baseline["samples"])
                for record in workload["scaling"]:
                    actual_teams = {n for sample in record["samples"] for n in sample["repeat_threads"]}
                    if actual_teams != {record["actual_threads"]}:
                        raise ValueError("observed team changed across timing samples")
                    core = duration_statistics([sample["campaign_seconds"] for sample in record["samples"]])
                    process = duration_statistics([sample["process_wall_seconds"] for sample in record["samples"]])
                    speedup = base_core / core["median_seconds"]
                    parallel.append({"job": job["id"], "workload": workload["workload"],
                                     "batch_size": workload["job_count"], "schedule": record["schedule"],
                                     "requested_threads": record["requested_threads"], "actual_threads": record["actual_threads"],
                                     "core": core, "process_wall": process, "median_core_speedup": speedup,
                                     "median_core_efficiency": speedup / record["actual_threads"],
                                     "median_process_speedup": base_process / process["median_seconds"],
                                     "minimum_core_speedup": record["speedup"]})
    for path in sorted((directory / "native_validation").glob("*/profile.json")):
        record = read_json(path)
        if not record["complete"]:
            continue
        if not record["fingerprints_verified_unchanged"] or not record["independently_feasible"] or not record["objective_agrees_bitwise"]:
            raise ValueError("supplemental native result lacks independent acceptance")
        root = path.parent
        pointers = [(record[key], record[key + "_sha256"])
                    for key in ("input", "native_full_evidence", "python_validation_evidence")]
        pointers += [(sample["evidence"], sample["evidence_sha256"]) for sample in record["samples"]]
        for relative, expected in pointers:
            target = (root / relative).resolve()
            if not target.is_relative_to(root.resolve()) or digest(target) != expected:
                raise ValueError("supplemental native evidence changed")
        verified_files += len(pointers)
        if any(row["shape"] == record["shape"] and row["method"] == record["method"] for row in serial):
            raise ValueError("supplemental result duplicates an existing method measurement")
        core = duration_statistics([value for sample in record["samples"] for value in sample["cpp_repeat_seconds"]])
        process = duration_statistics([sample["process_wall_seconds"] for sample in record["samples"]])
        serial.append({"job": "supplemental_" + record["case"], "method": record["method"], "shape": record["shape"],
                       "job_status": "supplemental_completed", "verification_mode": "independent_final_decision",
                       "feasible": True, "input_sha256": record["input_sha256"], "compared_numeric_values": None,
                       "cpp_core": core, "process_wall": process, "python_reference_seconds": None,
                       "python_independent_validation_seconds": record["python_independent_validation_seconds"],
                       "python_reference_to_cpp_median_ratio": None, "objective_components_usd": record["objective_components_usd"]})
    growth = []
    for method in ("gh", "agh"):
        rows = sorted((row for row in serial if row["method"] == method and row["shape"][1:] == [4, 4]),
                      key=lambda row: row["shape"][0])
        if len(rows) > 1:
            first, last = rows[0], rows[-1]
            n_ratio = last["shape"][0] / first["shape"][0]
            t_ratio = last["cpp_core"]["median_seconds"] / first["cpp_core"]["median_seconds"]
            growth.append({"method": method, "first_shape": first["shape"], "last_shape": last["shape"],
                           "query_count_ratio": n_ratio, "core_median_time_ratio": t_ratio,
                           "endpoint_empirical_exponent": math.log(t_ratio) / math.log(n_ratio)})
    best = max((row for row in parallel if row["schedule"] != "serial"),
               key=lambda row: row["median_core_speedup"], default=None)
    return {"classification": "synthetic local CPU implementation performance, not paper numerical replication",
            "completed_jobs": len(completed), "planned_jobs": len(plan["jobs"]),
            "coverage": [{"id": job["id"], "kind": job["kind"],
                          "status": "completed" if job["id"] in completed else
                          next((item["status"] for item in reversed(attempts) if item["id"] == job["id"]), "not_run")}
                         for job in plan["jobs"]],
            "verified_files": verified_files, "serial": serial, "openmp": parallel,
            "paired_quality": costs, "query_growth": growth, "best_observed_median_setting": best,
            "limitations": ["Python reference includes projection/independent validation and is timed once; C++ core uses five individual samples.",
                            "OpenMP speedup uses serial execution in the identical campaign binary and the observed team size.",
                            "Minimum, median and full-process times are separate; IQR describes samples, not a confidence interval.",
                            "The empirical endpoint exponent describes this tested range, not a formal complexity bound.",
                            "Synthetic menu values and modeled costs are not measured GPUs or cloud bills.",
                            "A serial row from a stopped worker is a finished, checked method with retained samples; its job status remains explicit.",
                            "Supplemental native rows validate final decisions/objectives in Python; full Python heuristic parity and its runtime are unavailable.",
                            "The 40 Stage-2 stress jobs are outside this timing subset."]}


def save_report(output, report):
    output.mkdir(parents=True, exist_ok=True)
    (output / "analysis.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    rows = [{"shape": "x".join(map(str, row["shape"])), "method": row["method"],
             "job_status": row["job_status"],
             "verification_mode": row["verification_mode"],
             "cpp_min_seconds": row["cpp_core"]["minimum_seconds"], "cpp_median_seconds": row["cpp_core"]["median_seconds"],
             "cpp_iqr_seconds": row["cpp_core"]["iqr_seconds"], "process_median_seconds": row["process_wall"]["median_seconds"],
             "python_reference_seconds": row["python_reference_seconds"],
             "implementation_ratio": row["python_reference_to_cpp_median_ratio"], "feasible": row["feasible"]}
            for row in report["serial"]]
    if rows:
        with (output / "serial_timings.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    lines = ["# Larger allocation instances: measured CPU performance", "",
             f"Completed timing jobs: **{report['completed_jobs']}/{report['planned_jobs']}**. Verified recorded files: **{report['verified_files']}**.", "",
             "Finished methods retain all samples and checks; a timeout label refers to the two-method worker job.", "",
             "Supplemental native rows have independently checked final decisions; full Python algorithm parity is not claimed.", "",
             "| Shape (queries x models x tiers) | Method | Verification | Job state | C++ median (s) | IQR (s) | Process median (s) | Python reference (s) |", "|---|---|---|---|---:|---:|---:|---:|"]
    for row in report["serial"]:
        reference = "unavailable" if row["python_reference_seconds"] is None else f"{row['python_reference_seconds']:.3f}"
        lines.append(f"| {'x'.join(map(str, row['shape']))} | {row['method'].upper()} | {row['verification_mode']} | {row['job_status']} | {row['cpp_core']['median_seconds']:.6f} | "
                     f"{row['cpp_core']['iqr_seconds']:.6f} | {row['process_wall']['median_seconds']:.6f} | {reference} |")
    lines += ["", "| Batch | Workload | Schedule | Actual team | Median core speedup | Efficiency | Median process speedup |", "|---:|---|---|---:|---:|---:|---:|"]
    for row in report["openmp"]:
        lines.append(f"| {row['batch_size']} | {row['workload']} | {row['schedule']} | {row['actual_threads']} | "
                     f"{row['median_core_speedup']:.2f} | {row['median_core_efficiency']:.3f} | {row['median_process_speedup']:.2f} |")
    lines += ["", *[f"- {item}" for item in report["limitations"]]]
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = analyze(args.campaign.resolve())
    save_report(args.output.resolve(), result)
    print(json.dumps({key: result[key] for key in ("completed_jobs", "planned_jobs", "verified_files")}))
