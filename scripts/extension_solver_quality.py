"""Prepare, resume, and independently replay the opt-in WP6 solver campaign.

Every limit starts a fresh MILP. Default Stage-1 feasibility, normalization and
objective acceptance remain unchanged; rejected objectives are diagnostic only.
"""

from __future__ import annotations

import argparse
import ast
from collections import Counter
from collections.abc import Mapping
from dataclasses import fields, is_dataclass, replace
from datetime import datetime, timezone
from enum import Enum
import csv
import gzip
import hashlib
from importlib.metadata import PackageNotFoundError, distribution, version
import json
import math
from pathlib import Path
import platform
from random import Random
import shutil
from statistics import median
import subprocess
import sys
from time import perf_counter
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "benchmarks/solver_quality_2026-10-14"
sys.path.insert(0, str(ROOT / "src"))

CASES = (
    {"id": "10x10x10_L1", "shape": [10, 10, 10], "load": 1.0},
    {"id": "10x10x10_L200", "shape": [10, 10, 10], "load": 200.0},
    {"id": "10x10x10_L100000", "shape": [10, 10, 10], "load": 100000.0},
    {"id": "6x6x10_L100000", "shape": [6, 6, 10], "load": 100000.0},
)
LIMITS = (20, 120, 600)
ARCHIVED_DIRECTORIES = ("raw", "snapshot", "inputs")


def plain(value):
    """Lossless dataclass fields and indexed mappings; no search-graph export."""
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {field.name: plain(getattr(value, field.name)) for field in fields(value)
                if not field.name.startswith("_")}
    if isinstance(value, Mapping):
        if all(isinstance(key, str) for key in value):
            return {key: plain(item) for key, item in value.items()}
        return [{"key": plain(key), "value": plain(item)} for key, item in value.items()]
    if isinstance(value, (tuple, list)):
        return [plain(item) for item in value]
    return value


def encoded(value):
    return (json.dumps(plain(value), separators=(",", ":"), allow_nan=False) + "\n").encode()


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(path.suffix + ".pending")
    pending.write_text(json.dumps(plain(value), indent=2, allow_nan=False) + "\n",
                       encoding="utf-8", newline="\n")
    pending.replace(path)


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def safe_path(directory, relative):
    path = (directory / relative).resolve()
    if not path.is_relative_to(directory.resolve()):
        raise ValueError("campaign evidence path escapes its root")
    return path


def unpack_campaign(output):
    """Verify portable archive membership and bytes before optional extraction."""
    if not (output / "evidence.zip").exists():
        return
    manifest = load_json(output / "evidence_manifest.json")
    if sha256(output / "evidence.zip") != manifest["archive_sha256"]:
        raise ValueError("campaign evidence archive changed")
    with zipfile.ZipFile(output / "evidence.zip") as archive:
        expected = {item["path"] for item in manifest["files"]}
        if len(expected) != len(manifest["files"]) or len(archive.namelist()) != len(expected) or set(archive.namelist()) != expected:
            raise ValueError("campaign archive membership changed")
        for item in manifest["files"]:
            payload = archive.read(item["path"])
            if len(payload) != item["bytes"] or hashlib.sha256(payload).hexdigest() != item["sha256"]:
                raise ValueError("campaign archive entry changed: " + item["path"])
            target = safe_path(output, item["path"])
            if target.exists():
                if sha256(target) != item["sha256"]:
                    raise ValueError("unpacked campaign evidence changed: " + item["path"])
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(payload)


def verify_inventory(output):
    if (output / "artifact_hashes.json").exists():
        for relative, expected in load_json(output / "artifact_hashes.json").items():
            if sha256(safe_path(output, relative)) != expected:
                raise ValueError("published campaign artifact changed: " + relative)


def inventory(output):
    save_json(output / "artifact_hashes.json", {
        path.relative_to(output).as_posix(): sha256(path)
        for path in sorted(output.rglob("*")) if path.is_file() and path.name != "artifact_hashes.json"
        and not any(path.is_relative_to(output / name) for name in ARCHIVED_DIRECTORIES)})


