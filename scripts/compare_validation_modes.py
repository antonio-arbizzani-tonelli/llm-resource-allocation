"""Exploratory rotated timings of frozen serial and validator-probe cases.

All probe variants use the same executable. Warm full scientific evidence is
checked against retained serial output and Python goldens before timing compact
repeat-one calls. No Python algorithm is rerun and no scientific input is tuned.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import gzip
import json
import math
from pathlib import Path
import statistics
from types import SimpleNamespace

from profile_large_instances import (
    ROOT, check_reference, measurement, omp_environment, run_transport,
    runtime_metadata, save_evidence, save_json, science_projection, sha256,
    verify_bitwise, verify_fingerprints, verify_summary,
)

DEFAULT_VARIANTS = ("serial", "append", "slots", "omp1", "omp2", "omp4", "omp8")
OBSERVATION_ABS_TOL = 1e-12
OBSERVATION_REL_TOL = 1e-12


@dataclass(frozen=True)
class Variant:
    name: str
    mode: str | None
    threads: int = 1

    def arguments(self, minimum_rows):
        if self.mode is None:
            return []
        return ["--validation-mode", self.mode, "--validation-threads", str(self.threads),
                "--validation-min-rows", str(minimum_rows)]


def variants(names):
    if not names or len(set(names)) != len(names):
        raise ValueError("variants must be nonempty and unique")
    if not {"serial", "append"}.issubset(names):
        raise ValueError("variants must include serial and append controls")
    result = []
    for name in names:
        if name in {"serial", "append", "slots"}:
            result.append(Variant(name, None if name == "serial" else name))
        elif name.startswith("omp") and name[3:].isdigit() and int(name[3:]) > 0:
            result.append(Variant(name, "omp", int(name[3:])))
        else:
            raise ValueError(f"unknown validation variant: {name}")
    return tuple(result)


def round_order(settings, index):
    """Rotate controls with competitors and reverse alternating rounds."""
    offset = index % len(settings)
    order = settings[offset:] + settings[:offset]
    return tuple(reversed(order)) if index % 2 else tuple(order)


def integer(value, *, minimum=0, label="count"):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise AssertionError(f"{label} must be an integer at least {minimum}")
    return value


def positive(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise AssertionError(f"{label} must be finite and positive")
    return value


def close_observation(left, right, label):
    # Rounding here concerns computed timing summaries, never scientific values.
    if not math.isclose(left, right, abs_tol=OBSERVATION_ABS_TOL, rel_tol=OBSERVATION_REL_TOL):
        raise AssertionError(f"{label} differs from retained per-call observations")


def mccormick_row_count(transport):
    """Derive the observer's row count from the frozen numeric configuration menu."""
    lines = transport.splitlines()
    if not lines or lines[0] != "PACS_GH_AGH 1":
        raise ValueError("expected version-1 frozen GH/AGH transport")
    queries, models, tiers, *_ = map(int, lines[1].split())
    if min(queries, models, tiers) < 1:
        raise ValueError("frozen dimensions must be positive")
    tier_lines = lines[3 + queries + models:3 + queries + models + tiers]
    if len(tier_lines) != tiers:
        raise ValueError("frozen transport lacks its tier configuration menu")
    counts = [int(line.split()[3]) for line in tier_lines]
    if any(count < 1 for count in counts):
        raise ValueError("frozen configuration counts must be positive")
    return 4 * queries * models * sum(counts)


