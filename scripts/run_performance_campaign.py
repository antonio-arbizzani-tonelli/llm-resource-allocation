"""Execute the declared timing subset of a verified prepared campaign.

Reuse exact prepared scientific sources, inputs and native binaries. The source
campaign is preserved; this directory has its own 12-job plan and attempt history.
"""

import argparse
import ctypes
from datetime import datetime, timezone
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from run_nightly_campaign import campaign_jobs, digest, load_configuration, output_directory, run_jobs, save_json, verify_snapshot


def prepare_timing_subset(prepared, output):
    """Copy an already verified snapshot and select the unchanged timing jobs."""
    config = load_configuration(prepared / "snapshot/configs/nightly_campaign.json")
    snapshot = verify_snapshot(prepared, config)
    all_jobs = campaign_jobs(config)
    jobs = [job for job in all_jobs if job["kind"] in ("serial", "openmp")]
    output.mkdir(parents=True, exist_ok=False)
    shutil.copytree(snapshot, output / "snapshot", ignore=shutil.ignore_patterns("__pycache__", "*.o", "*.d"))
    shutil.copyfile(prepared / "snapshot_manifest.json", output / "snapshot_manifest.json")
    (output / "logs").mkdir()
    save_json(output / "plan.json", {"execution_status": "not_run", "configuration": config,
                                    "selected_job_kinds": ["serial", "openmp"], "jobs": jobs,
                                    "job_count": len(jobs), "excluded_stage2_jobs": len(all_jobs) - len(jobs),
                                    "source_snapshot_manifest_sha256": digest(prepared / "snapshot_manifest.json")})
    save_json(output / "status.json", {"status": "prepared", "completed_jobs": 0,
                                      "planned_jobs": len(jobs), "active_job": None})
    verify_snapshot(output, config)
    return config, jobs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wsl")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--defer-known-memory-errors", action="store_true",
                        help="on resume, preserve failed MemoryError jobs and run the other declared jobs")
    args = parser.parse_args()
    if os.name == "nt" and not args.wsl:
        parser.error("Windows timing jobs require --wsl Ubuntu")
    output = output_directory(args.output)
    if args.resume:
        plan = json.loads((output / "plan.json").read_text(encoding="utf-8"))
        config, jobs = plan["configuration"], plan["jobs"]
        if plan["selected_job_kinds"] != ["serial", "openmp"]:
            parser.error("resume requires a timing-subset plan")
    else:
        config, jobs = prepare_timing_subset(args.prepared.resolve(), output)
    snapshot = verify_snapshot(output, config)
    deferred = []
    if args.defer_known_memory_errors:
        if not args.resume:
            parser.error("memory-error deferral requires --resume")
        attempts = json.loads((output / "jobs.json").read_text(encoding="utf-8"))
        latest = {item["id"]: item for item in attempts}
        for attempt in latest.values():
            if attempt["status"] == "worker_error" and "log" in attempt:
                log = (output / attempt["log"]).resolve()
                if not log.is_relative_to((output / "logs").resolve()):
                    raise ValueError("failed worker log escapes campaign directory")
                if "MemoryError" in log.read_text(encoding="utf-8"):
                    deferred.append({"id": attempt["id"], "reason": "Python reference MemoryError",
                                     "log": attempt["log"], "log_sha256": digest(log)})
        save_json(output / "deferred_jobs.json", deferred)
    environment = {"started_utc": datetime.now(timezone.utc).isoformat(),
                   "python_version": platform.python_version(), "platform": platform.platform(),
                   "logical_cpu_count": os.cpu_count(), "processor": platform.processor(),
                   "pyomo_version": version("pyomo"), "highspy_version": version("highspy"),
                   "wsl": args.wsl, "backend_used": None,
                   "scope": "GH/AGH allocation software timings; no MILP/Stage-2 solve",
                   "launcher_sha256": digest(Path(__file__)),
                   "coordinator_sha256": digest(ROOT / "scripts/run_nightly_campaign.py")}
    environment["deferred_job_ids"] = [item["id"] for item in deferred]
    if os.name == "nt":
        environment["power_plan"] = subprocess.run(["powercfg", "/getactivescheme"], capture_output=True, text=True, check=True).stdout.strip()
    if args.wsl:
        environment["compiler"] = subprocess.run(["wsl", "-d", args.wsl, "--exec", "g++", "--version"], capture_output=True, text=True, check=True).stdout.splitlines()[0]
        environment["linux_environment"] = subprocess.run(["wsl", "-d", args.wsl, "--exec", "uname", "-a"], capture_output=True, text=True, check=True).stdout.strip()
    history_path = output / "environment_history.json"
    history = json.loads(history_path.read_text(encoding="utf-8")) if history_path.exists() else []
    history.append(environment)
    save_json(history_path, history)
    save_json(output / "environment.json", environment)
    if os.name == "nt" and not ctypes.windll.kernel32.SetThreadExecutionState(ctypes.c_uint(0x80000001)):
        raise OSError("Windows rejected the process-scoped automatic-sleep request")
    try:
        try:
            state = run_jobs(output, config, jobs, snapshot, args.wsl,
                             deferred_jobs=[item["id"] for item in deferred])
        except KeyboardInterrupt:
            state = "interrupted"
    finally:
        if os.name == "nt":
            ctypes.windll.kernel32.SetThreadExecutionState(ctypes.c_uint(0x80000000))
    subprocess.run([sys.executable, str(snapshot / "scripts/summarize_nightly_campaign.py"),
                    "--output", str(output)], check=True)
    return 0 if state == "completed" else 130 if state == "interrupted" else 2


if __name__ == "__main__":
    raise SystemExit(main())
