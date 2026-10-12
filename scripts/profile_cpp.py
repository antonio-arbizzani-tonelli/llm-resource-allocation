"""Bounded serial profiling of identical synthetic Python and C++ instances.

PACS lecture 20: verify parity, profile bottlenecks, optimize, and recheck.
PACS lecture 21 p.19: repeat fixed inputs and retain minimum timing. Core C++
chrono time is reported separately from the process/WSL wall-clock boundary.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path
import platform
import subprocess
import tempfile
from time import perf_counter

from check_cpp_parity import (
    ROOT, ParityCase, check_case, linux_path, make_python_runner,
    run_cpp, serialize_case,
)
from llm_resource_allocation.data.scaling_experiment_instances import make_scaling_experiment_case
from llm_resource_allocation.domain import UnitConvention


def profile_cases():
    """Small explicit workload matrix; these are assumed synthetic inputs."""
    for dims, load in (((4, 2, 2), 1.0), ((8, 4, 4), 200.0), ((16, 4, 4), 200.0)):
        instance = replace(make_scaling_experiment_case(*dims, load_multiplier=load).instance,
                           unit_convention=UnitConvention.COHERENT)
        for method in ("gh", "agh"):
            yield ParityCase(f"{dims[0]}x{dims[1]}x{dims[2]}_load{load:g}_{method}", instance, method)


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False)+"\n", encoding="utf-8")


def command_output(command, *, cwd=None):
    process = subprocess.run(command, text=True, capture_output=True, cwd=cwd,
                             timeout=120, check=False)
    if process.returncode:
        raise RuntimeError(f"command failed ({process.returncode}): {process.stderr.strip()}")
    return process.stdout


def capture_fingerprints(args):
    """Hash the source inventory and both executables at a measurement boundary."""
    files = [*sorted((ROOT / "cpp").rglob("*.cpp")),
             *sorted((ROOT / "cpp").rglob("*.hpp")), ROOT / "cpp/Makefile",
             *sorted((ROOT / "src").rglob("*.py")),
             ROOT / "scripts/check_cpp_parity.py", ROOT / "scripts/profile_cpp.py"]
    fingerprints = {"source_sha256": {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                      for p in files},
                    "binary_sha256": hashlib.sha256(args.binary.read_bytes()).hexdigest()}
    if args.gprof_binary:
        fingerprints["gprof_binary_sha256"] = hashlib.sha256(args.gprof_binary.read_bytes()).hexdigest()
    return fingerprints


def verify_fingerprints(before, after):
    """Reject timings when their source or executable changed during the run."""
    changed = []
    for field in ("binary_sha256", "gprof_binary_sha256"):
        if before.get(field) != after.get(field):
            changed.append(field)
    old_sources, new_sources = before["source_sha256"], after["source_sha256"]
    changed.extend(name for name in sorted(old_sources.keys() | new_sources.keys())
                   if old_sources.get(name) != new_sources.get(name))
    if changed:
        raise RuntimeError("profiling inputs changed during the run: " + ", ".join(changed))


def capture_metadata(args):
    """Read build and execution fingerprints before measured work starts."""
    metadata = capture_fingerprints(args)
    if args.wsl:
        prefix = ["wsl", "-d", args.wsl, "--exec"]
        cpu = json.loads(command_output([*prefix, "lscpu", "--json"]))["lscpu"]
        keep = {"Architecture", "CPU(s)", "Model name", "Thread(s) per core", "Core(s) per socket",
                "Socket(s)", "Hypervisor vendor", "L1d cache", "L1i cache", "L2 cache", "L3 cache"}
        metadata["cpu"] = {row["field"].rstrip(":"): row["data"] for row in cpu
                           if row["field"].rstrip(":") in keep}
        metadata["cpp_runtime"] = command_output([*prefix, "uname", "-srmo"]).strip()
        metadata["compiler"] = command_output([*prefix, "g++", "--version"]).splitlines()[0]
    else:
        metadata["cpu"] = {"processor": platform.processor(), "machine": platform.machine()}
    return metadata


def gprof_profile(args, case):
    """Record a real instrumented profile; never label chrono timing profiling."""
    output = args.output.resolve()
    parent = output / "gprof"
    parent.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="run-", dir=parent))
    actual, _ = run_cpp(args.gprof_binary, case, repeat=args.gprof_repeat,
                        summary=True, wsl=args.wsl, cwd=directory)
    gmon_path = directory / "gmon.out"
    if not gmon_path.is_file() or gmon_path.stat().st_size == 0:
        raise RuntimeError(f"instrumented execution produced no nonempty gmon.out in {directory}")
    tool = "gprof" if args.wsl else args.gprof_tool
    executable = linux_path(args.gprof_binary) if args.wsl else str(args.gprof_binary.resolve())
    gmon = linux_path(gmon_path) if args.wsl else str(gmon_path.resolve())
    command = (["wsl", "-d", args.wsl, "--cd", linux_path(directory), "--exec",
                "gprof", "--demangle", executable, gmon] if args.wsl
               else [tool, "--demangle", executable, gmon])
    report = command_output(command, cwd=None if args.wsl else directory)
    (directory / "flat-and-callgraph.txt").write_text(report, encoding="utf-8")
    return {"case": case.name, "repetitions": args.gprof_repeat,
            "algorithm_seconds": actual["algorithm_seconds"],
            "report": (directory / "flat-and-callgraph.txt").relative_to(output).as_posix(),
            "gmon": gmon_path.relative_to(output).as_posix(),
            "gmon_sha256": hashlib.sha256(gmon_path.read_bytes()).hexdigest(),
            "instrumented": True, "fresh_directory": True}


def measure_python_calls(runner, count):
    """Retain individual algorithm durations, matching the C++ chrono samples."""
    seconds = []
    for _ in range(count):
        start = perf_counter()
        runner()
        duration = perf_counter() - start
        if not math.isfinite(duration) or duration <= 0:
            raise RuntimeError("Python algorithm timing must be finite and positive")
        seconds.append(duration)
    return seconds


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "cpp/build/release/pacs_serial")
    parser.add_argument("--wsl")
    parser.add_argument("--output", type=Path, default=ROOT / "results/cpp_serial_profile")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--inner-repeat", type=int, default=1)
    parser.add_argument("--case", action="append")
    parser.add_argument("--gprof-binary", type=Path,
                        help="C++ executable built with -pg at compilation and linking")
    parser.add_argument("--gprof-tool", default="gprof")
    parser.add_argument("--gprof-repeat", type=int, default=100)
    parser.add_argument("--build-description", default="unspecified; supply exact compiler and flags")
    args = parser.parse_args()
    if min(args.repeats, args.inner_repeat, args.gprof_repeat) < 1:
        parser.error("all repetition counts must be positive")
    cases = [c for c in profile_cases()
             if not args.case or any(label in c.name for label in args.case)]
    if not cases:
        parser.error("no matching cases")
    metadata = capture_metadata(args)
    records = []
    for case in cases:
        # Warm both runtimes and independently establish equivalence first.
        actual, _ = run_cpp(args.binary, case, wsl=args.wsl)
        expected = check_case(case, actual)
        inputs = args.output / "inputs"
        inputs.mkdir(parents=True, exist_ok=True)
        (inputs / (case.name + ".txt")).write_text(serialize_case(case), encoding="utf-8")
        python_run = make_python_runner(case)
        samples = []
        for _ in range(args.repeats):
            python_repeat_seconds = measure_python_calls(python_run, args.inner_repeat)
            python_seconds = min(python_repeat_seconds)
            actual, wall = run_cpp(args.binary, case, repeat=args.inner_repeat,
                                   summary=True, wsl=args.wsl)
            cpp_seconds = actual["algorithm_seconds"]
            if not math.isfinite(cpp_seconds) or cpp_seconds <= 0:
                raise RuntimeError("C++ core timing must be finite and positive")
            samples.append({"python_seconds": python_seconds, "cpp_core_seconds": cpp_seconds,
                            "python_repeat_seconds": python_repeat_seconds,
                            "python_repetitions": args.inner_repeat,
                            "cpp_process_wall_seconds": wall,
                            "cpp_repeat_seconds": actual["repeat_seconds"],
                            "cpp_repetitions": args.inner_repeat})
        minimum_python = min(s["python_seconds"] for s in samples)
        minimum_cpp = min(s["cpp_core_seconds"] for s in samples)
        record = {"case": case.name, "method": case.method, "dimensions": case.instance.dimensions,
                  "coherent": True, "seed": case.seed, "feasible": expected["feasible"],
                  "objective": expected["objective"],
                  "input_sha256": hashlib.sha256(serialize_case(case).encode()).hexdigest(),
                  "samples": samples, "python_min_seconds": minimum_python,
                  "cpp_core_min_seconds": minimum_cpp,
                  "python_over_cpp_core": minimum_python/minimum_cpp}
        records.append(record)
        print(f"{case.name}: Python {minimum_python:.6f}s; C++ core {minimum_cpp:.6f}s; "
              f"ratio {record['python_over_cpp_core']:.2f}", flush=True)
    profiler = None
    if args.gprof_binary:
        # Choose the slowest measured case: enough samples for the profiler.
        selected = max(records, key=lambda r: r["cpp_core_min_seconds"])["case"]
        profiler = gprof_profile(args, next(c for c in cases if c.name == selected))
    post_run_fingerprints = capture_fingerprints(args)
    verify_fingerprints(metadata, post_run_fingerprints)
    metadata["post_run_fingerprints"] = post_run_fingerprints
    metadata["fingerprints_verified_unchanged"] = True
    result = {"classification": "synthetic implementation performance; not paper numerical replication",
              "python": platform.python_version(), "platform": platform.platform(),
              "binary": str(args.binary.resolve()), "build": args.build_description,
              "wsl_distribution": args.wsl,
              "timing_policy": "minimum individual call duration across all warm repeats in both runtimes",
              "timing_scope": "public algorithm plus validation; excludes C++ parse/output/startup",
              "metadata": metadata,
              "limitations": ["Python public APIs validate original inputs; C++ algorithms use prepared inputs",
                              "Python retains richer trace objects than the C++ port",
                              "WSL/process wall time is separate from core timing",
                              "ratios compare implementations and runtime environments, not pure languages",
                              "ratios apply only to this measured synthetic workload"],
              "repeats": args.repeats, "inner_repeat": args.inner_repeat,
              "gprof": profiler, "cases": records}
    save(args.output / "profile.json", result)
    lines = ["# Serial C++ synthetic profiling", "", args.build_description, "",
             "Minimum of repeated identical inputs; parity and independent Python validation checked before timing.",
             "C++ core excludes transport/startup; Python builds richer trace evidence. This is not paper numerical replication.",
             "Python public APIs validate original inputs; C++ uses prepared inputs. Ratios compare these implementations and runtime environments, not pure languages.",
             "", "| Case | Python (s) | C++ core (s) | Ratio |", "|---|---:|---:|---:|"]
    lines.extend(f"| {r['case']} | {r['python_min_seconds']:.6f} | {r['cpp_core_min_seconds']:.6f} | {r['python_over_cpp_core']:.2f} |"
                 for r in records)
    if profiler:
        lines.extend(("", f"Real gprof flat profile and call graph: `{profiler['report']}`."))
    (args.output / "report.md").write_text("\n".join(lines)+"\n", encoding="utf-8")


if __name__ == "__main__":
    main()