def validate_observer(actual, setting, minimum_rows, expected_rows):
    """Reject mislabeled modes, teams, fallbacks and inconsistent timing summaries."""
    if setting.mode is None:
        if any(field in actual for field in ("validation_execution", "validation_statistics", "phase_seconds")):
            raise AssertionError("original serial control unexpectedly contains probe observations")
        return None
    execution = actual["validation_execution"]
    integer(execution["requested_threads"], minimum=1, label="requested threads")
    integer(execution["minimum_mccormick_rows"], label="minimum McCormick rows")
    if execution != {"mode": setting.mode, "requested_threads": setting.threads,
                     "minimum_mccormick_rows": minimum_rows}:
        raise AssertionError("validation execution differs from requested flags")
    summary = actual["validation_statistics"]
    calls = integer(summary["calls"], minimum=1, label="validation calls")
    samples = summary["samples"]
    if not isinstance(samples, list) or len(samples) != calls:
        raise AssertionError("validation sample count differs")
    offsets = summary["repeat_call_offsets"]
    if not isinstance(offsets, list) or any(isinstance(value, bool) or not isinstance(value, int) for value in offsets) \
            or offsets != [0, calls]:
        raise AssertionError("repeat-one call offsets must span all samples")
    durations, teams = [], []
    counts = {"failed_calls": 0, "parallel_region_calls": 0, "calls_with_parallel_team": 0,
              "nested_fallback_calls": 0, "grain_fallback_calls": 0}
    for sample in samples:
        durations.append(positive(sample["seconds"], "validator call duration"))
        rows = integer(sample["mccormick_rows"], minimum=1, label="McCormick rows")
        if rows != expected_rows:
            raise AssertionError("observer McCormick row count differs from frozen configurations")
        team = integer(sample["actual_threads"], minimum=1, label="observed team")
        if team > setting.threads:
            raise AssertionError("observed team exceeds requested threads")
        teams.append(team)
        for field in ("region_entered", "nested_fallback", "grain_fallback", "succeeded"):
            if type(sample[field]) is not bool:
                raise AssertionError(f"{field} must be a Boolean observation")
        nested, grain, region = (sample[field] for field in ("nested_fallback", "grain_fallback", "region_entered"))
        if nested:
            raise AssertionError("standalone CLI unexpectedly used nested parallel fallback")
        expected_grain = setting.mode == "omp" and rows < minimum_rows
        if grain != expected_grain or region != (setting.mode == "omp" and not grain):
            raise AssertionError("parallel-region/grain-fallback observations contradict execution flags")
        if not region and team != 1:
            raise AssertionError("serial/fallback validation must observe one thread")
        counts["failed_calls"] += not sample["succeeded"]
        counts["parallel_region_calls"] += region
        counts["calls_with_parallel_team"] += team > 1
        counts["nested_fallback_calls"] += nested
        counts["grain_fallback_calls"] += grain
    if counts["failed_calls"]:
        raise AssertionError("timed validation contains a failed call")
    for field, expected in counts.items():
        if integer(summary[field], label=field) != expected:
            raise AssertionError(f"{field} differs from retained call observations")
    observed_teams = summary["observed_teams"]
    if not isinstance(observed_teams, list) or any(isinstance(value, bool) or not isinstance(value, int) for value in observed_teams) \
            or observed_teams != sorted(set(teams)):
        raise AssertionError("observed team summary differs from samples")
    ordered = sorted(durations)
    for field, expected in (("seconds_total", sum(ordered)), ("minimum_seconds", ordered[0]),
                            ("median_seconds", statistics.median(ordered)), ("maximum_seconds", ordered[-1])):
        close_observation(positive(summary[field], field), expected, field)
    if summary["seconds_total"] > actual["algorithm_seconds"] + OBSERVATION_ABS_TOL:
        raise AssertionError("validator call durations exceed the complete algorithm duration")
    return {"calls": calls, "observed_teams": sorted(set(teams)), **counts}


def snapshot_hashes(directory):
    files = sorted(path for path in directory.rglob("*") if path.is_file()
                   and (path.suffix in {".cpp", ".hpp", ".py"} or path.name == "Makefile"))
    if not files:
        raise ValueError(f"no declared compiled sources in {directory}")
    return {path.relative_to(directory).as_posix(): sha256(path) for path in files}


def fingerprints(args, records):
    base = args.baseline_output
    paths = [base / "profile.json"]
    for record in records:
        paths.extend(base / record[field] for field in ("input", "python_golden", "full_cpp_evidence"))
    helper_paths = [Path(__file__), ROOT / "scripts/profile_large_instances.py",
                    ROOT / "scripts/check_cpp_parity.py", ROOT / "scripts/check_openmp_campaign.py"]
    return {"serial_binary_sha256": sha256(args.serial_binary), "probe_binary_sha256": sha256(args.probe_binary),
            "serial_source_directory": str(args.serial_source_dir.resolve()),
            "serial_source_sha256": snapshot_hashes(args.serial_source_dir),
            "probe_source_directory": str(args.probe_source_dir.resolve()),
            "probe_source_sha256": snapshot_hashes(args.probe_source_dir),
            "baseline_artifact_sha256": {path.relative_to(base).as_posix(): sha256(path) for path in paths},
            "measurement_tool_sha256": {path.name: sha256(path) for path in helper_paths}}


