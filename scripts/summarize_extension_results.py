"""Derive supplemental extension numbers without rewriting campaign evidence.

WP1's published ratio-of-medians estimand stays unchanged. This script adds
the separately labeled distribution and bootstrap median of per-round ratios.
All campaign bytes, source fingerprints and accepted raw hashes are verified
before those supplemental numbers are derived. Optional later analyses are
copied with their observed status and provenance; missing results are explicit.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from math import isfinite
from pathlib import Path
from random import Random
import shlex
from statistics import median
import zipfile


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WP1 = ROOT / "benchmarks/matched_runtime_2026-10-14"
DEFAULT_OUTPUT = ROOT / "docs/extension_numbers.json"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative_file(directory, relative):
    path = (directory / relative).resolve()
    if not path.is_relative_to(directory.resolve()):
        raise ValueError(f"evidence path escapes its root: {relative}")
    return path


def percentile(values, probability):
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (position - lower) * (ordered[upper] - ordered[lower])


def paired_ratio_distribution(numerator, denominator, *, seed=20261014, resamples=10000):
    """Median/IQR of paired ratios; percentile bootstrap of their median."""
    if len(numerator) != len(denominator) or len(numerator) < 2:
        raise ValueError("paired-ratio summaries require at least two complete pairs")
    if isinstance(resamples, bool) or not isinstance(resamples, int) or resamples < 100:
        raise ValueError("bootstrap requires at least 100 resamples")
    if any(isinstance(value, bool) or not isinstance(value, (int, float))
           or not isfinite(value) or value <= 0 for value in [*numerator, *denominator]):
        raise ValueError("paired durations must be finite and positive")
    ratios = [left / right for left, right in zip(numerator, denominator)]
    first, third = percentile(ratios, 0.25), percentile(ratios, 0.75)
    rng = Random(seed)
    draws = [median(ratios[rng.randrange(len(ratios))] for _ in ratios) for _ in range(resamples)]
    return {"estimand": "median of per-round Python/C++ duration ratios",
            "paired_round_count": len(ratios), "paired_ratios": ratios,
            "median_ratio": median(ratios), "q1_ratio": first, "q3_ratio": third,
            "iqr_ratio": third - first, "ci95_median_low": percentile(draws, 0.025),
            "ci95_median_high": percentile(draws, 0.975), "bootstrap_seed": seed,
            "bootstrap_resamples": resamples,
            "bootstrap_method": "percentile bootstrap of paired-round ratios; whole pairs resampled",
            "quartile_method": "R type 7 linear interpolation"}


def source_snapshot_for(directory, source_snapshot=None):
    return source_snapshot or directory / "source_snapshot.zip"


def verify_wp1_sources(directory, prepared, source_root=None, source_snapshot=None):
    """Use frozen bytes by default; later opt-in source changes are independent."""
    if source_root is not None:
        for relative, expected in prepared["source_sha256"].items():
            if digest(relative_file(source_root, relative)) != expected:
                raise ValueError(f"WP1 prepared source changed: {relative}")
        return {"kind": "explicit_source_root", "verified_entries": len(prepared["source_sha256"]),
                "source_root": "explicit --source-root command argument"}
    snapshot = source_snapshot_for(directory, source_snapshot)
    if not snapshot.is_file():
        raise ValueError("WP1 frozen source ZIP is missing; supply an exact --source-root or --source-snapshot")
    with zipfile.ZipFile(snapshot) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or set(names) != set(prepared["source_sha256"]):
            raise ValueError("WP1 frozen source ZIP entries differ from the exact prepared inventory")
        for relative, expected in prepared["source_sha256"].items():
            if hashlib.sha256(archive.read(relative)).hexdigest() != expected:
                raise ValueError(f"WP1 frozen source ZIP entry changed: {relative}")
    return {"kind": "frozen_source_zip", "path": portable_path(snapshot), "sha256": digest(snapshot),
            "verified_entries": len(prepared["source_sha256"]),
            "additional_snapshot_outside_original_manifest": True,
            "scope": "exact prepared source bytes; ZIP provenance is recorded separately without rewriting the original WP1 manifest"}


def verify_wp1(directory, source_root=None, source_snapshot=None):
    manifest = read_json(directory / "evidence_manifest.json")
    if manifest["file_count"] != len(manifest["files"]):
        raise ValueError("WP1 evidence manifest file count differs")
    hashes = {}
    for relative, expected in manifest["files"].items():
        observed = digest(relative_file(directory, relative))
        if observed != expected:
            raise ValueError(f"WP1 delivered evidence changed: {relative}")
        hashes[relative] = observed
    prepared = read_json(directory / "prepared.json")
    source_provenance = verify_wp1_sources(directory, prepared, source_root, source_snapshot)
    for spec in prepared["cases"]:
        for field in ("json", "numeric"):
            if hashes[spec[field]] != spec[field + "_sha256"]:
                raise ValueError(f"WP1 prepared input digest disagrees: {spec['name']} {field}")
    status = read_json(directory / "status.json")
    for key, record in status["samples"].items():
        for field, filename in (("stdout", "stdout.json"), ("stderr", "stderr.txt")):
            relative = record["directory"] + "/" + filename
            if hashes[relative] != record[field + "_sha256"]:
                raise ValueError(f"WP1 accepted raw digest disagrees: {key} {field}")
        actual = read_json(relative_file(directory, record["directory"] + "/stdout.json"))
        if actual["core_seconds"] != record["core_seconds"] or not record["verified_bitwise"]:
            raise ValueError(f"WP1 accepted core time/verification disagrees: {key}")
        invocation = read_json(relative_file(directory, record["directory"] + "/invocation.json"))
        if invocation["process_wall_seconds"] != record["process_wall_seconds"]:
            raise ValueError(f"WP1 invocation time disagrees: {key}")
    return prepared, status, {"verified_manifest_files": manifest["file_count"],
            "verified_prepared_sources": len(prepared["source_sha256"]),
            "verified_accepted_raw_samples": len(status["samples"]),
            "manifest_sha256": digest(directory / "evidence_manifest.json"),
            "prepared_sha256": digest(directory / "prepared.json"),
            "source_scope": "exact prepared source SHA-256 inventory; frozen ZIP or explicitly supplied snapshot root",
            "source_provenance": source_provenance}


def wp1_summary(directory, source_root=None, source_snapshot=None):
    prepared, status, verification = verify_wp1(directory, source_root, source_snapshot)
    analysis = read_json(directory / "analysis/analysis.json")
    primary = {(row["case"], row["boundary"]): row for row in analysis["rows"]}
    rows = []
    for spec in prepared["cases"]:
        for boundary in ("core", "invocation"):
            metric = "core_seconds" if boundary == "core" else "process_wall_seconds"
            pairs, indices = [], []
            for round_no in range(status["rounds"]):
                values = [status["samples"].get(f"{spec['name']}/{boundary}/round{round_no:02d}/{runtime}")
                          for runtime in ("python", "cpp")]
                if all(values):
                    pairs.append((values[0][metric], values[1][metric]))
                    indices.append(round_no)
            existing = primary[spec["name"], boundary]
            if existing["complete_paired_rounds"] != len(pairs):
                raise ValueError("WP1 primary analysis paired denominator differs")
            row = {"case": spec["name"], "shape": spec["shape"], "load": spec["load"],
                   "method": spec["method"], "boundary": boundary,
                   "timer_scope": analysis["timer_boundaries"][boundary],
                   "complete_paired_rounds": len(pairs), "planned_paired_rounds": status["rounds"],
                   "round_indices": indices,
                   "primary_ratio_of_medians": {"estimand": "median Python duration / median C++ duration",
                                                "source_result_unchanged": True, **existing.get("ratio", {})},
                   "python_duration_summary": existing.get("python"),
                   "cpp_duration_summary": existing.get("cpp"),
                   "supplemental_paired_ratio_distribution": None}
            if len(pairs) >= 2:
                row["supplemental_paired_ratio_distribution"] = paired_ratio_distribution(
                    [pair[0] for pair in pairs], [pair[1] for pair in pairs])
            rows.append(row)
    elapsed = None
    if "finished_utc" in status:
        elapsed = (datetime.fromisoformat(status["finished_utc"]) - datetime.fromisoformat(status["started_utc"])).total_seconds()
    return {"observed_campaign_state": status["state"], "method_shape_load_points": len(prepared["cases"]),
            "timer_boundary_rows": len(rows), "verified_samples": len(status["samples"]),
            "planned_samples": len(prepared["cases"]) * status["rounds"] * 4,
            "recorded_campaign_elapsed_seconds": elapsed, "verification": verification, "rows": rows,
            "source_analysis_sha256": digest(directory / "analysis/analysis.json"),
            "limitations": ["The two ratio estimands are distinct and neither replaces the historical primary result.",
                            "Paired ratios use the same round index; bootstrap units are complete measurement pairs.",
                            "These local CPU implementation ratios include implementation-specific input checks and rich traces.",
                            "Conditional ten-pair bootstrap intervals do not capture all thermal/systematic effects."]}


def optional_analysis(path):
    if path is None:
        return {"included": False, "availability": "analysis not supplied"}
    path = path.resolve()
    if not path.is_file():
        return {"included": False, "availability": "supplied analysis path does not exist",
                "source": portable_path(path)}
    analysis = read_json(path)
    status_fields = {field: analysis[field] for field in ("state", "status", "classification") if field in analysis}
    return {"included": True, "source": portable_path(path), "source_sha256": digest(path),
            "observed_status_fields": status_fields, "analysis": analysis}


def portable_path(path):
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.name


def build_summary(wp1, source_root, additional, source_snapshot=None):
    return {"format_version": 1,
            "classification": "supplemental derivation from retained synthetic CPU extension evidence",
            "scientific_attribution": "Formulation and GH/AGH: Cheng and Nguyen, arXiv:2604.07472; software is an independent implementation.",
            "wp1": wp1_summary(wp1, source_root, source_snapshot),
            "additional_analyses": {name: optional_analysis(path) for name, path in additional.items()},
            "replay": "python scripts/summarize_extension_results.py --output docs/extension_numbers.json; supply the same optional analysis paths"}


def replay_command(wp1, output, additional, *, source_root=None, source_snapshot=None):
    """Emit the same input/source options used by the producing CLI."""
    arguments = ["python", "scripts/summarize_extension_results.py", "--wp1", portable_path(wp1),
                 "--output", portable_path(output)]
    if source_root is not None:
        arguments.extend(["--source-root", "SOURCE_SNAPSHOT_ROOT"])
    elif source_snapshot is not None:
        arguments.extend(["--source-snapshot", portable_path(source_snapshot)])
    for name, path in additional.items():
        if path is not None:
            arguments.extend(["--" + name, portable_path(path.resolve())])
    return shlex.join(arguments)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wp1", type=Path, default=DEFAULT_WP1)
    sources = parser.add_mutually_exclusive_group()
    sources.add_argument("--source-root", type=Path, help="explicit exact prepared source directory")
    sources.add_argument("--source-snapshot", type=Path, help="exact prepared source ZIP; default: WP1/source_snapshot.zip")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    for name in ("wp2", "wp3", "wp4", "wp5", "wp6"):
        parser.add_argument("--" + name, type=Path)
    args = parser.parse_args()
    output, wp1 = args.output.resolve(), args.wp1.resolve()
    if output.is_relative_to(wp1):
        parser.error("write supplemental numbers outside the frozen WP1 campaign")
    additional = {name: getattr(args, name) for name in ("wp2", "wp3", "wp4", "wp5", "wp6")}
    summary = build_summary(wp1, args.source_root.resolve() if args.source_root else None, additional,
                            args.source_snapshot.resolve() if args.source_snapshot else None)
    summary["replay"] = replay_command(wp1, output, additional,
                                       source_root=args.source_root,
                                       source_snapshot=args.source_snapshot.resolve() if args.source_snapshot else None)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".pending")
    temporary.write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(output)
    print(json.dumps({"output": portable_path(output), "wp1_verified_samples": summary["wp1"]["verified_samples"],
                      "supplemental_ratio_rows": summary["wp1"]["timer_boundary_rows"]}))


if __name__ == "__main__":
    main()
