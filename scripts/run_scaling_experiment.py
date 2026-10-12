"""Frozen, bounded size/load campaign using the existing scientific runners.

New instances are explicitly synthetic. Algorithms, validators, tolerance
policies and Azure EWMA/keep-best semantics are unchanged. Run serially so
concurrent benchmark workers cannot contaminate each other's timings.
"""

import argparse
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import gzip
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False,
                               allow_nan=False) + "\n", encoding="utf-8")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(root):
    return {p.relative_to(root).as_posix(): sha(p)
            for directory in ("src", "tests", "scripts")
            for p in sorted((root / directory).rglob("*.py"))}


def make_case(spec):
    from llm_resource_allocation.data.scaling_experiment_instances import make_scaling_experiment_case
    case = make_scaling_experiment_case(
        *spec["dimensions"], load_multiplier=spec["load_multiplier"],
        delay_slo_multiplier=spec["delay_slo_multiplier"],
        budget_multiplier=spec["budget_multiplier"],
    )
    return replace(case, case_id=spec["case_id"], family=spec["family"])


def stage1_worker(config, output):
    from llm_resource_allocation.experiments.synthetic_benchmark import (
        SyntheticBenchmarkConfig, run_synthetic_benchmark, write_benchmark_results,
    )
    from llm_resource_allocation.optimization.solver import SolverBackend
    settings = SyntheticBenchmarkConfig(
        seeds=tuple(config["seeds"]), query_counts=(), warmup_repeats=1,
        backend=SolverBackend.GUROBI,
        solver_time_limit_seconds=config["stage1_solver_limit_seconds"],
    )
    cases = tuple(make_case(spec) for spec in config["case_specs"])
    runs = run_synthetic_benchmark(settings, cases, progress=lambda x: print(x, flush=True))
    write_benchmark_results(output / "stage1", settings, cases, runs, ROOT)
    # The standard exporter describes its original I-only family. Replace that
    # local prose for this separate campaign without changing its numerical data.
    report = output / "stage1/report.md"
    text = report.read_text(encoding="utf-8")
    text = text.replace(
        "Questa famiglia aumenta solo i tipi di query: modelli e tier restano due. Le prestazioni non vanno estrapolate oltre le dimensioni misurate.",
        "Questa campagna confronta aumento congiunto, soli tipi di query, sole alternative modello/tier e carico elevato. Le assunzioni degli input sono nel manifest; le prestazioni valgono per questi casi sintetici.",
    )
    report.write_text(text, encoding="utf-8")
    print(f"Stage1 saved: {len(runs)} attempts including warmups", flush=True)