def load_records(args):
    if args.output == args.baseline_output or args.baseline_output in args.output.parents:
        raise ValueError("comparison output must be outside the preserved baseline directory")
    baseline = json.loads((args.baseline_output / "profile.json").read_text(encoding="utf-8"))
    if baseline.get("mode") != "baseline" or not baseline.get("complete"):
        raise ValueError("comparison requires a completed frozen baseline")
    records = [record for record in baseline["cases"]
               if record["dimensions"][0] in args.query_counts and record["method"] in args.methods]
    wanted = {(count, method) for count in args.query_counts for method in args.methods}
    found = {(record["dimensions"][0], record["method"]) for record in records}
    if found != wanted or len(records) != len(wanted):
        raise ValueError("baseline does not contain exactly the requested shape/method matrix")
    for record in records:
        for field, digest in (("input", "input_sha256"), ("python_golden", "python_golden_sha256"),
                              ("full_cpp_evidence", "full_cpp_evidence_sha256")):
            if sha256(args.baseline_output / record[field]) != record[digest]:
                raise RuntimeError(f"frozen baseline checksum differs: {record[field]}")
    return records


def summarize(samples):
    result = {}
    for field, prefix in (("cpp_core_seconds", "core"), ("process_wall_seconds", "process")):
        durations = [positive(sample[field], field) for sample in samples]
        result[prefix + "_min_seconds"] = min(durations)
        result[prefix + "_median_seconds"] = statistics.median(durations)
    result["observed_teams"] = sorted({team for sample in samples
                                      for team in (sample.get("observer_check") or {}).get("observed_teams", [])})
    return result


def compare(args):
    records = load_records(args)
    settings = variants(args.variants)
    before = fingerprints(args, records)
    metadata_args = SimpleNamespace(binary=args.probe_binary, profile_binary=None, wsl=args.wsl,
                                    build_description=args.build_description, omp_wait_policy=args.omp_wait_policy)
    result = {"classification": "synthetic exploratory implementation performance; not paper numerical replication",
              "complete": False, "mode": "rotated_validation_comparison", "metadata": runtime_metadata(metadata_args),
              "configuration": {"query_counts": args.query_counts, "methods": args.methods, "variants": args.variants,
                                "minimum_mccormick_rows": args.minimum_mccormick_rows, "rounds": args.rounds,
                                "inner_repeat": 1, "omp_environment": omp_environment(args.omp_wait_policy)},
              "baseline": str(args.baseline_output), "fingerprints_before": before,
              "timing_policy": "one full warm-up per case/config; deterministic rotated/reversed repeat-one calls; separate minima and medians",
              "limitations": ["exploratory timings depend on this CPU/WSL/compiler and system activity",
                              "serial-to-append comparison includes observer and changed CLI/serialization overhead",
                              "slots/OpenMP-to-append comparisons share one executable and observer",
                              "process wall includes startup, parsing, evidence formatting/destruction and JSON/observer output",
                              "phase observed_body_before_write excludes observer formatting/stdout/OS startup",
                              "no Python algorithm is rerun and no numerical calibration is changed"],
              "cases": []}
    args.output.mkdir(parents=True, exist_ok=True)
    for record in records:
        base = args.baseline_output
        transport = (base / record["input"]).read_text(encoding="utf-8")
        expected = json.loads(gzip.decompress((base / record["full_cpp_evidence"]).read_bytes()))
        golden = json.loads((base / record["python_golden"]).read_text(encoding="utf-8"))["reference"]
        expected_rows = mccormick_row_count(transport)
        case = {"case": record["case"], "method": record["method"], "dimensions": record["dimensions"],
                "expected_mccormick_rows": expected_rows, "warm": [], "execution_order": [], "variants": []}
        samples = {setting.name: [] for setting in settings}

        def run(setting, summary):
            binary = args.serial_binary if setting.mode is None else args.probe_binary
            actual, wall = run_transport(binary, record["method"], transport, summary=summary, repeat=1,
                                         wsl=args.wsl, timeout=args.timeout, omp_wait_policy=args.omp_wait_policy,
                                         extra_arguments=setting.arguments(args.minimum_mccormick_rows))
            observed = measurement(actual, wall)
            check = validate_observer(actual, setting, args.minimum_mccormick_rows, expected_rows)
            if summary:
                verify_summary(expected, actual)
            else:
                check_reference(golden, actual)
                verify_bitwise(science_projection(expected), science_projection(actual), record["case"])
            return actual, observed, check

        for setting in settings:
            actual, observed, check = run(setting, False)
            path = args.output / "warm" / f"{record['case']}_{setting.name}.json.gz"
            case["warm"].append({"variant": setting.name, "full_bitwise_parity": True,
                                 "frozen_python_parity": True, "observer_check": check,
                                 "evidence": path.relative_to(args.output).as_posix(),
                                 "evidence_sha256": save_evidence(path, actual), **observed})
        for index in range(args.rounds):
            order = round_order(settings, index)
            case["execution_order"].append({"round": index, "variants": [setting.name for setting in order]})
            for setting in order:
                actual, observed, check = run(setting, True)
                path = args.output / "samples" / f"{record['case']}_{setting.name}_round{index}.json"
                save_json(path, actual)
                sample = {"round": index, "observer_check": check,
                          "evidence": path.relative_to(args.output).as_posix(), "evidence_sha256": sha256(path), **observed}
                samples[setting.name].append(sample)
        summaries = {name: summarize(values) for name, values in samples.items()}
        for setting in settings:
            summary = summaries[setting.name]
            ratios = {}
            for control in ("serial", "append"):
                for scope in ("core", "process"):
                    for aggregation in ("min", "median"):
                        field = f"{scope}_{aggregation}_seconds"
                        ratios[f"{scope}_{aggregation}_speedup_vs_{control}"] = summaries[control][field] / summary[field]
            case["variants"].append({"variant": setting.name, "mode": setting.mode,
                                     "requested_threads": setting.threads, "samples": samples[setting.name], **summary, **ratios})
        result["cases"].append(case)
        save_json(args.output / "profile.json", result)
        print(f"{record['case']}: {len(settings)} variants, {args.rounds} rotated rounds, full bitwise warm parity passes", flush=True)
    after = fingerprints(args, records)
    verify_fingerprints(before, after)
    result.update(complete=True, fingerprints_after=after, fingerprints_verified_unchanged=True)
    save_json(args.output / "profile.json", result)
    report(args.output, result)
    return result


