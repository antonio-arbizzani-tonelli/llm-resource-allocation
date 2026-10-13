"""Time native GH/AGH with Python validation of the supplied final decision.

This experiment does not execute the full Python heuristic and therefore does
not claim algorithm/trace parity. It preserves inputs, supplied auxiliaries,
independent feasibility, objective recomputation and native scientific evidence.
"""

import argparse
from pathlib import Path
from time import perf_counter
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from check_cpp_parity import decode_placement, objective_array, serialize_case
from check_openmp_campaign import verify_bitwise
from profile_large_instances import fingerprints, measure_case, measurement, runtime_metadata, save_evidence, save_json, sha256, verify_fingerprints, workload_cases, run_transport
from llm_resource_allocation.validation.placement import validate_placement
from llm_resource_allocation.math.objective import PaperVersion
from scripts.run_azure_replay import _plain


def validate_native_decision(instance, actual):
    """Decode raw supplied x/z/q/u/w/y/v and invoke the shared validator."""
    if actual["status"] != "completed" or not actual["feasible"] or actual["placement"] is None:
        raise ValueError("native result is not a completed independently feasible placement")
    placement = decode_placement(instance, actual["placement"])
    report = validate_placement(instance, placement, PaperVersion.V2)
    if not report.is_feasible:
        raise ValueError("native decisions fail Python independent validation")
    verify_bitwise(objective_array(report.objective_breakdown), actual["objective"], "independent objective")
    return report


def profile(args):
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    cases = [case for case in workload_cases((args.shape[0],), model_count=args.shape[1],
                                           tier_count=args.shape[2], seed=args.seed, load=args.load)
             if case.method == args.method]
    case = cases[0]
    input_path = args.output / "input.txt"
    input_path.write_text(serialize_case(case), encoding="utf-8", newline="")
    before = fingerprints(args, [input_path])
    actual, wall = run_transport(args.binary, case.method, input_path.read_text(encoding="utf-8"),
                                wsl=args.wsl, timeout=args.timeout, omp_wait_policy=args.omp_wait_policy)
    start = perf_counter()
    validation = validate_native_decision(case.instance, actual)
    validation_seconds = perf_counter() - start
    evidence_path = args.output / "native_full.json.gz"
    evidence_sha = save_evidence(evidence_path, actual)
    validation_path = args.output / "python_validation.json.gz"
    validation_sha = save_evidence(validation_path, _plain(validation))
    record = {"classification": "synthetic native performance with independent Python final-decision validation",
              "verification_mode": "independent_final_decision_validation; full Python heuristic not executed",
              "complete": False, "metadata": runtime_metadata(args), "case": case.name,
              "shape": list(args.shape), "method": case.method, "seed": case.seed,
              "load_multiplier": args.load, "beta": case.beta, "unit_convention": "coherent",
              "input": input_path.name, "input_sha256": sha256(input_path),
              "native_full_evidence": evidence_path.name, "native_full_evidence_sha256": evidence_sha,
              "python_validation_evidence": validation_path.name, "python_validation_evidence_sha256": validation_sha,
              "independently_feasible": validation.is_feasible, "objective_agrees_bitwise": True,
              "objective_components_usd": actual["objective"], "python_independent_validation_seconds": validation_seconds,
              "python_full_reference_seconds": None, "python_algorithm_parity": "not_checked",
              "warm_full_measurement": measurement(actual, wall), "fingerprints_before": before}
    save_json(args.output / "profile.json", record)
    args.extra_argument = []
    record.update(measure_case(args, case, input_path.read_text(encoding="utf-8"), actual))
    after = fingerprints(args, [input_path])
    verify_fingerprints(before, after)
    record.update(complete=True, fingerprints_after=after, fingerprints_verified_unchanged=True)
    save_json(args.output / "profile.json", record)
    print(f"{case.name}: Python final decision feasible, objective bitwise equal; {len(record['samples'])} native samples", flush=True)
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shape", type=int, nargs=3, required=True)
    parser.add_argument("--method", choices=("gh", "agh"), required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--baseline-source-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wsl")
    parser.add_argument("--seed", type=int, default=37)
    parser.add_argument("--load", type=float, default=200)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=1800)
    parser.add_argument("--build-description", required=True)
    args = parser.parse_args()
    if args.repeats < 2 or args.timeout <= 0:
        parser.error("at least two samples and a positive native timeout are required")
    args.profile_binary = None
    args.omp_wait_policy = "active"
    profile(args)
