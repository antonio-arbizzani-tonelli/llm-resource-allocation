"""Profile fixed larger GH/AGH instances and replay checked candidate binaries.

The baseline runs the Python algorithm exactly once per shape/method through
the existing parity authority. Its measured reference wall includes projection
and independent validation, so it is deliberately not called Python core time.
Synthetic dimensions, load and seeds are experiment assumptions, not paper data.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import subprocess
import tempfile
from time import perf_counter

from check_cpp_parity import (
    ROOT, ParityCase, check_case, check_reference, executable_command, linux_path,
    numerical_difference, serialize_case,
)
from check_openmp_campaign import verify_bitwise
from llm_resource_allocation.data.scaling_experiment_instances import make_scaling_experiment_case
from llm_resource_allocation.domain import UnitConvention


# These are adapter observations, never scientific evidence. Add new timing
# fields explicitly rather than silently dropping unknown scientific fields.
TIMING_FIELDS = {"algorithm_seconds", "repeat_seconds", "phase_seconds",
                 "validation_statistics", "validation_execution"}
VALIDATE_SYMBOL = "pacs::validate(pacs::Problem const&, pacs::Placement const&, pacs::Tolerances const&)"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def save_evidence(path, value):
    """Retain large full traces reproducibly without bloating the output tree."""
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(value, separators=(",", ":"), allow_nan=False) + "\n").encode()
    path.write_bytes(gzip.compress(encoded, mtime=0))
    return sha256(path)


def workload_cases(query_counts=(16, 32, 64), *, seed=37, load=200.0):
    """Hold J/K, coefficients and explicit AGH seed fixed across query counts."""
    if not query_counts or len(set(query_counts)) != len(query_counts):
        raise ValueError("query counts must be nonempty and unique")
    if any(isinstance(n, bool) or not isinstance(n, int) or n < 2 for n in query_counts):
        raise ValueError("query counts must be integers at least two")
    if isinstance(load, bool) or not isinstance(load, (int, float)) or not math.isfinite(load) or load <= 0:
        raise ValueError("load must be finite and positive")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an explicit integer")
    cases = []
    for count in query_counts:
        instance = replace(make_scaling_experiment_case(count, 4, 4, load_multiplier=load).instance,
                           unit_convention=UnitConvention.COHERENT)
        for method in ("gh", "agh"):
            cases.append(ParityCase(f"{count}x4x4_load{load:g}_{method}", instance, method, seed=seed))
    return tuple(cases)


def fingerprints(args, inputs):
    """Hash the declared compiled snapshot, executables and actual transports.

    The snapshot is supplied explicitly so concurrent prototype edits in the
    working C++ tree cannot change the provenance of a frozen baseline binary.
    The build description must identify the compiler flags used for that copy.
    """
    directory = args.baseline_source_dir.resolve()
    sources = sorted(p for p in directory.rglob("*")
                     if p.is_file() and (p.suffix in {".cpp", ".hpp"} or p.name == "Makefile"))
    if not sources:
        raise ValueError(f"no C++ source inventory in {directory}")
    python_sources = [*sorted((ROOT / "src").rglob("*.py")),
                      ROOT / "scripts/check_cpp_parity.py", ROOT / "scripts/check_openmp_campaign.py"]
    result = {
        "compiled_source_directory": str(directory),
        "compiled_source_sha256": {p.relative_to(directory).as_posix(): sha256(p) for p in sources},
        "python_source_sha256": {p.relative_to(ROOT).as_posix(): sha256(p) for p in python_sources},
        "runner_sha256": sha256(Path(__file__)),
        "binary_sha256": sha256(args.binary),
        "input_sha256": {p.name: sha256(p) for p in inputs},
    }
    if args.profile_binary:
        result["profile_binary_sha256"] = sha256(args.profile_binary)
    return result


def verify_fingerprints(before, after):
    if before != after:
        raise RuntimeError("declared sources, binary or inputs changed during profiling")


def science_projection(actual):
    return {key: value for key, value in actual.items() if key not in TIMING_FIELDS}


def measurement(actual, wall, *, repeat=1):
    seconds = actual["repeat_seconds"]
    if not isinstance(seconds, list) or len(seconds) != repeat:
        raise AssertionError("individual repeat count differs")
    values = [actual["algorithm_seconds"], wall, *seconds]
    if any(isinstance(value, bool) or not isinstance(value, (int, float))
           or not math.isfinite(value) or value <= 0 for value in values):
        raise AssertionError("measurement durations must be finite and positive")
    if actual["algorithm_seconds"] != min(seconds):
        raise AssertionError("algorithm_seconds must be the minimum individual duration")
    record = {"cpp_core_seconds": actual["algorithm_seconds"],
              "cpp_repeat_seconds": seconds, "process_wall_seconds": wall}
    if "phase_seconds" in actual:
        phases = actual["phase_seconds"]

        def valid_duration(value):
            return (not isinstance(value, bool) and isinstance(value, (int, float))
                    and math.isfinite(value) and value >= 0)

        if not isinstance(phases, dict) or any(
                not (all(valid_duration(item) for item in value) if isinstance(value, list)
                     else valid_duration(value)) for value in phases.values()):
            raise AssertionError("phase_seconds must contain finite nonnegative observations")
        if "algorithm" in phases and phases["algorithm"] != seconds:
            raise AssertionError("phase algorithm durations must match repeat_seconds")
        if "result_destruction" in phases and (not isinstance(phases["result_destruction"], list)
                or len(phases["result_destruction"]) != repeat):
            raise AssertionError("phase result_destruction count must match repeat count")
        record["phase_seconds"] = phases
    for field in ("validation_statistics", "validation_execution"):
        if field in actual:
            if not isinstance(actual[field], dict):
                raise AssertionError(f"{field} must be an observation object")
            record[field] = actual[field]
    # Startup/WSL, parse, serialization, destruction and transport cannot be
    # separated just by subtracting the inner algorithm timer from process wall.
    record["unattributed_process_minus_core_seconds"] = wall - sum(seconds)
    return record


def verify_summary(expected, actual):
    """Check retained evidence even when large placement/GH traces are omitted."""
    projection = science_projection(actual)
    reference = science_projection(expected)
    for key in ("placement", "gh_trace"):
        projection.pop(key, None)
        reference.pop(key, None)
    verify_bitwise(reference, projection)


def parse_gprof(report, repetitions):
    """Extract exact observed call counts and explicitly sampled grain estimates.

    Flat self time is sampled. Call-graph child time is propagated by gprof,
    not an independently timed inclusive stopwatch. Preserve both authorities.
    Match the complete function name to avoid confusing its residual lambda
    (often the dominant self-time row) with the validator itself.
    """
    if isinstance(repetitions, bool) or not isinstance(repetitions, int) or repetitions < 1:
        raise ValueError("repetitions must be a positive integer")
    flat = report.split("Call graph", 1)[0]
    row_pattern = re.compile(
        r"^\s*(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)"
        r"(?:\s+(\d+)\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?))?\s+(.+)$"
    )
    rows = []
    for line in flat.splitlines():
        match = row_pattern.match(line)
        if match:
            rows.append({"self_percent": float(match[1]), "cumulative_seconds": float(match[2]),
                         "self_seconds": float(match[3]), "calls": int(match[4]) if match[4] else None,
                         "symbol": match[7]})
    validator = next((row for row in rows if row["symbol"] == VALIDATE_SYMBOL), None)
    if validator is None or not validator["calls"]:
        raise ValueError("gprof flat profile has no exact validator call-count row")
    graph_pattern = re.compile(
        r"^\[\d+\]\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)"
        r"\s+(\d+)(?:\+\d+)?\s+" + re.escape(VALIDATE_SYMBOL) + r"\s+\[\d+\]\s*$",
        re.MULTILINE,
    )
    graph = graph_pattern.search(report)
    if graph is None or int(graph[4]) != validator["calls"]:
        raise ValueError("gprof call graph lacks matching exact validator call evidence")
    sample = re.search(r"Each sample counts as (\d+(?:\.\d+)?) seconds", report)
    calls = validator["calls"]
    inclusive = float(graph[2]) + float(graph[3])
    return {
        "sample_interval_seconds": float(sample[1]) if sample else None,
        "total_sampled_seconds": max(row["cumulative_seconds"] for row in rows),
        "validate_calls": calls, "validate_calls_per_algorithm": calls / repetitions,
        "validate_flat_self_seconds": validator["self_seconds"],
        "validate_flat_self_seconds_per_call": validator["self_seconds"] / calls,
        "validate_callgraph_self_seconds": float(graph[2]),
        "validate_callgraph_children_seconds": float(graph[3]),
        "validate_inclusive_propagated_seconds": inclusive,
        "validate_inclusive_propagated_seconds_per_call": inclusive / calls,
        "validate_callgraph_percent": float(graph[1]),
        "largest_flat_rows": sorted(rows, key=lambda row: row["self_seconds"], reverse=True)[:12],
        "grain_estimate_authority": "sampled flat self and gprof propagated call-graph child time; not direct per-call stopwatch",
    }


def command_output(command, *, timeout=120):
    result = subprocess.run(command, text=True, capture_output=True, timeout=timeout, check=False)
    if result.returncode:
        raise RuntimeError(f"command failed ({result.returncode}): {result.stderr.strip()}")
    return result.stdout


def omp_environment(wait_policy="active"):
    if wait_policy not in {"active", "passive"}:
        raise ValueError("OpenMP wait policy must be active or passive")
    return {"OMP_DYNAMIC": "FALSE", "OMP_PROC_BIND": "close", "OMP_PLACES": "cores",
            "OMP_WAIT_POLICY": wait_policy.upper()}


def run_transport(binary, method, transport, *, repeat=1, summary=False,
                  timeout=600, wsl=None, cwd=None, extra_arguments=(), omp_wait_policy="active"):
    """Keep affinity and wait policy scoped to the measured child process."""
    arguments = [method, "--repeat", str(repeat), *extra_arguments]
    if summary:
        arguments.append("--summary")
    command = executable_command(binary, arguments, wsl=wsl, cwd=cwd)
    settings = omp_environment(omp_wait_policy)
    environment = None
    if wsl:
        position = command.index("--exec") + 1
        command[position:position] = ["env", *(f"{key}={value}" for key, value in settings.items())]
    else:
        environment = {**os.environ, **settings}
    start = perf_counter()
    process = subprocess.run(command, input=transport.encode("utf-8"), capture_output=True,
                             timeout=timeout, check=False, cwd=None if wsl else cwd, env=environment)
    wall = perf_counter() - start
    if process.returncode:
        diagnostic = process.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"C++ exited {process.returncode}: {diagnostic}")
    return json.loads(process.stdout), wall


def runtime_metadata(args):
    prefix = ["wsl", "-d", args.wsl, "--exec"] if args.wsl else []
    result = {"python": platform.python_version(), "coordinator_platform": platform.platform(),
              "wsl_distribution": args.wsl, "build_description": args.build_description,
              "omp_environment": omp_environment(args.omp_wait_policy),
              "binary": str(args.binary.resolve()),
              "profile_binary": str(args.profile_binary.resolve()) if args.profile_binary else None}
    result["compiler"] = command_output([*prefix, "g++", "--version"]).splitlines()[0]
    result["cpp_runtime"] = command_output([*prefix, "uname", "-srmo"]).strip()
    cpu = json.loads(command_output([*prefix, "lscpu", "--json"]))["lscpu"]
    keep = {"Architecture", "CPU(s)", "Model name", "Thread(s) per core", "Core(s) per socket", "Socket(s)"}
    result["cpu"] = {row["field"].rstrip(":"): row["data"] for row in cpu
                     if row["field"].rstrip(":") in keep}
    return result


def profile_case(args, case, transport, core_seconds, full_reference):
    """Use fresh gmon files, enlarging repeats until at least target CPU samples."""
    repeats = args.gprof_repeat or max(2, math.ceil(args.gprof_target_seconds / core_seconds))
    attempts = []
    for attempt in range(4):
        parent = args.output / "gprof" / case.name
        parent.mkdir(parents=True, exist_ok=True)
        directory = Path(tempfile.mkdtemp(prefix="run-", dir=parent))
        actual, wall = run_transport(args.profile_binary, case.method, transport, repeat=repeats,
                                    summary=True, wsl=args.wsl, cwd=directory, timeout=args.timeout,
                                    omp_wait_policy=args.omp_wait_policy)
        measurement(actual, wall, repeat=repeats)
        verify_summary(full_reference, actual)
        gmon = directory / "gmon.out"
        if not gmon.is_file() or not gmon.stat().st_size:
            raise RuntimeError(f"fresh instrumented run produced no nonempty gmon.out in {directory}")
        executable = linux_path(args.profile_binary) if args.wsl else str(args.profile_binary.resolve())
        exposed_gmon = linux_path(gmon) if args.wsl else str(gmon.resolve())
        prefix = ["wsl", "-d", args.wsl, "--exec"] if args.wsl else []
        report = command_output([*prefix, "gprof", "--demangle", executable, exposed_gmon], timeout=args.timeout)
        report_path = directory / "flat-and-callgraph.txt"
        report_path.write_text(report, encoding="utf-8")
        parsed = parse_gprof(report, repeats)
        attempts.append({"repetitions": repeats, "process_wall_seconds": wall,
                         "report": report_path.relative_to(args.output).as_posix(),
                         "report_sha256": sha256(report_path),
                         "gmon": gmon.relative_to(args.output).as_posix(), "gmon_sha256": sha256(gmon),
                         "fresh_directory": True, **parsed})
        if parsed["total_sampled_seconds"] >= args.gprof_target_seconds:
            return {"case": case.name, "instrumented": True, "sample_target_seconds": args.gprof_target_seconds,
                    "target_reached": True, "attempts": attempts, "selected": attempts[-1]}
        sampled = parsed["total_sampled_seconds"]
        repeats = max(repeats * 2, math.ceil(repeats * args.gprof_target_seconds / max(sampled, 0.01) * 1.2))
    raise RuntimeError(f"gprof sample target not reached for {case.name} after {len(attempts)} attempts")


def measure_case(args, case, transport, full_reference):
    samples = []
    for index in range(args.repeats):
        actual, wall = run_transport(args.binary, case.method, transport, summary=True,
                                    wsl=args.wsl, timeout=args.timeout, extra_arguments=args.extra_argument,
                                    omp_wait_policy=args.omp_wait_policy)
        verify_summary(full_reference, actual)
        path = args.output / "samples" / f"{case.name}_{index}.json"
        save_json(path, actual)
        samples.append({"round": index, "evidence": path.relative_to(args.output).as_posix(),
                        "evidence_sha256": sha256(path), **measurement(actual, wall)})
    return {"samples": samples, "cpp_core_min_seconds": min(s["cpp_core_seconds"] for s in samples),
            "process_wall_min_seconds": min(s["process_wall_seconds"] for s in samples)}


def baseline(args):
    cases = workload_cases(args.query_counts, seed=args.seed, load=args.load)
    paths = []
    for case in cases:
        path = args.output / "inputs" / (case.name + ".txt")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(serialize_case(case), encoding="utf-8", newline="")
        paths.append(path)
    before = fingerprints(args, paths)
    result = {"classification": "synthetic implementation performance; not paper numerical replication",
              "mode": "baseline", "complete": False, "metadata": runtime_metadata(args),
              "configuration": {"query_counts": args.query_counts, "models": 4, "gpu_tiers": 4,
                                "load_multiplier": args.load, "seed": args.seed, "beta": 0.8,
                                "paper_version": "V2", "unit_convention": "COHERENT", "repeats": args.repeats},
              "fingerprints_before": before,
              "timing_policy": "minimum of individual C++ calls across warm coordinator repeats; process minima separate",
              "python_reference_timing_scope": "one check_case: public Python algorithm, projection and independent validation",
              "cases": []}
    for case, input_path in zip(cases, paths, strict=True):
        transport = input_path.read_text(encoding="utf-8")
        actual, wall = run_transport(args.binary, case.method, transport, wsl=args.wsl, timeout=args.timeout,
                                    omp_wait_policy=args.omp_wait_policy)
        print(f"Checking one Python reference: {case.name}", flush=True)
        start = perf_counter()
        expected = check_case(case, actual)
        reference_seconds = perf_counter() - start
        if not math.isfinite(reference_seconds) or reference_seconds <= 0:
            raise RuntimeError("Python reference duration must be finite and positive")
        golden_path = args.output / "goldens" / (case.name + ".json")
        save_json(golden_path, {"case": case.name, "method": case.method, "seed": case.seed,
                               "input_sha256": sha256(input_path), "reference": expected})
        cpp_path = args.output / "evidence" / (case.name + ".json.gz")
        cpp_sha = save_evidence(cpp_path, actual)
        record = {"case": case.name, "method": case.method, "dimensions": case.instance.dimensions,
                  "seed": case.seed, "feasible": expected["feasible"], "objective": expected["objective"],
                  "input": input_path.relative_to(args.output).as_posix(), "input_sha256": sha256(input_path),
                  "python_golden": golden_path.relative_to(args.output).as_posix(), "python_golden_sha256": sha256(golden_path),
                  "full_cpp_evidence": cpp_path.relative_to(args.output).as_posix(), "full_cpp_evidence_sha256": cpp_sha,
                  "python_reference_check_seconds": reference_seconds,
                  "reference_calls": 1, "warm_full_measurement": measurement(actual, wall),
                  "python_parity": numerical_difference(expected, actual),
                  **measure_case(args, case, transport, actual)}
        if args.profile_binary and case.method == "agh":
            record["gprof"] = profile_case(args, case, transport, record["cpp_core_min_seconds"], actual)
        result["cases"].append(record)
        save_json(args.output / "profile.json", result)
        print(f"{case.name}: core {record['cpp_core_min_seconds']:.6f}s; process {record['process_wall_min_seconds']:.6f}s", flush=True)
    after = fingerprints(args, paths)
    verify_fingerprints(before, after)
    result.update(complete=True, fingerprints_after=after, fingerprints_verified_unchanged=True)
    save_json(args.output / "profile.json", result)
    write_report(args.output, result)
    return result


def candidate(args):
    """Replay checksummed baseline inputs/goldens without another Python solve."""
    base = args.baseline_output.resolve()
    baseline_path = base / "profile.json"
    original = json.loads(baseline_path.read_text(encoding="utf-8"))
    if original.get("mode") != "baseline" or not original.get("complete"):
        raise ValueError("candidate requires a completed baseline profile")
    records = original["cases"]
    inputs = [base / record["input"] for record in records]
    before = fingerprints(args, inputs)
    baseline_sha = sha256(baseline_path)
    result = {"classification": original["classification"], "mode": "candidate", "complete": False,
              "candidate_label": args.candidate_label, "metadata": runtime_metadata(args),
              "extra_arguments": args.extra_argument, "baseline": str(base), "baseline_sha256": baseline_sha,
              "fingerprints_before": before, "repeats": args.repeats, "cases": []}
    for record, input_path in zip(records, inputs, strict=True):
        golden_path = base / record["python_golden"]
        cpp_path = base / record["full_cpp_evidence"]
        for path, field in ((input_path, "input_sha256"), (golden_path, "python_golden_sha256"),
                            (cpp_path, "full_cpp_evidence_sha256")):
            if sha256(path) != record[field]:
                raise RuntimeError(f"baseline artifact checksum differs: {path}")
        golden = json.loads(golden_path.read_text(encoding="utf-8"))
        full_reference = json.loads(gzip.decompress(cpp_path.read_bytes()))
        transport = input_path.read_text(encoding="utf-8")
        actual, wall = run_transport(args.binary, record["method"], transport, wsl=args.wsl,
                                    timeout=args.timeout, extra_arguments=args.extra_argument,
                                    omp_wait_policy=args.omp_wait_policy)
        check_reference(golden["reference"], actual)
        verify_bitwise(science_projection(full_reference), science_projection(actual), record["case"])
        # measure_case needs only case.name/method; avoid reconstructing inputs
        # or executing the Python algorithm during candidate replay.
        case = argparse.Namespace(name=record["case"], method=record["method"])
        path = args.output / "evidence" / (case.name + ".json.gz")
        current = {"case": case.name, "method": case.method, "dimensions": record["dimensions"],
                   "full_bitwise_parity": True, "frozen_python_parity": True,
                   "reference_calls": 0, "full_cpp_evidence": path.relative_to(args.output).as_posix(),
                   "full_cpp_evidence_sha256": save_evidence(path, actual),
                   "warm_full_measurement": measurement(actual, wall),
                   **measure_case(args, case, transport, full_reference)}
        current["core_speedup"] = record["cpp_core_min_seconds"] / current["cpp_core_min_seconds"]
        current["process_speedup"] = record["process_wall_min_seconds"] / current["process_wall_min_seconds"]
        result["cases"].append(current)
        save_json(args.output / "profile.json", result)
        print(f"{case.name}: complete bitwise pass; core {current['core_speedup']:.3f}x; process {current['process_speedup']:.3f}x", flush=True)
    after = fingerprints(args, inputs)
    verify_fingerprints(before, after)
    if sha256(baseline_path) != baseline_sha:
        raise RuntimeError("baseline profile changed during candidate replay")
    result.update(complete=True, fingerprints_after=after, fingerprints_verified_unchanged=True)
    save_json(args.output / "profile.json", result)
    write_report(args.output, result)
    return result


def write_report(directory, result):
    lines = ["# Larger synthetic GH/AGH profiling", "", result["classification"], "",
             "Core chrono and complete child-process wall use separate minima of fixed individual calls.",
             "Process minus core is unattributed overhead, not a measurement of parsing or destruction.", "",
             "| Case | C++ core (s) | Process wall (s) |", "|---|---:|---:|"]
    for record in result["cases"]:
        lines.append(f"| {record['case']} | {record['cpp_core_min_seconds']:.6f} | {record['process_wall_min_seconds']:.6f} |")
    for record in result["cases"]:
        if "gprof" in record:
            profile = record["gprof"]["selected"]
            lines.extend(("", f"{record['case']}: {profile['validate_calls_per_algorithm']:g} validate calls/solve; "
                          f"{profile['validate_inclusive_propagated_seconds_per_call'] * 1e6:.2f} us/call "
                          f"gprof propagated inclusive estimate, {profile['total_sampled_seconds']:.2f}s sampled. "
                          f"Report: `{profile['report']}`."))
    lines.extend(("", "gprof self times are sampled; inclusive child times are propagated estimates. "
                  "They identify grain and bottlenecks rather than directly timing individual validator calls."))
    (directory / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("baseline", "candidate"), default="baseline")
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--profile-binary", type=Path)
    parser.add_argument("--baseline-source-dir", type=Path, required=True,
                        help="exact frozen C++ source snapshot compiled for the supplied binary")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wsl")
    parser.add_argument("--omp-wait-policy", choices=("active", "passive"), default="active")
    parser.add_argument("--query-counts", type=int, nargs="+", default=[16, 32, 64])
    parser.add_argument("--seed", type=int, default=37)
    parser.add_argument("--load", type=float, default=200.0)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--gprof-repeat", type=int,
                        help="starting instrumented repeat count; increases if sampled target is not reached")
    parser.add_argument("--gprof-target-seconds", type=float, default=1.2)
    parser.add_argument("--build-description", required=True)
    parser.add_argument("--baseline-output", type=Path)
    parser.add_argument("--candidate-label", default="candidate")
    parser.add_argument("--extra-argument", action="append", default=[],
                        help="candidate child option; use --extra-argument=--option for leading dashes")
    args = parser.parse_args(argv)
    if args.repeats < 1 or args.gprof_repeat is not None and args.gprof_repeat < 1:
        parser.error("repetition counts must be positive")
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("timeout must be finite and positive")
    if not math.isfinite(args.gprof_target_seconds) or args.gprof_target_seconds < 1:
        parser.error("gprof target must be finite and at least one sampled second")
    if args.mode == "candidate" and args.baseline_output is None:
        parser.error("candidate mode requires --baseline-output")
    if args.mode == "baseline" and args.extra_argument:
        parser.error("extra arguments are reserved for candidate replay")
    if args.mode == "candidate" and args.output.resolve() == args.baseline_output.resolve():
        parser.error("candidate output must differ from preserved baseline output")
    try:
        workload_cases(args.query_counts, seed=args.seed, load=args.load)
    except ValueError as error:
        parser.error(str(error))
    return args


def main(argv=None):
    args = parse_args(argv)
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.mode == "baseline":
        baseline(args)
    else:
        candidate(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