def report(directory, result):
    lines = ["# Exploratory rotated validation modes", "", result["classification"], "",
             "Original serial and append are controls; all probe modes share one executable. "
             "Minima and medians use fixed repeat-one inputs after full scientific warm parity.", "",
             "| Case | Variant | Core min (s) | Core median (s) | Min speedup / append | Median speedup / append | Process median (s) | Teams |",
             "|---|---|---:|---:|---:|---:|---:|---|"]
    for case in result["cases"]:
        for variant in case["variants"]:
            lines.append(f"| {case['case']} | {variant['variant']} | {variant['core_min_seconds']:.6f} | "
                         f"{variant['core_median_seconds']:.6f} | {variant['core_min_speedup_vs_append']:.3f} | "
                         f"{variant['core_median_speedup_vs_append']:.3f} | {variant['process_median_seconds']:.6f} | "
                         f"{variant['observed_teams']} |")
    lines.extend(("", *result["limitations"]))
    (directory / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-output", type=Path, required=True)
    parser.add_argument("--serial-binary", type=Path, required=True)
    parser.add_argument("--probe-binary", type=Path, required=True)
    parser.add_argument("--serial-source-dir", type=Path, required=True)
    parser.add_argument("--probe-source-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wsl")
    parser.add_argument("--query-counts", type=int, nargs="+", default=[32, 64])
    parser.add_argument("--methods", choices=("gh", "agh"), nargs="+", default=["gh", "agh"])
    parser.add_argument("--variants", nargs="+", default=list(DEFAULT_VARIANTS))
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--minimum-mccormick-rows", type=int, default=0)
    parser.add_argument("--omp-wait-policy", choices=("active", "passive"), default="active")
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--build-description", required=True)
    args = parser.parse_args(argv)
    if args.rounds < 2 or args.minimum_mccormick_rows < 0:
        parser.error("at least two rounds and a nonnegative grain threshold are required")
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("timeout must be finite and positive")
    if any(n < 2 for n in args.query_counts) or len(set(args.query_counts)) != len(args.query_counts):
        parser.error("query counts must be unique and at least two")
    if len(set(args.methods)) != len(args.methods):
        parser.error("methods must be unique")
    try:
        variants(args.variants)
    except ValueError as error:
        parser.error(str(error))
    for field in ("baseline_output", "serial_source_dir", "probe_source_dir", "output", "serial_binary", "probe_binary"):
        setattr(args, field, getattr(args, field).resolve())
    if args.output == args.baseline_output or args.baseline_output in args.output.parents:
        parser.error("output must be outside the preserved baseline directory")
    return args


def main(argv=None):
    compare(parse_args(argv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
