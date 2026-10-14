"""Opt-in native scaling over independently seeded synthetic instance inputs."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import csv
import gzip
import hashlib
import json
from math import exp, isfinite, log
from pathlib import Path
from random import Random
from statistics import median
import sys
from time import perf_counter

from check_cpp_parity import ROOT, ParityCase, decode_placement, objective_array, serialize_case
from check_openmp_campaign import verify_bitwise
from extension_instances import seeded_instance
from extension_statistics import quantile, timing_summary
from llm_resource_allocation.validation.placement import validate_placement
import run_matched_runtime as matched


DEFAULT_OUTPUT = ROOT / "benchmarks/instance_scaling_2026-10-14"
INSTANCE_SEEDS = (11, 23, 37, 41, 53)
QUERY_COUNTS = (16, 32, 64, 128, 256, 384)
MENUS = ((4, 4), (8, 4), (8, 8), (12, 12))


def matrix_specifications():
    """Reuse the identical 64x4x4 instance in both query/menu analyses."""
    shapes = [(count, 4, 4) for count in QUERY_COUNTS]
    shapes.extend((64, models, tiers) for models, tiers in MENUS if (models, tiers) != (4, 4))
    for shape in shapes:
        families = ["query"] if shape[1:] == (4, 4) else []
        if shape[0] == 64:
            families.append("menu")
        for instance_seed in INSTANCE_SEEDS:
            for method in ("gh", "agh"):
                yield {"name": f"{'x'.join(map(str, shape))}_instance{instance_seed}_{method}",
                       "shape": list(shape), "instance_seed": instance_seed, "agh_seed": 37,
                       "load": 200.0, "method": method, "beta": 0.8, "families": families}


def fingerprints(binary):
    sources = matched.source_fingerprints()
    for path in (ROOT / "scripts/extension_instances.py", Path(__file__)):
        sources[path.relative_to(ROOT).as_posix()] = matched.sha256(path)
    return {"source_sha256": sources, "binary_sha256": matched.sha256(binary)}


def input_cohorts(specifications):
    """Verify genuinely distinct transported inputs, shared across methods."""
    shapes = {}
    for spec in specifications:
        shapes.setdefault(tuple(spec["shape"]), {}).setdefault(spec["instance_seed"], set()).add(spec["numeric_sha256"])
    result = {}
    for shape, seeds in shapes.items():
        if set(seeds) != set(INSTANCE_SEEDS):
            raise ValueError("prepared shape must contain all five instance seeds")
        if any(len(hashes) != 1 for hashes in seeds.values()):
            raise ValueError("GH and AGH must share identical numeric instance inputs")
        distinct = {next(iter(hashes)) for hashes in seeds.values()}
        if len(distinct) != len(INSTANCE_SEEDS):
            raise ValueError("instance seeds must produce five distinct numeric inputs per shape")
        result["x".join(map(str, shape))] = {"instance_seeds": sorted(seeds),
            "distinct_numeric_inputs": len(distinct), "numeric_sha256_by_seed":
            {str(seed): next(iter(hashes)) for seed, hashes in sorted(seeds.items())}}
    return result


def prepare(output, binary):
    if not (output / "PLAN.md").is_file():
        raise ValueError("write PLAN.md before preparing the scaling campaign")
    if not binary.is_file():
        raise ValueError("build the WP1 opt-in adapter before preparing WP5")
    if (output / "prepared.json").is_file():
        verify_prepared(output, matched.read_json(output / "prepared.json"))
        return
    before = fingerprints(binary)
    specifications = []
    for spec in matrix_specifications():
        instance = seeded_instance(tuple(spec["shape"]), spec["load"], spec["instance_seed"])
        case = ParityCase(spec["name"], instance, spec["method"], beta=spec["beta"], seed=spec["agh_seed"])
        json_path, numeric_path = output / "inputs" / (case.name + ".json"), output / "inputs" / (case.name + ".txt")
        matched.save_json(json_path, matched.case_record(case))
        numeric_path.write_text(serialize_case(case), encoding="utf-8", newline="")
        if serialize_case(matched.case_from_record(matched.read_json(json_path))).encode() != numeric_path.read_bytes():
            raise ValueError("prepared input roundtrip changed native transport")
        specifications.append({**spec, "json": json_path.relative_to(output).as_posix(),
                               "numeric": numeric_path.relative_to(output).as_posix(),
                               "json_sha256": matched.sha256(json_path), "numeric_sha256": matched.sha256(numeric_path)})
    if before != fingerprints(binary):
        raise ValueError("sources/binary changed during instance preparation")
    cohorts = input_cohorts(specifications)
    matched.save_json(output / "prepared.json", {"format_version": 1, "prepared_utc": matched.now(),
                      "cases": specifications, "binary": binary.relative_to(ROOT).as_posix(),
                      "fingerprints": before, "assumption": "independent uniform [0.9,1.1] input factors; seeded_instance",
                      "plan_sha256": matched.sha256(output / "PLAN.md"), "input_cohorts": cohorts,
                      "distinct_instance_count": sum(cohort["distinct_numeric_inputs"] for cohort in cohorts.values()),
                      "native_method_instance_points": len(specifications)})


def verify_prepared(output, prepared):
    if matched.sha256(output / "PLAN.md") != prepared["plan_sha256"]:
        raise ValueError("campaign PLAN changed after preparation")
    if fingerprints(ROOT / prepared["binary"]) != prepared["fingerprints"]:
        raise ValueError("prepared scientific/measurement sources or binary changed")
    for spec in prepared["cases"]:
        for name in ("json", "numeric"):
            if matched.sha256(output / spec[name]) != spec[name + "_sha256"]:
                raise ValueError(f"prepared input changed: {spec['name']} {name}")
    if input_cohorts(prepared["cases"]) != prepared["input_cohorts"]:
        raise ValueError("prepared numeric input cohorts changed")


def retain_invocation(output, destination, command, *, timeout):
    actual_directory = matched.attempt_directory(destination)
    record, actual = matched.retained_invocation(actual_directory, command, timeout=timeout)
    # Compress every stdout, including malformed/failed partial output. Keep the
    # original-byte digest as well as the compressed-file digest for replay.
    source = actual_directory / "stdout.json"
    compressed = actual_directory / "stdout.json.gz"
    raw = source.read_bytes()
    if hashlib.sha256(raw).hexdigest() != record["stdout_sha256"]:
        raise ValueError("worker stdout changed before compression")
    pending = compressed.with_suffix(compressed.suffix + ".pending")
    pending.write_bytes(gzip.compress(raw, mtime=0))
    pending.replace(compressed)
    record.update(directory=actual_directory.relative_to(output).as_posix(), stdout_path="stdout.json.gz",
                  stdout_uncompressed_sha256=record["stdout_sha256"], stdout_sha256=matched.sha256(compressed),
                  timeout_seconds=timeout)
    # Until this atomic metadata write succeeds, keep the original worker bytes.
    matched.save_json(actual_directory / "invocation.json", record)
    source.unlink()
    return record, actual


def retained_stdout(output, record):
    path = output / record["directory"] / record["stdout_path"]
    if matched.sha256(path) != record["stdout_sha256"]:
        raise ValueError(f"retained stdout changed: {record['directory']}")
    data = gzip.decompress(path.read_bytes())
    if hashlib.sha256(data).hexdigest() != record["stdout_uncompressed_sha256"]:
        raise ValueError("uncompressed stdout digest mismatch")
    if matched.sha256(output / record["directory"] / "stderr.txt") != record["stderr_sha256"]:
        raise ValueError("retained stderr digest mismatch")
    return json.loads(data)


def validate_native(case, actual):
    """Preserve supplied decisions and independently classify their feasibility."""
    if actual["placement"] is None:
        if actual["feasible"] or actual["objective"] is not None:
            raise AssertionError("missing placement with inconsistent evidence")
        return {"placement_available": False, "independently_feasible": False,
                "objective_agrees_bitwise": None, "violations": []}
    placement = decode_placement(case.instance, actual["placement"])
    report = validate_placement(case.instance, placement, paper_version=case.version)
    verify_bitwise(report.is_feasible, actual["feasible"], "independent feasibility")
    objective = objective_array(report.objective_breakdown)
    verify_bitwise(objective, actual["objective"], "independent C1-C5")
    return {"placement_available": True, "independently_feasible": report.is_feasible,
            "domain_valid": report.domain_diagnostic.is_valid, "objective_agrees_bitwise": True,
            "objective_components_usd": objective, "tolerances": asdict(report.tolerances),
            "violations": [{"family": violation.family.value, "location": list(violation.semantic_location),
                            "slack": violation.slack} for violation in report.violations]}


def budgeted_timeout(started, maximum_wall_seconds, timeout):
    """Bound each subprocess, including a Python reference, by remaining time."""
    return min(timeout, max(0.0, maximum_wall_seconds - (perf_counter() - started)))


def projected_pending_work(prepared, status):
    """Estimate only unfinished samples, retaining already completed checkpoints."""
    return sum(status["warm"][spec["name"]]["process_wall_seconds"]
               + status["warm"][spec["name"]].get("independent_validation_seconds", 0.0)
               for spec in prepared["cases"] if spec["name"] in status["warm"]
               for repeat in range(status["repeats"])
               if f"{spec['name']}/repeat{repeat:02d}" not in status["samples"])


def run(output, *, repeats=3, python_reference_max_queries=32, timeout=180,
        maximum_wall_seconds=10800, observed=None):
    if repeats < 3:
        raise ValueError("WP5 requires at least three native repeats per instance")
    if python_reference_max_queries not in (0, 16, 32):
        raise ValueError("optional full Python reference limit must be 0, 16 or 32")
    if sys.platform != "linux" or sys.version_info < (3, 13):
        raise ValueError("execute the campaign inside WSL with Python >=3.13")
    if not isfinite(timeout) or timeout <= 0:
        raise ValueError("worker timeout must be finite and positive")
    if not isfinite(maximum_wall_seconds) or not 0 < maximum_wall_seconds <= 10800:
        raise ValueError("coordinator budget must be finite, positive and at most three hours")
    prepared = matched.read_json(output / "prepared.json")
    verify_prepared(output, prepared)
    path = output / "status.json"
    status = matched.read_json(path) if path.exists() else {
        "format_version": 1, "started_utc": matched.now(), "repeats": repeats,
        "python_reference_max_queries": python_reference_max_queries,
        "warm": {}, "python_reference": {}, "samples": {}, "failures": [], "state": "running"}
    if status["repeats"] != repeats or status["python_reference_max_queries"] != python_reference_max_queries:
        raise ValueError("resume cannot change repeats or full Python reference scope")
    history_path = output / "environment_history.json"
    history = matched.read_json(history_path) if history_path.exists() else []
    history.append(matched.environment_metadata(observed))
    matched.save_json(history_path, history)
    started = perf_counter()
    def stop_for_budget(state="wall_budget_exhausted"):
        status.update(state=state, finished_utc=matched.now())
        matched.save_json(path, status)
        return status
    for spec in prepared["cases"]:
        name = spec["name"]
        if perf_counter() - started >= maximum_wall_seconds:
            return stop_for_budget()
        case = matched.case_from_record(matched.read_json(output / spec["json"]))
        full_reference = spec["shape"][0] <= python_reference_max_queries and spec["shape"][1:] == [4, 4]
        if name in status["warm"]:
            retained_stdout(output, status["warm"][name])
        else:
            command = matched.invocation_command(output, prepared, spec, "cpp", evidence=full_reference)
            worker_timeout = budgeted_timeout(started, maximum_wall_seconds, timeout)
            if worker_timeout <= 0:
                return stop_for_budget()
            record, actual = retain_invocation(output, output / "raw" / name / "warm_cpp", command, timeout=worker_timeout)
            record.update(case=name, method=spec["method"], phase="warm")
            if actual is not None:
                try:
                    validation_started = perf_counter()
                    validation = validate_native(case, actual)
                    record.update(core_seconds=actual["core_seconds"], independent_validation=validation,
                                  independent_validation_seconds=perf_counter() - validation_started,
                                  reference={key: actual[key] for key in matched.FINAL_KEYS})
                    status["warm"][name] = record
                except (AssertionError, KeyError, ValueError, TypeError) as error:
                    record.update(status="validation_failed", error=f"{type(error).__name__}: {error}")
                    matched.save_json(output / record["directory"] / "validation_failure.json", record)
                    status["failures"].append(record)
            else:
                status["failures"].append(record)
            matched.save_json(path, status)
        if full_reference and name in status["warm"] and name not in status["python_reference"]:
            command = matched.invocation_command(output, prepared, spec, "python", evidence=True)
            worker_timeout = budgeted_timeout(started, maximum_wall_seconds, timeout)
            if worker_timeout <= 0:
                return stop_for_budget()
            record, actual = retain_invocation(output, output / "raw" / name / "python_reference", command, timeout=worker_timeout)
            record.update(case=name, method=spec["method"], phase="full_python_reference")
            if actual is not None:
                try:
                    record["comparison"] = matched.verify_full_reference(actual, retained_stdout(output, status["warm"][name]))
                    record["verification_mode"] = "full_python_algorithm_transition_parity"
                    status["python_reference"][name] = record
                except (AssertionError, KeyError, ValueError, TypeError) as error:
                    record.update(status="parity_failed", error=f"{type(error).__name__}: {error}")
                    status["failures"].append(record)
            else:
                status["failures"].append(record)
            matched.save_json(path, status)
        print(f"instance scaling warm: {name}; {len(status['warm'])}/{len(prepared['cases'])}", flush=True)
    projected = projected_pending_work(prepared, status)
    remaining_budget = max(0.0, maximum_wall_seconds - (perf_counter() - started))
    status["pilot_estimate"] = {"native_remaining_seconds": projected, "safety_factor": 2,
                               "estimated_seconds": projected * 2,
                               "remaining_wall_budget_seconds": remaining_budget,
                               "basis": "unfinished samples only; warm subprocess plus independent validation durations, with 2x allowance"}
    matched.save_json(path, status)
    if projected * 2 > remaining_budget:
        return stop_for_budget("skipped_projection_exceeds_remaining_wall_budget")
    for repeat in range(repeats):
        offset = repeat % len(prepared["cases"])
        specifications = prepared["cases"][offset:] + prepared["cases"][:offset]
        if repeat % 2:
            specifications.reverse()
        for spec in specifications:
            name, key = spec["name"], f"{spec['name']}/repeat{repeat:02d}"
            if name not in status["warm"]:
                continue
            if key in status["samples"]:
                retained_stdout(output, status["samples"][key])
                continue
            if perf_counter() - started >= maximum_wall_seconds:
                return stop_for_budget()
            case = matched.case_from_record(matched.read_json(output / spec["json"]))
            command = matched.invocation_command(output, prepared, spec, "cpp")
            worker_timeout = budgeted_timeout(started, maximum_wall_seconds, timeout)
            if worker_timeout <= 0:
                return stop_for_budget()
            record, actual = retain_invocation(output, output / "raw" / name / f"repeat{repeat:02d}", command, timeout=worker_timeout)
            record.update(case=name, method=spec["method"], phase="measured", repeat=repeat)
            if actual is not None:
                try:
                    verify_bitwise(status["warm"][name]["reference"],
                                   {field: actual[field] for field in matched.FINAL_KEYS}, key)
                    record.update(core_seconds=actual["core_seconds"], verified_bitwise=True,
                                  independent_validation=validate_native(case, actual))
                    status["samples"][key] = record
                except (AssertionError, KeyError, ValueError, TypeError) as error:
                    record.update(status="validation_failed", error=f"{type(error).__name__}: {error}")
                    matched.save_json(output / record["directory"] / "validation_failure.json", record)
                    status["failures"].append(record)
            else:
                status["failures"].append(record)
            matched.save_json(path, status)
        print(f"instance scaling: round {repeat + 1}/{repeats}, {len(status['samples'])} accepted measurements", flush=True)
    verify_prepared(output, prepared)
    expected = len(prepared["cases"]) * repeats
    status.update(state="completed" if len(status["samples"]) == expected else "incomplete",
                  expected_samples=expected, finished_utc=matched.now(), fingerprints_verified_unchanged=True)
    matched.save_json(path, status)
    return status


def ordinary_log_fit(log_points):
    """Unweighted ordinary least squares; each point is one instance median."""
    if len(log_points) < 3:
        raise ValueError("a log-log fit needs at least three instance observations")
    mean_x = sum(point[0] for point in log_points) / len(log_points)
    mean_y = sum(point[1] for point in log_points) / len(log_points)
    xx = sum((x - mean_x) ** 2 for x, _ in log_points)
    if xx <= 0:
        raise ValueError("a log-log fit needs distinct size values")
    slope = sum((x - mean_x) * (y - mean_y) for x, y in log_points) / xx
    intercept = mean_y - slope * mean_x
    ss_residual = sum((y - intercept - slope * x) ** 2 for x, y in log_points)
    ss_total = sum((y - mean_y) ** 2 for _, y in log_points)
    return {"exponent": slope, "log_intercept": intercept,
            "r_squared_log_space": 1 - ss_residual / ss_total if ss_total > 0 else None}


def clustered_log_fit(points, *, seed=20261014, resamples=10000):
    """Resample input-seed clusters, never treating repeats as new instances."""
    if resamples < 100:
        raise ValueError("cluster bootstrap needs at least 100 draws")
    groups = {}
    for point in points:
        size, seconds = point["size"], point["median_seconds"]
        if not isfinite(size) or not isfinite(seconds) or size <= 0 or seconds <= 0:
            raise ValueError("fit size and median runtime must be finite and positive")
        groups.setdefault(point["instance_seed"], []).append((log(size), log(seconds)))
    clusters = sorted(groups)
    if len(clusters) < 2:
        raise ValueError("cluster bootstrap requires at least two independent input seeds")
    levels = sorted({point["size"] for point in points})
    for group in groups.values():
        if sorted(x for x, _ in group) != [log(level) for level in levels]:
            raise ValueError("cluster bootstrap requires a complete common size grid for every seed")
    central = ordinary_log_fit([point for group in groups.values() for point in group])
    rng, slopes, predictions = Random(seed), [], {level: [] for level in levels}
    for _ in range(resamples):
        selected = [clusters[rng.randrange(len(clusters))] for _ in clusters]
        fitted = ordinary_log_fit([point for cluster in selected for point in groups[cluster]])
        slopes.append(fitted["exponent"])
        for level in levels:
            predictions[level].append(exp(fitted["log_intercept"] + fitted["exponent"] * log(level)))
    central.update(ci95_exponent_low=quantile(slopes, 0.025), ci95_exponent_high=quantile(slopes, 0.975),
                   cluster_count=len(clusters), instance_point_count=len(points), size_level_count=len(levels),
                   bootstrap_seed=seed, bootstrap_resamples=resamples,
                   method="OLS in log space over per-instance medians; percentile bootstrap of complete instance-seed clusters",
                   predicted=[{"size": level, "seconds": exp(central["log_intercept"] + central["exponent"] * log(level)),
                               "ci95_low_seconds": quantile(predictions[level], 0.025),
                               "ci95_high_seconds": quantile(predictions[level], 0.975)} for level in levels])
    return central


def derived_analysis(output):
    prepared, status = matched.read_json(output / "prepared.json"), matched.read_json(output / "status.json")
    points = []
    for spec in prepared["cases"]:
        name = spec["name"]
        samples = [status["samples"].get(f"{name}/repeat{repeat:02d}") for repeat in range(status["repeats"])]
        available = [sample for sample in samples if sample is not None]
        point = {**{key: spec[key] for key in ("name", "shape", "instance_seed", "agh_seed", "load", "method", "families")},
                 "measured_repeats": len(available), "planned_repeats": status["repeats"],
                 "complete": len(available) == status["repeats"], "verification_mode":
                 "full_python_algorithm_transition_parity" if name in status["python_reference"] else "independent_final_decision",
                 "independently_feasible": status["warm"].get(name, {}).get("reference", {}).get("feasible"),
                 "algorithm_status": status["warm"].get(name, {}).get("reference", {}).get("status")}
        if available:
            point.update(core=timing_summary([sample["core_seconds"] for sample in available]),
                         invocation=timing_summary([sample["process_wall_seconds"] for sample in available]))
        points.append(point)
    fits = []
    for family, required_levels in (("query", len(QUERY_COUNTS)), ("menu", len(MENUS))):
        for method in ("gh", "agh"):
            selected = [point for point in points if family in point["families"] and point["method"] == method and point["complete"]]
            record = {"family": family, "method": method, "expected_instance_points": required_levels * len(INSTANCE_SEEDS),
                      "complete_instance_points": len(selected), "status": "incomplete; fit withheld"}
            if len(selected) == required_levels * len(INSTANCE_SEEDS):
                fitted = clustered_log_fit([{"size": point["shape"][0] if family == "query" else point["shape"][1] * point["shape"][2],
                                            "median_seconds": point["core"]["median_seconds"],
                                            "instance_seed": point["instance_seed"]} for point in selected])
                record.update(status="complete", fit=fitted,
                              independently_feasible_instances=sum(point["independently_feasible"] is True for point in selected),
                              descriptive_fit="weak (R² < 0.8)" if fitted["r_squared_log_space"] is None or fitted["r_squared_log_space"] < 0.8 else "R² >= 0.8 on this tested grid")
            fits.append(record)
    return {"classification": "synthetic serial C++ CPU allocation scaling with instance variability",
            "state": status["state"], "distinct_instance_count": prepared["distinct_instance_count"],
            "native_method_instance_points": len(points), "complete_method_instance_points": sum(point["complete"] for point in points),
            "verified_samples": len(status["samples"]), "planned_samples": len(points) * status["repeats"],
            "full_python_parity_points": len(status["python_reference"]),
            "planned_full_python_parity_points": sum(spec["shape"][0] <= status["python_reference_max_queries"]
                                                    and spec["shape"][1:] == [4, 4] for spec in prepared["cases"]),
            "retained_failed_attempts": len(status["failures"]),
            "points": points, "fits": fits,
            "limitations": ["Input seeds are separate from the fixed AGH seed 37; repeats are not independent instances.",
                            "Warmup is one excluded external subprocess pilot per point; measured workers are fresh single-solve processes without same-process warmup. Process/allocator state is fresh, while machine-wide cache/thermal history may persist.",
                            "The fit includes all complete verified native measurements, with scientific feasibility/status shown separately.",
                            "Five seed clusters limit confidence-interval precision and do not represent every possible workload.",
                            "Menu size is J*K at fixed I=64; different aspect ratios and structural branches confound a single product exponent.",
                            "Empirical log-log slopes on the observed range are not asymptotic complexity bounds or extrapolation evidence.",
                            "Large points have final-decision independent validation, without full Python algorithm/trace parity."]}


def analyze(output, *, plots=True):
    analysis = derived_analysis(output)
    matched.save_json(output / "analysis/analysis.json", analysis)
    rows = []
    for point in analysis["points"]:
        rows.append({"name": point["name"], "I": point["shape"][0], "J": point["shape"][1], "K": point["shape"][2],
                     "method": point["method"], "instance_seed": point["instance_seed"], "agh_seed": point["agh_seed"],
                     "repeats": point["measured_repeats"], "independently_feasible": point["independently_feasible"],
                     "algorithm_status": point["algorithm_status"], "verification_mode": point["verification_mode"],
                     "core_median_seconds": point.get("core", {}).get("median_seconds"),
                     "core_iqr_seconds": point.get("core", {}).get("iqr_seconds")})
    with (output / "analysis/instance_timings.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)
    lines = ["# C++ scaling across synthetic instances", "", f"State: {analysis['state']}; "
             f"{analysis['complete_method_instance_points']}/{analysis['native_method_instance_points']} complete method/instance points; "
             f"{analysis['verified_samples']}/{analysis['planned_samples']} verified native samples.",
             f"Full small-point Python parity: {analysis['full_python_parity_points']}/{analysis['planned_full_python_parity_points']} points; failures retained: {analysis['retained_failed_attempts']}.",
             "", "Core is a fresh complete public solve including validation/traces; excludes startup, input parsing, output projection/serialization and destruction.",
             "Warmup is one excluded external subprocess pilot per point. Measured workers are fresh single-solve processes, without same-process warmup.",
             "", "| Family | Method | Instance points | Feasible | Exponent [cluster bootstrap 95% CI] | Log-space R² |",
             "|---|---|---:|---:|---:|---:|"]
    for record in analysis["fits"]:
        if record["status"] == "complete":
            fit = record["fit"]
            r_squared = f"{fit['r_squared_log_space']:.4f}" if fit["r_squared_log_space"] is not None else "undefined"
            lines.append(f"| {record['family']} | {record['method']} | {record['complete_instance_points']}/{record['expected_instance_points']} | "
                         f"{record['independently_feasible_instances']} | {fit['exponent']:.4f} "
                         f"[{fit['ci95_exponent_low']:.4f}, {fit['ci95_exponent_high']:.4f}] | {r_squared} |")
        else:
            lines.append(f"| {record['family']} | {record['method']} | {record['complete_instance_points']}/{record['expected_instance_points']} | unavailable | withheld | withheld |")
    lines.extend(["", *[f"- {limitation}" for limitation in analysis["limitations"]], "",
                  "Replay: `python scripts/run_instance_scaling.py replay --output benchmarks/instance_scaling_2026-10-14`."])
    (output / "analysis/report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if plots:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        for family in ("query", "menu"):
            figure, axes = plt.subplots(1, 2, figsize=(11, 4.5))
            for axis, method in zip(axes, ("gh", "agh")):
                selected = [point for point in analysis["points"] if family in point["families"] and point["method"] == method and point["complete"]]
                for instance_seed in INSTANCE_SEEDS:
                    seed_points = [point for point in selected if point["instance_seed"] == instance_seed]
                    x = [point["shape"][0] if family == "query" else point["shape"][1] * point["shape"][2] for point in seed_points]
                    axis.plot(x, [point["core"]["median_seconds"] for point in seed_points], ".", label=f"seed {instance_seed}", alpha=0.8)
                fitted = next(record for record in analysis["fits"] if record["family"] == family and record["method"] == method)
                if fitted["status"] == "complete":
                    prediction = fitted["fit"]["predicted"]
                    axis.plot([row["size"] for row in prediction], [row["seconds"] for row in prediction], color="#333333", label="log-log fit")
                    axis.fill_between([row["size"] for row in prediction], [row["ci95_low_seconds"] for row in prediction],
                                      [row["ci95_high_seconds"] for row in prediction], color="#333333", alpha=0.12)
                    r_squared = f"{fitted['fit']['r_squared_log_space']:.3f}" if fitted["fit"]["r_squared_log_space"] is not None else "undefined"
                    axis.set_title(f"{method.upper()}: exponent {fitted['fit']['exponent']:.2f}, R² {r_squared}")
                else:
                    axis.set_title(f"{method.upper()}: incomplete grid; fit withheld")
                axis.set_xscale("log")
                levels = QUERY_COUNTS if family == "query" else sorted(models * tiers for models, tiers in MENUS)
                axis.set_xticks(levels, [str(level) for level in levels])
                axis.tick_params(axis="x", which="minor", labelbottom=False)
                axis.set_yscale("log")
                axis.set_xlabel("Query count I; J=K=4" if family == "query" else "Menu product J*K; I=64")
                axis.set_ylabel("Median of three native core solves (s)")
                axis.grid(alpha=0.2)
                axis.legend(fontsize=7)
            figure.suptitle("Synthetic instance variability; cluster bootstrap 95% fit band")
            figure.tight_layout()
            for suffix in ("png", "svg"):
                figure.savefig(output / f"analysis/{family}_scaling.{suffix}", dpi=160)
            plt.close(figure)
    inventory = {path.relative_to(output).as_posix(): matched.sha256(path) for path in sorted(output.rglob("*"))
                 if path.is_file() and path.name != "evidence_manifest.json"}
    matched.save_json(output / "evidence_manifest.json", {"format_version": 1, "file_count": len(inventory), "files": inventory})
    return analysis


def replay(output):
    manifest = matched.read_json(output / "evidence_manifest.json")
    for path, expected in manifest["files"].items():
        if matched.sha256(output / path) != expected:
            raise ValueError(f"retained evidence changed: {path}")
    prepared, status = matched.read_json(output / "prepared.json"), matched.read_json(output / "status.json")
    cases = {spec["name"]: matched.case_from_record(matched.read_json(output / spec["json"])) for spec in prepared["cases"]}
    validations = 0
    for key, record in status["samples"].items():
        actual = retained_stdout(output, record)
        verify_bitwise(status["warm"][record["case"]]["reference"], {field: actual[field] for field in matched.FINAL_KEYS}, key)
        if validate_native(cases[record["case"]], actual) != record["independent_validation"]:
            raise ValueError("replayed independent validation evidence differs")
        validations += 1
    for name, record in status["warm"].items():
        actual = retained_stdout(output, record)
        if validate_native(cases[name], actual) != record["independent_validation"]:
            raise ValueError("replayed warm validation evidence differs")
        validations += 1
    if matched.read_json(output / "analysis/analysis.json") != derived_analysis(output):
        raise ValueError("analysis does not reproduce exactly")
    print(json.dumps({"replay": "passed", "verified_files": manifest["file_count"],
                      "independent_native_validations": validations, "analysis_reproduced": True}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("prepare", "run", "analyze", "replay"))
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--binary", type=Path, default=ROOT / "cpp/build/release/pacs_matched_runtime")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--python-reference-max-queries", type=int, default=32)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--maximum-wall-seconds", type=float, default=10800)
    parser.add_argument("--environment-json", type=Path)
    parser.add_argument("--no-plots", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    if args.operation == "prepare":
        prepare(output, args.binary.resolve())
    elif args.operation == "run":
        status = run(output, repeats=args.repeats, python_reference_max_queries=args.python_reference_max_queries,
                     timeout=args.timeout, maximum_wall_seconds=args.maximum_wall_seconds, observed=args.environment_json)
        return 0 if status["state"] == "completed" else 2
    elif args.operation == "analyze":
        analyze(output, plots=not args.no_plots)
    else:
        replay(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
