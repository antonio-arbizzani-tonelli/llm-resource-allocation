"""Replay real Azure diurnal demand on an explicitly synthetic reference instance."""

import argparse
from collections.abc import Mapping
import csv
from dataclasses import is_dataclass
from enum import Enum
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
from statistics import median
import sys
from time import perf_counter
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]


def _plain(value):
    """Serialize plain scientific evidence, retaining tuple mapping keys."""
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        from llm_resource_allocation.experiments._record_serialization import public_record_items

        return {
            name: _plain(item) for name, item in public_record_items(value)
        }
    if isinstance(value, Mapping):
        if all(isinstance(key, str) for key in value):
            return {key: _plain(item) for key, item in value.items()}
        return [{"key": _plain(key), "value": _plain(item)} for key, item in value.items()]
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


def _source_evidence(source, method):
    """Keep construction inputs, placement and validation without AGH search graphs."""
    result = source.source_result
    placement = validation = solver = None
    if result is not None:
        if method == "p_dm":
            placement = result.solution
            validation = result.scientific_evidence.validation_report
            solver = result.solver_evidence
        elif method == "gh":
            placement, validation = result.placement_decisions, result.validation_report
        else:
            placement, validation = result.final_placement, result.final_validation
    return _plain({
        "construction_instance": source.construction_problem_data.instance,
        "forecast_multiplier": source.forecast_multiplier,
        "random_seed": source.random_seed,
        "elapsed_seconds": source.elapsed_seconds,
        "accepted": source.accepted,
        "failure": source.failure,
        "placement": placement,
        "independent_validation": validation,
        "solver": solver,
    })


def _write_csv(path, rows, fieldnames=None):
    if not rows and fieldnames is None:
        raise ValueError("Cannot export an empty result table")
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]) if fieldnames is None else fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _timing_row(result, replay_time_seconds):
    """Count actual calls, retaining rejected attempts and repeated evaluations."""
    sources = {}
    if result.static_source is not None:
        sources[id(result.static_source)] = result.static_source
    forecast_evaluations, operations = [], []
    for window in result.windows:
        if window.candidate is not None:
            sources[id(window.candidate)] = window.candidate
        forecast_evaluations.extend(value for value in (
            window.candidate_forecast_evaluation, window.incumbent_forecast_evaluation,
        ) if value is not None)
        if window.operation is not None:
            operations.append(window.operation)
    stage1_times = [source.elapsed_seconds for source in sources.values()]
    stage1_total = sum(stage1_times)
    forecast_total = sum(value.elapsed_seconds for value in forecast_evaluations)
    operation_total = sum(value.elapsed_seconds for value in operations)
    return {
        "replay_time_seconds": replay_time_seconds,
        "stage1_attempt_count": len(sources),
        "stage1_accepted_count": sum(source.accepted for source in sources.values()),
        "stage1_total_seconds": stage1_total,
        "stage1_median_seconds": median(stage1_times) if stage1_times else None,
        "forecast_stage2_eval_count": len(forecast_evaluations),
        "forecast_stage2_total_seconds": forecast_total,
        "operational_stage2_eval_count": len(operations),
        "operational_stage2_total_seconds": operation_total,
        "orchestration_seconds": replay_time_seconds - stage1_total - forecast_total - operation_total,
    }


def _presentation_timings(rows, source_rows):
    """Aggregate days while computing medians from individual constructions."""
    keys = list(dict.fromkeys((row["method"], row["variant"]) for row in rows))
    summary = []
    for method, variant in keys:
        selected = [row for row in rows if (row["method"], row["variant"]) == (method, variant)]
        sources = [row for row in source_rows if (row["method"], row["variant"]) == (method, variant)]
        times = [row["elapsed_seconds"] for row in sources]
        summary.append({
            "method": method, "variant": variant, "day_count": len(selected),
            "window_count": sum(row["window_count"] for row in selected),
            "replay_total_seconds": sum(row["replay_time_seconds"] for row in selected),
            "stage1_attempt_count": len(times),
            "stage1_accepted_count": sum(row["accepted"] for row in sources),
            "stage1_median_milliseconds": 1000 * median(times) if times else None,
            "stage1_total_seconds": sum(times),
            "forecast_stage2_total_seconds": sum(row["forecast_stage2_total_seconds"] for row in selected),
            "operational_stage2_total_seconds": sum(row["operational_stage2_total_seconds"] for row in selected),
            "orchestration_seconds": sum(row["orchestration_seconds"] for row in selected),
        })
    return summary