def azure_worker(config, output, job):
    from llm_resource_allocation.experiments.azure_replay import (
        AzureReplayConfig, AzureReplayVariant, AzureReplayWindow, run_azure_replay,
    )
    from llm_resource_allocation.optimization.solver import SolverBackend, SolverConfig
    from llm_resource_allocation.optimization.stage2_adapter import Stage1Method
    from run_azure_replay import _plain, _source_evidence, _timing_row, _write_csv

    spec = next(spec for spec in config["case_specs"] if spec["case_id"] == job["case_id"])
    case = make_case(spec)
    profile = json.loads((ROOT / "results/azure_trace/profiles.json").read_text(encoding="utf-8"))
    day = next(day for day in profile["days"] if day["date"] == job["date"])
    if len(day["windows"]) != 288 or [w["index"] for w in day["windows"]] != list(range(288)):
        raise ValueError("Expected the complete ordered real Azure day profile")
    if sum(w["request_count"] for w in day["windows"]) != day["request_count"]:
        raise ValueError("Azure day/window counts disagree")
    if any(w["daily_multiplier"] != w["request_count"] * 288 / day["request_count"] for w in day["windows"]):
        raise ValueError("Azure multipliers disagree with D-0089 normalization")
    windows = tuple(AzureReplayWindow(w["index"], w["daily_multiplier"], w["request_count"])
                    for w in day["windows"][:job["window_count"]])
    settings = AzureReplayConfig(
        method=Stage1Method(job["method"]), variant=AzureReplayVariant(job["variant"]),
        random_seed=job["seed"], solver_config=SolverConfig(
            backend=SolverBackend.GUROBI,
            time_limit_seconds=config["azure_solver_limit_seconds"],
            relative_mip_gap=0.0, absolute_mip_gap=0.0,
        ),
    )
    warmup_start = perf_counter()
    warmup = run_azure_replay(windows[:3], settings, instance=case.instance)
    excluded_warmup_seconds = perf_counter() - warmup_start
    warmup_successful = warmup.aggregate.successful_window_count
    del warmup
    start = perf_counter()
    result = run_azure_replay(windows, settings, instance=case.instance)
    elapsed = perf_counter() - start
    target = output / "azure" / job["job_id"]
    target.mkdir(parents=True, exist_ok=True)
    summary = {
        **job, "family": spec["family"], "dimensions": spec["dimensions"],
        "load_multiplier": spec["load_multiplier"],
        **_plain(result.aggregate), **_timing_row(result, elapsed),
        "excluded_warmup_seconds": excluded_warmup_seconds,
        "excluded_warmup_successful_count": warmup_successful,
        "instance_provenance": dict(case.provenance),
        "model_score_horizon_hours": case.instance.horizon_hours,
        "classification": "REAL_AZURE_SHAPE_ON_ASSUMED_MULTIDIMENSIONAL_INPUTS",
    }
    sources, windows_rows, queries, source_rows, evaluations = {}, [], [], [], []
    with gzip.open(target / "evidence.jsonl.gz", "wt", encoding="utf-8") as stream:
        def register(source):
            if source is None or id(source) in sources:
                return
            index = len(sources)
            sources[id(source)] = index
            source_rows.append(dict(source_id=index, forecast_multiplier=source.forecast_multiplier,
                                    accepted=source.accepted, elapsed_seconds=source.elapsed_seconds))
            stream.write(json.dumps(dict(kind="stage1_source", source_id=index,
                **_source_evidence(source, job["method"])), allow_nan=False) + "\n")
        register(result.static_source)
        for row in result.windows:
            for source in (row.candidate, row.incumbent_before, row.selected_source):
                register(source)
            for role, value in (("candidate_forecast", row.candidate_forecast_evaluation),
                                ("incumbent_forecast", row.incumbent_forecast_evaluation),
                                ("operation", row.operation)):
                if value is None:
                    continue
                integrated = value.evaluation_result
                record = integrated.stage2_run_record if integrated else None
                solver = record.solver_evidence.result if record and record.solver_evidence else None
                evaluations.append(dict(window_index=row.window.window_index, role=role,
                    source_id=sources[id(value.source)], successful=value.successful,
                    elapsed_seconds=value.elapsed_seconds,
                    solver_solve_seconds=solver.solve_time_seconds if solver else None))
                # Retain every forecast and operation's independent evidence;
                # source inputs are stored once, without AGH search graphs.
                stream.write(json.dumps(dict(kind="stage2_evaluation",
                    **evaluations[-1], stage2_run_record=_plain(record),
                    failure=_plain(value.failure)), allow_nan=False) + "\n")
            windows_rows.append(dict(window_index=row.window.window_index,
                request_count=row.window.request_count,
                realized_multiplier=row.window.realized_multiplier,
                forecast_multiplier=row.forecast_multiplier,
                next_forecast_multiplier=row.next_forecast_multiplier,
                selection=row.selection.value, successful=row.successful,
                model_cost=row.model_cost,
                candidate_source_id=sources.get(id(row.candidate)),
                selected_source_id=sources.get(id(row.selected_source)),
                failure=row.failure.message if row.failure else None))
            queries.extend(dict(window_index=row.window.window_index, **_plain(metric))
                           for metric in row.query_metrics)
    _write_csv(target / "windows.csv", windows_rows)
    _write_csv(target / "query_metrics.csv", queries, fieldnames=["window_index", "query_id",
        "arrival_rate_per_hour", "unmet_fraction", "served_fraction", "violation"])
    _write_csv(target / "stage1_timings.csv", source_rows,
        fieldnames=["source_id", "forecast_multiplier", "accepted", "elapsed_seconds"])
    _write_csv(target / "evaluation_timings.csv", evaluations,
        fieldnames=["window_index", "role", "source_id", "successful", "elapsed_seconds", "solver_solve_seconds"])
    save(target / "summary.json", summary)
    print(f"{job['job_id']}: {result.aggregate.successful_window_count}/{len(windows)} windows, {elapsed:.3f}s", flush=True)


