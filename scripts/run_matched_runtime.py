"""Opt-in same-WSL Python/C++ experiment with matched fresh-solve boundaries.

Prepare immutable inputs and this measurement-only native adapter first, then
execute resumable paired rounds. Existing scientific algorithms/defaults and
benchmarks are never rewritten. Analysis and replay need no solver execution.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, fields, replace
from datetime import datetime, timezone
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
from time import perf_counter

from check_cpp_parity import (
    ROOT, ParityCase, check_reference, decode_placement, numerical_difference,
    objective_array, placement_arrays, python_gh_trace, make_python_runner,
    serialize_case,
)
from check_openmp_campaign import verify_bitwise
from extension_statistics import paired_ratio_bootstrap, timing_summary
from llm_resource_allocation.data.scaling_experiment_instances import make_scaling_experiment_case
from llm_resource_allocation.domain import (
    FoundationModel, GpuTier, ProblemInstance, QueryType, UnitConvention,
    validate_problem_instance,
)
from llm_resource_allocation.math.objective import PaperVersion
from llm_resource_allocation.validation.placement import validate_placement


DEFAULT_OUTPUT = ROOT / "benchmarks/matched_runtime_2026-10-14"
MAPPING_FIELDS = ("base_error_rate", "compute_delay_seconds_per_token",
                  "communication_delay_seconds_per_token", "compute_gflop_per_token",
                  "kv_cache_residency_seconds")
FINAL_KEYS = ("status", "placement", "feasible", "objective")
BUILD_FLAGS = ["-std=c++20", "-O2", "-g", "-Wall", "-Wextra", "-Wpedantic", "-ffp-contract=off"]


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".partial")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def case_record(case):
    """Serialize full domain data, retaining scientific IDs and coefficient order."""
    instance = case.instance
    record = {"format_version": 1, "name": case.name, "method": case.method,
              "beta": case.beta, "seed": case.seed, "paper_version": case.version.value,
              "instance": {}}
    for field in fields(instance):
        value = getattr(instance, field.name)
        if field.name in MAPPING_FIELDS:
            value = [[list(key), coefficient] for key, coefficient in value.items()]
        elif field.name in ("queries", "models", "gpu_tiers"):
            value = [asdict(item) for item in value]
        elif field.name == "unit_convention":
            value = value.value
        record["instance"][field.name] = value
    return record


def case_from_record(record):
    """Construct/validate the immutable prepared input before the solve timer."""
    if record.get("format_version") != 1:
        raise ValueError("unsupported prepared input")
    data = dict(record["instance"])
    data["queries"] = tuple(QueryType(**item) for item in data["queries"])
    data["models"] = tuple(FoundationModel(**item) for item in data["models"])
    data["gpu_tiers"] = tuple(GpuTier(**item) for item in data["gpu_tiers"])
    data["unit_convention"] = UnitConvention(data["unit_convention"])
    for name in MAPPING_FIELDS:
        data[name] = {tuple(key): value for key, value in data[name]}
    instance = ProblemInstance(**data)
    validate_problem_instance(instance)
    return ParityCase(record["name"], instance, record["method"], record["beta"],
                      record["seed"], PaperVersion(record["paper_version"]))


def workload_cases():
    for shape in ((4, 2, 2), (8, 4, 4), (16, 4, 4)):
        for load in (1.0, 200.0):
            instance = replace(make_scaling_experiment_case(*shape, load_multiplier=load).instance,
                               unit_convention=UnitConvention.COHERENT)
            for method in ("gh", "agh"):
                name = f"{'x'.join(map(str, shape))}_load{load:g}_{method}"
                yield ParityCase(name, instance, method, seed=37), load


def python_projection(case, result, *, evidence=False):
    """Project an existing solve result; never rerun a solve inside reporting."""
    if case.method == "gh":
        placement, report = result.placement_decisions, result.validation_report
    else:
        placement, report = result.final_placement, result.final_validation
    record = {"status": result.completion_status.value,
              "placement": None if placement is None else placement_arrays(case.instance, placement),
              "feasible": report is not None and report.is_feasible,
              "objective": None if report is None else objective_array(report.objective_breakdown)}
    if evidence and case.method == "gh":
        record["gh_trace"] = python_gh_trace(case.instance, result)
    elif evidence:
        traces = result.multistart_result.start_traces
        record.update(executed_count=result.executed_start_count,
                      termination=result.termination_reason.value,
                      incumbent_index=next((trace.schedule_index for trace in reversed(traces)
                                            if trace.incumbent_changed), -1),
                      orders=[[case.instance.query_ids.index(query) for query in trace.ordering.query_ids]
                              for trace in traces],
                      counters=[trace.consecutive_nonimprovements_after for trace in traces],
                      costs=[trace.candidate_objective for trace in traces],
                      comparisons=[trace.comparison_outcome.value for trace in traces])
    return record


def python_worker(input_json, input_numeric, *, warmup=False, evidence=False):
    case = case_from_record(read_json(input_json))
    if serialize_case(case).encode("utf-8") != input_numeric.read_bytes():
        raise ValueError("prepared Python input does not match the native numeric input bytewise")
    runner = make_python_runner(case)
    if warmup:
        discarded = runner()
        del discarded
    begin = perf_counter()
    result = runner()
    seconds = perf_counter() - begin
    record = python_projection(case, result, evidence=evidence)
    # Printing and all result destruction occur after the core stopwatch stops.
    record["core_seconds"] = seconds
    print(json.dumps(record, separators=(",", ":"), allow_nan=False), flush=True)


def source_fingerprints():
    paths = [*sorted((ROOT / "src").rglob("*.py")),
             *sorted((ROOT / "cpp/include").rglob("*.hpp")),
             *sorted((ROOT / "cpp/src").rglob("*.cpp")),
             ROOT / "cpp/experiments/matched_runtime_main.cpp",
             ROOT / "scripts/check_cpp_parity.py", ROOT / "scripts/check_openmp_campaign.py",
             ROOT / "scripts/extension_statistics.py", Path(__file__)]
    return {path.relative_to(ROOT).as_posix(): sha256(path) for path in paths}


def prepare(output, *, compiler="g++"):
    if not (output / "PLAN.md").is_file():
        raise ValueError("write PLAN.md before preparing this campaign")
    if (output / "prepared.json").exists():
        verify_prepared(output, read_json(output / "prepared.json"))
        return
    binary = ROOT / "cpp/build/release/pacs_matched_runtime"
    binary.parent.mkdir(parents=True, exist_ok=True)
    sources = ["cpp/src/core.cpp", "cpp/src/gh.cpp", "cpp/src/agh.cpp", "cpp/src/io.cpp",
               "cpp/experiments/matched_runtime_main.cpp"]
    command = [compiler, *BUILD_FLAGS, "-Icpp/include", *sources, "-o", str(binary.relative_to(ROOT))]
    started = now()
    process = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=600, check=False)
    (output / "build").mkdir(exist_ok=True)
    (output / "build/stdout.txt").write_bytes(process.stdout)
    (output / "build/stderr.txt").write_bytes(process.stderr)
    save_json(output / "build/command.json", {"argv": command, "cwd": "repository root",
              "exit_code": process.returncode, "started_utc": started, "finished_utc": now()})
    if process.returncode:
        raise RuntimeError("opt-in measurement adapter compilation failed; retained build/stderr.txt")
    cases = []
    for case, load in workload_cases():
        json_path = output / "inputs" / f"{case.name}.json"
        numeric_path = json_path.with_suffix(".txt")
        save_json(json_path, case_record(case))
        numeric_path.write_text(serialize_case(case), encoding="utf-8", newline="")
        rebuilt = case_from_record(read_json(json_path))
        if serialize_case(rebuilt).encode() != numeric_path.read_bytes():
            raise ValueError("input serialization roundtrip changed native numeric input")
        cases.append({"name": case.name, "method": case.method, "shape": list(case.instance.dimensions),
                      "load": load, "seed": case.seed, "beta": case.beta,
                      "json": json_path.relative_to(output).as_posix(),
                      "json_sha256": sha256(json_path), "numeric": numeric_path.relative_to(output).as_posix(),
                      "numeric_sha256": sha256(numeric_path)})
    save_json(output / "prepared.json", {"format_version": 1, "prepared_utc": now(),
              "cases": cases, "binary": binary.relative_to(ROOT).as_posix(),
              "binary_sha256": sha256(binary), "source_sha256": source_fingerprints(),
              "classification": "synthetic CPU allocation implementation performance"})


def verify_prepared(output, prepared):
    if prepared["source_sha256"] != source_fingerprints():
        raise ValueError("scientific/measurement sources changed since campaign preparation")
    if sha256(ROOT / prepared["binary"]) != prepared["binary_sha256"]:
        raise ValueError("native measurement adapter changed since preparation")
    for case in prepared["cases"]:
        for name in ("json", "numeric"):
            if sha256(output / case[name]) != case[name + "_sha256"]:
                raise ValueError(f"prepared input changed: {case['name']} {name}")


def environment_metadata(observed=None):
    result = {"recorded_utc": now(), "python": platform.python_version(),
              "platform": platform.platform(), "processor": platform.processor(),
              "timer": "Python perf_counter and C++ steady_clock; monotonic wall time",
              "observed_external_environment": read_json(observed) if observed else None,
              "closed_apps": "not independently established; use supplied observations",
              "parallel_campaigns": "parent-coordinated single timing campaign"}
    for name, command in (("cpu", ["lscpu", "--json"]), ("topology", ["lscpu", "-e"]),
                          ("kernel", ["uname", "-srmo"]), ("compiler", ["g++", "--version"]),
                          ("git_head", ["git", "rev-parse", "HEAD"])):
        try:
            process = subprocess.run(command, capture_output=True, text=True, timeout=30,
                                     cwd=ROOT, check=False)
            result[name] = {"exit_code": process.returncode, "stdout": process.stdout,
                            "stderr": process.stderr}
        except OSError as error:
            result[name] = {"unavailable": str(error)}
    frequency_paths = sorted(Path("/sys/devices/system/cpu").glob("cpu*/cpufreq/scaling_governor"))
    result["governors"] = {path.parent.parent.name: path.read_text().strip() for path in frequency_paths}
    if not frequency_paths:
        result["governor_limitation"] = "WSL exposes no cpufreq governor files; host policy is supplied separately"
    return result


def invocation_command(output, prepared, spec, runtime, *, warmup=False, evidence=False):
    if runtime == "python":
        command = [sys.executable, str(Path(__file__)), "worker", "--input-json", str(output / spec["json"]),
                   "--input-numeric", str(output / spec["numeric"])]
    else:
        command = [str(ROOT / prepared["binary"]), spec["method"], str(output / spec["numeric"])]
    if warmup:
        command.append("--warmup")
    if evidence:
        command.append("--evidence")
    return command


def portable_command(command):
    result = []
    for index, value in enumerate(command):
        if index == 0 and value == sys.executable:
            result.append("python")
        else:
            try:
                result.append(Path(value).relative_to(ROOT).as_posix())
            except ValueError:
                result.append(value)
    return result


def retained_invocation(directory, command, *, timeout):
    """Retain failures and the whole subprocess boundary before interpreting output."""
    directory.mkdir(parents=True, exist_ok=False)
    record = {"argv": portable_command(command), "cwd": "repository root", "started_utc": now(),
              "status": "running"}
    save_json(directory / "invocation.json", record)
    begin = perf_counter()
    try:
        process = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=timeout,
                                 check=False, env={**os.environ, "PYTHONHASHSEED": "0"})
        record.update(process_wall_seconds=perf_counter() - begin,
                      exit_code=process.returncode, status="completed" if process.returncode == 0 else "failed")
        stdout, stderr = process.stdout, process.stderr
    except subprocess.TimeoutExpired as error:
        record.update(process_wall_seconds=perf_counter() - begin, exit_code=None, status="timeout")
        stdout, stderr = error.stdout or b"", error.stderr or b""
    (directory / "stdout.json").write_bytes(stdout)
    (directory / "stderr.txt").write_bytes(stderr)
    record.update(finished_utc=now(), stdout_sha256=sha256(directory / "stdout.json"),
                  stderr_sha256=sha256(directory / "stderr.txt"))
    save_json(directory / "invocation.json", record)
    if record["status"] != "completed":
        return record, None
    try:
        actual = json.loads(stdout)
        timing_summary([actual["core_seconds"], record["process_wall_seconds"]])
    except (KeyError, ValueError, TypeError) as error:
        record.update(status="invalid_output", error=f"{type(error).__name__}: {error}")
        save_json(directory / "invocation.json", record)
        return record, None
    return record, actual


def verify_full_reference(expected, native):
    check_reference(expected, native)
    numeric = numerical_difference(expected, native)
    if numeric["bitwise_difference_count"]:
        raise AssertionError("warm reference final numeric values differ bitwise")
    verify_bitwise({key: expected[key] for key in FINAL_KEYS},
                   {key: native[key] for key in FINAL_KEYS}, "warm final decision")
    if "gh_trace" in expected:
        verify_bitwise(expected["gh_trace"], native["gh_trace"], "warm GH transitions")
    if "orders" in expected:
        for index, start in enumerate(native["starts"]):
            verify_bitwise(expected["orders"][index], start["order"], "warm AGH ordering")
            verify_bitwise(expected["counters"][index], start["counter"], "warm AGH counter")
            verify_bitwise(expected["costs"][index], start["cost"], "warm AGH cost")
            verify_bitwise(expected["comparisons"][index], start["comparison"].lower(), "warm AGH acceptance")
    return numeric


def validate_native(case, actual):
    """Validate native decisions unchanged; feasibility and completion stay separate."""
    if actual["placement"] is None:
        if actual["feasible"] or actual["objective"] is not None:
            raise AssertionError("missing placement has inconsistent feasibility/objective")
        return {"placement_available": False, "independently_feasible": False,
                "objective_agrees_bitwise": None}
    placement = decode_placement(case.instance, actual["placement"])
    report = validate_placement(case.instance, placement, paper_version=case.version)
    verify_bitwise(report.is_feasible, actual["feasible"], "independent feasibility")
    verify_bitwise(objective_array(report.objective_breakdown), actual["objective"], "independent objective")
    return {"placement_available": True, "independently_feasible": report.is_feasible,
            "objective_agrees_bitwise": True}


def attempt_directory(base):
    # An interrupted invocation is preserved before a fresh attempt starts.
    if not base.exists():
        return base
    index = 1
    while base.with_name(base.name + f"_retry{index}").exists():
        index += 1
    return base.with_name(base.name + f"_retry{index}")


def verify_retained_invocation(output, record):
    for field, path in (("stdout", "stdout.json"), ("stderr", "stderr.txt")):
        if sha256(output / record["directory"] / path) != record[field + "_sha256"]:
            raise ValueError(f"retained invocation changed: {record['directory']} {field}")


def run(output, *, rounds=10, timeout=120, maximum_wall_seconds=10800, observed=None):
    if rounds < 10:
        raise ValueError("WP1 requires at least ten paired rounds")
    if sys.platform != "linux" or sys.version_info < (3, 13):
        raise ValueError("the matched campaign must execute inside WSL with Python >=3.13")
    prepared = read_json(output / "prepared.json")
    verify_prepared(output, prepared)
    status_path = output / "status.json"
    status = read_json(status_path) if status_path.exists() else {
        "format_version": 1, "rounds": rounds, "case_count": len(prepared["cases"]),
        "started_utc": now(), "preflight": {}, "samples": {}, "failures": [], "state": "running"}
    if status["rounds"] != rounds:
        raise ValueError("resume cannot change the number of paired rounds")
    metadata = environment_metadata(observed)
    history_path = output / "environment_history.json"
    history = read_json(history_path) if history_path.exists() else []
    history.append(metadata)
    save_json(history_path, history)
    started = perf_counter()
    for spec in prepared["cases"]:
        name = spec["name"]
        case = case_from_record(read_json(output / spec["json"]))
        if name in status["preflight"]:
            for record in status["preflight"][name]["invocations"]:
                verify_retained_invocation(output, record)
        if name not in status["preflight"]:
            values, invocations = {}, []
            for runtime in ("python", "cpp"):
                destination = attempt_directory(output / "raw" / name / f"warm_{runtime}")
                record, actual = retained_invocation(destination, invocation_command(output, prepared, spec, runtime,
                                                 warmup=True, evidence=True), timeout=timeout)
                record["directory"] = destination.relative_to(output).as_posix()
                invocations.append(record)
                if actual is not None:
                    values[runtime] = actual
            if len(values) != 2:
                status["failures"].append({"case": name, "phase": "preflight", "invocations": invocations})
                save_json(status_path, status)
                continue
            expected, native = values["python"], values["cpp"]
            try:
                numeric = verify_full_reference(expected, native)
                validation = validate_native(case, native)
            except (AssertionError, ValueError, TypeError) as error:
                status["failures"].append({"case": name, "phase": "preflight_validation",
                                          "error": f"{type(error).__name__}: {error}", "invocations": invocations})
                save_json(status_path, status)
                continue
            status["preflight"][name] = {"comparison": numeric, "independent_validation": validation,
                                        "invocations": invocations,
                                        "reference": {key: expected[key] for key in FINAL_KEYS}}
            save_json(status_path, status)
    # Derive a conservative pilot forecast from observed complete warm workers.
    # Each core worker makes two solves, while each invocation worker makes one.
    projected_seconds = 0.0
    for preflight in status["preflight"].values():
        for record in preflight["invocations"]:
            actual = read_json(output / record["directory"] / "stdout.json")
            solve = actual["core_seconds"]
            overhead = max(0.0, record["process_wall_seconds"] - 2 * solve)
            projected_seconds += rounds * (3 * solve + 2 * overhead)
    status["pilot_estimate"] = {"remaining_campaign_seconds_before_safety_factor": projected_seconds,
                               "safety_factor": 1.5, "estimated_seconds": 1.5 * projected_seconds,
                               "basis": "observed warm subprocess core and process durations; every planned measured call"}
    save_json(status_path, status)
    if 1.5 * projected_seconds > 10800:
        status.update(state="skipped_projection_exceeds_three_hours", finished_utc=now())
        save_json(status_path, status)
        return status
    for round_index in range(rounds):
        specifications = prepared["cases"]
        offset = round_index % len(specifications)
        rotated = specifications[offset:] + specifications[:offset]
        if round_index % 2:
            rotated.reverse()
        for spec in rotated:
            name = spec["name"]
            if name not in status["preflight"]:
                continue
            case = case_from_record(read_json(output / spec["json"]))
            for boundary in ("core", "invocation"):
                for runtime in (("python", "cpp") if round_index % 2 == 0 else ("cpp", "python")):
                    key = f"{name}/{boundary}/round{round_index:02d}/{runtime}"
                    if key in status["samples"]:
                        verify_retained_invocation(output, status["samples"][key])
                        continue
                    if perf_counter() - started >= maximum_wall_seconds:
                        status.update(state="wall_budget_exhausted", finished_utc=now())
                        save_json(status_path, status)
                        return status
                    destination = attempt_directory(output / "raw" / name / f"{boundary}_r{round_index:02d}_{runtime}")
                    record, actual = retained_invocation(destination,
                        invocation_command(output, prepared, spec, runtime, warmup=boundary == "core"), timeout=timeout)
                    record.update(directory=destination.relative_to(output).as_posix(), case=name,
                                  boundary=boundary, runtime=runtime, round=round_index)
                    if actual is not None:
                        try:
                            verify_bitwise(status["preflight"][name]["reference"],
                                           {item: actual[item] for item in FINAL_KEYS}, key)
                            validation = validate_native(case, actual) if runtime == "cpp" else None
                            record.update(core_seconds=actual["core_seconds"], verified_bitwise=True,
                                          independent_validation=validation)
                            status["samples"][key] = record
                        except (AssertionError, KeyError, ValueError, TypeError) as error:
                            record.update(status="validation_failed", error=f"{type(error).__name__}: {error}")
                            save_json(destination / "validation_failure.json", record)
                            status["failures"].append(record)
                    else:
                        status["failures"].append(record)
                    save_json(status_path, status)
        print(f"matched runtime: round {round_index + 1}/{rounds}, {len(status['samples'])} verified samples", flush=True)
    verify_prepared(output, prepared)
    expected_count = len(prepared["cases"]) * rounds * 4
    status.update(state="completed" if len(status["samples"]) == expected_count else "incomplete",
                  expected_samples=expected_count, finished_utc=now(), fingerprints_verified_unchanged=True)
    save_json(status_path, status)
    return status


def derived_analysis(output):
    prepared, status = read_json(output / "prepared.json"), read_json(output / "status.json")
    rows = []
    for spec in prepared["cases"]:
        name = spec["name"]
        for boundary in ("core", "invocation"):
            complete = []
            for index in range(status["rounds"]):
                pair = [status["samples"].get(f"{name}/{boundary}/round{index:02d}/{runtime}")
                        for runtime in ("python", "cpp")]
                if all(pair):
                    complete.append(pair)
            row = {"case": name, "shape": spec["shape"], "load": spec["load"], "method": spec["method"],
                   "boundary": boundary, "planned_paired_rounds": status["rounds"],
                   "complete_paired_rounds": len(complete), "independently_feasible": None,
                   "claim": "incomplete; no speedup conclusion"}
            if name in status["preflight"]:
                row["independently_feasible"] = status["preflight"][name]["reference"]["feasible"]
            if len(complete) >= 2:
                metric = "core_seconds" if boundary == "core" else "process_wall_seconds"
                python = [pair[0][metric] for pair in complete]
                cpp = [pair[1][metric] for pair in complete]
                row.update(python=timing_summary(python), cpp=timing_summary(cpp),
                           ratio=paired_ratio_bootstrap(python, cpp))
                if len(complete) == status["rounds"]:
                    low, high = row["ratio"]["ci95_low"], row["ratio"]["ci95_high"]
                    row["claim"] = ("C++ faster on this workload" if low > 1 else
                                    "Python faster on this workload" if high < 1 else "inconclusive interval")
            rows.append(row)
    return {"classification": "synthetic CPU allocation implementation performance; not GPU inference",
            "state": status["state"], "case_count": len(prepared["cases"]), "rows": rows,
            "failure_count": len(status["failures"]), "verified_sample_count": len(status["samples"]),
            "timer_boundaries": {"core": "public fresh-result solve on constructed input; validation/traces included; "
                                 "startup/parsing/projection/output/destruction excluded; same-process warmup excluded",
                                 "invocation": "single-solve Linux subprocess startup through exit; same final-decision "
                                 "schema; no in-process warmup; external preflight excluded"},
            "limitations": ["Ratios compare these implementations including their different trace/input-check costs, not pure languages.",
                            "Bootstrap resamples paired rounds; ten conditional observations cannot describe every system effect.",
                            "Core samples and invocation samples are distinct solves with separately retained evidence.",
                            "Scientific completion, independent feasibility and measured runtime are separate statuses."]}


def analyze(output, *, plots=True):
    analysis = derived_analysis(output)
    save_json(output / "analysis/analysis.json", analysis)
    rows = []
    for row in analysis["rows"]:
        flat = {name: row[name] for name in ("case", "load", "method", "boundary", "complete_paired_rounds",
                                             "planned_paired_rounds", "independently_feasible", "claim")}
        for runtime in ("python", "cpp"):
            for field in ("median_seconds", "iqr_seconds"):
                flat[f"{runtime}_{field}"] = row.get(runtime, {}).get(field)
        for field in ("ratio_of_medians", "ci95_low", "ci95_high"):
            flat[field] = row.get("ratio", {}).get(field)
        rows.append(flat)
    with (output / "analysis/timings.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)
    lines = ["# Matched WSL Python/C++ runtime", "", "Synthetic CPU allocation software; modeled GPU delays are coefficients.",
             "", f"State: {analysis['state']}. Verified samples: {analysis['verified_sample_count']}; "
             f"retained failed attempts: {analysis['failure_count']}.", "",
             "Core: public fresh-result solve including validation/traces; excludes startup, input parsing, projection, output and destruction.",
             "Invocation: separate single-solve Linux subprocess, startup through exit, same final-decision schema; no in-process warmup.",
             "", "| Case | Boundary | Pairs | Python median / IQR (s) | C++ median / IQR (s) | Median ratio [95% CI] |",
             "|---|---|---:|---:|---:|---:|"]
    for row in analysis["rows"]:
        if "ratio" in row:
            python, cpp, ratio = row["python"], row["cpp"], row["ratio"]
            lines.append(f"| {row['case']} | {row['boundary']} | {row['complete_paired_rounds']}/{row['planned_paired_rounds']} | "
                         f"{python['median_seconds']:.6g} / {python['iqr_seconds']:.6g} | "
                         f"{cpp['median_seconds']:.6g} / {cpp['iqr_seconds']:.6g} | "
                         f"{ratio['ratio_of_medians']:.3f} [{ratio['ci95_low']:.3f}, {ratio['ci95_high']:.3f}] |")
        else:
            lines.append(f"| {row['case']} | {row['boundary']} | {row['complete_paired_rounds']}/{row['planned_paired_rounds']} | unavailable | unavailable | unavailable |")
    lines.extend(["", *[f"- {limitation}" for limitation in analysis["limitations"]], "",
                  "Replay: `python scripts/run_matched_runtime.py replay --output benchmarks/matched_runtime_2026-10-14`.",
                  "Analysis: `python scripts/run_matched_runtime.py analyze --output benchmarks/matched_runtime_2026-10-14`."])
    (output / "analysis/report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if plots:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        for boundary in ("core", "invocation"):
            selected = [row for row in analysis["rows"] if row["boundary"] == boundary and "ratio" in row]
            if not selected:
                continue
            centers = [row["ratio"]["ratio_of_medians"] for row in selected]
            lower = [center - row["ratio"]["ci95_low"] for center, row in zip(centers, selected)]
            upper = [row["ratio"]["ci95_high"] - center for center, row in zip(centers, selected)]
            figure, axis = plt.subplots(figsize=(10, 5))
            axis.errorbar(range(len(selected)), centers, yerr=[lower, upper], fmt="o", capsize=3, color="#235789")
            axis.axhline(1, color="#666666", linewidth=1, linestyle="--")
            axis.set_xticks(range(len(selected)), [row["case"].replace("_", "\n") for row in selected], fontsize=8)
            axis.set_ylabel("Median Python duration / median C++ duration")
            axis.set_title(f"Matched WSL {boundary} boundary; paired bootstrap 95% CI")
            axis.grid(axis="y", alpha=0.25)
            figure.tight_layout()
            for suffix in ("png", "svg"):
                figure.savefig(output / f"analysis/{boundary}_ratios.{suffix}", dpi=160)
            plt.close(figure)
    inventory = {path.relative_to(output).as_posix(): sha256(path) for path in sorted(output.rglob("*"))
                 if path.is_file() and path.name != "evidence_manifest.json"}
    save_json(output / "evidence_manifest.json", {"format_version": 1, "file_count": len(inventory),
              "files": inventory})
    return analysis


def replay(output):
    """Solver-free audit of every delivered byte and each accepted final decision."""
    manifest = read_json(output / "evidence_manifest.json")
    for relative, digest in manifest["files"].items():
        if sha256(output / relative) != digest:
            raise ValueError(f"retained evidence digest mismatch: {relative}")
    prepared, status = read_json(output / "prepared.json"), read_json(output / "status.json")
    cases = {spec["name"]: case_from_record(read_json(output / spec["json"])) for spec in prepared["cases"]}
    checked = 0
    for key, record in status["samples"].items():
        actual = read_json(output / record["directory"] / "stdout.json")
        verify_bitwise(status["preflight"][record["case"]]["reference"],
                       {name: actual[name] for name in FINAL_KEYS}, key)
        if record["runtime"] == "cpp":
            validate_native(cases[record["case"]], actual)
        checked += 1
    stored, fresh = read_json(output / "analysis/analysis.json"), derived_analysis(output)
    if stored != fresh:
        raise ValueError("delivered analysis does not match deterministic derivation")
    print(json.dumps({"replay": "passed", "verified_files": manifest["file_count"],
                      "verified_samples": checked, "analysis_reproduced": True}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("prepare", "run", "analyze", "replay", "worker"))
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--compiler", default="g++")
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--maximum-wall-seconds", type=float, default=10800)
    parser.add_argument("--environment-json", type=Path)
    parser.add_argument("--input-json", type=Path)
    parser.add_argument("--input-numeric", type=Path)
    parser.add_argument("--warmup", action="store_true")
    parser.add_argument("--evidence", action="store_true")
    parser.add_argument("--no-plots", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    if args.operation == "prepare":
        prepare(output, compiler=args.compiler)
    elif args.operation == "run":
        status = run(output, rounds=args.rounds, timeout=args.timeout,
                     maximum_wall_seconds=args.maximum_wall_seconds, observed=args.environment_json)
        return 0 if status["state"] == "completed" else 2
    elif args.operation == "analyze":
        analyze(output, plots=not args.no_plots)
    elif args.operation == "replay":
        replay(output)
    else:
        if args.input_json is None or args.input_numeric is None:
            parser.error("worker requires both prepared inputs")
        python_worker(args.input_json, args.input_numeric, warmup=args.warmup, evidence=args.evidence)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