def _plot_timings(output, rows):
    """Presentation figures use full Stage-1/replay times, not solver-only times."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    methods = list(dict.fromkeys(row["method"] for row in rows))
    lookup = {(row["method"], row["variant"]): row for row in rows}
    fig, axes = plt.subplots(1, 2, figsize=(11, 5), layout="constrained")
    variants = ("static", "rolling")
    colors = ("#176b89", "#dc683b")
    for index, (variant, color) in enumerate(zip(variants, colors)):
        positions = [position + (index - .5) * .36 for position in range(len(methods))]
        values = [lookup.get((method, variant)) for method in methods]
        for axis, field in zip(axes, ("stage1_median_milliseconds", "replay_total_seconds")):
            heights = [row[field] if row is not None and row[field] is not None else 0 for row in values]
            bars = axis.bar(positions, heights, width=.34, label=variant, color=color)
            labels = [f"{height:.2f}" if row is not None and row[field] is not None else "n.d."
                      for row, height in zip(values, heights)]
            axis.bar_label(bars, labels=labels, padding=3, fontsize=9)
    axes[0].set_title("Tempo di costruzione Stage 1")
    axes[0].set_ylabel("Mediana per costruzione [ms]")
    axes[1].set_title("Tempo totale di replay dei giorni misurati")
    axes[1].set_ylabel("Replay completo [s]")
    for axis in axes:
        axis.set_xticks(range(len(methods)), [method.upper() for method in methods])
        axis.set_ylim(0, axis.get_ylim()[1] * 1.15)
        axis.grid(axis="y", alpha=.2)
        axis.set_axisbelow(True)
        axis.legend()
    fig.suptitle("Tempi Azure — trace reale su istanza sintetica 2×2×2", fontsize=14)
    fig.supxlabel("Un replay per giorno e combinazione; warmup escluso. Stage 1 include costruzione e validazione.", fontsize=9)
    fig.savefig(output / "runtime_comparison.png", dpi=180)
    fig.savefig(output / "runtime_comparison.svg")
    plt.close(fig)


def _plot(output, profiles, rows):
    os.environ.setdefault("MPLCONFIGDIR", str(output / "matplotlib_cache"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    for day in profiles:
        fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True, layout="constrained")
        hours = [window["index"] / 12 for window in day["windows"]]
        axes[0].plot(hours, [window["daily_multiplier"] for window in day["windows"]], color="#176b89", linewidth=1.5)
        axes[0].axhline(1, color="#888888", linestyle="--", linewidth=0.8)
        axes[0].set_ylabel("Domanda / media giornaliera")
        axes[0].set_title(f"Azure Code {day['date']} — trace reale, istanza sintetica 2×2×2")
        colors = {"p_dm": "#176b89", "gh": "#dc683b", "agh": "#7a5195"}
        for method in colors:
            for variant in ("static", "rolling"):
                values = [row for row in rows if row["date"] == day["date"] and row["method"] == method and row["variant"] == variant]
                if values:
                    axes[1].plot([row["window_index"] / 12 for row in values],
                                 [row["model_cost"] if row["model_cost"] is not None else float("nan") for row in values],
                                 label=f"{method.upper()} {variant}", color=colors[method],
                                 linestyle="-" if variant == "static" else "--", alpha=0.8)
        axes[1].set_ylabel("Costo del modello (orizzonte 2 h)")
        axes[1].set_xlabel("Ora UTC")
        axes[1].legend(ncol=3, fontsize=8)
        axes[1].ticklabel_format(axis="y", style="plain", useOffset=False)
        for axis in axes:
            axis.grid(alpha=0.2)
        fig.savefig(output / f"azure_{day['date']}.png", dpi=170)
        fig.savefig(output / f"azure_{day['date']}.svg")
        plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profiles", type=Path, default=ROOT / "results/azure_trace/profiles.json")
    parser.add_argument("--config", type=Path, default=ROOT / "configs/azure_replay.json")
    parser.add_argument("--output", type=Path, default=ROOT / "results/azure_replay")
    parser.add_argument("--window-limit", type=int, help="Explicit partial-day pilot; full-day is the default")
    parser.add_argument("--warmup-windows", type=int, default=3, help="Excluded warmup windows per case (default: 3; 0 disables)")
    args = parser.parse_args()
    if args.window_limit is not None and not 1 <= args.window_limit <= 288:
        parser.error("--window-limit must be between 1 and 288")
    if not 0 <= args.warmup_windows <= 288:
        parser.error("--warmup-windows must be between 0 and 288")
    config_text = args.config.read_text(encoding="utf-8")
    config = json.loads(config_text)
    if config["instance"] != "make_heterogeneous_tiny_instance":
        raise ValueError("This driver supports only the explicitly selected verified fixture")
    profile_text = args.profiles.read_text(encoding="utf-8")
    profile = json.loads(profile_text)
    if profile["classification"] != "REAL_TRACE_COUNTS_WITHOUT_SCIENTIFIC_CALIBRATION":
        raise ValueError("Input must retain the trace-preprocessing provenance")
    days_by_date = {day["date"]: day for day in profile["days"]}
    days = [days_by_date[value] for value in config["dates"]]
    for day in days:
        windows = day["windows"]
        if day["request_count"] <= 0 or len(windows) != 288 or [window["index"] for window in windows] != list(range(288)):
            raise ValueError("A replay day requires all 288 ordered windows and a nonempty trace")
        if sum(window["request_count"] for window in windows) != day["request_count"]:
            raise ValueError("Profile day count differs from its window counts")
        if any(window["daily_multiplier"] != window["request_count"] * 288 / day["request_count"] for window in windows):
            raise ValueError("Profile multipliers differ from the documented daily normalization")
    args.output.mkdir(parents=True, exist_ok=True)
    snapshot = args.output / "source_snapshot" / uuid4().hex
    for directory in ("src", "scripts"):
        for source in sorted((ROOT / directory).rglob("*.py")):
            target = snapshot / source.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
    (snapshot / "configs").mkdir()
    (snapshot / "configs/azure_replay.json").write_text(config_text, encoding="utf-8")
    sys.path.insert(0, str(snapshot / "src"))
    from llm_resource_allocation.experiments.azure_replay import (
        AzureReplayConfig, AzureReplayVariant, AzureReplayWindow, run_azure_replay,
    )
    from llm_resource_allocation.optimization.solver import SolverBackend, SolverConfig
    from llm_resource_allocation.optimization.stage2_adapter import Stage1Method
    from llm_resource_allocation.math.objective import PaperVersion
    solver = SolverConfig(backend=SolverBackend(config["backend"]), time_limit_seconds=config["solver_time_limit_seconds"], relative_mip_gap=0, absolute_mip_gap=0)
    manifest = {
        "classification": config["classification"], "reference_decision": config["reference_decision"],
        "configuration": config, "window_limit": args.window_limit,
        "trace_provenance": {key: value for key, value in profile.items() if key != "days"},
        "profiles_sha256": hashlib.sha256(profile_text.encode("utf-8")).hexdigest(),
        "python": platform.python_version(), "platform": platform.platform(),
        "pyomo": version("pyomo"), "highspy": version("highspy"),
        "logical_cpu_count": os.cpu_count(),
        "timing_policy": {
            "reference_decision": "D-0090", "clock": "time.perf_counter",
            "repetitions_per_day_method_variant": 1,
            "warmup_windows_per_case": args.warmup_windows,
            "stage1_scope": "demand scaling, problem construction, algorithm/solver, extraction and independent validation",
            "stage2_scope": "source/scenario integration, LP construction/solve, extraction and independent validation",
            "replay_scope": "run_azure_replay call, including Stage 1, forecast and operational Stage 2, metrics and orchestration",
            "excluded_from_replay": ["warmup", "imports", "console output", "serialization", "file output", "plotting"],
            "median_population": "distinct measured Stage-1 attempts across selected days; not repeated identical inputs",
        },
        "source_snapshot": snapshot.relative_to(args.output).as_posix(),
        "source_sha256": {source.relative_to(snapshot).as_posix(): hashlib.sha256(source.read_bytes()).hexdigest() for source in sorted(snapshot.rglob("*")) if source.is_file()},
        "cost_caveat": config["cost_reporting"],
    }
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    summaries, window_rows, query_rows = [], [], []
    timing_rows, source_rows, evaluation_rows, warmup_rows = [], [], [], []
    start = perf_counter()
    with (args.output / "evidence.jsonl").open("w", encoding="utf-8") as evidence:
        for day in days:
            windows = [AzureReplayWindow(item["index"], item["daily_multiplier"], item["request_count"]) for item in day["windows"][:args.window_limit]]
            for method in config["methods"]:
                for variant in config["variants"]:
                    print(f"{day['date']} {method} {variant}: {len(windows)} windows", flush=True)
                    settings = AzureReplayConfig(method=Stage1Method(method), variant=AzureReplayVariant(variant),
                        ewma_alpha=config["ewma_alpha"], initial_forecast_multiplier=config["initial_forecast_multiplier"],
                        random_seed=config["random_seed"], gh_budget_fraction=config["gh_budget_fraction"],
                        solver_config=solver, paper_version=PaperVersion(config["paper_version"]))
                    prefix = {"date": day["date"], "method": method, "variant": variant}
                    warmup_count = min(args.warmup_windows, len(windows))
                    if warmup_count:
                        warmup_start = perf_counter()
                        warmup = run_azure_replay(windows[:warmup_count], settings, progress=None)
                        warmup_rows.append({**prefix, "window_count": warmup_count,
                            "successful_window_count": warmup.aggregate.successful_window_count,
                            "excluded_elapsed_seconds": perf_counter() - warmup_start})
                        del warmup
                    case_start = perf_counter()
                    result = run_azure_replay(windows, settings, progress=None)
                    replay_seconds = perf_counter() - case_start
                    timing_rows.append({**prefix, "window_count": len(windows), **_timing_row(result, replay_seconds)})
                    summaries.append({**prefix, **_plain(result.aggregate)})
                    source_ids = {}
                    def register_source(source):
                        if source is None or id(source) in source_ids:
                            return
                        source_id = len(source_ids)
                        source_ids[id(source)] = source_id
                        source_rows.append({**prefix, "source_id": source_id,
                            "forecast_multiplier": source.forecast_multiplier,
                            "accepted": source.accepted, "elapsed_seconds": source.elapsed_seconds})
                        evidence.write(json.dumps({"kind": "stage1_source", **prefix,
                            "source_id": source_id, **_source_evidence(source, method)}, allow_nan=False) + "\n")
                    register_source(result.static_source)
                    for row in result.windows:
                        for source in (row.candidate, row.incumbent_before, row.selected_source):
                            register_source(source)
                        for role, evaluation in (("candidate_forecast", row.candidate_forecast_evaluation),
                                                 ("incumbent_forecast", row.incumbent_forecast_evaluation),
                                                 ("operation", row.operation)):
                            if evaluation is not None:
                                integrated_evaluation = evaluation.evaluation_result
                                evaluated_run = integrated_evaluation.stage2_run_record if integrated_evaluation else None
                                solver_evidence = evaluated_run.solver_evidence if evaluated_run else None
                                evaluation_rows.append({**prefix, "window_index": row.window.window_index,
                                    "role": role, "source_id": source_ids[id(evaluation.source)],
                                    "successful": evaluation.successful,
                                    "elapsed_seconds": evaluation.elapsed_seconds,
                                    "solver_solve_seconds": solver_evidence.result.solve_time_seconds if solver_evidence else None})
                        operation = row.operation
                        integrated = operation.evaluation_result if operation else None
                        run_record = integrated.stage2_run_record if integrated else None
                        window_rows.append({**prefix, "window_index": row.window.window_index,
                            "request_count": row.window.request_count, "realized_multiplier": row.window.realized_multiplier,
                            "forecast_multiplier": row.forecast_multiplier, "next_forecast_multiplier": row.next_forecast_multiplier,
                            "selection": row.selection.value, "successful": row.successful, "model_cost": row.model_cost,
                            "construction_multiplier": row.selected_source.forecast_multiplier if row.selected_source else None,
                            "candidate_forecast_cost": row.candidate_forecast_evaluation.full_model_cost if row.candidate_forecast_evaluation else None,
                            "incumbent_forecast_cost": row.incumbent_forecast_evaluation.full_model_cost if row.incumbent_forecast_evaluation else None,
                            "candidate_stage1_elapsed_seconds": row.candidate.elapsed_seconds if row.candidate else None,
                            "candidate_forecast_elapsed_seconds": row.candidate_forecast_evaluation.elapsed_seconds if row.candidate_forecast_evaluation else None,
                            "incumbent_forecast_elapsed_seconds": row.incumbent_forecast_evaluation.elapsed_seconds if row.incumbent_forecast_evaluation else None,
                            "operational_elapsed_seconds": operation.elapsed_seconds if operation else None,
                            "failure": row.failure.message if row.failure else None})
                        query_rows.extend({**prefix, "window_index": row.window.window_index, **_plain(metric)} for metric in row.query_metrics)
                        evidence.write(json.dumps({"kind": "operational_window", **window_rows[-1],
                            "selected_source_id": source_ids.get(id(row.selected_source)),
                            "candidate_source_id": source_ids.get(id(row.candidate)),
                            "stage2_run_record": _plain(run_record),
                            "failure_evidence": _plain(row.failure),
                            "candidate_forecast_failure": _plain(row.candidate_forecast_evaluation.failure) if row.candidate_forecast_evaluation else None,
                            "incumbent_forecast_failure": _plain(row.incumbent_forecast_evaluation.failure) if row.incumbent_forecast_evaluation else None}, allow_nan=False) + "\n")
                    print(f"  validated {result.aggregate.successful_window_count}/{result.aggregate.window_count}; replay {replay_seconds:.3f} s", flush=True)
    _write_csv(args.output / "summary.csv", summaries)
    _write_csv(args.output / "windows.csv", window_rows)
    _write_csv(args.output / "query_metrics.csv", query_rows, fieldnames=[
        "date", "method", "variant", "window_index", "query_id",
        "arrival_rate_per_hour", "unmet_fraction", "served_fraction", "violation",
    ])
    _write_csv(args.output / "timing_summary.csv", timing_rows)
    _write_csv(args.output / "stage1_timings.csv", source_rows, fieldnames=[
        "date", "method", "variant", "source_id", "forecast_multiplier", "accepted", "elapsed_seconds",
    ])
    _write_csv(args.output / "evaluation_timings.csv", evaluation_rows, fieldnames=[
        "date", "method", "variant", "window_index", "role", "source_id", "successful", "elapsed_seconds", "solver_solve_seconds",
    ])
    presentation_timings = _presentation_timings(timing_rows, source_rows)
    _write_csv(args.output / "timing_presentation.csv", presentation_timings)
    manifest["excluded_warmups"] = warmup_rows
    manifest["measured_replay_total_seconds"] = sum(row["replay_time_seconds"] for row in timing_rows)
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    report = ["# Replay Azure su istanza sintetica", "", "Trace reale Code del 2024; istanza sintetica 2×2×2. Non è una replica della Tabella 5.", "", f"EWMA causale alpha={config['ewma_alpha']}, inizializzata a {config['initial_forecast_multiplier']}; keep-best sul costo del modello sotto la stessa previsione. Parametri completi in manifest.json.", "", "Costo: media e somma dei punteggi per finestra, mantenendo l'orizzonte sintetico di 2 ore. La somma non è una fattura reale sulle 24 ore; convenzioni C3/C4 del riferimento conservate.", "", "| Giorno | Metodo | Variante | Finestre valide | Costo medio modello | Somma costi modello | Violazioni u>1% |", "|---|---|---|---:|---:|---:|---:|"]
    for row in summaries:
        mean = f"{row['mean_window_model_cost']:.9f}" if row["mean_window_model_cost"] is not None else "non disponibile"
        total = f"{row['sum_window_model_cost']:.9f}" if row["sum_window_model_cost"] is not None else "non disponibile"
        violation = f"{100*row['violation_rate']:.3f}%" if row["violation_rate"] is not None else "non disponibile"
        report.append(f"| {row['date']} | {row['method'].upper()} | {row['variant']} | {row['successful_window_count']}/{row['window_count']} | {mean} | {total} | {violation} |")
    report.extend(["", "I moltiplicatori temporali provengono dai conteggi Azure. Tassi medi 12/4 richieste/ora, token, risorse, SLO, penalità e cap 10%/5% restano sintetici. Non abbiamo eseguito richieste LLM o usato risorse Azure a pagamento.", "", "## Tempi per la presentazione", "", "Stage 1 include costruzione, algoritmo/solver e validazione indipendente. Il replay include anche le valutazioni LP sulla previsione e le operazioni sul carico osservato. Warmup, importazioni, scrittura su disco, stampe e grafici sono esclusi dal tempo di replay.", "", f"Una misura per giorno/metodo/variante; warmup iniziale di {args.warmup_windows} finestre per caso (limitato alle finestre disponibili). Le mediane descrivono allocazioni sui diversi carichi, non repliche statistiche dello stesso problema.", "", "| Metodo | Variante | Giorni | Finestre | Allocazioni Stage 1 | Mediana Stage 1 [ms] | Totale Stage 1 [s] | Replay completo [s] |", "|---|---|---:|---:|---:|---:|---:|---:|"])
    for row in presentation_timings:
        allocation_median = f"{row['stage1_median_milliseconds']:.3f}" if row["stage1_median_milliseconds"] is not None else "non disponibile"
        report.append(f"| {row['method'].upper()} | {row['variant']} | {row['day_count']} | {row['window_count']} | {row['stage1_attempt_count']} | {allocation_median} | {row['stage1_total_seconds']:.3f} | {row['replay_total_seconds']:.3f} |")
    report.extend(["", "![Confronto dei tempi](runtime_comparison.png)", "", "Il caso statico costruisce una sola allocazione al giorno; rolling ne costruisce una a ogni finestra e valuta candidato e incumbent sulla previsione. I tempi totali riflettono questo diverso numero di operazioni.", "", "Tempi di ogni tentativo in stage1_timings.csv; tempi di ogni LP integrato in evaluation_timings.csv; scomposizione per giorno in timing_summary.csv. Il solo solver.solve è una sottofase del tempo integrato Stage 2.", "", f"Somma dei replay misurati: {manifest['measured_replay_total_seconds']:.3f} s.", f"Durata del driver fino alle esportazioni (inclusi warmup): {perf_counter()-start:.3f} s.", ""])
    (args.output / "report.md").write_text("\n".join(report), encoding="utf-8")
    _plot(args.output, days, window_rows)
    _plot_timings(args.output, presentation_timings)
    print(f"Saved {len(window_rows)} operational windows to {args.output.resolve()}", flush=True)
    return 0 if all(row["successful_window_count"] == row["window_count"] for row in summaries) else 1


if __name__ == "__main__":
    raise SystemExit(main())
