"""Replay WP2 statistics and export exact-path-redacted portable evidence.

This reader never runs the measured binary. The frozen measurement producer,
scientific source, inputs, and golden decisions remain unchanged.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import shutil
from statistics import median
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "benchmarks/openmp_diagnostics_2026-10-14"
DEFAULT_BACKUP = ROOT / "results/openmp_original_2026-10-14"
sys.path.insert(0, str(ROOT / "scripts"))
from extension_statistics import paired_ratio_bootstrap, timing_summary

CONFIG_FIELDS = ("threads", "places", "bind", "schedule", "chunk", "sorted", "arena")
CONTROLS = {"schedule": "dynamic", "chunk": 1, "places": "cores",
            "bind": "close", "sorted": False, "arena": None}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(path.suffix + ".pending")
    pending.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    pending.replace(path)


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def key(config):
    return "_".join(str(config[field]) for field in CONFIG_FIELDS)


def safe_target(directory, relative):
    target = (directory / relative).resolve()
    if not target.is_relative_to(directory.resolve()):
        raise ValueError("evidence path escapes campaign")
    return target


def unpack(output):
    """Validate archive membership and SHA before automatically unpacking."""
    archive_path = output / "evidence.zip"
    if not archive_path.exists():
        return
    manifest = read(output / "evidence_manifest.json")
    if digest(archive_path) != manifest["archive_sha256"]:
        raise ValueError("portable evidence archive hash changed")
    with zipfile.ZipFile(archive_path) as archive:
        expected = {item["path"] for item in manifest["files"]}
        if len(expected) != len(manifest["files"]) or set(archive.namelist()) != expected:
            raise ValueError("portable archive membership changed")
        for item in manifest["files"]:
            payload = archive.read(item["path"])
            if len(payload) != item["bytes"] or hashlib.sha256(payload).hexdigest() != item["sha256"]:
                raise ValueError("portable archive entry changed: " + item["path"])
            target = safe_target(output, item["path"])
            if target.exists():
                if digest(target) != item["sha256"]:
                    raise ValueError("unpacked evidence differs from archive: " + item["path"])
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(payload)


def verify(output, repository=ROOT):
    unpack(output)
    if (output / "inventory_provenance.json").exists():
        if digest(output / "artifact_hashes.json") != read(output / "inventory_provenance.json")["portable_sha256"]:
            raise ValueError("portable inventory provenance changed")
    if (output / "artifact_hashes.json").exists():
        for relative, expected in read(output / "artifact_hashes.json").items():
            if digest(safe_target(output, relative)) != expected:
                raise ValueError("campaign artifact changed: " + relative)
    for relative, expected in read(output / "preparation_complete.json")["files"].items():
        if digest(safe_target(output, relative)) != expected:
            raise ValueError("frozen preparation artifact changed: " + relative)
    for relative, expected in read(output / "hashes.json").items():
        if relative.startswith("cpp/build/"):
            continue  # Historical binary SHA remains evidence; replay needs no executable.
        path = safe_target(repository, relative)
        if digest(path) != expected:
            raise ValueError("measured scientific source/input changed: " + relative)
    for path in sorted((output / "raw").glob("*.json")):
        if path.with_suffix(".sha256").read_text().strip() != digest(path):
            raise ValueError("raw observation hash changed: " + path.name)


def paired(control, candidate, resamples):
    rounds = sorted(control.keys() & candidate.keys())
    if len(rounds) < 2:
        return None
    result = paired_ratio_bootstrap([control[index]["core_seconds"] for index in rounds],
                                    [candidate[index]["core_seconds"] for index in rounds],
                                    resamples=resamples)
    return {**result, "rounds": rounds}


def wall_accounting(sample, baseline_seconds=None):
    """Wall accounting, not CPU utilization or causal serial-code attribution."""
    team, core, busy = sample["actual_threads"], sample["core_seconds"], sample["busy_seconds"]
    if team < 1 or len(busy) != team or not math.isfinite(core) or core <= 0:
        raise ValueError("invalid observed team or core timer")
    if any(not math.isfinite(value) or value < 0 or value > core for value in busy):
        raise ValueError("worker wall-busy duration exceeds core boundary")
    average, maximum = math.fsum(busy) / team, max(busy)
    result = {"wall_idle_fraction": 1 - average / core,
              "imbalance_fraction": (maximum - average) / core,
              "imbalance_seconds": maximum - average,
              "other_wall_idle_fraction": 1 - maximum / core}
    if baseline_seconds is not None:
        result.update(efficiency_loss_fraction=1 - baseline_seconds / (team * core),
                      work_duration_change_fraction=(math.fsum(busy) - baseline_seconds) / (team * core),
                      ideal_seconds=baseline_seconds / team,
                      remainder_seconds=core - baseline_seconds / team - (maximum - average))
    return result


def analyze_observations(configs, observations, planned_rounds, resamples=10000):
    rows, threads, comparisons = [], [], []
    for config in configs:
        identity = key(config)
        samples = observations[identity]
        if not samples:
            continue
        teams = {sample["actual_threads"] for sample in samples.values()}
        if teams != {config["threads"]}:
            raise ValueError("observed team changed or differs: " + identity)
        team = config["threads"]
        baseline_identity = key({**config, "threads": 1})
        baseline = observations.get(baseline_identity, {})
        speedup = paired(baseline, samples, resamples)
        accounts = [wall_accounting(sample, baseline[index]["core_seconds"] if index in baseline else None)
                    for index, sample in samples.items()]
        invocation_samples = [sample for sample in samples.values()
                              if not (len(sample.get("command", [])) > 4 and sample["command"][4] == "warm")]
        row = {"key": identity, "configuration": config, "valid_rounds": len(samples),
               "planned_rounds": planned_rounds,
               "core": timing_summary([sample["core_seconds"] for sample in samples.values()]),
               "invocation": timing_summary([sample["invocation_seconds"] for sample in invocation_samples]) if invocation_samples else None,
               "invocation_rounds_with_warmup_excluded": len(samples) - len(invocation_samples),
               "speedup_vs_same_setting_one_thread": speedup,
               **{name + "_median": median(account[name] for account in accounts)
                  for name in ("wall_idle_fraction", "imbalance_fraction", "other_wall_idle_fraction")}}
        matched_accounts = [account for account in accounts if "efficiency_loss_fraction" in account]
        for name in ("efficiency_loss_fraction", "work_duration_change_fraction", "ideal_seconds", "remainder_seconds"):
            row[name + "_median"] = median(account[name] for account in matched_accounts) if matched_accounts else None
        row["imbalance_seconds_median"] = median(account["imbalance_seconds"] for account in accounts)
        row["decomposition_paired_rounds"] = len(matched_accounts)
        row["amdahl_equivalent_serial_fraction"] = ((team / speedup["ratio_of_medians"] - 1) / (team - 1)
                                                    if speedup and team > 1 else None)
        rows.append(row)
        for worker in range(team):
            threads.append({"configuration_key": identity, "requested_threads": team, "actual_threads": team,
                "worker": worker, "valid_rounds": len(samples), "planned_rounds": planned_rounds,
                "median_busy_seconds": median(sample["busy_seconds"][worker] for sample in samples.values()),
                "median_wall_idle_percent": median(100 * (1 - sample["busy_seconds"][worker] / sample["core_seconds"])
                                                    for sample in samples.values()),
                "median_jobs": median(sample["job_count"][worker] for sample in samples.values()),
                "observed_guest_cpus": ",".join(map(str, sorted({sample["cpu_start"][worker] for sample in samples.values()})))})
        for factor, value in CONTROLS.items():
            if config[factor] == value:
                continue
            control_config = {**config, factor: value}
            control_identity = key(control_config)
            control = observations.get(control_identity)
            if control is None:
                continue
            estimate = paired(control, samples, resamples)
            comparisons.append({"factor": factor, "candidate_key": identity, "control_key": control_identity,
                "threads": team, "candidate_value": config[factor], "control_value": value,
                "paired_speedup": estimate,
                "exploratory_lower_bound_above_one": estimate is not None and estimate["ci95_low"] > 1,
                "interpretation": "one factor changes at the same observed team; unadjusted exploratory CI"})
    eligible = [row for row in rows if row["valid_rounds"] == planned_rounds]
    best = min(eligible, key=lambda row: row["core"]["median_seconds"], default=None)
    recommendation = None
    if best:
        config = best["configuration"]
        control_key = key({**config, **CONTROLS})
        control = observations.get(control_key, {})
        comparison = paired(control, observations[best["key"]], resamples)
        recommendation = {"configuration": config, "median_core_seconds": best["core"]["median_seconds"],
            "valid_rounds": best["valid_rounds"], "eligible_complete_settings": len(eligible),
            "same_team_reference_key": control_key, "paired_speedup_vs_same_team_reference": comparison,
            "improvement_supported_exploratorily": comparison is not None and comparison["ci95_low"] > 1,
            "selection_limit": "fastest median selected on the same data across many settings; unadjusted CIs have selection optimism; no held-out confirmation or universal optimum"}
    return {"settings": rows, "thread_rows": threads, "same_team_controls": comparisons,
            "recommendation": recommendation,
            "accounting": {"identity_each_round": "wall_idle = imbalance + other_wall_idle; efficiency_loss = wall_idle + work_duration_change",
                "time_decomposition": "Tp = T1/p + (max busy - mean busy) + remainder; remainder is signed and not causal attribution",
                "serial_fraction": "Amdahl-equivalent fit from response time; not measured serial code and not additive to the wall-idle terms",
                "busy": "wall time within jobs, including memory waits and descheduling; not CPU utilization",
                "remaining": "startup/barriers/scheduling/instrumentation contribute to other wall idle; work-duration changes include allocation/cache/frequency/contention without causal separation",
                "aggregation": "per-round components are computed before medians; medians need not sum"}}


def hypothesis_status(environment):
    availability = environment.get("availability", {})
    return {
        "load_balance": "measured schedule/order sensitivity and per-worker wall accounting; imbalance remains descriptive",
        "physical_p_e_and_hyperthreading": "unresolved: guest affinity/SMT topology does not identify physical P/E cores or provide a physical SMT on/off intervention",
        "memory_bandwidth_and_cache": "unresolved: no workload hardware counters; perf observation: " + str(availability.get("perf", "not recorded")),
        "allocation": "MALLOC_ARENA_MAX sensitivity measured at selected teams; no allocation counters or causal contention attribution",
        "frequency_and_throttling": "unresolved: no frequency/temperature time series; governor=" + str(availability.get("governor", "not recorded"))
            + "; frequency=" + str(availability.get("frequency", "not recorded")) + "; temperature=" + str(availability.get("temperature", "not recorded")),
        "environment": "power plan and app observations are retained; no fixed-frequency or closed-app claim beyond recorded evidence"}


def csv_file(path, rows):
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def analyze(output, resamples=10000):
    verify(output)
    plan = read(output / "configuration.json")
    configs = plan["configurations"]
    observations = {key(config): {} for config in configs}
    expected = {key(config): config for config in configs}
    reference = read(output / "pilot.json")["fingerprints"]
    permutation = read(output / "cost_ordering.json")["original_indices"]
    failures, attempted = [], 0
    for path in sorted((output / "raw").glob("*.json")):
        row = read(path)
        attempted += 1
        identity = row["configuration_key"]
        if identity not in expected or row["configuration"] != expected[identity] or not 0 <= row["round"] < plan["rounds"]:
            raise ValueError("raw observation is outside frozen schedule")
        fingerprints = [reference[index] for index in permutation] if row["configuration"]["sorted"] else reference
        matches = row.get("fingerprints") == fingerprints
        if row["projection_fingerprints_match"] != matches:
            raise ValueError("retained projection comparison differs")
        if row["returncode"] or not matches:
            failures.append({"path": path.relative_to(output).as_posix(), "returncode": row["returncode"],
                             "projection_fingerprints_match": matches})
            continue
        team = row["actual_threads"]
        if any(len(row[name]) != team for name in ("busy_seconds", "job_count", "cpu_start")) or sum(row["job_count"]) != len(reference):
            raise ValueError("worker evidence does not cover the fixed batch")
        if row["round"] in observations[identity]:
            raise ValueError("duplicate configuration/round observation")
        observations[identity][row["round"]] = row
    summary = analyze_observations(configs, observations, plan["rounds"], resamples)
    summary.update(classification="SYNTHETIC_CPU_OPENMP_EXTENSION", planned_settings=len(configs),
        planned_rounds=plan["rounds"], planned_observations=len(configs) * plan["rounds"],
        attempted_observations=attempted, valid_observations=sum(map(len, observations.values())),
        failed_observations=failures, complete=attempted == len(configs) * plan["rounds"],
        projection_scope="64-bit FNV compact final x/z/q/u/w/y/v, objective and feasibility projection; no full-trace bitwise-parity claim",
        golden_validation=read(output / "golden_validation.json"),
        golden_scope="excluded 32-case goldens were checked by the shared independent Python validator; objective components compared bitwise during preparation",
        hypotheses=hypothesis_status(read(output / "environment.json")),
        analyzer_sha256=digest(Path(__file__)), bootstrap_resamples=resamples, bootstrap_seed=20261014)
    save(output / "analysis/extension.json", summary)
    csv_file(output / "analysis/thread_statistics.csv", summary["thread_rows"])
    csv_file(output / "analysis/decomposition.csv", [{
        "configuration_key": row["key"], "actual_threads": row["configuration"]["threads"],
        "valid_rounds": row["valid_rounds"], "paired_rounds": row["decomposition_paired_rounds"],
        "median_core_seconds": row["core"]["median_seconds"],
        "median_ideal_seconds": row["ideal_seconds_median"],
        "median_imbalance_seconds": row["imbalance_seconds_median"],
        "median_signed_remainder_seconds": row["remainder_seconds_median"],
        "amdahl_equivalent_serial_fraction": row["amdahl_equivalent_serial_fraction"],
        "median_wall_idle_fraction": row["wall_idle_fraction_median"]} for row in summary["settings"]])
    control_rows = []
    for row in summary["same_team_controls"]:
        estimate = row["paired_speedup"]
        control_rows.append({key: value for key, value in row.items() if key not in ("paired_speedup", "interpretation")}
                            | {"paired_round_count": estimate["paired_round_count"] if estimate else 0,
                               "ratio_of_medians": estimate["ratio_of_medians"] if estimate else None,
                               "ci95_low": estimate["ci95_low"] if estimate else None,
                               "ci95_high": estimate["ci95_high"] if estimate else None})
    csv_file(output / "analysis/same_team_controls.csv", control_rows)
    return summary


def root_prefix(repository=ROOT):
    value = repository.resolve().as_posix()
    if len(value) > 2 and value[1] == ":":
        return "/mnt/" + value[0].lower() + value[2:]
    return value


def portable_values(value, prefix):
    """Replace exactly the measured Linux workspace prefix in string values."""
    if isinstance(value, dict):
        return {key: portable_values(item, prefix) for key, item in value.items()}
    if isinstance(value, list):
        return [portable_values(item, prefix) for item in value]
    return value.replace(prefix, ".") if isinstance(value, str) else value


def preserve_nonpath_values(original, portable, prefix):
    """Audit numeric bits/types and every non-path, non-SHA string recursively."""
    if type(original) is not type(portable):
        raise ValueError("portable transformation changed a value type")
    if isinstance(original, dict):
        if original.keys() != portable.keys():
            raise ValueError("portable transformation changed mapping keys")
        for name in original:
            preserve_nonpath_values(original[name], portable[name], prefix)
    elif isinstance(original, list):
        if len(original) != len(portable):
            raise ValueError("portable transformation changed sequence length")
        for left, right in zip(original, portable, strict=True):
            preserve_nonpath_values(left, right, prefix)
    elif isinstance(original, float):
        if original.hex() != portable.hex():
            raise ValueError("portable transformation changed numeric bits")
    elif isinstance(original, str):
        hash_pointer = len(original) == 64 and len(portable) == 64 and all(character in "0123456789abcdef" for character in original + portable)
        if portable != original.replace(prefix, ".") and not hash_pointer:
            raise ValueError("portable transformation changed a scientific string")
    elif original != portable:
        raise ValueError("portable transformation changed a scientific value")


def preserve_originals(output, backup):
    """Copy and verify originals and referenced measured source/binary bytes."""
    if backup.exists():
        manifest = read(backup / "manifest.json")
        for item in manifest["files"]:
            if digest(safe_target(backup, item["snapshot_path"])) != item["sha256"]:
                raise ValueError("private original snapshot changed")
        return manifest
    backup.mkdir(parents=True, exist_ok=False)
    entries = []
    for source in sorted(path for path in output.rglob("*") if path.is_file()):
        relative = source.relative_to(output).as_posix()
        target = backup / "campaign" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        expected = digest(source)
        if digest(target) != expected:
            raise ValueError("original campaign snapshot copy differs")
        entries.append({"scope": "campaign", "path": relative,
                        "snapshot_path": target.relative_to(backup).as_posix(), "sha256": expected})
    for relative, expected in read(output / "hashes.json").items():
        source = safe_target(ROOT, relative)
        target = backup / "referenced" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        if digest(target) != expected:
            raise ValueError("referenced measured source/binary differs")
        entries.append({"scope": "referenced", "path": relative,
                        "snapshot_path": target.relative_to(backup).as_posix(), "sha256": expected})
    manifest = {"format_version": 1, "classification": "IMMUTABLE_PRIVATE_ORIGINAL_OPENMP_EVIDENCE",
                "files": entries, "policy": "all original campaign files and referenced sources/binary copied before path redaction"}
    save(backup / "manifest.json", manifest)
    return manifest


def package(output):
    entries = []
    with zipfile.ZipFile(output / "evidence.zip", "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for directory in ("raw", "golden"):
            for path in sorted((output / directory).rglob("*")):
                if not path.is_file():
                    continue
                relative = path.relative_to(output).as_posix()
                payload = path.read_bytes()
                info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, payload)
                entries.append({"path": relative, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()})
    save(output / "evidence_manifest.json", {"archive_sha256": digest(output / "evidence.zip"), "files": entries})
    unpack(output)  # Read and validate every just-written entry against its retained file.


def inventory(output):
    archive_only = (output / "provenance.json").exists() and read(output / "provenance.json").get("archive_only", False)
    save(output / "artifact_hashes.json", {path.relative_to(output).as_posix(): digest(path)
        for path in sorted(output.rglob("*")) if path.is_file() and path.name not in ("artifact_hashes.json", "inventory_provenance.json")
        and not (archive_only and any(path.is_relative_to(output / name) for name in ("raw", "golden")))})
    if (output / "inventory_provenance.json").exists():
        provenance = read(output / "inventory_provenance.json")
        provenance["portable_sha256"] = digest(output / "artifact_hashes.json")
        save(output / "inventory_provenance.json", provenance)


def write_report(output, summary):
    best = summary["recommendation"]
    lines = ["# OpenMP extension observations", "",
        f"Recorded {summary['attempted_observations']}/{summary['planned_observations']} configuration/round attempts; {summary['valid_observations']} complete projection-matching batches. Each batch contains 32 fixed synthetic GH/AGH cases. Timing uses the prepared-input native solve boundary including team creation and barriers, excluding parsing/output. Warmups are excluded from core observations.", "",
        "The compact FNV comparison covers final decisions, objective components and feasibility. The separate 32 excluded goldens retain full projected evidence and the original shared Python independent feasibility/bitwise objective checks. Full rich-trace parity is not inferred from a compact fingerprint.", ""]
    if best:
        comparison = best["paired_speedup_vs_same_team_reference"]
        lines += [f"The fastest observed median is {best['median_core_seconds']:.9g} s over {best['valid_rounds']} rounds at `{key(best['configuration'])}`, selected from {best['eligible_complete_settings']} complete settings.", ""]
        if comparison:
            lines += [f"Against the cores/close/dynamic/chunk1/unsorted/default-arena control at the same team, the ratio of medians is {comparison['ratio_of_medians']:.6g}, paired bootstrap95% [{comparison['ci95_low']:.6g}, {comparison['ci95_high']:.6g}] over {comparison['paired_round_count']} rounds. "
                      + ("Its lower bound exceeds one in this exploratory comparison." if best["improvement_supported_exploratorily"] else "These data do not establish an improvement over that control."), ""]
        lines += ["Recommendation: use this setting as the measured local candidate and confirm it on an independent run/workload before adopting it generally. Selection used the same timing data across many configurations; the unadjusted intervals have selection optimism and do not certify an optimum.", ""]
    lines += ["Per-worker busy seconds and wall-idle percentages are in [thread_statistics.csv](analysis/thread_statistics.csv). All one-factor same-team schedule/chunk/place/bind/sort/arena comparisons and paired denominators are in [same_team_controls.csv](analysis/same_team_controls.csv). The time decomposition is in [decomposition.csv](analysis/decomposition.csv); median/IQR, boundaries, failures and hypotheses are in [extension.json](analysis/extension.json).", "",
        "The time decomposition is `Tp = T1/p + (max busy - mean busy) + remainder`, using paired rounds and time units. Signed remainders are retained, including negative values. Per round, wall idle also equals `(max busy - mean busy)/core + (1 - max busy/core)`. Components are computed before medians; medians need not sum. The Amdahl-equivalent serial fraction is a separate response-time fit, not measured serial code and not an additive causal component. Busy includes stalls/descheduling and is not CPU utilization; the remainder does not identify allocation, cache or frequency causes.", "",
        "| Hypothesis | Evidence and limit |", "|---|---|"]
    lines += [f"| {name.replace('_', ' ')} | {value} |" for name, value in summary["hypotheses"].items()]
    lines += ["", "All inputs and timings are synthetic CPU allocation-software observations. GPU delays are model coefficients. Allocation formulations and GH/AGH follow Cheng and Nguyen, arXiv2604.07472. No paper-table replication or universal hardware attribution is claimed.", "",
        "Replay in a fresh clone (no measured binary, compiler, or optional solver license required):", "",
        "```bash", "python scripts/analyze_openmp_extension.py --output benchmarks/openmp_diagnostics_2026-10-14", "```", "",
        "The command verifies the archive, automatically unpacks raw/golden evidence, checks source/input/preparation hashes and raw sidecars, and recomputes statistics. Only standard-library Python and the shipped statistics helper are needed. No scientific algorithm is rerun. `evidence.zip` retains all observations, failures and goldens. Portable metadata replaces only the exact measured Linux workspace prefix with `.`; original SHA and portable SHA are retained in provenance.json. Complete originals, including measured sources/binary, remain in the ignored local results snapshot."]
    (output / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def publish_portable(output, backup, prefix=None, archive_only=True, resamples=10000):
    if read(output / "execution.json")["status"] not in ("complete", "wall_budget_reached"):
        raise ValueError("portable publication requires a stopped/completed campaign")
    verify(output)
    original = preserve_originals(output, backup)
    prefix = root_prefix() if prefix is None else prefix
    if not prefix or prefix == ".":
        raise ValueError("exact original workspace prefix is required")
    records = {}
    for item in original["files"]:
        if item["scope"] != "campaign":
            continue
        name = item["path"]
        payload = safe_target(backup, item["snapshot_path"]).read_bytes()
        converted = payload
        if name.endswith(".json") and name not in ("artifact_hashes.json", "evidence_manifest.json"):
            value = json.loads(payload)
            portable = portable_values(value, prefix)
            preserve_nonpath_values(value, portable, prefix)
            if portable != value:
                converted = (json.dumps(portable, indent=2, allow_nan=False) + "\n").encode()
        elif name.endswith((".txt", ".log", ".md", ".csv", ".partial")):
            converted = payload.decode("utf-8").replace(prefix, ".").encode()
        if name.startswith(("golden/", "inputs/")) and converted != payload:
            raise ValueError("scientific golden/input bytes would change")
        target = safe_target(output, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(converted)
        records[name] = {"original_sha256": item["sha256"], "portable_sha256": digest(target),
                         "transformation": "exact workspace prefix -> ." if converted != payload else "unchanged bytes"}
    for path in sorted((output / "raw").glob("*.json")):
        row = read(path)
        changed = False
        for item in row.get("partial_output", {}).values():
            expected = digest(safe_target(output, item["path"]))
            if item["sha256"] != expected:
                item["sha256"] = expected
                changed = True
        if changed:
            save(path, row)
        path.with_suffix(".sha256").write_text(digest(path) + "\n", encoding="utf-8", newline="\n")
    hashes = read(output / "hashes.json")
    for relative in hashes:
        candidate = safe_target(ROOT, relative)
        if candidate.is_relative_to(output.resolve()):
            hashes[relative] = digest(candidate)
    save(output / "hashes.json", hashes)
    preparation = read(output / "preparation_complete.json")
    preparation["files"] = {relative: digest(safe_target(output, relative)) for relative in preparation["files"]}
    save(output / "preparation_complete.json", preparation)
    for name, record in records.items():
        if name.endswith(".json") and name not in ("artifact_hashes.json", "evidence_manifest.json"):
            previous = read(backup / "campaign" / name)
            current = read(output / name)
            preserve_nonpath_values(previous, current, prefix)
        if (output / name).exists():
            record["portable_sha256"] = digest(output / name)
            if record["portable_sha256"] != record["original_sha256"] and record["transformation"] == "unchanged bytes":
                record["transformation"] = "metadata digest pointers refreshed"
    # The immutable original archive is in the private snapshot; package only portable bytes.
    package(output)
    for name in ("evidence.zip", "evidence_manifest.json"):
        if name in records:
            records[name].update(portable_sha256=digest(output / name), transformation="portable evidence archive and entry bookkeeping rebuilt")
    # Refresh the preexisting inventory before invoking the strict replay reader.
    inventory_record = records.pop("artifact_hashes.json", None)
    records.pop("inventory_provenance.json", None)
    inventory_sidecar = output / "inventory_provenance.json"
    if inventory_sidecar.exists():
        inventory_sidecar.unlink()
    inventory(output)
    summary = analyze(output, resamples)
    write_report(output, summary)
    for name, record in records.items():
        if (output / name).exists():
            record["portable_sha256"] = digest(output / name)
    save(output / "provenance.json", {"format_version": 1,
        "policy": "exact measured Linux ROOT prefix -> . in metadata; numeric bits, booleans and non-path scientific strings unchanged; digest/byte bookkeeping refreshed",
        "original_snapshot": backup.relative_to(ROOT).as_posix(),
        "original_manifest_sha256": digest(backup / "manifest.json"),
        "scientific_inputs_and_goldens_unchanged": True,
        "numeric_boolean_nonpath_audit_passed": True,
        "archive_only": archive_only,
        "inventory_digest_provenance": "inventory_provenance.json (outside the inventory to avoid a self-referential digest)",
        "files": [{"path": name, **record} for name, record in sorted(records.items())]})
    if archive_only:
        for name in ("raw", "golden"):
            target = (output / name).resolve()
            if target.parent != output.resolve():
                raise ValueError("archive-only cleanup escapes campaign")
            shutil.rmtree(target)
    inventory(output)
    if inventory_record is not None:
        save(inventory_sidecar, {"path": "artifact_hashes.json",
            "original_sha256": inventory_record["original_sha256"],
            "portable_sha256": digest(output / "artifact_hashes.json"),
            "transformation": "fresh portable artifact inventory; sidecar excluded from its inventory to avoid digest recursion"})
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--original-backup", type=Path, default=DEFAULT_BACKUP)
    parser.add_argument("--resamples", type=int, default=10000)
    parser.add_argument("--keep-unpacked", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    if output != DEFAULT_OUTPUT.resolve():
        parser.error("this publication command is scoped to the new WP2 campaign only")
    if args.publish:
        backup = args.original_backup.resolve()
        if not backup.is_relative_to((ROOT / "results").resolve()):
            parser.error("original backup must remain within ignored repository results")
        summary = publish_portable(output, backup, archive_only=not args.keep_unpacked, resamples=args.resamples)
    else:
        summary = analyze(output, args.resamples)
        write_report(output, summary)
        inventory(output)
    print(json.dumps({name: summary[name] for name in ("planned_observations", "attempted_observations", "valid_observations")}, indent=2))


if __name__ == "__main__":
    main()
