"""Prepare or execute an isolated, resumable allocation experiment campaign.

The default plan has 40 fixed-deployment stress jobs, nine paired Python/C++
profiles and three OpenMP profiles. Preparation compiles and verifies binaries
but does not execute those experimental jobs. Runtime evidence is kept locally.
"""

import argparse
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import subprocess
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from check_cpp_parity import linux_path
from llm_resource_allocation.experiments.stress_grid import StressGrid
from llm_resource_allocation.optimization.solver import SolverBackend, SolverBackendAvailability, probe_solver_backend


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".pending")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    temporary.replace(path)


def load_configuration(path, backend=None):
    config = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or config.get("format_version") != 1:
        raise ValueError("expected campaign format_version 1")
    if config.get("paper_version") != "v2" or config.get("unit_convention") != "coherent":
        raise ValueError("this campaign requires coherent V2")
    if backend is not None:
        config["backend"] = backend
    SolverBackend(config["backend"])
    StressGrid(tuple(config["arrival_factors"]), tuple(config["stress_factors"]))
    for name in ("maximum_wall_seconds", "job_timeout_seconds", "stage1_solver_limit_seconds",
                 "stage2_solver_limit_seconds", "serial_load"):
        value = config[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be finite and positive")
    residency = config["data_residency_hours"]
    if isinstance(residency, bool) or not isinstance(residency, (int, float)) or not math.isfinite(residency) or residency < 0:
        raise ValueError("data residency must be finite and nonnegative")
    if not isinstance(config["gh_budget_fraction"], (int, float)) or isinstance(config["gh_budget_fraction"], bool) or not 0 <= config["gh_budget_fraction"] <= 1:
        raise ValueError("GH budget fraction must be in [0,1]")
    for name in ("stage2_shapes", "serial_shapes"):
        shapes = config[name]
        if not shapes or any(len(shape) != 3 or any(isinstance(n, bool) or not isinstance(n, int) or n < 2 for n in shape) for shape in shapes):
            raise ValueError(f"{name} must contain triples of integers >=2")
        if len({tuple(shape) for shape in shapes}) != len(shapes):
            raise ValueError(f"duplicate {name}")
    for name in ("seeds", "openmp_threads", "openmp_batch_sizes"):
        values = config[name]
        if not values or len(set(values)) != len(values) or any(isinstance(n, bool) or not isinstance(n, int) for n in values):
            raise ValueError(f"{name} must contain unique integers")
    if any(n < 1 for n in config["openmp_threads"]):
        raise ValueError("OpenMP team requests must be positive")
    if any(n < 4 or n % 4 for n in config["openmp_batch_sizes"]):
        raise ValueError("OpenMP batches must be multiples of four >=4")
    for name in ("serial_repeats", "openmp_rounds"):
        value = config[name]
        if isinstance(value, bool) or not isinstance(value, int) or value < 2:
            raise ValueError(f"{name} must be an integer >=2")
    for name in ("serial_seed", "openmp_seed"):
        if isinstance(config[name], bool) or not isinstance(config[name], int):
            raise ValueError(f"{name} must be an integer")
    if not config["stage2_loads"] or len(set(config["stage2_loads"])) != len(config["stage2_loads"]) or any(
        isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0
        for value in config["stage2_loads"]):
        raise ValueError("stage2 loads must be unique finite positive factors")
    if not config["stage2_methods"] or len(set(config["stage2_methods"])) != len(config["stage2_methods"]) or any(
        method not in ("gh", "agh", "p_dm") for method in config["stage2_methods"]):
        raise ValueError("unknown or duplicate Stage-1 method")
    # Existing native profiling uses the fixed reference residency/beta contract.
    if config["data_residency_hours"] != 1.0 or config["gh_budget_fraction"] != 0.8:
        raise ValueError("paired native campaign requires reference residency=1 and GH beta=0.8")
    return config


def configuration_digest(config):
    return hashlib.sha256(json.dumps(config, sort_keys=True, allow_nan=False).encode()).hexdigest()


def campaign_jobs(config):
    jobs = []
    for shape in config["stage2_shapes"]:
        for load in config["stage2_loads"]:
            for method in config["stage2_methods"]:
                seeds = config["seeds"] if method == "agh" else (config["seeds"][0],)
                for seed in seeds:
                    name = f"stress_{'x'.join(map(str, shape))}_L{load:g}_{method}_s{seed}"
                    jobs.append({"id": name, "kind": "stress", "shape": shape,
                                 "load": load, "method": method, "seed": seed})
    for shape in config["serial_shapes"]:
        jobs.append({"id": "serial_" + "x".join(map(str, shape)), "kind": "serial", "shape": shape})
    for size in config["openmp_batch_sizes"]:
        jobs.append({"id": f"openmp_{size}", "kind": "openmp", "batch_size": size})
    return jobs


def source_inventory(root):
    paths = [path for directory in ("src", "scripts", "tests") for path in (root / directory).rglob("*")
             if path.is_file() and path.suffix in (".py", ".ps1")]
    paths += [path for directory in ("cpp/include", "cpp/src", "cpp/experiments", "cpp/tests")
              for path in (root / directory).rglob("*")
              if path.is_file() and path.suffix in (".cpp", ".hpp", ".py", ".txt", ".json", ".md")]
    paths.append(root / "cpp/Makefile")
    return {path.relative_to(root).as_posix(): digest(path) for path in sorted(paths)}


def prepare_snapshot(output, config, wsl):
    snapshot = output / "snapshot"
    before = source_inventory(ROOT)
    for name in before:
        target = snapshot / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    if source_inventory(ROOT) != before or source_inventory(snapshot) != before:
        raise RuntimeError("sources changed while creating snapshot")
    save_json(snapshot / "configs/nightly_campaign.json", config)
    command = ["make", "-C", str(snapshot / "cpp"), "-j4", "MODE=release", "all", "test", "openmp", "campaign-test"]
    if wsl:
        command = ["wsl", "-d", wsl, "--exec", "make", "-C", linux_path(snapshot / "cpp"),
                   "-j4", "MODE=release", "all", "test", "openmp", "campaign-test"]
    logs = output / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    with (logs / "build.log").open("w", encoding="utf-8") as stream:
        subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, timeout=600, check=True)
    binaries = {name: digest(snapshot / "cpp/build/release" / name) for name in ("pacs_serial", "pacs_campaign")}
    record = {"source_sha256": before, "binary_sha256": binaries,
              "configuration_sha256": configuration_digest(config), "build_command": command}
    save_json(output / "snapshot_manifest.json", record)
    return snapshot


