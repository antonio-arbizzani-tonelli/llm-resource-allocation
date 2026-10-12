"""Measure strong scaling of verified, independent GH/AGH campaigns.

Work is fixed across schedules and team sizes. Serial GH/AGH arithmetic,
acceptance, validation, seeds and early stopping remain inside every job.
Chrono campaign time excludes parsing, JSON transport and process startup.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
import gzip
import hashlib
import json
import math
from pathlib import Path
import platform
import subprocess

from check_openmp_campaign import (
    OMP_ENVIRONMENT, ROOT, ParityCase, run_campaign, save_json,
    serial_references, verify_cases, write_manifest,
)
from check_cpp_parity import linux_path
from llm_resource_allocation.data.scaling_experiment_instances import make_scaling_experiment_case
from llm_resource_allocation.domain import UnitConvention


def campaign_workloads(batch_size=16, seed=37, seed_step=1):
    """Two fixed synthetic loads: uniform large AGH and clustered mixed costs."""
    if batch_size < 4 or batch_size % 4:
        raise ValueError("batch_size must be a positive multiple of four, at least four")
    large = replace(make_scaling_experiment_case(16, 4, 4, load_multiplier=200.0).instance,
                    unit_convention=UnitConvention.COHERENT)
    medium = replace(make_scaling_experiment_case(8, 4, 4, load_multiplier=200.0).instance,
                     unit_convention=UnitConvention.COHERENT)
    uniform = tuple(ParityCase(f"uniform_{index:03d}_agh", large, "agh", seed=seed + index * seed_step)
                    for index in range(batch_size))
    mixed = []
    for index in range(batch_size):
        # Deliberately cluster expensive jobs. Static and dynamic scheduling
        # operate on exactly the same manifest, making load balance observable.
        instance = large if index < batch_size // 2 else medium
        method = "agh" if index < 3 * batch_size // 4 else "gh"
        mixed.append(ParityCase(f"mixed_{index:03d}_{method}", instance, method,
                                seed=seed + index * seed_step))
    return {"uniform": uniform, "mixed": tuple(mixed)}


def scaling_statistics(serial_seconds, samples):
    """Use minima consistently and efficiency based on the observed team size."""
    if not samples or not math.isfinite(serial_seconds) or serial_seconds <= 0:
        raise ValueError("serial duration must be positive and samples must be nonempty")
    teams = {team for sample in samples for team in sample.get("repeat_threads", [sample["actual_threads"]])}
    teams.update(sample["actual_threads"] for sample in samples)
    if len(teams) != 1:
        raise ValueError("observed OpenMP team changed between samples")
    team = next(iter(teams))
    if isinstance(team, bool) or not isinstance(team, int) or team < 1:
        raise ValueError("actual_threads must be a positive integer")
    durations = [sample["campaign_seconds"] for sample in samples]
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0
           for value in durations):
        raise ValueError("sample durations must be finite and positive")
    minimum = min(durations)
    speedup = serial_seconds / minimum
    return {"actual_threads": team, "campaign_min_seconds": minimum,
            "speedup": speedup, "efficiency": speedup / team}


def fingerprints(args, manifests):
    sources = [*sorted((ROOT / "cpp").rglob("*.cpp")),
               *sorted((ROOT / "cpp").rglob("*.hpp")), ROOT / "cpp/Makefile",
               *sorted((ROOT / "src").rglob("*.py")),
               ROOT / "scripts/check_cpp_parity.py", ROOT / "scripts/profile_cpp.py",
               ROOT / "scripts/check_openmp_campaign.py", ROOT / "scripts/profile_openmp.py"]
    inputs = sorted({path for manifest in manifests.values() for path in manifest.parent.glob("*.txt")})
    return {
        "source_sha256": {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in sources},
        "input_sha256": {str(path.resolve()): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs},
        "binary_sha256": hashlib.sha256(args.binary.read_bytes()).hexdigest(),
        "serial_binary_sha256": hashlib.sha256(args.serial_binary.read_bytes()).hexdigest(),
    }


def verify_fingerprints(before, after):
    if before != after:
        raise RuntimeError("benchmark sources, binaries or numeric inputs changed during measurement")


def command_output(command):
    process = subprocess.run(command, text=True, capture_output=True, timeout=120, check=False)
    if process.returncode:
        raise RuntimeError(f"metadata command failed ({process.returncode}): {process.stderr.strip()}")
    return process.stdout.strip()


def metadata(args):
    result = {"coordinator_python": platform.python_version(), "coordinator_platform": platform.platform(),
              "wsl_distribution": args.wsl, "omp_environment": OMP_ENVIRONMENT,
              "build_description": args.build_description}
    prefix = ["wsl", "-d", args.wsl, "--exec"] if args.wsl else []
    result["compiler"] = command_output([*prefix, "g++", "--version"]).splitlines()[0]
    result["runtime"] = command_output([*prefix, "uname", "-srmo"])
    cpu = json.loads(command_output([*prefix, "lscpu", "--json"]))["lscpu"]
    keep = {"Architecture", "CPU(s)", "Model name", "Thread(s) per core", "Core(s) per socket",
            "Socket(s)", "Hypervisor vendor", "L1d cache", "L1i cache", "L2 cache", "L3 cache"}
    result["cpu"] = {row["field"].rstrip(":"): row["data"] for row in cpu
                     if row["field"].rstrip(":") in keep}
    proc = command_output([*prefix, "cat", "/proc/self/status"])
    result["cpu_affinity"] = next(line.split(":", 1)[1].strip() for line in proc.splitlines()
                                  if line.startswith("Cpus_allowed_list:"))
    library = command_output([*prefix, "g++", "-print-file-name=libgomp.so"])
    result["openmp_library"] = library
    result["openmp_library_sha256"] = command_output([*prefix, "sha256sum", library]).split()[0]
    executable = linux_path(args.binary) if args.wsl else str(args.binary.resolve())
    result["linked_libraries"] = command_output([*prefix, "ldd", executable])
    return result


def save_full_evidence(path, value):
    """Retain full warm-up traces without inflating the measurement directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(value, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
    path.write_bytes(gzip.compress(encoded, mtime=0))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "cpp/build/release/pacs_campaign")
    parser.add_argument("--serial-binary", type=Path, default=ROOT / "cpp/build/release/pacs_serial")
    parser.add_argument("--wsl")
    parser.add_argument("--output", type=Path, default=ROOT / "results/openmp_campaign_profile")
    parser.add_argument("--threads", type=int, nargs="+", default=[1, 2, 4, 8])
    parser.add_argument("--repeats", type=int, default=3, help="rotated coordinator rounds")
    parser.add_argument("--inner-repeat", type=int, default=1)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--seed", type=int, default=37)
    parser.add_argument("--seed-step", type=int, default=1)
    parser.add_argument("--workload", choices=("uniform", "mixed"), action="append")
    parser.add_argument("--build-description", default="unspecified; supply exact compiler and flags")
    args = parser.parse_args()
    if args.repeats < 2 or args.inner_repeat < 1 or any(n < 1 for n in args.threads):
        parser.error("at least two coordinator rounds and positive thread/inner-repeat counts are required")
    if args.batch_size < 4 or args.batch_size % 4:
        parser.error("batch-size must be a multiple of four, at least four")
    workloads = {name: cases for name, cases in campaign_workloads(args.batch_size, args.seed, args.seed_step).items()
                 if not args.workload or name in args.workload}
    manifests = {name: write_manifest(cases, args.output / "inputs" / name, wsl=args.wsl)
                 for name, cases in workloads.items()}
    before = fingerprints(args, manifests)
    runtime_metadata = metadata(args)
    settings = [("serial", 1), *((schedule, n) for schedule in ("static", "dynamic") for n in args.threads)]
    records = []
    for name, cases in workloads.items():
        manifest = manifests[name]
        # Python remains an independent authority. Large cases are bounded to
        # one representative per shape/method rather than timing Python again.
        python_indices = (0,) if name == "uniform" else (len(cases) // 2, 3 * len(cases) // 4)
        expected = serial_references(args.serial_binary, cases, wsl=args.wsl, python_indices=python_indices)
        save_full_evidence(args.output / "evidence" / f"{name}_serial_reference.json.gz", expected)
        warm_records = []
        for schedule, threads in settings:
            actual, wall = run_campaign(args.binary, manifest, schedule=schedule, threads=threads, wsl=args.wsl)
            verify_cases(cases, expected, actual)
            path = args.output / "evidence" / f"{name}_warm_{schedule}_{threads}.json.gz"
            digest = save_full_evidence(path, actual)
            warm_records.append({"schedule": schedule, "requested_threads": threads,
                                 "actual_threads": actual["actual_threads"], "verified_cases": len(cases),
                                 "process_wall_seconds": wall, "evidence": path.relative_to(args.output).as_posix(),
                                 "evidence_sha256": digest})
        samples = {setting: [] for setting in settings}
        execution_order = []
        for round_index in range(args.repeats):
            rotated = settings[round_index % len(settings):] + settings[:round_index % len(settings)]
            if round_index % 2:
                rotated = list(reversed(rotated))
            for schedule, threads in rotated:
                actual, wall = run_campaign(args.binary, manifest, schedule=schedule, threads=threads,
                                            repeat=args.inner_repeat, summary=True, wsl=args.wsl)
                verify_cases(cases, expected, actual, summary=True)
                path = args.output / "samples" / f"{name}_round{round_index}_{schedule}_{threads}.json"
                save_json(path, actual)
                samples[schedule, threads].append({"round": round_index, "actual_threads": actual["actual_threads"],
                    "repeat_threads": actual.get("repeat_threads", [actual["actual_threads"]] * args.inner_repeat),
                    "campaign_seconds": actual["campaign_seconds"], "repeat_seconds": actual["repeat_seconds"],
                    "process_wall_seconds": wall, "evidence": path.relative_to(args.output).as_posix(),
                    "evidence_sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
                execution_order.append({"round": round_index, "schedule": schedule, "requested_threads": threads})
        serial_seconds = min(sample["campaign_seconds"] for sample in samples["serial", 1])
        scaling = []
        for schedule, threads in settings:
            statistics = scaling_statistics(serial_seconds, samples[schedule, threads])
            scaling.append({"schedule": schedule, "requested_threads": threads, "samples": samples[schedule, threads],
                            **statistics})
            print(f"{name}: {schedule}/{threads} requested, {statistics['actual_threads']} actual; "
                  f"{statistics['campaign_min_seconds']:.6f}s, speedup {statistics['speedup']:.2f}, "
                  f"efficiency {statistics['efficiency']:.3f}", flush=True)
        records.append({"workload": name, "job_count": len(cases), "serial_min_seconds": serial_seconds,
                        "manifest": manifest.relative_to(args.output).as_posix(),
                        "python_independently_checked_cases": len(python_indices),
                        "jobs": [{"name": case.name, "method": case.method, "dimensions": case.instance.dimensions,
                                  "seed": case.seed, "beta": case.beta, "unit_convention": case.instance.unit_convention.value,
                                  "feasible": reference["feasible"], "status": reference["status"]}
                                 for case, reference in zip(cases, expected, strict=True)],
                        "warm_verified_runs": warm_records, "execution_order": execution_order, "scaling": scaling})
    after = fingerprints(args, manifests)
    verify_fingerprints(before, after)
    runtime_metadata.update(fingerprints_before=before, fingerprints_after=after, fingerprints_verified_unchanged=True)
    result = {"classification": "synthetic independent-case strong scaling; not paper numerical replication",
              "timing_policy": "minimum individual campaign duration across rotated warm coordinator rounds",
              "timing_scope": "all serial GH/AGH computation, traces and independent C++ validation; excludes parse/startup/output",
              "speedup_baseline": "serial schedule in the identical OpenMP-linked campaign executable",
              "efficiency_denominator": "observed actual_threads", "repeats": args.repeats,
              "inner_repeat": args.inner_repeat, "seed": args.seed, "seed_step": args.seed_step,
              "metadata": runtime_metadata, "workloads": records,
              "limitations": ["Throughput of independent cases does not accelerate a single GH/AGH solve",
                              "WSL, hardware affinity and other system activity affect these local timings",
                              "Only these fixed synthetic job batches support the measured speedups"]}
    save_json(args.output / "profile.json", result)
    lines = ["# Independent-case OpenMP strong scaling", "", args.build_description, "",
             "Fixed synthetic jobs; complete evidence verified against serial before timing.",
             "Minimum individual campaign duration; efficiency uses observed threads. This is not paper replication.", "",
             "| Workload | Schedule | Requested | Actual | Seconds | Speedup | Efficiency |",
             "|---|---|---:|---:|---:|---:|---:|"]
    for workload in records:
        for record in workload["scaling"]:
            lines.append(f"| {workload['workload']} | {record['schedule']} | {record['requested_threads']} | "
                         f"{record['actual_threads']} | {record['campaign_min_seconds']:.6f} | {record['speedup']:.2f} | "
                         f"{record['efficiency']:.3f} |")
    (args.output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