def execute(command, cwd, log_path, env):
    start = perf_counter()
    with log_path.open("w", encoding="utf-8") as log:
        result = subprocess.run(command, cwd=cwd, env=env, stdout=log,
                                stderr=subprocess.STDOUT)
    return dict(command=command, exit_code=result.returncode,
                elapsed_seconds=perf_counter() - start, log=log_path.name)


def campaign(config_path, output):
    if output.exists():
        raise ValueError("Use a fresh output directory; prior evidence is preserved")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    output.mkdir(parents=True)
    workspace = output / "execution_workspace"
    before = inventory(ROOT)
    for relative in before:
        target = workspace / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    for source in sorted((ROOT / "docs").rglob("*.md")):
        target = workspace / source.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    for source in sorted((ROOT / "configs").glob("*.json")):
        target = workspace / source.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    for relative in ("AGENTS.md", "README.md", "pyproject.toml", "2604.07472v1.pdf",
                     "2604.07472v2.pdf", "results/azure_trace/profiles.json"):
        target = workspace / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    save(output / "config.json", config)
    save(workspace / "configs/scaling_experiment.json", config)
    frozen = inventory(workspace)
    if frozen != before or inventory(ROOT) != before:
        raise RuntimeError("Source changed while freezing; this copy is not measured")
    from importlib.metadata import version
    manifest = dict(started_at_utc=datetime.now(timezone.utc).isoformat(),
        classification="ASSUMED_SIZE_LOAD_CAMPAIGN_WITH_REAL_AZURE_SHAPE",
        reference_decision="D-0100", source_sha256=frozen,
        config_sha256=sha(output / "config.json"),
        azure_profiles_sha256=sha(workspace / "results/azure_trace/profiles.json"),
        supporting_authority_sha256={p.relative_to(workspace).as_posix(): sha(p)
            for p in sorted(workspace.rglob("*")) if p.is_file()
            and (p.suffix.lower() in (".md", ".pdf", ".toml"))},
        python=sys.version, python_executable=sys.executable, platform=platform.platform(),
        logical_cpu_count=os.cpu_count(), versions={name: version(name) for name in
            ("pyomo", "gurobipy", "highspy", "matplotlib")},
        baseline_authority="runtime-check-cleanup-2026-10-09; 139 hashes verified before this extension",
        independent_validation_policy="D-0097", commands=[], jobs=[], complete=False)
    save(output / "manifest.json", manifest)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(workspace / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    script = str(workspace / "scripts/run_scaling_experiment.py")
    base = [sys.executable, "-B", "-X", "utf8"]
    regression = execute(base + ["-m", "unittest", "discover", "-s", "tests", "-q"],
                         workspace, output / "regression.log", env)
    manifest["commands"].append(regression)
    save(output / "manifest.json", manifest)
    print(f"Regression exit={regression['exit_code']}, {regression['elapsed_seconds']:.3f}s", flush=True)
    if regression["exit_code"]:
        raise RuntimeError("Frozen regression failed; inspect regression.log")
    compile_check = execute(base + ["-c", "from pathlib import Path; files=[p for d in ('src','scripts') for p in Path(d).rglob('*.py')]; [compile(p.read_text(encoding='utf-8'), str(p), 'exec') for p in files]; print('Compiled', len(files), 'Python files without writing caches')"],
                            workspace, output / "compile.log", env)
    manifest["commands"].append(compile_check)
    if compile_check["exit_code"]:
        raise RuntimeError("Compilation failed")
    command = base + [script, "--worker", "stage1", "--config",
        str(workspace / "configs/scaling_experiment.json"), "--output", str(output)]
    print("Starting paired Stage1 size/load comparisons", flush=True)
    stage1 = execute(command, workspace, output / "stage1.log", env)
    manifest["commands"].append(stage1)
    save(output / "manifest.json", manifest)
    if stage1["exit_code"]:
        raise RuntimeError("Stage1 campaign failed; inspect stage1.log")
    print(f"Stage1 finished in {stage1['elapsed_seconds']:.3f}s", flush=True)
    jobs = []
    for spec in config["case_specs"]:
        if spec["family"] not in ("nominal_joint", "loaded_joint"):
            continue
        variants = ["static"]
        if spec["family"] == "loaded_joint" and spec["dimensions"][0] <= 6:
            variants.append("rolling")
        for date in config["dates"]:
            for method in ("p_dm", "gh", "agh"):
                for variant in variants:
                    identity = f"{spec['case_id']}_{date}_{method}_{variant}"
                    jobs.append(dict(job_id=identity, case_id=spec["case_id"], date=date,
                        method=method, variant=variant, seed=config["seeds"][0],
                        window_count=288, pilot=False))
    for job in jobs:
        if job["variant"] == "rolling":
            pilot = {**job, "job_id": job["job_id"] + "_pilot",
                     "window_count": config["rolling_pilot_windows"], "pilot": True}
            pilot_command = base + [script, "--worker", "azure", "--config",
                str(workspace / "configs/scaling_experiment.json"), "--output", str(output),
                "--job", json.dumps(pilot)]
            record = execute(pilot_command, workspace, output / (pilot["job_id"] + ".log"), env)
            manifest["jobs"].append({**pilot, **record})
            if record["exit_code"]:
                manifest["jobs"].append({**job, "skipped": True, "reason": "pilot_execution_failure"})
                save(output / "manifest.json", manifest)
                continue
            pilot_summary = json.loads((output / "azure" / pilot["job_id"] / "summary.json").read_text(encoding="utf-8"))
            projected = pilot_summary["replay_time_seconds"] * 288 / pilot["window_count"]
            if projected > config["rolling_full_projection_limit_seconds"]:
                manifest["jobs"].append({**job, "skipped": True,
                    "reason": "predeclared_runtime_gate", "projected_seconds": projected})
                save(output / "manifest.json", manifest)
                print(f"{job['job_id']}: pilot retained, projection {projected:.1f}s exceeds gate", flush=True)
                continue
        print(f"Starting {job['job_id']}", flush=True)
        command = base + [script, "--worker", "azure", "--config",
            str(workspace / "configs/scaling_experiment.json"), "--output", str(output),
            "--job", json.dumps(job)]
        record = execute(command, workspace, output / (job["job_id"] + ".log"), env)
        manifest["jobs"].append({**job, **record})
        save(output / "manifest.json", manifest)
        print(f"Finished {job['job_id']}, exit={record['exit_code']}, {record['elapsed_seconds']:.2f}s", flush=True)
    manifest["source_stable_during_run"] = frozen == inventory(workspace)
    manifest["live_source_matches_snapshot_at_completion"] = inventory(ROOT) == frozen
    manifest["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    manifest["complete"] = manifest["source_stable_during_run"] and all(
        job.get("skipped", False) or job.get("exit_code") == 0 for job in manifest["jobs"])
    save(output / "manifest.json", manifest)
    print(f"Campaign completed; frozen source stable={manifest['source_stable_during_run']}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/scaling_experiment.json")
    parser.add_argument("--output", type=Path, default=ROOT / "results/scaling_2026-10-09")
    parser.add_argument("--worker", choices=("stage1", "azure"))
    parser.add_argument("--job", help="Structured JSON job supplied by the campaign")
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT / "src"))
    if args.worker:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        if args.worker == "stage1":
            stage1_worker(config, args.output)
        else:
            azure_worker(config, args.output, json.loads(args.job))
    else:
        campaign(args.config.resolve(), args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