def save_evidence(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(path.suffix + ".pending")
    pending.write_bytes(gzip.compress(encoded(value), mtime=0))
    pending.replace(path)


def unpack_mapping(value):
    if isinstance(value, dict):
        return value
    return {tuple(row["key"]): row["value"] for row in value}


def decode_instance(value):
    from llm_resource_allocation.domain.types import FoundationModel, GpuTier, ProblemInstance, QueryType
    from llm_resource_allocation.domain.units import UnitConvention
    data = dict(value)
    for name, record_type in (("queries", QueryType), ("models", FoundationModel), ("gpu_tiers", GpuTier)):
        data[name] = tuple(record_type(**item) for item in data[name])
    for name in ("base_error_rate", "compute_delay_seconds_per_token",
                 "communication_delay_seconds_per_token", "compute_gflop_per_token",
                 "kv_cache_residency_seconds"):
        data[name] = unpack_mapping(data[name])
    data["unit_convention"] = UnitConvention(data["unit_convention"])
    return ProblemInstance(**data)


def decode_placement(value):
    from llm_resource_allocation.math.parallelism import ParallelismDecisionState
    from llm_resource_allocation.math.placement import PlacementDecisionState
    from llm_resource_allocation.math.routing import RoutingDecisionState
    parallel = value["parallelism_decisions"]
    routing = RoutingDecisionState(**{key: unpack_mapping(item) for key, item in parallel["routing_decisions"].items()})
    return PlacementDecisionState(ParallelismDecisionState(
        routing, unpack_mapping(parallel["configuration_selectors"]), unpack_mapping(parallel["gpu_counts"])),
        unpack_mapping(value["auxiliary_products"]))


def campaign_jobs(backends, limits=LIMITS):
    """Rotate backend/case order across limits; no result-dependent schedule."""
    jobs = [{"id": f"warmup_{backend}", "case": "warmup", "method": "p_dm",
             "backend": backend, "limit": 20, "warmup": True} for backend in backends]
    jobs += [{"id": f"warmup_{method}", "case": "warmup", "method": method,
              "backend": None, "limit": None, "warmup": True} for method in ("gh", "agh")]
    for index, case in enumerate(CASES):
        methods = ("gh", "agh") if index % 2 == 0 else ("agh", "gh")
        jobs += [{"id": f"{case['id']}_{method}", "case": case["id"], "method": method,
                  "backend": None, "limit": None, "warmup": False} for method in methods]
    combinations = [(case["id"], backend) for case in CASES for backend in backends]
    for round_index, limit in enumerate(limits):
        shift = round_index % len(combinations)
        order = combinations[shift:] + combinations[:shift]
        if round_index % 2:
            order.reverse()
        jobs += [{"id": f"{case}_{backend}_{limit}", "case": case, "method": "p_dm",
                  "backend": backend, "limit": limit, "warmup": False} for case, backend in order]
    return jobs


def runtime_estimate(backends, limits=LIMITS):
    native = len(CASES) * len(backends) * sum(limits)
    # Conservative predeclared planning margin, not measured serving/runtime data.
    overhead = len(CASES) * len(backends) * len(limits) * 30
    heuristic_allowance = len(CASES) * 2 * 120
    warmup_allowance = (len(backends) + 2) * 30
    return {"native_limit_sum_seconds": native,
            "estimated_seconds": native * 1.25 + overhead + heuristic_allowance + warmup_allowance,
            "policy": "1.25*native limits + 30s/MILP + 120s/heuristic + 30s/warmup",
            "maximum_seconds": 10800}


def prepare(output, requested_backends, gurobi_skip_reason=None):
    from llm_resource_allocation.data.scaling_experiment_instances import make_scaling_experiment_case
    from llm_resource_allocation.domain.units import UnitConvention
    from llm_resource_allocation.optimization.solver import SolverBackend, SolverBackendAvailability, probe_solver_backend
    if (output / "manifest.json").exists():
        raise ValueError("campaign is already prepared; use run or summarize")
    if not requested_backends or len(set(requested_backends)) != len(requested_backends):
        raise ValueError("requested backends must be nonempty and unique")
    output.mkdir(parents=True, exist_ok=True)
    # Write the hypothesis before probing backends or generating campaign inputs.
    plan = """# WP6 solver-quality plan

Hypothesis: accepted incumbents and the case-specific ordering among Gurobi,
AGH and HiGHS may change when the native limit grows from 20 to 120 to 600 s.
Four fixed synthetic cases use 10x10x10 at loads 1, 200 and 100000, and
6x6x10 at load100000. They vary load, not random instance seeds. Coherent V2,
one-hour residency, GH beta0.8 and AGH seed37 remain explicit assumptions.

Each backend/limit is an independent cold solve, with zero requested MIP gaps;
no warm start or transfer of another method's decisions is allowed. One tiny
warmup per selected solver and heuristic is retained and excluded. Case and
backend order rotates across limits. These quality experiments have one solve
per cell; no repeat-based runtime uncertainty is claimed.

Record native incumbent, bound, normalized gap, status, APPSI call time, complete raw
x/z/q/u/w/y/v, normalized placement, and independent default acceptance.
The normalized gap is abs(incumbent-bound)/abs(incumbent); it is unavailable
without both values or for a zero incumbent with a nonzero absolute gap.
The approved APPSI adapter does not expose a separate backend-native MIPGap;
that observation is explicitly unavailable, never replaced by the normalized gap.
The 1e-8 absolute objective threshold remains the Stage-1 default. Rejected
incumbents remain diagnostic; no rejection enters a ranking, optimum gap,
accepted-objective ratio or bootstrap interval. Heuristic completion alone
is insufficient. Bounds are backend evidence about the constructed model.

Success: replay every usable decision and objective without solving and
report the complete accepted comparison at each limit when it exists.
Negative outcome: preserve timeouts, missing incumbents, numerical rejections
and absent complete cohorts; explicitly leave the ordering question open.
The paired bootstrap across complete cases is descriptive of this four-case
convenience cohort, not a population CI or universal method ranking.

Gate: planned estimated runtime must be at most 3 h. If the gate fails, skip
execution and report why. Resume checks hashes and creates a new attempt
directory for interrupted workers. No campaign run is started by prepare.

Environment: Python>=3.13, i7-13620H, requested WSL Ubuntu where available;
actual Python/platform/solver versions and operator energy/app observations
are retained. GPU delay coefficients are model inputs; timing is CPU allocation
software. This is not numerical replication of Cheng and Nguyen's tables.

Replay: python scripts/extension_solver_quality.py summarize --output
benchmarks/solver_quality_2026-10-14
The replay automatically verifies/unpacks evidence.zip and delegates to the
hashed campaign source snapshot; no solver or current scientific source is used.
Execution: python scripts/extension_solver_quality.py run --output
benchmarks/solver_quality_2026-10-14 --environment-note '<observed state>'
"""
    if gurobi_skip_reason:
        plan += "\nGurobi execution is skipped: " + gurobi_skip_reason + ". No matched\nGurobi/AGH/HiGHS ordering will be inferred from historical cohorts.\n"
    (output / "PLAN.md").write_text(plan, encoding="utf-8", newline="\n")
    probes = [probe_solver_backend(SolverBackend(name)) for name in requested_backends]
    selected = [info.backend.value for info in probes if info.availability is SolverBackendAvailability.AVAILABLE]
    if "highs" not in selected:
        raise RuntimeError("the mandatory HiGHS backend is unavailable")
    source_hashes = {}
    for source in sorted((ROOT / "src").rglob("*.py")):
        relative = source.relative_to(ROOT)
        target = output / "snapshot" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        source_hashes[relative.as_posix()] = sha256(target)
    source = Path(__file__).resolve()
    target = output / "snapshot/scripts/extension_solver_quality.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    source_hashes["scripts/extension_solver_quality.py"] = sha256(target)
    inputs = {}
    for spec in (*CASES, {"id": "warmup", "shape": [2, 2, 2], "load": 1.0}):
        original = make_scaling_experiment_case(*spec["shape"], load_multiplier=spec["load"])
        instance = replace(original.instance, id="wp6_" + spec["id"],
                           unit_convention=UnitConvention.COHERENT, data_residency_hours=1.0)
        target = output / "inputs" / (spec["id"] + ".json.gz")
        save_evidence(target, {"instance": instance, "provenance": original.provenance,
                               "intervention": spec})
        inputs[spec["id"]] = {"path": target.relative_to(output).as_posix(), "sha256": sha256(target)}
    estimate = runtime_estimate(selected)
    manifest = {"format_version": 1, "prepared_utc": datetime.now(timezone.utc).isoformat(),
                "classification": "ASSUMED_SYNTHETIC_CPU_SOLVER_QUALITY",
                "probes": plain(probes), "backends": selected, "limits": list(LIMITS),
                "gurobi_skip_reason": gurobi_skip_reason,
                "cases": list(CASES), "agh_seed": 37, "gh_beta": 0.8,
                "paper_version": "v2", "unit_convention": "coherent", "data_residency_hours": 1.0,
                "jobs": campaign_jobs(selected), "source_sha256": source_hashes,
                "inputs": inputs, "plan_sha256": sha256(output / "PLAN.md"),
                "runtime_estimate": estimate, "gate_passed": estimate["estimated_seconds"] <= 10800,
                "python_version": platform.python_version(), "platform": platform.platform()}
    save_json(output / "manifest.json", manifest)
    save_json(output / "checkpoint.json", {"attempts": [], "complete": False, "invocations": []})
    return manifest


def environment_record(note):
    packages = {}
    native_artifacts = {}
    for name in ("pyomo", "highspy", "gurobipy"):
        try:
            packages[name] = version(name)
            installed = distribution(name)
            native_artifacts[name] = [{"distribution_member": str(member).replace(chr(92), "/"),
                "bytes": installed.locate_file(member).stat().st_size,
                "sha256": sha256(installed.locate_file(member))}
                for member in sorted(installed.files or (), key=str)
                if str(member).lower().endswith((".so", ".pyd", ".dll", ".dylib"))]
        except PackageNotFoundError:
            packages[name] = None
            native_artifacts[name] = []
    topology = None
    if shutil.which("lscpu"):
        process = subprocess.run(["lscpu", "--json"], capture_output=True, text=True, timeout=10)
        if process.returncode == 0:
            topology = json.loads(process.stdout)
    governors = {}
    for path in sorted(Path("/sys/devices/system/cpu").glob("cpu[0-9]*/cpufreq/scaling_governor")):
        try:
            governors[path.parent.parent.name] = path.read_text().strip()
        except OSError:
            governors[path.parent.parent.name] = "unavailable"
    return {"python_version": platform.python_version(), "platform": platform.platform(),
            "packages": packages, "cpu_topology": topology,
            "runtime_executable": {"filename": Path(sys.executable).name, "sha256": sha256(Path(sys.executable))},
            "native_package_artifacts": native_artifacts,
            "cpu_governors": governors or "not exposed by this execution environment",
            "operator_observations": note}


def verify_prepared(output):
    unpack_campaign(output)
    verify_inventory(output)
    manifest = load_json(output / "manifest.json")
    if sha256(output / "PLAN.md") != manifest["plan_sha256"]:
        raise ValueError("campaign PLAN changed after preparation")
    for name, expected in manifest["source_sha256"].items():
        if sha256(safe_path(output / "snapshot", name)) != expected:
            raise ValueError("frozen source hash mismatch: " + name)
    for item in manifest["inputs"].values():
        if sha256(safe_path(output, item["path"])) != item["sha256"]:
            raise ValueError("campaign input hash mismatch: " + item["path"])
    return manifest


def load_input(output, manifest, case):
    with gzip.open(output / manifest["inputs"][case]["path"], "rt", encoding="utf-8") as stream:
        return decode_instance(json.load(stream)["instance"])


def run_worker(output, job, destination):
    from llm_resource_allocation.algorithms import GHPhase1Config, run_agh, run_gh
    from llm_resource_allocation.optimization.extraction import (
        PdmSolutionExtractionError, PdmSolutionNormalizationError, SolutionNormalizationTolerances,
        extract_raw_pdm_solution_from_pyomo, normalize_raw_pdm_solution)
    from llm_resource_allocation.optimization.problem_data import PdmProblemData
    from llm_resource_allocation.optimization.pyomo_pdm import build_pdm_pyomo_model
    from llm_resource_allocation.optimization.solver import SolverBackend, SolverConfig, solve_pyomo_model
    from llm_resource_allocation.math.objective import PaperVersion
    from llm_resource_allocation.validation.objective_comparison import ObjectiveComparison
    from llm_resource_allocation.validation.placement import ValidationTolerances, validate_placement
    manifest = verify_prepared(output)
    instance = load_input(output, manifest, job["case"])
    started = perf_counter()
    solver = raw = placement = report = comparison = None
    normalization = SolutionNormalizationTolerances()
    policy = ValidationTolerances()
    failure = None
    completed = False
    method_status = None
    if job["method"] == "p_dm":
        problem = PdmProblemData(instance)
        model = build_pdm_pyomo_model(problem)
        solver = solve_pyomo_model(model, SolverConfig(
            backend=SolverBackend(job["backend"]), time_limit_seconds=job["limit"],
            relative_mip_gap=0.0, absolute_mip_gap=0.0))
        method_status = solver.status.value
        if solver.has_incumbent:
            try:
                raw = extract_raw_pdm_solution_from_pyomo(model, problem)
                placement = normalize_raw_pdm_solution(raw, problem, normalization)
                completed = True
            except (PdmSolutionExtractionError, PdmSolutionNormalizationError) as error:
                failure = {"type": type(error).__name__, "message": str(error)}
    else:
        if job["method"] == "gh":
            result = run_gh(instance, GHPhase1Config(manifest["gh_beta"]))
            placement, completed = result.placement_decisions, result.algorithm_completed
        else:
            result = run_agh(instance, GHPhase1Config(manifest["gh_beta"]), random_seed=manifest["agh_seed"])
            placement, completed = result.final_placement, result.completed
        method_status = result.completion_status.value
    if placement is not None:
        report = validate_placement(instance, placement, PaperVersion.V2, tolerances=policy)
        if solver is not None and report.objective_breakdown is not None:
            comparison = ObjectiveComparison(solver.objective_value, report.objective_breakdown.total)
    accepted = bool(completed and report is not None and report.is_feasible
                    and (solver is None or comparison is not None and comparison.agrees))
    reasons = []
    if not completed:
        reasons.append("no_complete_placement")
    if report is not None and not report.is_feasible:
        reasons.append("independent_constraints")
    if comparison is not None and not comparison.agrees:
        reasons.append("objective_disagreement")
    elapsed = perf_counter() - started
    evidence = {"job": job, "solver": solver, "raw": raw, "placement": placement,
                "validation": report, "comparison": comparison,
                "normalization": normalization, "validation_tolerances": policy,
                "completed": completed, "accepted": accepted, "failure": failure,
                "method_status": method_status}
    save_evidence(destination / "evidence.json.gz", evidence)
    independent = report.objective_breakdown.total if report and report.objective_breakdown else None
    row = {**job, "completed": completed, "accepted": accepted,
           "method_status": method_status,
           "independently_feasible": report.is_feasible if report else None,
           "objective_agrees": comparison.agrees if comparison else None,
           "rejection_reasons": reasons, "failure": failure, "integrated_seconds": elapsed,
           "solver_status": solver.status.value if solver else None,
           "solver_seconds": solver.solve_time_seconds if solver else None,
           "incumbent_usd": solver.objective_value if solver else None,
           "best_bound_usd": solver.best_bound if solver else None,
           "normalized_gap": solver.relative_gap if solver else None,
           "native_gap": None,
           "native_gap_observation": "not exposed by approved APPSI adapter" if solver else "not applicable to heuristic",
           "independent_objective_diagnostic_usd": independent,
           "usable_objective_usd": independent if accepted else None,
           "objective_absolute_difference_usd": comparison.absolute_difference if comparison else None,
           "python_version": platform.python_version(),
           "evidence_sha256": sha256(destination / "evidence.json.gz")}
    save_json(destination / "result.json", row)
    return row


def verify_attempt(output, attempt):
    for name, expected in attempt["sha256"].items():
        if sha256(safe_path(safe_path(output, attempt["directory"]), name)) != expected:
            raise ValueError("retained attempt hash mismatch: " + attempt["directory"] + "/" + name)
    if "source_manifest_sha256" in attempt and attempt["source_manifest_sha256"] != sha256(output / "manifest.json"):
        raise ValueError("attempt source-manifest provenance differs")
    if "input_sha256" in attempt:
        manifest = load_json(output / "manifest.json")
        job = next(item for item in manifest["jobs"] if item["id"] == attempt["job_id"])
        if attempt["input_sha256"] != manifest["inputs"][job["case"]]["sha256"]:
            raise ValueError("attempt input provenance differs")


def seal_interrupted_attempts(output, checkpoint, manifest=None):
    """Retain uncommitted worker files as an interruption, never a completion."""
    if manifest is not None:
        owned = {attempt["directory"] for attempt in checkpoint["attempts"]}
        jobs = {job["id"] for job in manifest["jobs"]}
        for directory in sorted((output / "raw").glob("*/attempt_*")):
            relative = directory.relative_to(output).as_posix()
            if directory.is_dir() and relative not in owned and directory.parent.name in jobs:
                checkpoint["attempts"].append({"job_id": directory.parent.name,
                    "directory": relative, "status": "running", "sha256": {},
                    "orphan_provenance": "attempt directory created before its parent checkpoint became durable"})
    for attempt in checkpoint["attempts"]:
        verify_attempt(output, attempt)
        if attempt["status"] != "running":
            continue
        directory = safe_path(output, attempt["directory"])
        attempt["sha256"] = {path.name: sha256(path) for path in sorted(directory.iterdir()) if path.is_file()}
        attempt["status"] = "interrupted"
        attempt["interruption_provenance"] = {
            "sealed_utc": datetime.now(timezone.utc).isoformat(),
            "policy": "original worker files retained; no uncommitted result promoted; retry the same frozen job/input",
            "scientifically_accepted": False}


def run_campaign(output, environment_note, max_jobs=None):
    if (output / "evidence.zip").exists():
        raise ValueError("published campaign is immutable; resume an unpublished working copy")
    manifest = verify_prepared(output)
    if not manifest["gate_passed"]:
        raise ValueError("predeclared three-hour runtime gate failed; campaign remains skipped")
    checkpoint = load_json(output / "checkpoint.json")
    seal_interrupted_attempts(output, checkpoint, manifest)
    save_json(output / "checkpoint.json", checkpoint)
    complete = {attempt["job_id"] for attempt in checkpoint["attempts"] if attempt["status"] == "complete"}
    invocation = {"started_utc": datetime.now(timezone.utc).isoformat(),
                  "environment": environment_record(environment_note), "completed_jobs": 0}
    checkpoint["invocations"].append(invocation)
    save_json(output / "checkpoint.json", checkpoint)
    start = perf_counter()
    for job in manifest["jobs"]:
        if job["id"] in complete:
            continue
        if max_jobs is not None and invocation["completed_jobs"] >= max_jobs:
            break
        remaining = 10800 - (perf_counter() - start)
        timeout = job["limit"] * 1.25 + 90 if job["limit"] else 180
        if remaining < timeout:
            invocation["stop_reason"] = "three-hour invocation budget"
            break
        number = 1 + sum(attempt["job_id"] == job["id"] for attempt in checkpoint["attempts"])
        relative = Path("raw") / job["id"] / f"attempt_{number:02d}"
        destination = output / relative
        destination.mkdir(parents=True, exist_ok=False)
        portable_command = ["python", "-B", "snapshot/scripts/extension_solver_quality.py",
                            "worker", "--output", ".", "--job-id", job["id"], "--destination", relative.as_posix()]
        attempt = {"job_id": job["id"], "directory": relative.as_posix(), "status": "running", "sha256": {},
                   "invocation_index": len(checkpoint["invocations"]) - 1,
                   "command": portable_command, "command_working_directory": "campaign root",
                   "source_manifest_sha256": sha256(output / "manifest.json"),
                   "input_sha256": manifest["inputs"][job["case"]]["sha256"]}
        checkpoint["attempts"].append(attempt)
        save_json(output / "checkpoint.json", checkpoint)
        command = [sys.executable, *portable_command[1:]]
        print("Starting " + job["id"], flush=True)
        with (destination / "worker.log").open("w", encoding="utf-8") as stream:
            try:
                process = subprocess.run(command, cwd=output, stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
                attempt["returncode"] = process.returncode
                attempt["status"] = "complete" if process.returncode == 0 and (destination / "result.json").exists() else "failed"
            except subprocess.TimeoutExpired:
                attempt["status"] = "timeout"
        attempt["sha256"] = {path.name: sha256(path) for path in sorted(destination.iterdir()) if path.is_file()}
        invocation["completed_jobs"] += 1
        save_json(output / "checkpoint.json", checkpoint)
        print(job["id"] + ": " + attempt["status"], flush=True)
    complete = {attempt["job_id"] for attempt in checkpoint["attempts"] if attempt["status"] == "complete"}
    checkpoint["complete"] = len(complete) == len(manifest["jobs"])
    invocation["elapsed_seconds"] = perf_counter() - start
    save_json(output / "checkpoint.json", checkpoint)
    return checkpoint


def replay_row(output, manifest, attempt):
    from llm_resource_allocation.optimization.extraction import (RawPdmSolution, SolutionNormalizationTolerances,
        PdmSolutionNormalizationError, normalize_raw_pdm_solution)
    from llm_resource_allocation.optimization.problem_data import PdmProblemData
    from llm_resource_allocation.math.objective import PaperVersion
    from llm_resource_allocation.validation.objective_comparison import ObjectiveComparison
    from llm_resource_allocation.validation.placement import ValidationTolerances, validate_placement
    verify_attempt(output, attempt)
    directory = output / attempt["directory"]
    row = load_json(directory / "result.json")
    with gzip.open(directory / "evidence.json.gz", "rt", encoding="utf-8") as stream:
        evidence = json.load(stream)
    if sha256(directory / "evidence.json.gz") != row["evidence_sha256"]:
        raise ValueError("row/evidence SHA mismatch")
    job = evidence["job"]
    if any(row[name] != value for name, value in job.items()) or job != next(item for item in manifest["jobs"] if item["id"] == job["id"]):
        raise ValueError("row/evidence job differs from frozen schedule")
    instance = load_input(output, manifest, row["case"])
    solver = evidence["solver"]
    expected_solver_fields = {
        "solver_status": solver["status"] if solver else None,
        "solver_seconds": solver["solve_time_seconds"] if solver else None,
        "incumbent_usd": solver["objective_value"] if solver else None,
        "best_bound_usd": solver["best_bound"] if solver else None,
        "normalized_gap": solver["relative_gap"] if solver else None,
        "native_gap": None,
        "native_gap_observation": "not exposed by approved APPSI adapter" if solver else "not applicable to heuristic",
    }
    if any(row[key] != value for key, value in expected_solver_fields.items()):
        raise ValueError("row solver evidence differs")
    if row["method_status"] != evidence["method_status"]:
        raise ValueError("row method status differs")
    if any(row[name] != evidence[name] for name in ("completed", "accepted", "failure")):
        raise ValueError("row completion/failure evidence differs")
    normalized = None
    if evidence["raw"] is not None:
        raw = RawPdmSolution(**{name: unpack_mapping(value) for name, value in evidence["raw"].items()})
        try:
            normalized = normalize_raw_pdm_solution(raw, PdmProblemData(instance),
                SolutionNormalizationTolerances(**evidence["normalization"]))
        except PdmSolutionNormalizationError as error:
            expected_failure = {"type": type(error).__name__, "message": str(error)}
            if evidence["placement"] is not None or evidence["failure"] != expected_failure:
                raise ValueError("raw normalization rejection differs") from error
        else:
            if evidence["placement"] is None:
                raise ValueError("raw normalization succeeds without a recorded placement")
    report = comparison = None
    if evidence["placement"] is not None:
        placement = decode_placement(evidence["placement"])
        if evidence["raw"] is not None:
            if normalized != placement:
                raise ValueError("raw normalization differs from recorded placement")
        elif solver is not None:
            raise ValueError("solver placement is missing raw decision evidence")
        report = validate_placement(instance, placement, PaperVersion.V2,
                                    tolerances=ValidationTolerances(**evidence["validation_tolerances"]))
        if plain(report) != evidence["validation"] or report.is_feasible != row["independently_feasible"]:
            raise ValueError("independent validation replay differs")
        if solver is not None and report.objective_breakdown is not None:
            recorded = ObjectiveComparison(**evidence["comparison"])
            comparison = ObjectiveComparison(solver["objective_value"], report.objective_breakdown.total,
                recorded.absolute_tolerance, recorded.relative_tolerance)
    if plain(comparison) != evidence["comparison"]:
        raise ValueError("objective comparison sources differ")
    accepted = bool(evidence["completed"] and report is not None and report.is_feasible
                    and (solver is None or comparison is not None and comparison.agrees))
    if accepted != row["accepted"] or accepted != evidence["accepted"]:
        raise ValueError("acceptance replay differs")
    independent = report.objective_breakdown.total if report and report.objective_breakdown else None
    expected_fields = {"independent_objective_diagnostic_usd": independent,
        "usable_objective_usd": independent if accepted else None,
        "objective_agrees": comparison.agrees if comparison else None,
        "objective_absolute_difference_usd": comparison.absolute_difference if comparison else None,
        "independently_feasible": report.is_feasible if report else None}
    if any(row[name] != value for name, value in expected_fields.items()):
        raise ValueError("row independent objective/acceptance fields differ")
    reasons = (["no_complete_placement"] if not evidence["completed"] else [])
    if report is not None and not report.is_feasible:
        reasons.append("independent_constraints")
    if comparison is not None and not comparison.agrees:
        reasons.append("objective_disagreement")
    if row["rejection_reasons"] != reasons:
        raise ValueError("row rejection reasons differ")
    return row


def bootstrap_median(values, seed=113, draws=5000):
    """Descriptive paired-case bootstrap; at least two accepted pairs required."""
    if len(values) < 2:
        return None
    rng = Random(seed)
    samples = sorted(median([values[rng.randrange(len(values))] for _ in values]) for _ in range(draws))
    return [samples[int((draws - 1) * 0.025)], samples[int((draws - 1) * 0.975)]]


def summarize_rows(rows, manifest):
    measured = [row for row in rows if not row["warmup"]]
    indexed = {row["id"]: row for row in measured}
    comparisons, case_orders = [], []
    for limit in manifest["limits"]:
        for case in manifest["cases"]:
            expected = [f"{case['id']}_agh"] + [f"{case['id']}_{backend}_{limit}" for backend in manifest["backends"]]
            group = [indexed.get(name) for name in expected]
            comparable = all(row is not None and row["accepted"] for row in group)
            order = sorted(group, key=lambda row: row["usable_objective_usd"]) if comparable else None
            case_orders.append({"case": case["id"], "limit_seconds": limit,
                                "complete_accepted_cohort": comparable,
                                "order_by_objective": [{"method": row["backend"] or row["method"],
                                                        "objective_usd": row["usable_objective_usd"]} for row in order] if order else None})
        for backend in manifest["backends"]:
            pairs = []
            for case in manifest["cases"]:
                solver = indexed.get(f"{case['id']}_{backend}_{limit}")
                agh = indexed.get(f"{case['id']}_agh")
                if solver and agh and solver["accepted"] and agh["accepted"] and solver["usable_objective_usd"] != 0:
                    pairs.append({"case": case["id"], "agh_over_solver_incumbent": agh["usable_objective_usd"] / solver["usable_objective_usd"]})
            values = [pair["agh_over_solver_incumbent"] for pair in pairs]
            comparisons.append({"backend": backend, "limit_seconds": limit, "accepted_paired_cases": len(pairs),
                                "planned_cases": len(manifest["cases"]), "pairs": pairs,
                                "median_agh_over_incumbent": median(values) if values else None,
                                "descriptive_bootstrap95_median": bootstrap_median(values),
                                "bootstrap_unit": "accepted case, four-case convenience cohort; no population inference"})
    return {"planned_measured_jobs": sum(not job["warmup"] for job in manifest["jobs"]),
            "completed_measurement_rows": len(measured), "accepted_measurement_rows": sum(row["accepted"] for row in measured),
            "completed_warmup_rows": len(rows) - len(measured), "case_orders": case_orders,
            "agh_incumbent_comparisons": comparisons,
            "scope": "four synthetic coherent V2 cases; cold limit-specific solves; accepted-only quality; no universal ranking",
            "rows": measured}


def attempted_counts(checkpoint, manifest):
    """Keep attempted jobs, repeated worker calls and missing results separate."""
    jobs = {job["id"]: job for job in manifest["jobs"]}
    calls = [attempt for attempt in checkpoint["attempts"] if not jobs[attempt["job_id"]]["warmup"]]
    attempted = {attempt["job_id"] for attempt in calls}
    completed = {attempt["job_id"] for attempt in calls if attempt["status"] == "complete"}
    return {"attempted_unique_measured_jobs": len(attempted),
            "attempted_measured_worker_calls": len(calls),
            "completed_unique_measured_jobs": len(completed),
            "measured_jobs_without_completed_result": len(attempted - completed),
            "measured_worker_status_counts": dict(Counter(attempt["status"] for attempt in calls)),
            "measured_jobs_without_completed_result_ids": sorted(attempted - completed)}


def summarize(output, plots=False):
    manifest = verify_prepared(output)
    checkpoint = load_json(output / "checkpoint.json")
    for attempt in checkpoint["attempts"]:
        verify_attempt(output, attempt)
    latest = {attempt["job_id"]: attempt for attempt in checkpoint["attempts"] if attempt["status"] == "complete"}
    rows = [replay_row(output, manifest, latest[job["id"]]) for job in manifest["jobs"] if job["id"] in latest]
    summary = summarize_rows(rows, manifest)
    summary.update(attempted_counts(checkpoint, manifest))
    if summary["completed_unique_measured_jobs"] != summary["completed_measurement_rows"]:
        raise ValueError("completed worker/result-row denominator differs")
    summary["complete"] = checkpoint["complete"]
    summary["worker_failures"] = [attempt for attempt in checkpoint["attempts"] if attempt["status"] != "complete"]
    summary["verified_completed_jobs"] = len(rows)
    summary["manifest_sha256"] = sha256(output / "manifest.json")
    summary["checkpoint_sha256"] = sha256(output / "checkpoint.json")
    summary["gurobi_skip_reason"] = manifest["gurobi_skip_reason"]
    summary["normalized_gap_definition"] = "abs(incumbent-bound)/abs(incumbent); zero for identical values, unavailable for missing values or zero incumbent with nonzero gap"
    summary["native_gap_exposure"] = "not exposed by the approved APPSI adapter; normalized_gap is a separately derived diagnostic"
    save_json(output / "analysis.json", summary)
    if rows:
        with (output / "runs.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            for row in rows:
                writer.writerow({key: json.dumps(value) if isinstance(value, (list, dict)) else value for key, value in row.items()})
    lines = ["# WP6 solver-quality observations", "", summary["scope"], "",
             f"Attempted unique measured jobs: {summary['attempted_unique_measured_jobs']}/{summary['planned_measured_jobs']}; independently accepted rows: {summary['accepted_measurement_rows']}/{summary['attempted_unique_measured_jobs']} attempted unique jobs. Worker calls including retries: {summary['attempted_measured_worker_calls']}; completed worker result rows: {summary['completed_measurement_rows']}; jobs without a completed result: {summary['measured_jobs_without_completed_result']}. Warmup completed rows excluded: {summary['completed_warmup_rows']}.", "",
             "| Case | Method | Limit s | Accepted | Incumbent USD (diagnostic) | Bound USD | Normalized gap | Native gap | Usable objective USD |", "|---|---|---:|---|---:|---:|---:|---:|---:|"]
    for row in summary["rows"]:
        show = lambda value: "unavailable" if value is None else f"{value:.9g}"
        lines.append(f"| {row['case']} | {row['backend'] or row['method']} | {row['limit'] or '—'} | {row['accepted']} | {show(row['incumbent_usd'])} | {show(row['best_bound_usd'])} | {show(row['normalized_gap'])} | {show(row['native_gap'])} | {show(row['usable_objective_usd'])} |")
    lines += ["", "Rankings exist only for complete accepted case/limit cohorts. Equal displayed costs do not establish unique placements. Rejected native incumbents and bounds are diagnostic. No time-limited incumbent is called optimal; solver status remains separate from independent acceptance.", "",
              "The normalized gap is abs(incumbent-bound)/abs(incumbent), with the predeclared zero/missing-value rules. A separate backend-native MIPGap is unavailable through the approved APPSI adapter; no normalized value is called native.", "",
              "Replay uses the frozen source, raw decisions, original normalization and default independent policies. Every retained attempt hash is checked, including failures/timeouts. Interrupted attempts and logs remain in raw/ or evidence.zip. A failed worker without complete decision extraction supplies no independently usable objective."]
    if manifest["gurobi_skip_reason"]:
        lines += ["", "Gurobi skipped: " + manifest["gurobi_skip_reason"] + ". The three-way ordering question remains open."]
    (output / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    if plots:
        plot_results(output, summary, manifest)
    if (output / "artifact_hashes.json").exists():
        inventory(output)
    return summary


def plot_results(output, summary, manifest):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import NullFormatter
    figure, axes = plt.subplots(2, 2, figsize=(12, 8), constrained_layout=True)
    for axis, case in zip(axes.flat, manifest["cases"], strict=True):
        for backend in manifest["backends"]:
            rows = sorted((row for row in summary["rows"] if row["case"] == case["id"] and row["backend"] == backend), key=lambda row: row["limit"])
            axis.plot([row["limit"] for row in rows], [row["usable_objective_usd"] if row["usable_objective_usd"] is not None else math.nan for row in rows], marker="o", label=backend + " accepted incumbent")
            axis.plot([row["limit"] for row in rows], [row["best_bound_usd"] if row["best_bound_usd"] is not None else math.nan for row in rows], linestyle=":", label=backend + " bound")
        agh = next((row for row in summary["rows"] if row["case"] == case["id"] and row["method"] == "agh" and row["accepted"]), None)
        if agh:
            axis.axhline(agh["usable_objective_usd"], linestyle="--", color="black", label="accepted AGH")
        axis.set(title=case["id"], xlabel="Native limit (s)", ylabel="Model objective (USD)", xscale="log")
        axis.set_xticks(manifest["limits"], [str(value) for value in manifest["limits"]])
        axis.xaxis.set_minor_formatter(NullFormatter())
        axis.legend(fontsize=7)
        axis.grid(alpha=.2)
    figure.suptitle("Synthetic CPU planning: accepted incumbents and diagnostic bounds")
    for suffix in ("png", "svg"):
        figure.savefig(output / ("solver_quality." + suffix), dpi=150)
    plt.close(figure)


def measured_root_prefix():
    path = ROOT.resolve().as_posix()
    return "/mnt/" + path[0].lower() + path[2:] if len(path) > 2 and path[1] == ":" else path


def redact_metadata(value, prefix):
    """Only exact workspace text changes; scientific numeric values are reused."""
    if isinstance(value, dict):
        return {name: redact_metadata(item, prefix) for name, item in value.items()}
    if isinstance(value, list):
        return [redact_metadata(item, prefix) for item in value]
    return value.replace(prefix, ".") if isinstance(value, str) else value


def package_campaign(output):
    entries = []
    with zipfile.ZipFile(output / "evidence.zip", "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in ARCHIVED_DIRECTORIES:
            for path in sorted((output / name).rglob("*")):
                if not path.is_file():
                    continue
                payload = path.read_bytes()
                relative = path.relative_to(output).as_posix()
                info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, payload)
                entries.append({"path": relative, "bytes": len(payload),
                                "sha256": hashlib.sha256(payload).hexdigest()})
    save_json(output / "evidence_manifest.json", {"archive_sha256": sha256(output / "evidence.zip"),
                                                "files": entries})
    unpack_campaign(output)


def publish_campaign(output, backup=None, prefix=None, archive_only=True):
    """Publish a stopped campaign; preserve exact originals before any changes."""
    if (output / "evidence.zip").exists() or (output / "provenance.json").exists():
        raise ValueError("campaign has already been published")
    manifest = verify_prepared(output)
    checkpoint = load_json(output / "checkpoint.json")
    for attempt in checkpoint["attempts"]:
        verify_attempt(output, attempt)
    backup = ROOT / "results/solver_quality_original_2026-10-14" if backup is None else backup.resolve()
    if not backup.is_relative_to((ROOT / "results").resolve()):
        raise ValueError("private original snapshot must remain in ignored repository results")
    if backup.is_relative_to(output.resolve()):
        raise ValueError("private original snapshot cannot be nested within the campaign")
    if backup.exists():
        raise ValueError("private original snapshot already exists")
    originals = []
    backup.mkdir(parents=True, exist_ok=False)
    for path in sorted(output.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(output).as_posix()
        target = backup / "campaign" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        original_sha = sha256(path)
        if sha256(target) != original_sha:
            raise ValueError("private original snapshot differs: " + relative)
        originals.append({"path": relative, "original_sha256": original_sha})
    save_json(backup / "manifest.json", {"classification": "IMMUTABLE_PRIVATE_ORIGINAL_WP6_EVIDENCE",
              "files": originals, "policy": "all original input, source, attempt and runtime metadata bytes copied before publication"})
    seal_interrupted_attempts(output, checkpoint, manifest)
    save_json(output / "checkpoint.json", checkpoint)
    prefix = measured_root_prefix() if prefix is None else prefix
    if not prefix or prefix == ".":
        raise ValueError("an exact measured workspace prefix is required")
    for path in sorted(output.rglob("*")):
        if not path.is_file() or path.is_relative_to(output / "snapshot") or path.is_relative_to(output / "inputs"):
            continue
        if path.name.endswith(".json.gz"):
            value = json.loads(gzip.decompress(path.read_bytes()))
            portable = redact_metadata(value, prefix)
            if portable != value:
                save_evidence(path, portable)
        elif path.suffix == ".json":
            value = load_json(path)
            portable = redact_metadata(value, prefix)
            if portable != value:
                save_json(path, portable)
        elif path.suffix in (".log", ".txt", ".md", ".csv"):
            original = path.read_text(encoding="utf-8")
            portable = original.replace(prefix, ".")
            if portable != original:
                path.write_text(portable, encoding="utf-8", newline="\n")
    manifest = load_json(output / "manifest.json")
    manifest["plan_sha256"] = sha256(output / "PLAN.md")
    save_json(output / "manifest.json", manifest)
    checkpoint = load_json(output / "checkpoint.json")
    for attempt in checkpoint["attempts"]:
        directory = safe_path(output, attempt["directory"])
        if (directory / "result.json").exists():
            row = load_json(directory / "result.json")
            row["evidence_sha256"] = sha256(directory / "evidence.json.gz")
            save_json(directory / "result.json", row)
        if "source_manifest_sha256" in attempt:
            attempt["source_manifest_sha256"] = sha256(output / "manifest.json")
        attempt["sha256"] = {path.name: sha256(path) for path in sorted(directory.iterdir()) if path.is_file()}
    save_json(output / "checkpoint.json", checkpoint)
    verify_prepared(output)
    process = subprocess.run([sys.executable, "-B", str(output / "snapshot/scripts/extension_solver_quality.py"),
                              "summarize", "--output", str(output)], capture_output=True, text=True)
    if process.returncode:
        raise RuntimeError("frozen-source independent replay failed: " + process.stderr)
    package_campaign(output)
    archive_manifest = load_json(output / "evidence_manifest.json")
    archived = {item["path"]: item["sha256"] for item in archive_manifest["files"]}
    for item in originals:
        item["portable_sha256"] = sha256(safe_path(output, item["path"]))
        if item["path"].startswith(("snapshot/", "inputs/")) and item["portable_sha256"] != item["original_sha256"]:
            raise ValueError("scientific input/source snapshot changed during publication")
    save_json(output / "provenance.json", {"classification": "PORTABLE_WP6_EVIDENCE",
        "original_snapshot": backup.relative_to(ROOT).as_posix(), "original_manifest_sha256": sha256(backup / "manifest.json"),
        "archive_only": archive_only, "source_and_input_bytes_unchanged": True,
        "path_policy": "only exact measured workspace prefix replaced by . in metadata; scientific numeric values unchanged; SHA pointers refreshed",
        "native_runtime_artifacts": "distribution-relative members and executable basename with SHA recorded per invocation; runtime binaries are metadata, not redistributed",
        "frozen_source_sha256": manifest["source_sha256"], "files": originals})
    if archive_only:
        for name in ARCHIVED_DIRECTORIES:
            target = (output / name).resolve()
            if target.parent != output.resolve():
                raise ValueError("archive-only cleanup escapes campaign")
            shutil.rmtree(target)
    (output / "README.md").write_text("# Solver-quality extension\n\n"
        "See [REPORT.md](REPORT.md) for accepted-only comparisons and complete attempted/completed denominators. "
        "Raw numerical rejections, solver failures, worker timeouts and interrupted attempts remain in evidence.zip. "
        "Native incumbent/bound observations are separate from independently recomputed usable costs. "
        "The approved adapter does not expose native MIPGap; normalized_gap is explicitly derived.\n\n"
        "Replay without a solver or current scientific source:\n\n"
        "```bash\npython scripts/extension_solver_quality.py summarize --output benchmarks/solver_quality_2026-10-14\n```\n\n"
        "The command verifies the portable inventory, archive membership/entry SHA, frozen source/input hashes, "
        "all retained attempt hashes and raw normalization/independent validation/objective comparison, "
        "then delegates to the hashed source snapshot. It automatically unpacks archived raw/input/source files. "
        "Standard-library Python>=3.13 is sufficient for numerical replay; optional --plots needs Matplotlib. "
        "No compiler, measured binary or proprietary solver license is required. "
        "Original-to-portable SHA provenance and runtime-artifact hashes remain machine readable.\n", encoding="utf-8", newline="\n")
    inventory(output)
    verify_inventory(output)
    return {"original_files": len(originals), "archived_files": len(archived),
            "archive_sha256": archive_manifest["archive_sha256"], "source_and_input_bytes_unchanged": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "run", "worker", "summarize", "publish", "render"))
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--backends", nargs="+", choices=("highs", "gurobi"), default=["highs", "gurobi"])
    parser.add_argument("--gurobi-skip-reason")
    parser.add_argument("--environment-note")
    parser.add_argument("--max-jobs", type=int)
    parser.add_argument("--job-id")
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--plots", action="store_true")
    parser.add_argument("--original-backup", type=Path)
    parser.add_argument("--measured-root-prefix")
    args = parser.parse_args()
    output = args.output.resolve()
    if sys.version_info < (3, 13):
        parser.error("Python>=3.13 is required")
    if args.max_jobs is not None and args.max_jobs <= 0:
        parser.error("--max-jobs must be positive")
    if args.command == "prepare":
        record = prepare(output, args.backends, args.gurobi_skip_reason)
        print(json.dumps({"selected_backends": record["backends"], "jobs": len(record["jobs"]),
                          "runtime_estimate": record["runtime_estimate"], "gate_passed": record["gate_passed"]}, indent=2))
    elif args.command == "run":
        if not args.environment_note:
            parser.error("run requires --environment-note with observed energy/CPU governor/app state")
        run_campaign(output, args.environment_note, args.max_jobs)
    elif args.command == "worker":
        if args.job_id is None or args.destination is None:
            parser.error("worker requires --job-id and --destination")
        manifest = verify_prepared(output)
        job = next(job for job in manifest["jobs"] if job["id"] == args.job_id)
        run_worker(output, job, args.destination)
    elif args.command == "publish":
        print(json.dumps(publish_campaign(output, args.original_backup, args.measured_root_prefix), indent=2))
    elif args.command == "render":
        unpack_campaign(output)
        verify_inventory(output)
        frozen_script = output / "snapshot/scripts/extension_solver_quality.py"
        numerical_hashes = {name: sha256(output / name) for name in ("analysis.json", "runs.csv", "REPORT.md")}
        archive_hash = sha256(output / "evidence.zip")
        replay_verification_hash = sha256(output / "archive_replay_verification.json")
        frozen_script_hash = sha256(frozen_script)
        renderer_script = Path(__file__).resolve()
        frozen_functions = {node.name: ast.dump(node, include_attributes=False)
            for node in ast.parse(frozen_script.read_text(encoding="utf-8")).body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        current_functions = {node.name: ast.dump(node, include_attributes=False)
            for node in ast.parse(renderer_script.read_text(encoding="utf-8")).body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        if frozen_functions.keys() != current_functions.keys():
            raise ValueError("presentation update changed the set of source functions")
        unchanged_functions = sorted(frozen_functions.keys() - {"plot_results", "main"})
        if any(frozen_functions[name] != current_functions[name] for name in unchanged_functions):
            raise ValueError("presentation update changed a function outside plot_results/main")
        process = subprocess.run([sys.executable, "-B", str(frozen_script), "summarize", "--output", str(output)],
                                 capture_output=True, text=True)
        if process.returncode:
            raise RuntimeError("frozen numerical replay before rendering failed: " + process.stderr)
        if any(sha256(output / name) != expected for name, expected in numerical_hashes.items()):
            raise ValueError("presentation update changed a numerical summary")
        plot_results(output, load_json(output / "analysis.json"), load_json(output / "manifest.json"))
        if sha256(output / "evidence.zip") != archive_hash or sha256(frozen_script) != frozen_script_hash:
            raise ValueError("presentation update changed frozen measured evidence/source")
        if sha256(output / "archive_replay_verification.json") != replay_verification_hash:
            raise ValueError("presentation update changed prior archive replay verification")
        save_json(output / "plot_presentation_verification.json", {
            "classification": "PRESENTATION_ONLY_CURRENT_RENDERER_AFTER_FROZEN_NUMERICAL_REPLAY",
            "frozen_measured_script": "evidence.zip:snapshot/scripts/extension_solver_quality.py",
            "frozen_measured_script_sha256": frozen_script_hash,
            "renderer_script": "scripts/extension_solver_quality.py", "renderer_script_sha256": sha256(renderer_script),
            "python_version": platform.python_version(), "platform": platform.platform(),
            "unchanged_numerical_artifacts_sha256": numerical_hashes,
            "unchanged_function_ast_sha256": {name: hashlib.sha256(frozen_functions[name].encode()).hexdigest()
                                              for name in unchanged_functions},
            "only_function_ast_changes_allowed": ["plot_results", "main"],
            "frozen_archive_sha256": archive_hash, "frozen_archive_unchanged": True,
            "prior_archive_replay_verification_sha256": replay_verification_hash,
            "prior_archive_replay_verification_unchanged": True,
            "major_tick_values": load_json(output / "manifest.json")["limits"], "minor_tick_labels": "hidden",
            "solver_or_algorithm_executed": False})
        readme = output / "README.md"
        render_command = "python scripts/extension_solver_quality.py render --output benchmarks/solver_quality_2026-10-14"
        text = readme.read_text(encoding="utf-8")
        if render_command not in text:
            readme.write_text(text + "\nOptional presentation refresh with the current renderer (Matplotlib required):\n\n"
                + "```bash\n" + render_command + "\n```\n\n"
                + "This command first replays the frozen numerical summary without plotting, then refreshes only the current presentation. "
                + "plot_presentation_verification.json distinguishes measured and renderer source hashes and verifies unchanged numerical outputs, "
                + "the measured archive, prior replay evidence and all function ASTs except plot_results/main.\n", encoding="utf-8", newline="\n")
        inventory(output)
        verify_inventory(output)
        print("Rendered exact limit ticks with hidden minor labels; frozen archive, numerical outputs and prior replay evidence unchanged.")
    else:
        # Use measured source for replay, including a standalone copied campaign.
        unpack_campaign(output)
        verify_inventory(output)
        script = output / "snapshot/scripts/extension_solver_quality.py"
        if script.exists() and script.resolve() != Path(__file__).resolve():
            command = [sys.executable, "-B", str(script), "summarize", "--output", str(output)]
            if args.plots:
                command.append("--plots")
            return subprocess.call(command)
        record = summarize(output, args.plots)
        print(f"Replayed {record['verified_completed_jobs']} completed jobs; independently accepted {record['accepted_measurement_rows']}/{record['attempted_unique_measured_jobs']} attempted unique measured jobs. Worker calls including retries: {record['attempted_measured_worker_calls']}; completed measured rows: {record['completed_measurement_rows']}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
