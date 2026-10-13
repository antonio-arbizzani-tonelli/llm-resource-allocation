"""Create standalone scientific figures from verified timing analysis."""

import argparse
import json
from pathlib import Path


def make_plots(report, output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    output.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "svg.hashsalt": "allocation-performance-2026-10-13"})

    def save(fig, name):
        fig.tight_layout()
        fig.savefig(output / (name + ".png"), dpi=180)
        fig.savefig(output / (name + ".svg"), metadata={"Date": None})
        plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(10, 4.1))
    for axis, method in zip(axes, ("gh", "agh"), strict=True):
        rows = sorted((row for row in report["serial"] if row["method"] == method and row["shape"][1:] == [4, 4]),
                      key=lambda row: row["shape"][0])
        if rows:
            x = [row["shape"][0] for row in rows]
            y = [row["cpp_core"]["median_seconds"] for row in rows]
            errors = [[row["cpp_core"]["median_seconds"] - row["cpp_core"]["q1_seconds"] for row in rows],
                      [row["cpp_core"]["q3_seconds"] - row["cpp_core"]["median_seconds"] for row in rows]]
            axis.errorbar(x, y, yerr=errors, marker="o", capsize=4, color="#136c83")
            supplemental = [row for row in rows if row["verification_mode"] == "independent_final_decision"]
            if supplemental:
                axis.plot([row["shape"][0] for row in supplemental],
                          [row["cpp_core"]["median_seconds"] for row in supplemental],
                          linestyle="none", marker="D", markersize=8, markerfacecolor="white",
                          markeredgecolor="#136c83", zorder=4, label="Final decision validated")
                axis.legend(fontsize=8)
            axis.set_xscale("log", base=2)
            axis.set_yscale("log")
            axis.set_xticks(x, labels=[str(value) for value in x])
        axis.set(title=method.upper() + ": fixed 4-model / 4-tier menu", xlabel="Query count", ylabel="C++ core median (seconds)")
        axis.grid(alpha=0.2)
    fig.suptitle("Local synthetic allocation timing; bars span Q1–Q3", fontsize=11)
    save(fig, "query_scaling")

    controls = sorted({tuple(row["shape"]) for row in report["serial"] if row["shape"][1:] != [4, 4]})
    if controls:
        fig, axis = plt.subplots(figsize=(8.5, 4))
        for offset, method, color in ((-0.18, "gh", "#136c83"), (0.18, "agh", "#c47424")):
            lookup = {tuple(row["shape"]): row for row in report["serial"] if row["method"] == method}
            available = [(index, shape) for index, shape in enumerate(controls) if shape in lookup and (shape[0], 4, 4) in lookup]
            bars = axis.bar([index + offset for index, _ in available],
                     [lookup[shape]["cpp_core"]["median_seconds"] / lookup[(shape[0], 4, 4)]["cpp_core"]["median_seconds"]
                      for _, shape in available], width=0.34, label=method.upper(), color=color)
            for bar, (_, shape) in zip(bars, available, strict=True):
                if lookup[shape]["verification_mode"] == "independent_final_decision":
                    bar.set_hatch("//")
        axis.axhline(1, color="gray", linestyle=":", linewidth=1)
        axis.set_xticks(range(len(controls)), labels=["x".join(map(str, shape)) for shape in controls])
        axis.set(xlabel="Queries x model alternatives x tier alternatives",
                 ylabel="Median C++ time / same-query 4x4 baseline", title="Effect of a larger search menu on the same query count")
        axis.legend()
        axis.grid(axis="y", alpha=0.2)
        save(fig, "menu_scaling")

    for metric, name, title in (("median_core_speedup", "openmp_core_scaling", "OpenMP independent-case core speedup"),
                                ("median_process_speedup", "openmp_process_scaling", "Complete invocation speedup, including transport/startup")):
        if not report["openmp"]:
            continue
        fig, axes = plt.subplots(1, 2, figsize=(11, 4.3))
        colors = {32: "#136c83", 64: "#c47424", 128: "#6f5291"}
        for axis, workload in zip(axes, ("uniform", "mixed"), strict=True):
            for size in sorted({row["batch_size"] for row in report["openmp"]}):
                for schedule, line in (("static", "--"), ("dynamic", "-")):
                    rows = sorted((row for row in report["openmp"] if row["workload"] == workload
                                   and row["batch_size"] == size and row["schedule"] == schedule),
                                  key=lambda row: row["actual_threads"])
                    axis.plot([row["actual_threads"] for row in rows], [row[metric] for row in rows],
                              line, marker="o", color=colors.get(size), label=f"{size} cases, {schedule}")
            if metric == "median_core_speedup":
                axis.plot([1, 8], [1, 8], ":", color="gray", label="Ideal linear")
            axis.set(title=workload.capitalize(), xlabel="Observed team size", ylabel="Serial median / candidate median")
            axis.set_xticks([1, 2, 4, 8])
            axis.grid(alpha=0.2)
        axes[1].legend(fontsize=8, loc="upper left")
        fig.suptitle(title + "; same-binary serial baseline", fontsize=11)
        save(fig, name)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    make_plots(json.loads(args.analysis.read_text(encoding="utf-8")), args.output)
