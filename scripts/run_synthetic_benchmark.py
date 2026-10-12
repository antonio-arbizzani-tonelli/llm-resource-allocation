"""CLI for shared-instance Stage-1 synthetic benchmarks (no paper data)."""

import argparse
import json
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def capture_source_snapshot(output: Path, repository_root: Path, config_text: str) -> Path:
    """Capture the exact importable source before loading scientific modules."""
    snapshot = output / "source_snapshot" / uuid4().hex
    for directory in ("src", "scripts"):
        for source in sorted((repository_root / directory).rglob("*.py")):
            target = snapshot / source.relative_to(repository_root)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
    config_path = snapshot / "configs/synthetic_benchmark.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(config_text, encoding="utf-8")
    return snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/synthetic_benchmark.json")
    parser.add_argument("--output", type=Path, default=ROOT / "results/synthetic_benchmark")
    args = parser.parse_args()
    config_text = args.config.read_text(encoding="utf-8")
    snapshot = capture_source_snapshot(args.output, ROOT, config_text)
    sys.path.insert(0, str(snapshot / "src"))
    from llm_resource_allocation.data.synthetic_benchmark_instances import make_synthetic_benchmark_cases
    from llm_resource_allocation.experiments.synthetic_benchmark import (
        SyntheticBenchmarkConfig, run_synthetic_benchmark, write_benchmark_results,
    )
    from llm_resource_allocation.math.objective import PaperVersion
    from llm_resource_allocation.optimization.solver import SolverBackend

    values = json.loads(config_text)
    values["backend"] = SolverBackend(values["backend"])
    values["paper_version"] = PaperVersion(values["paper_version"])
    config = SyntheticBenchmarkConfig(**values)
    cases = make_synthetic_benchmark_cases(config.query_counts)
    runs = run_synthetic_benchmark(config, cases, progress=lambda text: print(text, flush=True))
    summary = write_benchmark_results(args.output, config, cases, runs, snapshot)
    manifest_path = args.output / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_snapshot"] = snapshot.relative_to(args.output).as_posix()
    manifest["source_snapshot_scope"] = "copied before scientific imports; source_sha256 paths are relative to this snapshot"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    measured = [run for run in runs if not run.is_warmup]
    print(f"Saved {len(measured)} measured attempts; {sum(run.accepted for run in measured)} accepted.")
    print(f"Summary: {args.output.resolve() / 'summary.csv'} ({len(summary)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
