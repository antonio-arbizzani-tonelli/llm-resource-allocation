"""Summarize retained campaign evidence without inventing unexecuted results."""

import argparse
import csv
import hashlib
import json
from pathlib import Path
from statistics import median, quantiles


def duration_statistics(values):
    """Keep minimum and median separate; use linear inclusive quartiles."""
    if not values:
        raise ValueError("duration statistics require observed samples")
    q1, _, q3 = quantiles(values, n=4, method="inclusive") if len(values) > 1 else (values[0],) * 3
    return {"count": len(values), "minimum_seconds": min(values),
            "median_seconds": median(values), "q1_seconds": q1, "q3_seconds": q3,
            "iqr_seconds": q3 - q1}


def write_csv(path, rows):
    if not rows:
        return
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def summarize(output):
    plan = json.loads((output / "plan.json").read_text(encoding="utf-8"))
    status = json.loads((output / "status.json").read_text(encoding="utf-8"))
    manifest = json.loads((output / "snapshot_manifest.json").read_text(encoding="utf-8"))
    history_path = output / "jobs.json"
    history = json.loads(history_path.read_text(encoding="utf-8")) if history_path.exists() else []
    latest = {record["id"]: record for record in history}
    # Completed attempts have precedence over any earlier timed-out attempts.
    latest.update({record["id"]: record for record in history if record["status"] == "completed"})
    stress, stress_sources, serial, parallel, coverage = [], [], [], [], []
    for job in plan["jobs"]:
        attempt = latest.get(job["id"])
        state = attempt["status"] if attempt else "not_run"
        coverage.append({"id": job["id"], "kind": job["kind"], "status": state})
        if not attempt:
            continue
        directory = (output / attempt["output"]).resolve()
        if not directory.is_relative_to((output / "jobs").resolve()):
            raise ValueError("job evidence escapes campaign directory")
        if state == "completed":
            actual = {path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                      for path in sorted(directory.rglob("*")) if path.is_file()}
            if actual != attempt["evidence_sha256"]:
                raise RuntimeError(f"completed evidence changed: {job['id']}")
        record_path = directory / ("result.json" if job["kind"] == "stress" else "profile.json")
        if not record_path.exists():
            continue
        record = json.loads(record_path.read_text(encoding="utf-8"))
        if job["kind"] == "stress":
            coverage[-1].update(stage1_accepted=record.get("stage1_accepted"),
                                attempted_scenarios=len(record["attempts"]),
                                accepted_scenarios=sum(item["successful"] for item in record["attempts"]))
            frozen_failures = sum(not item["frozen_routing_feasible"] for item in record["attempts"])
            recovered = sum(item["successful"] and not item["frozen_routing_feasible"] for item in record["attempts"])
            stress_sources.append({"job": job["id"], "job_status": state,
                                   "stage1_accepted": record.get("stage1_accepted"),
                                   "planned_scenarios": record["planned_scenario_count"],
                                   "attempted_scenarios": len(record["attempts"]),
                                   "accepted_scenarios": coverage[-1]["accepted_scenarios"],
                                   "frozen_routing_infeasible_count": frozen_failures,
                                   "recovered_feasibility_count": recovered,
                                   "recovery_fraction_of_attempted_frozen_failures": recovered / frozen_failures if frozen_failures else None,
                                   "full_grid_quality_mean": record.get("aggregate")})
            for item in record["attempts"]:
                stress.append({"job": job["id"], "job_status": state, "complete_grid": record["complete"],
                               **{key: value for key, value in item.items() if key not in ("quality", "frozen_quality")},
                               **(item["quality"] or {}),
                               **{"frozen_" + key: value for key, value in (item.get("frozen_quality") or {}).items()}})
        elif state == "completed" and job["kind"] == "serial":
            for case in record["cases"]:
                values = [value for sample in case["samples"] for value in sample["cpp_repeat_seconds"]]
                stats = duration_statistics(values)
                serial.append({"job": job["id"], "case": case["case"], "method": case["method"],
                               "shape": "x".join(map(str, case["dimensions"])), "feasible": case["feasible"],
                               **stats, "process_wall_min_seconds": case["process_wall_min_seconds"],
                               "python_reference_check_seconds": case["python_reference_check_seconds"],
                               "implementation_ratio_to_cpp_min": case["python_reference_check_seconds"] / stats["minimum_seconds"]})
        elif state == "completed":
            for workload in record["workloads"]:
                baseline = next(item for item in workload["scaling"] if item["schedule"] == "serial")
                baseline_median = median(sample["campaign_seconds"] for sample in baseline["samples"])
                baseline_wall = min(sample["process_wall_seconds"] for sample in baseline["samples"])
                for setting in workload["scaling"]:
                    stats = duration_statistics([sample["campaign_seconds"] for sample in setting["samples"]])
                    parallel.append({"job": job["id"], "workload": workload["workload"],
                                     "schedule": setting["schedule"], "requested_threads": setting["requested_threads"],
                                     "actual_threads": setting["actual_threads"], **stats,
                                     "core_min_speedup": setting["speedup"], "core_min_efficiency": setting["efficiency"],
                                     "core_median_speedup": baseline_median / stats["median_seconds"],
                                     "process_min_speedup": baseline_wall / min(sample["process_wall_seconds"] for sample in setting["samples"])})
    report = {"status": status["status"], "configuration_sha256": manifest["configuration_sha256"],
              "coverage": coverage, "stress_sources": stress_sources, "stress_scenarios": stress, "serial_profiles": serial, "openmp_profiles": parallel,
              "limitations": ["Synthetic sensitivity study, not paper numerical replication or real GPU inference.",
                              "Rejected scenarios have no usable cost/service values; incomplete grids have no full-grid mean.",
                              "Serial implementation ratios compare one Python reference check with C++ core minima, with different scopes.",
                              "OpenMP accelerates independent cases; minimum, median and process measures are distinct."]}
    (output / "summary.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    write_csv(output / "stress_scenarios.csv", stress)
    write_csv(output / "serial_profiles.csv", serial)
    write_csv(output / "openmp_profiles.csv", parallel)
    completed = sum(item["status"] == "completed" for item in coverage)
    lines = ["# Allocation campaign evidence", "", f"Status: **{status['status']}**. Completed jobs: **{completed}/{len(coverage)}**.", "",
             f"Configuration SHA256: `{manifest['configuration_sha256']}`.", "",
             "No experimental measurements exist yet." if not history else
             "Raw evidence and per-attempt logs are retained; CSV files contain observed values only.", "",
             *[f"- {item}" for item in report["limitations"]], "",
             "| Job | State |", "|---|---|"]
    lines += [f"| {item['id']} | {item['status']} |" for item in coverage]
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    summarize(parser.parse_args().output.resolve())
