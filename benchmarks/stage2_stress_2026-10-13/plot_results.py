"""Render recorded counts, paired costs and rejected-objective diagnostics."""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

DATASET = Path(__file__).resolve().parent
TEAL, ORANGE, GRAY = "#176B78", "#DC8A43", "#87939A"


def save_figure(figure, name):
    destination = DATASET / "plots"
    destination.mkdir(exist_ok=True)
    figure.savefig(destination / f"{name}.png", dpi=180, bbox_inches="tight")
    figure.savefig(destination / f"{name}.svg", bbox_inches="tight")
    plt.close(figure)


def main():
    report = json.loads((DATASET / "analysis/analysis.json").read_text())
    diagnostics = json.loads((DATASET / "analysis/numerical_diagnostics.json").read_text())
    overall = report["overall"]
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "svg.hashsalt": "stage2-recorded-campaign"})

    figure, axis = plt.subplots(figsize=(8.5, 3.9))
    statuses = overall["stage2_status_counts"]
    values = [statuses["success"], statuses["solver_no_usable_solution"], statuses["objective_inconsistent"]]
    axis.barh(["Scientifically usable", "Solver infeasible", "Objective disagreement"], values,
              color=[TEAL, GRAY, ORANGE], height=0.58)
    for index, value in enumerate(values):
        axis.text(value + 12, index, f"{value:,}", va="center", fontweight="bold")
    axis.invert_yaxis()
    axis.set_xlim(0, max(values) * 1.15)
    axis.set_xlabel("Operational scenarios (1,850 attempted)")
    axis.set_title("Completed execution does not imply accepted decisions", loc="left", pad=18)
    figure.text(0.01, -0.02, "40 completed workers • 37 accepted sources • 150 scenarios skipped after rejected sources", color="#505A61")
    figure.tight_layout()
    save_figure(figure, "outcomes")

    figure, (recovery_axis, cost_axis) = plt.subplots(1, 2, figsize=(9.8, 4.1))
    failures = overall["frozen_infeasible_scenarios"]
    recovered = overall["recovered_scenarios"]
    recovery_axis.barh(["Frozen-routing failures"], [recovered], color=TEAL, label="Recovered and usable")
    recovery_axis.barh(["Frozen-routing failures"], [failures - recovered], left=[recovered], color=GRAY, label="Not usable after adaptation")
    recovery_axis.set_xlim(0, failures * 1.08)
    recovery_axis.set_xlabel("Scenarios")
    recovery_axis.set_title(f"Recovery: {recovered}/{failures}\n{100 * recovered / failures:.2f}% of frozen failures", loc="left")
    recovery_axis.text(recovered / 2, 0, str(recovered), color="white", va="center", ha="center", fontweight="bold")
    recovery_axis.text(recovered + (failures - recovered) / 2, 0, str(failures - recovered), color="white", va="center", ha="center")
    recovery_axis.legend(loc="upper left", bbox_to_anchor=(0, -0.20), frameon=False, fontsize=8)
    ratio = overall["paired_adapted_operational_cost_sum_usd"] / overall["paired_frozen_operational_cost_sum_usd"]
    cost_axis.bar(["Frozen", "Adapted"], [100, 100 * ratio], color=[GRAY, TEAL], width=0.6)
    for index, value in enumerate([100, 100 * ratio]):
        cost_axis.text(index, value + 2, f"{value:.2f}", ha="center")
    cost_axis.set_ylim(0, 118)
    cost_axis.set_ylabel("Sum of modeled C4+C5 (frozen = 100)")
    cost_axis.set_title(f"Paired cost reduction: {100 * (1 - ratio):.2f}%\n390 scenarios with both decisions usable", loc="left")
    figure.text(0.01, -0.03, "Deterministic synthetic comparisons; no cost saving assigned to infeasible baselines or rejected decisions.", fontsize=9, color="#505A61")
    figure.tight_layout(w_pad=3)
    save_figure(figure, "recovery_and_cost")

    figure, axis = plt.subplots(figsize=(8.7, 4.2))
    records = diagnostics["records"]
    axis.scatter([row["independent_objective"] for row in records],
                 [row["absolute_difference"] for row in records], s=28, alpha=0.5,
                 color=ORANGE, label="204 feasible decisions rejected for objective disagreement")
    axis.axhline(diagnostics["absolute_tolerance"], color=TEAL, linestyle="--", linewidth=1.7,
                 label="Unchanged absolute acceptance threshold: 1e-8 USD")
    axis.set_xscale("log")
    axis.set_yscale("log")
    axis.set_xlabel("Independently recomputed C4+C5 (modeled USD)")
    axis.set_ylabel("Absolute solver/reference difference (USD)")
    axis.set_title("One to three floating-point spacings exceed the absolute threshold", loc="left", pad=16)
    axis.legend(loc="upper left", frameon=False, fontsize=8)
    axis.set_ylim(7e-9, 4e-7)
    figure.text(0.01, -0.02, f"Maximum relative difference: {diagnostics['max_relative_difference']:.3e} • Rejected metrics remain unavailable", color="#505A61")
    figure.tight_layout()
    save_figure(figure, "objective_roundoff")
    print("Rendered three recorded Stage-2 figures (PNG/SVG)")


if __name__ == "__main__":
    main()