def verify_snapshot(output, config):
    snapshot = output / "snapshot"
    manifest = json.loads((output / "snapshot_manifest.json").read_text(encoding="utf-8"))
    if manifest["configuration_sha256"] != configuration_digest(config):
        raise ValueError("resume configuration differs from prepared snapshot")
    frozen_config = json.loads((snapshot / "configs/nightly_campaign.json").read_text(encoding="utf-8"))
    if configuration_digest(frozen_config) != manifest["configuration_sha256"]:
        raise RuntimeError("prepared configuration changed")
    if source_inventory(snapshot) != manifest["source_sha256"]:
        raise RuntimeError("prepared sources changed")
    if any(digest(snapshot / "cpp/build/release" / name) != value for name, value in manifest["binary_sha256"].items()):
        raise RuntimeError("prepared native binaries changed")
    return snapshot


def job_command(job, config, snapshot, destination, wsl):
    command = [sys.executable]
    if job["kind"] == "stress":
        return command + [str(snapshot / "scripts/run_stage2_stress.py"), "--config",
                          str(snapshot / "configs/nightly_campaign.json"), "--shape", *map(str, job["shape"]),
                          "--load", str(job["load"]), "--method", job["method"], "--seed", str(job["seed"]),
                          "--output", str(destination)]
    if job["kind"] == "serial":
        shape = job["shape"]
        command += [str(snapshot / "scripts/profile_large_instances.py"), "--mode", "baseline",
                    "--binary", str(snapshot / "cpp/build/release/pacs_serial"),
                    "--baseline-source-dir", str(snapshot / "cpp"), "--query-counts", str(shape[0]),
                    "--model-count", str(shape[1]), "--tier-count", str(shape[2]),
                    "--load", str(config["serial_load"]), "--seed", str(config["serial_seed"]),
                    "--repeats", str(config["serial_repeats"]), "--timeout", str(config["job_timeout_seconds"])]
    else:
        command += [str(snapshot / "scripts/profile_openmp.py"), "--binary", str(snapshot / "cpp/build/release/pacs_campaign"),
                    "--serial-binary", str(snapshot / "cpp/build/release/pacs_serial"),
                    "--batch-size", str(job["batch_size"]), "--threads", *map(str, config["openmp_threads"]),
                    "--repeats", str(config["openmp_rounds"]), "--seed", str(config["openmp_seed"])]
    command += ["--output", str(destination), "--build-description", config["build_description"]]
    if wsl:
        command += ["--wsl", wsl]
    return command


