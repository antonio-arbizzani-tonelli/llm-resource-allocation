"""Summarize saved Stage-1/Azure scaling evidence without rerunning algorithms.

Missing objectives and failed jobs remain visible. Full-day Azure runs and
runtime-gated pilot runs are reported separately. Matplotlib is loaded only
when figures are requested.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
from pathlib import Path
from statistics import median
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
COLORS = {"P_DM": "#285A9F", "GH": "#E28B21", "AGH": "#158579"}
FAMILIES = {
    "nominal_joint": "Crescita congiunta, carico nominale",
    "query_only": "Più tipi di query, alternative fisse",
    "options_only": "Più alternative, tipi di query fissi",
    "loaded_joint": "Crescita congiunta, carico elevato",
}


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def number(value) -> float | None:
    """Accept only finite recorded numbers; a blank is not a zero."""
    if value is None or value == "":
        return None
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"Misura non finita: {value!r}")
    return result


def boolean(value) -> bool:
    return value is True or str(value).lower() == "true"


def fmt(value, precision: int = 6) -> str:
    parsed = number(value)
    return "n.d." if parsed is None else f"{parsed:.{precision}g}"


def percent(value) -> str:
    parsed = number(value)
    return "n.d." if parsed is None else f"{100 * parsed:.3f}%"


def method(row: dict) -> str:
    return row["method"].upper()


def dimensions(row: dict) -> tuple[int, int, int]:
    values = row.get("dimensions")
    if values is not None:
        return tuple(int(value) for value in values)
    return tuple(int(row[key]) for key in ("query_count", "model_count", "tier_count"))


def dim_label(row: dict) -> str:
    return "×".join(str(value) for value in dimensions(row))


def is_pilot(row: dict) -> bool:
    return boolean(row.get("pilot")) or boolean(row.get("pilot_execution")) or row.get("job_id", "").endswith("_pilot")


def markdown_table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> list[str]:
    return ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"] + [
        "| " + " | ".join(str(value).replace("|", "/").replace("\n", " ") for value in row) + " |"
        for row in rows
    ]


def failure_reason(row: dict) -> str:
    evidence = [row.get("error_type"), row.get("error_message"), row.get("violated_families")]
    reason = "; ".join(str(value) for value in evidence if value)
    return reason or str(row.get("failure_message") or row.get("failure") or row.get("status") or "Vedi evidence.jsonl")


def azure_groups(rows: Sequence[dict]) -> list[dict]:
    """Pool full runs only; incomplete quality evidence is never imputed."""
    groups: dict[tuple[str, str, str], list[dict]] = {}
    for row in rows:
        groups.setdefault((row["case_id"], method(row), row["variant"]), []).append(row)
    pooled = []
    for (case_id, name, variant), selected in groups.items():
        windows = sum(number(row.get("window_count")) or 0 for row in selected)
        successful = [number(row.get("successful_window_count")) for row in selected]
        success = sum(successful) / windows if windows and all(value is not None for value in successful) else None
        costs = [number(row.get("sum_window_model_cost")) for row in selected]
        violations = [number(row.get("violation_rate")) for row in selected]
        all_valid = success == 1 and all(value is not None for value in costs)
        weighted_violation = (
            sum(value * number(row["window_count"]) for value, row in zip(violations, selected, strict=True)) / windows
            if all_valid and all(value is not None for value in violations) else None
        )
        times = [number(row.get("replay_time_seconds")) for row in selected]
        pooled.append({
            **selected[0], "case_id": case_id, "method": name, "variant": variant,
            "job_count": len(selected), "success_fraction": success,
            "mean_cost": sum(costs) / windows if all_valid else None,
            "violation_percent": 100 * weighted_violation if weighted_violation is not None else None,
            "median_replay_seconds": median(times) if all(value is not None for value in times) else None,
        })
    return pooled


def _style(axis) -> None:
    axis.spines[["top", "right"]].set_visible(False)
    axis.grid(axis="y", color="#DFE5EB", linewidth=0.7)
    axis.set_axisbelow(True)


def _line(axis, selected: Sequence[dict], cases: Sequence[dict], field: str, label: str, color: str, linestyle: str = "-") -> None:
    lookup = {row["case_id"]: row for row in selected}
    values = [number(lookup.get(case["case_id"], {}).get(field)) for case in cases]
    axis.plot(range(len(cases)), [float("nan") if value is None else value for value in values],
              marker="o", linewidth=1.7, color=color, linestyle=linestyle, label=label)
    # Missing-value markers are positioned outside the data coordinate system.
    missing = [index for index, value in enumerate(values) if value is None]
    if missing:
        axis.plot(missing, [0.03] * len(missing), "x", color=color,
                  transform=axis.get_xaxis_transform(), markersize=6)


def render_figures(stage1: Sequence[dict], azure: Sequence[dict], output: Path) -> list[Path]:
    os.environ.setdefault("MPLCONFIGDIR", str(output / "matplotlib_cache"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    output.mkdir(parents=True, exist_ok=True)
    outputs = []
    with plt.rc_context({"font.family": "DejaVu Sans", "font.size": 10, "svg.fonttype": "none"}):
        for family, title in FAMILIES.items():
            selected = [row for row in stage1 if row["family"] == family]
            if not selected:
                continue
            cases = sorted({row["case_id"]: row for row in selected}.values(), key=dimensions)
            figure, axes = plt.subplots(2, 2, figsize=(11.5, 7.3), layout="constrained")
            for name, color in COLORS.items():
                measured = [row for row in selected if method(row) == name]
                for axis, field in zip(axes.flat, ("objective_median", "time_median_seconds", "gap_median_percent", "accepted_percent"), strict=True):
                    data = [{**row, "accepted_percent": 100 * int(row["accepted_count"]) / int(row["run_count"])} for row in measured]
                    _line(axis, data, cases, field, name, color)
            labels = ("Obiettivo mediano accettato [punteggio modello]", "Tempo totale mediano [s]",
                      "Gap mediano da P_DM ottimo [%]", "Tentativi accettati [%]")
            for axis, label in zip(axes.flat, labels, strict=True):
                _style(axis)
                axis.set_ylabel(label)
                axis.set_xticks(range(len(cases)), [dim_label(row) for row in cases])
                axis.set_xlabel("Dimensioni I × J × K")
            positive_times = [number(row["time_median_seconds"]) for row in selected]
            if all(value is not None and value > 0 for value in positive_times):
                axes[0, 1].set_yscale("log")
            axes[1, 0].axhline(0, color="#526070", linewidth=0.7, linestyle="--")
            axes[1, 1].set_ylim(-5, 105)
            axes[0, 0].legend(frameon=False, ncols=3)
            figure.suptitle(f"Stage 1 — {title}\nIstanze sintetiche; × = misura non disponibile", fontsize=12)
            for extension in ("png", "svg"):
                path = output / f"stage1_{family}.{extension}"
                figure.savefig(path, dpi=180, facecolor="white")
                outputs.append(path)
            plt.close(figure)

        pooled = azure_groups([row for row in azure if not is_pilot(row)])
        for family, title in FAMILIES.items():
            selected = [row for row in pooled if row["family"] == family]
            if not selected:
                continue
            cases = sorted({row["case_id"]: row for row in selected}.values(), key=dimensions)
            figure, axes = plt.subplots(2, 2, figsize=(11.5, 7.6), layout="constrained")
            for name, color in COLORS.items():
                for variant, linestyle in (("static", "-"), ("rolling", "--")):
                    measured = [row for row in selected if method(row) == name and row["variant"] == variant]
                    if not measured:
                        continue
                    for axis, field in zip(axes.flat, ("mean_cost", "violation_percent", "median_replay_seconds", "success_percent"), strict=True):
                        data = [{**row, "success_percent": 100 * row["success_fraction"] if row["success_fraction"] is not None else None} for row in measured]
                        _line(axis, data, cases, field, f"{name} {variant}", color, linestyle)
            labels = ("Costo medio finestra [punteggio modello]", "Query con u > 1% [%]",
                      "Tempo mediano del replay per giorno [s]", "Finestre operative valide [%]")
            for axis, label in zip(axes.flat, labels, strict=True):
                _style(axis)
                axis.set_ylabel(label)
                axis.set_xticks(range(len(cases)), [dim_label(row) for row in cases])
                axis.set_xlabel("Dimensioni I × J × K")
            axes[1, 1].set_ylim(-5, 105)
            axes[0, 0].legend(frameon=False, ncols=2, fontsize=8)
            figure.suptitle(f"Azure — {title}\nSolo replay completi; × = qualità non disponibile", fontsize=12)
            for extension in ("png", "svg"):
                path = output / f"azure_{family}.{extension}"
                figure.savefig(path, dpi=180, facecolor="white")
                outputs.append(path)
            plt.close(figure)
    return outputs


def report_lines(config: dict, manifest: dict, stage1: Sequence[dict], runs: Sequence[dict], azure: Sequence[dict], figures: Sequence[Path]) -> list[str]:
    measured = [row for row in runs if not boolean(row.get("is_warmup"))]
    full = [row for row in azure if not is_pilot(row)]
    pilots = [row for row in azure if is_pilot(row)]
    lines = [
        "# Effetto della dimensione delle istanze — Stage 1 e replay Azure", "",
        "Questa campagna confronta P_DM, GH e AGH sugli stessi input salvati. La forma temporale Azure è reale; "
        "coefficienti, carichi assoluti e caratteristiche delle istanze sono sintetici. Non è una replica numerica dei risultati del paper.", "",
        "## Cosa cambia tra le istanze", "",
        "I × J × K indica tipi di query × modelli × tier GPU. Crescita congiunta e crescita del solo I cambiano il problema "
        "da risolvere: un costo maggiore può dipendere dalla domanda aggiunta, e non misura da solo un peggioramento dell'algoritmo. "
        "La famiglia options_only mantiene I e la domanda e aggiunge alternative annidate: in questo confronto controllato "
        "l'ottimo non dovrebbe aumentare, salvo differenze nei vincoli/input che rompano l'annidamento.", "",
        "Il carico elevato è dichiarato nella configurazione prima del confronto e non è calibrato per avvicinare una tabella del paper. "
        "Tutti i costi sono punteggi del modello con le convenzioni scientifiche del riferimento; non sono USD/giorno. "
        "La media di finestra e la somma dei punteggi del replay mantengono l'orizzonte sintetico dell'istanza.", "",
        "Configurazione integrale: [config.json](config.json); provenienza e inventario: [manifest.json](manifest.json).", "",
    ]
    specs = config.get("case_specs", [])
    if specs:
        lines += markdown_table(("Famiglia", "Caso", "I×J×K", "Moltiplicatore carico", "SLO", "Budget"), [
            (spec["family"], spec["case_id"], dim_label(spec), fmt(spec.get("load_multiplier")),
             fmt(spec.get("delay_slo_multiplier")), fmt(spec.get("budget_multiplier"))) for spec in specs
        ]) + [""]
    if stage1:
        count = sum(int(row["run_count"]) for row in stage1)
        accepted = sum(int(row["accepted_count"]) for row in stage1)
        optimal = sum(int(row["optimal_count"]) for row in stage1 if method(row) == "P_DM")
        lines += ["## Stage 1: qualità, fallimenti e tempi", "",
                  f"**{accepted}/{count} tentativi misurati accettati**; {count - accepted} respinti. "
                  f"P_DM: {optimal} tentativi con ottimalità riportata dal solver. I warm-up sono esclusi.", "",
                  "Le mediane dell'obiettivo usano solo gli esiti accettati; i tempi comprendono tutti i tentativi. "
                  "Il gap usa solo coppie dello stesso caso/ripetizione/seed con P_DM accettato e solver-reported optimal. "
                  "Il denominatore delle coppie valide è mostrato: un gap assente non equivale a zero e un gap nullo su questi casi "
                  "non dimostra l'ottimalità generale delle euristiche.", ""]
        lines += markdown_table(("Famiglia", "I×J×K", "Metodo", "Accettati", "Fattibili", "Ottimi solver", "Obiettivo mediano", "Gap [%] / coppie", "Tempo mediano [s]"), [
            (row["family"], dim_label(row), method(row), f"{row['accepted_count']}/{row['run_count']}",
             f"{row['feasible_count']}/{row['run_count']}", row["optimal_count"], fmt(row["objective_median"]),
             f"{fmt(row['gap_median_percent'])} / {row['gap_count']}", fmt(row["time_median_seconds"]))
            for row in stage1
        ]) + [""]
        lines += ["### Variazioni osservate nella crescita congiunta", ""]
        for family in ("nominal_joint", "loaded_joint"):
            for name in COLORS:
                selected = sorted([row for row in stage1 if row["family"] == family and method(row) == name], key=dimensions)
                if len(selected) < 2:
                    continue
                first, last = selected[0], selected[-1]
                lines.append(f"- {family}, {name}: da {dim_label(first)} a {dim_label(last)}, obiettivo mediano "
                             f"{fmt(first['objective_median'])} → {fmt(last['objective_median'])}; tempo mediano "
                             f"{fmt(first['time_median_seconds'])} → {fmt(last['time_median_seconds'])} s; "
                             f"accettati {first['accepted_count']}/{first['run_count']} → {last['accepted_count']}/{last['run_count']}.")
        lines += [""]
        failures = [row for row in measured if not boolean(row.get("accepted"))]
        if failures:
            lines += ["### Tentativi Stage 1 respinti", ""]
            lines += markdown_table(("Caso", "Metodo", "Seed", "Motivo / stato solver"), [
                (row["case_id"], method(row), row.get("random_seed", row.get("seed", "n.d.")),
                 failure_reason(row))
                for row in failures
            ]) + [""]
        lines += ["Dati completi: [summary.csv](stage1/summary.csv), [runs.csv](stage1/runs.csv), "
                  "[metriche query](stage1/query_metrics.csv), [evidenza](stage1/evidence.jsonl).", ""]
    else:
        lines += ["Stage 1: riepilogo non ancora disponibile; nessun risultato è imputato.", ""]

    lines += ["## Azure: replay completi", "",
              "Costo e violazioni sono disponibili solo quando l'aggregato del replay è completo secondo il contratto "
              "del produttore. Il conteggio delle finestre e dei tentativi respinti resta visibile anche quando l'aggregato "
              "è nullo. Static costruisce una sola allocazione; rolling ricostruisce e confronta candidato/incumbent "
              "sulla previsione causale, quindi i tempi totali includono un numero diverso di operazioni.", ""]
    if full:
        lines += markdown_table(("Giorno", "Famiglia / I×J×K", "Metodo", "Variante", "Seed", "Finestre valide", "Costo medio", "Violazioni", "Stage 1 accettati", "Replay [s]"), [
            (row["date"], f"{row['family']} / {dim_label(row)}", method(row), row["variant"], row.get("seed", "n.d."),
             f"{fmt(row.get('successful_window_count'), 8)}/{row['window_count']}", fmt(row.get("mean_window_model_cost")),
             percent(row.get("violation_rate")), f"{fmt(row.get('stage1_accepted_count'), 8)}/{fmt(row.get('stage1_attempt_count'), 8)}",
             fmt(row.get("replay_time_seconds"))) for row in full
        ]) + [""]
        available = [row for row in full if number(row.get("successful_window_count")) is not None]
        success = sum(int(row["successful_window_count"]) for row in available)
        windows = sum(int(row["window_count"]) for row in available)
        lines += [f"Replay con conteggio disponibile: **{success}/{windows} finestre operative valide** "
                  f"su {len(available)}/{len(full)} job. I {windows - success} fallimenti operativi sono compresi nel denominatore.", ""]
        lines += ["### Scomposizione dei tempi dei replay completi", ""]
        lines += markdown_table(("Job", "Stage 1 totale [s]", "Stage 1 mediana [s]", "LP previsione [s]", "LP operativi [s]", "Orchestrazione [s]"), [
            (row["job_id"], fmt(row.get("stage1_total_seconds")), fmt(row.get("stage1_median_seconds")),
             fmt(row.get("forecast_stage2_total_seconds")), fmt(row.get("operational_stage2_total_seconds")),
             fmt(row.get("orchestration_seconds"))) for row in full
        ]) + [""]
    else:
        lines += ["Nessun riepilogo di replay completo disponibile.", ""]
    if pilots:
        lines += ["## Pilot rolling e limite di durata", "",
                  "Queste misure riguardano soltanto il prefisso dichiarato del giorno. Un pilot trattenuto dal limite "
                  "di durata non è un replay di 24 ore e non entra negli aggregati o grafici dei giorni completi. "
                  "La proiezione lineare di durata serve a decidere il budget di esecuzione; non è un tempo completo misurato.", ""]
        lines += markdown_table(("Job", "I×J×K", "Metodo", "Finestre valide", "Costo medio prefisso", "Violazioni prefisso", "Tempo pilot [s]", "Gate"), [
            (row["job_id"], dim_label(row), method(row), f"{fmt(row.get('successful_window_count'), 8)}/{row['window_count']}",
             fmt(row.get("mean_window_model_cost")), percent(row.get("violation_rate")), fmt(row.get("replay_time_seconds")),
             str(row.get("runtime_gate", "n.d."))) for row in pilots
        ]) + [""]
    errors = [row for row in azure if row.get("error") or row.get("exception")]
    if errors:
        lines += ["## Job con errore", ""]
        lines += markdown_table(("Job", "Errore"), [(row["job_id"], str(row.get("error") or row.get("exception"))) for row in errors]) + [""]
    lines += ["Ogni sottocartella [azure/](azure/) conserva finestre, metriche per query, tempi dei tentativi Stage 1, "
              "tempi degli LP ed evidenza scientifica. Nessun fallimento è sostituito con una soluzione riparata.", ""]
    if figures:
        lines += ["## Figure", ""]
        for path in figures:
            if path.suffix == ".png":
                lines += [f"![{path.stem}](figures/{path.name})", ""]
    lines += ["## Interpretazione e limiti", "",
              "Le dimensioni più grandi rendono questo confronto più informativo rispetto al solo caso 2×2×2, "
              "ma le conclusioni restano limitate a queste famiglie e ai seed registrati. Il carico elevato può far "
              "emergere domanda non servita o fallimenti: vanno confrontati insieme a costo e durata, senza selezionare "
              "soltanto gli esiti favorevoli.", "",
              "Per riprodurre i valori quantitativi del paper mancano ancora la calibrazione e gli input esatti degli autori. "
              "Questa campagna misura la sensibilità alle dimensioni e al carico delle istanze sintetiche, non la qualità "
              "delle risposte dei modelli né la latenza di serving reale.", ""]
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "results/scaling_2026-10-09")
    parser.add_argument("--no-plots", action="store_true")
    args = parser.parse_args(argv)
    config = read_json(args.input / "config.json")
    manifest = read_json(args.input / "manifest.json")
    stage1 = read_csv(args.input / "stage1/summary.csv")
    runs = read_csv(args.input / "stage1/runs.csv")
    azure = [read_json(path) for path in sorted((args.input / "azure").glob("*/summary.json"))]
    figures = [] if args.no_plots else render_figures(stage1, azure, args.input / "figures")
    report = args.input / "report.md"
    report.write_text("\n".join(report_lines(config, manifest, stage1, runs, azure, figures)), encoding="utf-8")
    print(f"Report: {report.resolve()}; {len(stage1)} righe Stage 1, {len(azure)} job Azure, {len(figures)} figure.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
