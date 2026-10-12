"""Render presentation figures from the synthetic benchmark summary CSV.

Missing quality values remain unavailable; they are never replaced by zero.
Matplotlib is optional and is imported only when figures are requested.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Sequence


PROVENANCE = "Istanze sintetiche — Paper v2; convenzioni di riferimento"
OBJECTIVE_LABEL = "Valore obiettivo (convenzione del paper)"
COUNT_FIELDS = (
    "query_count", "model_count", "tier_count", "run_count",
    "accepted_count", "feasible_count", "optimal_count", "gap_count",
)
VALUE_FIELDS = (
    "time_median_seconds", "time_q1_seconds", "time_q3_seconds",
    "objective_median", "c1_median", "c2_median", "c3_median",
    "c4_median", "c5_median", "gap_median_percent",
    "mean_unmet_fraction_median", "unmet_over_1pct_rate_median",
)
REQUIRED_FIELDS = ("case_id", "family", "method") + COUNT_FIELDS + VALUE_FIELDS
METHOD_COLORS = {"P_DM": "#285A9F", "GH": "#E28B21", "AGH": "#158579"}
METHOD_LABELS = {"P_DM": r"$P_{DM}$ (MILP)", "GH": "GH", "AGH": "AGH"}


@dataclass(frozen=True, slots=True)
class SummaryRow:
    """One method on one case; None denotes an unavailable measurement."""

    case_id: str
    family: str
    method: str
    query_count: int
    model_count: int
    tier_count: int
    run_count: int
    accepted_count: int
    feasible_count: int
    optimal_count: int
    gap_count: int
    time_median_seconds: float | None
    time_q1_seconds: float | None
    time_q3_seconds: float | None
    objective_median: float | None
    c1_median: float | None
    c2_median: float | None
    c3_median: float | None
    c4_median: float | None
    c5_median: float | None
    gap_median_percent: float | None
    mean_unmet_fraction_median: float | None
    unmet_over_1pct_rate_median: float | None


def read_summary(path: Path) -> tuple[SummaryRow, ...]:
    """Read finite CSV measurements without imputing missing observations."""

    rows: list[SummaryRow] = []
    seen: set[tuple[str, str]] = set()
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing = set(REQUIRED_FIELDS) - set(reader.fieldnames or ())
        if missing:
            raise ValueError("Colonne mancanti: " + ", ".join(sorted(missing)))
        for line_number, record in enumerate(reader, start=2):
            try:
                labels = {
                    name: record[name].strip() for name in ("case_id", "family", "method")
                }
                if not all(labels.values()):
                    raise ValueError("case_id, family e method devono essere presenti")
                counts = {name: int(record[name]) for name in COUNT_FIELDS}
                if any(counts[name] <= 0 for name in COUNT_FIELDS[:4]):
                    raise ValueError("dimensioni e run_count devono essere positivi")
                if any(
                    not 0 <= counts[name] <= counts["run_count"]
                    for name in COUNT_FIELDS[4:]
                ):
                    raise ValueError("conteggi di esito fuori da [0, run_count]")
                values = {
                    name: float(record[name]) if record[name].strip() else None
                    for name in VALUE_FIELDS
                }
                if any(value is not None and not math.isfinite(value) for value in values.values()):
                    raise ValueError("le misure devono essere finite o vuote")
                if any(
                    values[name] is not None and values[name] < 0
                    for name in VALUE_FIELDS[:3]
                ):
                    raise ValueError("i tempi devono essere non negativi")
                row = SummaryRow(**labels, **counts, **values)
                key = (row.case_id, row.method)
                if key in seen:
                    raise ValueError("case_id/method duplicati")
                seen.add(key)
                rows.append(row)
            except (TypeError, ValueError, AttributeError) as error:
                raise ValueError(f"Riga CSV {line_number}: {error}") from error
    if not rows:
        raise ValueError("Il CSV non contiene risultati")
    return tuple(rows)


def _methods(rows: Sequence[SummaryRow]) -> tuple[str, ...]:
    found = {row.method for row in rows}
    return tuple(name for name in METHOD_COLORS if name in found) + tuple(
        sorted(found - METHOD_COLORS.keys())
    )


def _color(method: str) -> str:
    return METHOD_COLORS.get(method, "#7B5AA6")


def _label(method: str) -> str:
    return METHOD_LABELS.get(method, method)


def _style_axis(axis) -> None:
    axis.spines[["top", "right"]].set_visible(False)
    axis.set_axisbelow(True)
    axis.grid(axis="y", color="#DFE5EB", linewidth=0.7)
    axis.tick_params(labelsize=9)


def _case_ticks(axis, cases: Sequence[str]) -> None:
    axis.set_xticks(range(len(cases)), cases, rotation=25, ha="right")
    axis.set_xlim(-0.6, len(cases) - 0.4)
    axis.set_xlabel("Istanza sintetica")


def _unavailable(axis, x: float) -> None:
    """Place a missing-value marker in axes coordinates, outside numeric data."""

    axis.plot(
        [x], [0.025], "x", color="#9B3541", markersize=6,
        transform=axis.get_xaxis_transform(), zorder=5,
    )
    axis.annotate(
        "n.d.", (x, 0.025), xycoords=axis.get_xaxis_transform(),
        xytext=(0, 8), textcoords="offset points", ha="center",
        fontsize=7, color="#9B3541",
    )


def _runtime_figure(plt, rows: Sequence[SummaryRow]):
    figure, axis = plt.subplots(figsize=(12, 6.4))
    scaling = [
        row for row in rows
        if row.family == "query_scaling" and row.model_count == 2 and row.tier_count == 2
    ]
    for method in _methods(scaling):
        measured = sorted(
            (row for row in scaling if row.method == method and row.time_median_seconds is not None),
            key=lambda row: row.query_count,
        )
        if not measured:
            continue
        axis.plot(
            [row.query_count for row in measured],
            [row.time_median_seconds for row in measured],
            marker="o", linewidth=2, color=_color(method), label=_label(method),
        )
        intervals = [
            row for row in measured
            if row.time_q1_seconds is not None and row.time_q3_seconds is not None
        ]
        axis.fill_between(
            [row.query_count for row in intervals],
            [row.time_q1_seconds for row in intervals],
            [row.time_q3_seconds for row in intervals], color=_color(method), alpha=0.16,
        )
    if scaling:
        axis.set_xticks(sorted({row.query_count for row in scaling}))
        if axis.lines:
            axis.legend(frameon=False)
    else:
        axis.text(
            0.5, 0.5, "Serie query_scaling con 2 modelli e 2 tier non disponibile",
            transform=axis.transAxes, ha="center",
        )
    axis.set_xlabel("Numero di tipi di query (2 modelli, 2 tier GPU)")
    axis.set_ylabel("Tempo totale di esecuzione [s]")
    axis.set_title("Tempo di esecuzione — mediana e intervallo interquartile", loc="left", pad=16)
    _style_axis(axis)
    figure.text(0.07, 0.025, "Tempi di tutti i tentativi; warm-up escluso. Il grafico copre solo le dimensioni misurate.", fontsize=9)
    return figure


def _quality_figure(plt, rows: Sequence[SummaryRow]):
    cases = tuple(dict.fromkeys(row.case_id for row in rows))
    methods = _methods(rows)
    lookup = {(row.case_id, row.method): row for row in rows}
    figure, axes = plt.subplots(2, 1, figsize=(12, 8.6), sharex=True)
    width = 0.76 / len(methods)
    for method_index, method in enumerate(methods):
        for case_index, case in enumerate(cases):
            position = case_index + (method_index - (len(methods) - 1) / 2) * width
            row = lookup.get((case, method))
            if row is None or row.accepted_count == 0 or row.objective_median is None:
                _unavailable(axes[0], position)
            else:
                axes[0].bar(
                    position, row.objective_median, width * 0.9, color=_color(method),
                    label=_label(method) if case_index == 0 else None,
                )
            if row is None or row.gap_count == 0 or row.gap_median_percent is None:
                _unavailable(axes[1], position)
            else:
                axes[1].plot(position, row.gap_median_percent, "o", color=_color(method), markersize=7)
    # Explicit legend handles also retain methods whose first instance failed.
    axes[0].legend(
        handles=[plt.Line2D([0], [0], color=_color(method), linewidth=8, label=_label(method)) for method in methods],
        frameon=False, ncols=len(methods),
    )
    axes[0].set_title("Qualità delle soluzioni accettate", loc="left", pad=15)
    axes[0].set_ylabel(OBJECTIVE_LABEL)
    axes[1].set_ylabel("Gap rispetto a P_DM ottimo [%]")
    axes[1].axhline(0, color="#526070", linewidth=0.8, linestyle="--")
    available_gaps = [
        row.gap_median_percent for row in rows
        if row.gap_count > 0 and row.gap_median_percent is not None
    ]
    small_gaps = available_gaps and all(-0.1 <= value <= 0.1 for value in available_gaps)
    if small_gaps:
        axes[1].set_ylim(-0.1, 0.1)
    for axis in axes:
        _style_axis(axis)
    _case_ticks(axes[1], cases)
    figure.text(0.07, 0.045, "Mediane; gap solo con P_DM accettato e ottimo nello stesso caso e ripetizione. × n.d. = non disponibile.", fontsize=9)
    if small_gaps:
        figure.text(0.07, 0.025, "Scala del gap: ±0,1%; i valori numerici restano invariati.", fontsize=9)
    return figure


def _components_figure(plt, rows: Sequence[SummaryRow]):
    figure, axis = plt.subplots(figsize=(12, 6.4))
    component_colors = ("#285A9F", "#6996CE", "#158579", "#E4A442", "#BA5865")
    component_labels = ("C1 · GPU", "C2 · modelli", "C3 · dati", "C4 · ritardo", "C5 · domanda non servita")
    methods = _methods(rows)
    cases = tuple(dict.fromkeys(row.case_id for row in rows))
    lookup = {(row.case_id, row.method): row for row in rows}
    labels: list[str] = []
    legend_added = False
    for case in cases:
        for method in methods:
            position = len(labels)
            labels.append(f"{case}\n{method}")
            row = lookup.get((case, method))
            components = (
                (row.c1_median, row.c2_median, row.c3_median, row.c4_median, row.c5_median)
                if row is not None else (None,) * 5
            )
            if row is None or row.accepted_count == 0 or any(value is None for value in components):
                _unavailable(axis, position)
                continue
            # Separate positive/negative stacks preserve signed component values.
            positive = negative = 0.0
            for value, color, label in zip(components, component_colors, component_labels, strict=True):
                bottom = positive if value >= 0 else negative
                axis.bar(position, value, 0.76, bottom=bottom, color=color, label=label if not legend_added else None)
                if value >= 0:
                    positive += value
                else:
                    negative += value
            legend_added = True
    axis.set_xticks(range(len(labels)), labels, rotation=55, ha="right", fontsize=8)
    axis.set_ylabel(OBJECTIVE_LABEL)
    axis.set_title("Componenti dell'obiettivo — mediane delle esecuzioni accettate", loc="left", pad=16)
    if legend_added:
        axis.legend(frameon=False, ncols=3, fontsize=9)
    _style_axis(axis)
    figure.text(0.07, 0.025, "La somma delle mediane delle componenti può differire dalla mediana del totale. × n.d. = non disponibile.", fontsize=9)
    return figure


def _success_figure(plt, rows: Sequence[SummaryRow]):
    figure, axis = plt.subplots(figsize=(12, 6.4))
    labels = [f"{row.case_id}\n{row.method}" for row in rows]
    for position, row in enumerate(rows):
        accepted = 100 * row.accepted_count / row.run_count
        feasible = 100 * row.feasible_count / row.run_count
        color = _color(row.method)
        axis.bar(position - 0.18, accepted, 0.34, color=color)
        axis.bar(position + 0.18, feasible, 0.34, facecolor="white", edgecolor=color, hatch="//")
        axis.text(position, max(accepted, feasible) + 2, f"{row.accepted_count}/{row.run_count}", ha="center", fontsize=8)
    axis.set_xticks(range(len(labels)), labels, rotation=55, ha="right", fontsize=8)
    axis.set_ylim(0, 115)
    axis.set_yticks((0, 25, 50, 75, 100))
    axis.set_ylabel("Esecuzioni [%]")
    axis.set_title("Completamento e validazione indipendente", loc="left", pad=16)
    axis.legend(
        handles=[
            plt.Rectangle((0, 0), 1, 1, color="#526070", label="Accettate secondo il criterio del metodo"),
            plt.Rectangle((0, 0), 1, 1, facecolor="white", edgecolor="#526070", hatch="//", label="Fattibili secondo il validatore"),
        ], frameon=False, ncols=2, fontsize=9,
    )
    _style_axis(axis)
    figure.text(0.07, 0.025, "Denominatore: tutti i tentativi misurati, inclusi i fallimenti. Etichette: accettate / tentativi.", fontsize=9)
    return figure


def render_figures(
    rows: Sequence[SummaryRow], output_dir: Path, paper_version: str = "v2",
) -> tuple[Path, ...]:
    """Save four PNG/SVG figures, preserving the summary's failure evidence."""

    if not rows:
        raise ValueError("Non ci sono risultati da rappresentare")
    if paper_version not in ("v1", "v2"):
        raise ValueError("paper_version deve essere v1 o v2")
    provenance = f"Istanze sintetiche — Paper {paper_version}; convenzioni di riferimento"
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as error:
        raise RuntimeError("Matplotlib non disponibile. Installa: pip install -e '.[plots]'") from error
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    with plt.rc_context({"font.family": "DejaVu Sans", "font.size": 11, "svg.fonttype": "none"}):
        for name, factory in (
            ("runtime_scaling", _runtime_figure),
            ("objective_and_gap", _quality_figure),
            ("objective_components", _components_figure),
            ("validation_success", _success_figure),
        ):
            figure = factory(plt, rows)
            figure.suptitle(provenance, fontsize=11, color="#526070", y=0.98)
            figure.tight_layout(rect=(0.02, 0.075, 0.98, 0.94))
            for extension in ("png", "svg"):
                path = output_dir / f"{name}.{extension}"
                figure.savefig(path, dpi=160, facecolor="white", metadata={"Title": provenance})
                outputs.append(path)
            plt.close(figure)
    return tuple(outputs)


def _resolve_paper_version(input_path: Path, requested: str | None) -> str:
    """Honor persisted provenance; default to v2 only without a manifest."""

    manifest_path = input_path.with_name("manifest.json")
    if not manifest_path.exists():
        return requested or "v2"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    try:
        version = manifest["config"]["paper_version"]
    except (KeyError, TypeError) as error:
        raise ValueError("manifest.json non contiene config.paper_version") from error
    if version not in ("v1", "v2"):
        raise ValueError("Versione del paper non valida in manifest.json")
    if requested is not None and requested != version:
        raise ValueError("--paper-version contraddice la versione registrata in manifest.json")
    return version


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("results/synthetic_benchmark/summary.csv"))
    parser.add_argument("--output", type=Path, default=Path("results/synthetic_benchmark/figures"))
    parser.add_argument(
        "--paper-version", choices=("v1", "v2"),
        help="Versione del paper: letta da manifest.json, altrimenti v2; le contraddizioni sono rifiutate",
    )
    args = parser.parse_args(argv)
    try:
        version = _resolve_paper_version(args.input, args.paper_version)
        outputs = render_figures(read_summary(args.input), args.output, version)
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(1, f"Errore: {error}\n")
    print(f"Generati {len(outputs)} file in {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