def terminate_worker(process, snapshot, wsl):
    """Stop only this worker tree and native executables in its run snapshot."""
    if process.poll() is None:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, check=False)
        else:
            os.killpg(process.pid, signal.SIGTERM)
    if wsl:
        binary_directory = linux_path(snapshot / "cpp/build/release")
        pattern = "^" + re.escape(binary_directory) + r"/pacs_(serial|campaign)( |$)"
        subprocess.run(["wsl", "-d", wsl, "--exec", "pkill", "-TERM", "-f", pattern],
                       capture_output=True, timeout=30, check=False)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        if os.name != "nt":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        process.wait(timeout=5)


def run_jobs(output, config, jobs, snapshot, wsl, *, deferred_jobs=()):
    history_path = output / "jobs.json"
    history = json.loads(history_path.read_text(encoding="utf-8")) if history_path.exists() else []
    for item in history:
        if item["status"] == "completed":
            directory = (output / item["output"]).resolve()
            if not directory.is_relative_to((output / "jobs").resolve()):
                raise ValueError("job evidence path escapes campaign output")
            if evidence_inventory(directory) != item["evidence_sha256"]:
                raise RuntimeError(f"completed evidence changed: {item['id']}")
    completed = {item["id"] for item in history if item["status"] == "completed"}
    deferred = set(deferred_jobs)
    if not deferred <= {job["id"] for job in jobs}:
        raise ValueError("deferred jobs must belong to this campaign")
    deadline = perf_counter() + config["maximum_wall_seconds"]
    for index, job in enumerate(jobs):
        if job["id"] in completed or job["id"] in deferred:
            continue
        remaining = deadline - perf_counter()
        if remaining <= 0:
            print("Wall-time budget exhausted; remaining jobs stay unexecuted.", flush=True)
            break
        destination = output / "jobs" / job["id"]
        attempt = sum(item["id"] == job["id"] for item in history) + 1
        if destination.exists():
            destination = output / "jobs" / f"{job['id']}_attempt{attempt}"
        destination.mkdir(parents=True, exist_ok=False)
        logfile = output / "logs" / f"{job['id']}_attempt{attempt}.log"
        command = job_command(job, config, snapshot, destination, wsl)
        print(f"[{index + 1}/{len(jobs)}] {job['id']}", flush=True)
        save_json(output / "status.json", {"status": "running", "active_job": job["id"],
                                          "completed_jobs": len(completed), "planned_jobs": len(jobs)})
        start = perf_counter()
        with logfile.open("w", encoding="utf-8") as log:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                       cwd=snapshot, start_new_session=os.name != "nt")
            try:
                process.wait(timeout=min(config["job_timeout_seconds"], remaining))
                status = "completed" if process.returncode == 0 else "worker_error"
                if status == "completed":
                    record_path = destination / ("result.json" if job["kind"] == "stress" else "profile.json")
                    try:
                        record = json.loads(record_path.read_text(encoding="utf-8"))
                    except (OSError, ValueError):
                        record = None
                    if record is None or (job["kind"] != "openmp" and not record.get("complete")):
                        status = "worker_error"
                if status == "worker_error":
                    terminate_worker(process, snapshot, wsl)
            except subprocess.TimeoutExpired:
                terminate_worker(process, snapshot, wsl)
                status = "timeout"
            except KeyboardInterrupt:
                terminate_worker(process, snapshot, wsl)
                history.append({**job, "status": "interrupted", "attempt": attempt,
                                "output": destination.relative_to(output).as_posix(),
                                "wall_seconds": perf_counter() - start})
                save_json(history_path, history)
                save_json(output / "status.json", {"status": "interrupted", "active_job": None,
                                                  "completed_jobs": len(completed), "planned_jobs": len(jobs)})
                raise
        history.append({**job, "status": status, "attempt": attempt,
                        "output": destination.relative_to(output).as_posix(),
                        "log": logfile.relative_to(output).as_posix(), "wall_seconds": perf_counter() - start})
        if status == "completed":
            history[-1]["evidence_sha256"] = evidence_inventory(destination)
        save_json(history_path, history)
        if status == "completed":
            completed.add(job["id"])
        elif status == "worker_error":
            print(f"Worker error; inspect {logfile}. Execution stops before further measurements.", flush=True)
            break
    verify_snapshot(output, config)
    final_status = "completed" if len(completed) == len(jobs) else "incomplete"
    save_json(output / "status.json", {"status": final_status, "active_job": None,
                                      "completed_jobs": len(completed), "planned_jobs": len(jobs)})
    return final_status


