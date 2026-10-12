"""Verify independent-case OpenMP campaigns against serial and Python evidence.

Each job retains its original GH/AGH seed, algorithm ordering and validation.
The campaign preserves manifest order, even when workers finish out of order.
All inputs here are synthetic verification evidence, not paper replication.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path
import platform
import subprocess
from time import perf_counter

from check_cpp_parity import (
    ROOT, ParityCase, check_case, executable_command, linux_path,
    run_cpp, serialize_case, verification_cases,
)

OMP_ENVIRONMENT = {"OMP_DYNAMIC": "FALSE", "OMP_PROC_BIND": "close", "OMP_PLACES": "cores"}
TIMING_FIELDS = {"algorithm_seconds", "repeat_seconds"}


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def verify_bitwise(expected, actual, label="case"):
    """Compare complete serial evidence, including IEEE signed-zero distinctions."""
    if isinstance(expected, dict):
        if not isinstance(actual, dict) or expected.keys() != actual.keys():
            raise AssertionError(f"{label}: evidence keys differ")
        for key, value in expected.items():
            verify_bitwise(value, actual[key], f"{label}.{key}")
    elif isinstance(expected, list):
        if not isinstance(actual, list) or len(expected) != len(actual):
            raise AssertionError(f"{label}: evidence lengths differ")
        for index, (left, right) in enumerate(zip(expected, actual, strict=True)):
            verify_bitwise(left, right, f"{label}[{index}]")
    elif isinstance(expected, (int, float)) and not isinstance(expected, bool):
        if not isinstance(actual, (int, float)) or isinstance(actual, bool):
            raise AssertionError(f"{label}: invalid numeric evidence")
        if not math.isfinite(expected) or not math.isfinite(actual):
            raise AssertionError(f"{label}: nonfinite numeric evidence")
        if float(expected).hex() != float(actual).hex():
            raise AssertionError(f"{label}: bitwise numeric mismatch {expected!r} != {actual!r}")
    elif type(actual) is not type(expected) or expected != actual:
        raise AssertionError(f"{label}: evidence mismatch {expected!r} != {actual!r}")


def serial_projection(actual):
    return {key: value for key, value in actual.items() if key not in TIMING_FIELDS}


def validate_measurement(actual, *, schedule, threads, repeat):
    """Validate observed teams and durations before computing any speedup."""
    if actual["schedule"] != schedule or actual["requested_threads"] != threads:
        raise AssertionError("campaign execution configuration differs")
    team = actual["actual_threads"]
    if isinstance(team, bool) or not isinstance(team, int) or not 1 <= team <= threads:
        raise AssertionError("actual_threads must be an integer between 1 and requested_threads")
    if schedule == "serial" and team != 1:
        raise AssertionError("serial campaign must use one actual thread")
    seconds = actual["repeat_seconds"]
    if not isinstance(seconds, list) or len(seconds) != repeat:
        raise AssertionError("repeat_seconds count differs")
    for value in [actual["campaign_seconds"], *seconds]:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise AssertionError("campaign durations must be finite and positive")
    if actual["campaign_seconds"] != min(seconds):
        raise AssertionError("campaign_seconds must be the minimum individual duration")
    if "repeat_threads" in actual:
        teams = actual["repeat_threads"]
        if not isinstance(teams, list) or len(teams) != repeat:
            raise AssertionError("repeat_threads count differs")
        if any(isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= threads
               for value in teams):
            raise AssertionError("repeat_threads must contain bounded positive integer teams")
        if schedule == "serial" and any(value != 1 for value in teams):
            raise AssertionError("serial repeat_threads must all equal one")
        if teams[seconds.index(min(seconds))] != team:
            raise AssertionError("actual_threads must describe the minimum-duration repeat")


def verify_cases(cases, expected, actual, *, summary=False):
    if len(actual["cases"]) != len(cases):
        raise AssertionError("campaign case count differs")
    for case, reference, supplied in zip(cases, expected, actual["cases"], strict=True):
        if supplied.get("name") != case.name or supplied.get("method") != case.method:
            raise AssertionError("campaign manifest order or case identity differs")
        projection = {key: value for key, value in supplied.items() if key not in {"name", "method"}}
        if summary:
            # The summary only suppresses transport of large evidence. Full
            # algorithm/validation work still runs inside the timed campaign.
            reference = {key: reference[key] for key in ("status", "feasible", "objective")}
        verify_bitwise(reference, projection, case.name)


def quoted_token(value):
    """Encode C++ std::quoted tokens, preserving Unicode and control characters.

    std::quoted removes only its backslash escape character. JSON escapes such
    as \\u00e9 or \\n would therefore change the scientific name or input path.
    """
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def write_manifest(cases, directory, *, wsl=None):
    """Prepare and retain immutable numeric jobs before a measured invocation."""
    directory.mkdir(parents=True, exist_ok=True)
    lines = ["PACS_CAMPAIGN 1", str(len(cases))]
    for index, case in enumerate(cases):
        path = (directory / f"{index:03d}_{case.method}.txt").resolve()
        path.write_text(serialize_case(case), encoding="utf-8")
        exposed = linux_path(path) if wsl else str(path)
        lines.append(f"{case.method} {quoted_token(case.name)} {quoted_token(exposed)}")
    manifest = directory / "manifest.txt"
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="")
    return manifest


def run_campaign(binary, manifest, *, schedule, threads, repeat=1, summary=False, wsl=None, timeout=300):
    arguments = ["--threads", str(threads), "--schedule", schedule, "--repeat", str(repeat)]
    if summary:
        arguments.append("--summary")
    command = executable_command(binary, arguments, wsl=wsl, cwd=ROOT)
    environment = None
    if wsl:
        position = command.index("--exec") + 1
        command[position:position] = ["env", *(f"{key}={value}" for key, value in OMP_ENVIRONMENT.items())]
    else:
        # A child-only copy avoids changing the coordinator's process environment.
        import os
        environment = {**os.environ, **OMP_ENVIRONMENT}
    start = perf_counter()
    # Raw UTF-8 bytes preserve literal CR/LF inside quoted tokens through both
    # file reading and Windows child pipes, without locale/newline conversion.
    process = subprocess.run(command, input=manifest.read_bytes(),
                             capture_output=True, timeout=timeout,
                             check=False, cwd=None if wsl else ROOT, env=environment)
    wall = perf_counter() - start
    if process.returncode:
        diagnostic = process.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"campaign exited {process.returncode}: {diagnostic}")
    actual = json.loads(process.stdout)
    validate_measurement(actual, schedule=schedule, threads=threads, repeat=repeat)
    return actual, wall


def campaign_verification_cases():
    available = {case.name: case for case in verification_cases(random_count=0)}
    names = ("minimal_coherent_agh", "frozen_batch_d0039_gh", "phase1_zero_cap_agh",
             "heterogeneous_coherent_gh", "minimal_coherent_gh", "frozen_batch_d0039_agh")
    cases = [available[name] for name in names]
    # Exercise the real manifest/JSON boundary under every tested schedule.
    cases[0] = replace(cases[0], name='café "AGH"\nverification')
    # Repeated inputs exercise per-worker RNG ownership. Different signed and
    # large seeds also ensure transport does not truncate scientific provenance.
    base = available["scaling_(4, 3, 3)_200.0_agh"]
    for index, seed in enumerate((37, 37, -37, 2**65 + 11)):
        cases.append(replace(base, name=f"seeded_agh_{index}_{seed}", seed=seed))
    return tuple(cases)


def serial_references(binary, cases, *, wsl=None, python_indices=()):
    references = []
    for index, case in enumerate(cases):
        actual, _ = run_cpp(binary, case, wsl=wsl)
        if index in python_indices:
            check_case(case, actual)
        references.append(serial_projection(actual))
    return references


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "cpp/build/release/pacs_campaign")
    parser.add_argument("--serial-binary", type=Path, default=ROOT / "cpp/build/release/pacs_serial")
    parser.add_argument("--wsl")
    parser.add_argument("--output", type=Path, default=ROOT / "results/openmp_campaign_verification")
    parser.add_argument("--threads", type=int, nargs="+", default=[1, 2, 4, 8])
    parser.add_argument("--repeat", type=int, default=2)
    args = parser.parse_args()
    if args.repeat < 1 or any(n < 1 for n in args.threads):
        parser.error("thread and repetition counts must be positive")
    cases = campaign_verification_cases()
    manifest = write_manifest(cases, args.output / "inputs", wsl=args.wsl)
    references = serial_references(args.serial_binary, cases, wsl=args.wsl, python_indices=range(len(cases)))
    if not any(reference["feasible"] for reference in references) or not any(not reference["feasible"] for reference in references):
        raise AssertionError("verification campaign must include feasible and infeasible outputs")
    settings = [("serial", 1), *((schedule, threads) for schedule in ("static", "dynamic") for threads in args.threads)]
    records = []
    for schedule, threads in settings:
        actual, wall = run_campaign(args.binary, manifest, schedule=schedule, threads=threads,
                                    repeat=args.repeat, wsl=args.wsl)
        verify_cases(cases, references, actual)
        path = args.output / f"{schedule}_{threads}.json"
        save_json(path, actual)
        records.append({"schedule": schedule, "requested_threads": threads,
                        "actual_threads": actual["actual_threads"], "passed": True,
                        "case_count": len(cases), "process_wall_seconds": wall,
                        "evidence": path.name})
        print(f"campaign parity: {schedule}/{threads} requested, {actual['actual_threads']} actual; {len(cases)} pass", flush=True)
    save_json(args.output / "serial_reference.json", references)
    save_json(args.output / "verification.json", {
        "classification": "synthetic independent-case verification; not paper numerical replication",
        "python": platform.python_version(), "comparison": "complete serial JSON evidence, bitwise numbers",
        "python_independently_checked_cases": len(cases), "omp_environment": OMP_ENVIRONMENT,
        "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "total_case_comparisons": sum(record["case_count"] for record in records), "runs": records,
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