def evidence_inventory(directory):
    """Hash retained outputs so a resumed campaign cannot silently reuse edits."""
    return {path.relative_to(directory).as_posix(): digest(path)
            for path in sorted(directory.rglob("*")) if path.is_file()}


def output_directory(path):
    output = path.resolve()
    protected = (".git", "src", "scripts", "tests", "docs", "configs", "cpp", "benchmarks", "examples")
    if output == ROOT or any(output.is_relative_to(ROOT / name) for name in protected):
        raise ValueError("campaign output must be separate from project sources")
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/nightly_campaign.json")
    parser.add_argument("--output", type=Path, default=ROOT / "results/nightly_campaign")
    parser.add_argument("--backend", choices=("gurobi", "highs"))
    parser.add_argument("--wsl", help="Windows Linux distribution, normally Ubuntu")
    parser.add_argument("--plan", action="store_true", help="validate and print the plan without writing or executing")
    parser.add_argument("--prepare-only", action="store_true", help="freeze sources/build/tests only; no experimental jobs")
    parser.add_argument("--resume", action="store_true", help="continue from the exact verified prepared snapshot")
    args = parser.parse_args()
    config = load_configuration(args.config, args.backend)
    jobs = campaign_jobs(config)
    plan = {"execution_status": "not_run", "job_count": len(jobs),
            "stage2_scenarios_per_source": len(config["arrival_factors"]) * len(config["stress_factors"]),
            "maximum_wall_hours_per_invocation": config["maximum_wall_seconds"] / 3600,
            "configuration": config, "jobs": jobs}
    if args.plan:
        print(json.dumps(plan, indent=2))
        return 0
    if os.name == "nt" and not args.wsl:
        parser.error("native experiments on Windows require --wsl Ubuntu")
    backend = probe_solver_backend(SolverBackend(config["backend"]))
    if backend.availability is not SolverBackendAvailability.AVAILABLE:
        parser.error(f"selected backend unavailable: {backend.detail}; explicitly choose --backend highs if desired")
    output = output_directory(args.output)
    if args.resume:
        snapshot = verify_snapshot(output, config)
    else:
        output.mkdir(parents=True, exist_ok=False)
        save_json(output / "plan.json", plan)
        snapshot = prepare_snapshot(output, config, args.wsl)
    environment = {"python_version": platform.python_version(), "platform": platform.platform(),
                   "logical_cpu_count": os.cpu_count(), "wsl": args.wsl, "backend": config["backend"],
                   "backend_version": backend.version, "started_utc": datetime.now(timezone.utc).isoformat(),
                   "pyomo_version": version("pyomo"), "highspy_version": version("highspy")}
    if os.name == "nt":
        environment["power_plan"] = subprocess.run(["powercfg", "/getactivescheme"], capture_output=True, text=True, check=True).stdout.strip()
        environment["processor"] = platform.processor()
    if args.wsl:
        environment["linux_environment"] = subprocess.run(
            ["wsl", "-d", args.wsl, "--exec", "uname", "-a"], capture_output=True, text=True, check=True).stdout.strip()
        environment["compiler"] = subprocess.run(
            ["wsl", "-d", args.wsl, "--exec", "g++", "--version"], capture_output=True, text=True, check=True).stdout.splitlines()[0]
    environment_history_path = output / "environment_history.json"
    environments = json.loads(environment_history_path.read_text(encoding="utf-8")) if environment_history_path.exists() else []
    environments.append(environment)
    save_json(environment_history_path, environments)
    save_json(output / "environment.json", environment)
    if args.prepare_only:
        save_json(output / "status.json", {"status": "prepared", "active_job": None,
                                          "completed_jobs": 0, "planned_jobs": len(jobs)})
        print(f"Prepared {len(jobs)} jobs; no experimental job executed. Resume with the same output/configuration.")
        subprocess.run([sys.executable, str(snapshot / "scripts/summarize_nightly_campaign.py"), "--output", str(output)], check=True)
        return 0
    try:
        status = run_jobs(output, config, jobs, snapshot, args.wsl)
    except KeyboardInterrupt:
        subprocess.run([sys.executable, str(snapshot / "scripts/summarize_nightly_campaign.py"), "--output", str(output)], check=True)
        return 130
    subprocess.run([sys.executable, str(snapshot / "scripts/summarize_nightly_campaign.py"), "--output", str(output)], check=True)
    return 0 if status == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
