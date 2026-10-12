"""Compare the serial C++ port with the trusted Python scientific reference.

Inputs are synthetic verification fixtures. Supplied C++ x/z/q/u/w/y/v are
decoded unchanged and checked by the backend-neutral Python validator; no
decision is repaired. Comparison tolerances below concern cross-language
reporting only and never change scientific acceptance or validator policy.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
import hashlib
import json
import math
from functools import partial
from pathlib import Path
import platform
from random import Random
import subprocess
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from llm_resource_allocation.algorithms import (
    GHPhase1Config, build_seeded_random_agh_ordering, run_agh,
    run_agh_consolidation_scan, run_agh_relocate, run_gh,
)
from llm_resource_allocation.data import (
    make_coherent_tiny_instance, make_heterogeneous_tiny_instance,
    make_minimal_tiny_instance, make_parallelism_tradeoff_tiny_instance,
)
from llm_resource_allocation.data.scaling_experiment_instances import make_scaling_experiment_case
from llm_resource_allocation.domain import ProblemInstance, UnitConvention, validate_problem_instance
from llm_resource_allocation.math.objective import PaperVersion
from llm_resource_allocation.math.parallelism import ParallelismDecisionState
from llm_resource_allocation.math.placement import PlacementDecisionState
from llm_resource_allocation.math.routing import RoutingDecisionState
from llm_resource_allocation.validation.placement import validate_placement

ARRAY_NAMES = ("x", "z", "q", "u", "w", "y", "v")
OBJECTIVE_NAMES = (
    "gpu_rental_cost", "model_storage_cost", "data_storage_cost",
    "delay_penalty", "unmet_demand_penalty",
)
PARITY_ATOL = 1e-10
PARITY_RTOL = 1e-11


@dataclass(frozen=True)
class ParityCase:
    name: str
    instance: ProblemInstance
    method: str = "gh"
    beta: float = 0.8
    seed: int = 37
    version: PaperVersion = PaperVersion.V2
    placement: PlacementDecisionState | None = None


def decision_keys(instance):
    """Return each dense lattice in the C++ transport's semantic order."""
    routes = tuple((i, j, k) for i in instance.query_ids
                   for j in instance.model_ids for k in instance.gpu_tier_ids)
    pairs = tuple((j, k) for j in instance.model_ids for k in instance.gpu_tier_ids)
    configs = tuple((j, tier.id, c.tensor_parallel_degree, c.pipeline_parallel_depth)
                    for j in instance.model_ids for tier in instance.gpu_tiers
                    for c in tier.parallelism_configs)
    products = tuple((i, *key) for i in instance.query_ids for key in configs)
    return {"x": routes, "z": routes, "q": pairs, "u": instance.query_ids,
            "w": configs, "y": pairs, "v": products}


def placement_arrays(instance, placement):
    mappings = (placement.routing_fractions, placement.admission_indicators,
                placement.deployment_indicators, placement.unmet_fractions,
                placement.configuration_selectors, placement.gpu_counts,
                placement.auxiliary_products)
    keys = decision_keys(instance)
    return {name: [mapping.get(key, 0.0) for key in keys[name]]
            for name, mapping in zip(ARRAY_NAMES, mappings, strict=True)}


def decode_placement(instance, arrays):
    """Preserve all supplied decisions, including the independent auxiliaries."""
    keys = decision_keys(instance)
    mappings = {}
    for name in ARRAY_NAMES:
        values = arrays[name]
        if len(values) != len(keys[name]):
            raise AssertionError(f"{name}: expected {len(keys[name])} entries, got {len(values)}")
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
               for v in values):
            raise AssertionError(f"{name}: expected finite numeric decisions")
        mappings[name] = dict(zip(keys[name], values, strict=True))
    routing = RoutingDecisionState(mappings["x"], mappings["z"], mappings["q"], mappings["u"])
    parallelism = ParallelismDecisionState(routing, mappings["w"], mappings["y"])
    return PlacementDecisionState(parallelism, mappings["v"])


def _row(values):
    return " ".join(str(value) if isinstance(value, int) else format(value, ".17g")
                    for value in values)


def serialize_case(case):
    """Versioned numeric boundary; the C++ core does not parse Python objects."""
    instance = case.instance
    validate_problem_instance(instance)
    lines = ["PACS_GH_AGH 1", _row((*instance.dimensions, int(instance.uses_coherent_units),
                                   1 if case.version is PaperVersion.V1 else 2)),
             _row((instance.storage_price_usd_per_gb_hour, instance.cost_budget_usd,
                   instance.storage_capacity_gb, instance.horizon_hours,
                   instance.compute_utilization, instance.seconds_per_hour,
                   instance.data_residency_hours))]
    for q in instance.queries:
        lines.append(_row((q.arrival_rate_per_hour, q.input_tokens, q.output_tokens,
                           q.storage_gb_per_token, q.delay_slo_seconds, q.error_slo,
                           q.delay_penalty_usd_per_millisecond_query,
                           q.unmet_penalty_usd_per_hour, q.max_unmet_fraction)))
    for model in instance.models:
        lines.append(_row((model.weight_gb, model.kv_cache_gb_per_token)))
    for tier in instance.gpu_tiers:
        configs = tier.parallelism_configs
        lines.append(_row((tier.memory_capacity_gb, tier.compute_throughput_tflops,
                           tier.hourly_rental_usd, len(configs),
                           *(value for c in configs for value in
                             (c.tensor_parallel_degree, c.pipeline_parallel_depth)))))
    for i, j, k in decision_keys(instance)["x"]:
        multiplier = next(t.quantization_error_multiplier for t in instance.gpu_tiers if t.id == k)
        lines.append(_row((instance.base_error_rate[i, j] * multiplier,
                           instance.compute_delay_seconds_per_token[i, j, k],
                           instance.communication_delay_seconds_per_token[i, j, k],
                           instance.compute_gflop_per_token[i, j, k],
                           instance.kv_cache_residency_seconds[i, j, k])))
    lines.append(f"{case.beta:.17g} {case.seed}")
    lines.append(str(int(case.placement is not None)))
    if case.placement is not None:
        arrays = placement_arrays(instance, case.placement)
        lines.extend(_row(arrays[name]) for name in ARRAY_NAMES)
    return "\n".join(lines) + "\n"


def linux_path(path):
    """Translate a local Windows path for a WSL compiler/runner boundary."""
    value = str(path)
    if value.startswith("/"):
        return value
    resolved = Path(path).resolve()
    if resolved.drive:
        return "/mnt/" + resolved.drive[0].lower() + resolved.as_posix()[2:]
    return str(resolved)


def executable_command(binary, arguments, wsl=None, cwd=None):
    if wsl:
        command = ["wsl", "-d", wsl]
        if cwd is not None:
            command.extend(("--cd", linux_path(cwd)))
        return [*command, "--exec", linux_path(binary), *arguments]
    return [str(Path(binary).resolve()), *arguments]


def run_cpp(binary, case, *, repeat=1, summary=False, timeout=120, wsl=None,
            cwd=None, extra_arguments=()):
    return run_cpp_transport(binary, case.method, serialize_case(case), repeat=repeat,
                             summary=summary, timeout=timeout, wsl=wsl, cwd=cwd,
                             extra_arguments=extra_arguments)


def run_cpp_transport(binary, method, transport, *, repeat=1, summary=False,
                      timeout=120, wsl=None, cwd=None, extra_arguments=()):
    """Run either a live case or an unchanged frozen numeric transport."""
    arguments = [method, "--repeat", str(repeat), *extra_arguments]
    if summary:
        arguments.append("--summary")
    command = executable_command(binary, arguments, wsl=wsl, cwd=cwd)
    start = perf_counter()
    process = subprocess.run(command, input=transport, text=True,
                             capture_output=True, timeout=timeout, check=False,
                             cwd=None if wsl else cwd)
    elapsed = perf_counter() - start
    if process.returncode:
        raise RuntimeError(f"C++ exited {process.returncode}: {process.stderr.strip()}")
    return json.loads(process.stdout), elapsed


def objective_array(objective):
    return None if objective is None else [getattr(objective, name) for name in OBJECTIVE_NAMES]


def python_gh_trace(instance, result):
    keys = decision_keys(instance)
    pairs = keys["q"]
    selected = []
    for iteration in result.phase1_result.iterations:
        candidate = iteration.ranked_candidates[0].coverage
        pair_index = pairs.index((candidate.model_id, candidate.tier_id))
        tier = next(t for t in instance.gpu_tiers if t.id == candidate.tier_id)
        selected.append([pair_index, tier.parallelism_configs.index(candidate.common_configuration)])
    queries = []
    for trace in result.phase2_result.query_traces:
        process = trace.query_process_result
        attempts = []
        for attempt in process.attempts:
            state = attempt.state_after
            attempts.append({"position": attempt.ranked_candidate_index,
                "allocation": attempt.commit_result.diagnostic.allocation.proposed_routing_fraction,
                "committed": attempt.committed, "budget": state.accumulated_budget_cost_usd,
                "x": [state.routing_fraction_by_candidate.get(key, 0.0) for key in keys["x"]],
                "remaining": [state.remaining_demand_by_query[i] for i in instance.query_ids]})
        queries.append({"query": instance.query_ids.index(trace.query_id),
                        "ranked": [pairs.index(c.pair_id) for c in process.query_evaluation.ranked_candidates],
                        "attempts": attempts, "termination": process.termination_reason.value})
    return {"phase1_termination": result.phase1_result.termination_reason.value,
            "phase1_selected": selected, "queries": queries}


def make_python_runner(case):
    """Prepare unchanged input/configuration outside a timed algorithm call."""
    options = {"paper_version": case.version}
    config = GHPhase1Config(case.beta)
    if case.method == "gh":
        return partial(run_gh, case.instance, config, **options)
    if case.method == "agh":
        return partial(run_agh, case.instance, config, random_seed=case.seed, **options)
    if case.method == "relocate":
        return partial(run_agh_relocate, case.instance, case.placement, **options)
    if case.method == "consolidate":
        return partial(run_agh_consolidation_scan, case.instance, case.placement, **options)
    if case.method == "validate":
        return partial(validate_placement, case.instance, case.placement, **options)
    raise ValueError(f"unknown method {case.method}")


def python_algorithm(case):
    """Run only the public scientific authority, excluding transport conversion."""
    return make_python_runner(case)()


def python_reference(case):
    """Map trusted public result evidence into the C++ comparison contract."""
    result = python_algorithm(case)
    extra = {}
    if case.method == "gh":
        placement, report = result.placement_decisions, result.validation_report
        status = result.completion_status.value
        extra = {"gh_trace": python_gh_trace(case.instance, result)}
    elif case.method == "agh":
        placement, report = result.final_placement, result.final_validation
        status = result.completion_status.value
        traces = result.multistart_result.start_traces
        incumbent_index = next((trace.schedule_index for trace in reversed(traces)
                                if trace.incumbent_changed), -1)
        extra = {"executed_count": result.executed_start_count,
                 "termination": result.termination_reason.value,
                 "incumbent_index": incumbent_index,
                 "orders": [[case.instance.query_ids.index(i) for i in trace.ordering.query_ids]
                            for trace in traces],
                 "counters": [t.consecutive_nonimprovements_after for t in traces],
                 "costs": [t.candidate_objective for t in traces],
                 "comparisons": [t.comparison_outcome.value for t in traces]}
    elif case.method == "relocate":
        placement = result.placement_after
        report = result.pass_results[-1].validation_after
        status = result.termination_reason.value
        extra = {"accepted_count": result.accepted_move_count,
                 "passes_executed": result.passes_executed}
    elif case.method == "consolidate":
        placement, report = result.placement_after, result.validation_after
        status = "completed"
        extra = {"accepted_count": result.accepted_source_count}
    elif case.method == "validate":
        placement = case.placement
        report = result
        status = "valid" if report.is_feasible else "invalid"
    return {"placement": None if placement is None else placement_arrays(case.instance, placement),
            "objective": None if report is None else objective_array(report.objective_breakdown),
            "feasible": report is not None and report.is_feasible,
            "status": status, **extra}


def compare_numeric(expected, actual, label):
    if len(expected) != len(actual):
        raise AssertionError(f"{label}: lengths differ ({len(expected)} != {len(actual)})")
    for index, (left, right) in enumerate(zip(expected, actual, strict=True)):
        if not isinstance(right, (int, float)) or isinstance(right, bool) or not math.isfinite(right):
            raise AssertionError(f"{label}[{index}]: invalid number {right!r}")
        if not math.isclose(left, right, abs_tol=PARITY_ATOL, rel_tol=PARITY_RTOL):
            raise AssertionError(f"{label}[{index}]: Python {left:.17g} != C++ {right:.17g}")


def compare_structure(expected, actual, label):
    if isinstance(expected, dict):
        for key, value in expected.items():
            compare_structure(value, actual[key], f"{label}.{key}")
    elif isinstance(expected, list):
        if len(expected) != len(actual):
            raise AssertionError(f"{label}: trace lengths differ")
        for index, (left, right) in enumerate(zip(expected, actual, strict=True)):
            compare_structure(left, right, f"{label}[{index}]")
    elif isinstance(expected, float):
        compare_numeric([expected], [actual], label)
    elif expected != actual:
        raise AssertionError(f"{label}: Python {expected!r} != C++ {actual!r}")


def check_reference(expected, actual):
    """Compare the shared live/frozen evidence contract, without regenerating it."""
    if actual["status"].lower() != expected["status"]:
        raise AssertionError(f"status: Python {expected['status']} != C++ {actual['status']}")
    if actual["feasible"] != expected["feasible"]:
        raise AssertionError("reported feasibility differs")
    left, right = expected["placement"], actual["placement"]
    if (left is None) != (right is None):
        raise AssertionError("placement availability differs")
    if left is not None:
        for name in ARRAY_NAMES:
            compare_numeric(left[name], right[name], name)
    if (expected["objective"] is None) != (actual["objective"] is None):
        raise AssertionError("objective availability differs")
    if expected["objective"] is not None:
        compare_numeric(expected["objective"], actual["objective"], "objective")
    if "gh_trace" in expected:
        compare_structure(expected["gh_trace"], actual["gh_trace"], "gh_trace")
    for name in ("executed_count", "incumbent_index", "accepted_count", "passes_executed"):
        if name in expected and actual.get(name) != expected[name]:
            raise AssertionError(f"{name}: Python {expected[name]} != C++ {actual.get(name)}")
    if "termination" in expected and actual["termination"].lower() != expected["termination"]:
        raise AssertionError("AGH schedule termination differs")
    if "orders" in expected:
        starts = actual["starts"]
        if [s["order"] for s in starts] != expected["orders"]:
            raise AssertionError("AGH executed query permutations differ")
        if [s["counter"] for s in starts] != expected["counters"]:
            raise AssertionError("AGH ordered nonimprovement counters differ")
        for index, (cost, start) in enumerate(zip(expected["costs"], starts, strict=True)):
            for field in ("cost", "comparison"):
                if field not in start:
                    raise AssertionError(f"start[{index}] missing mandatory {field}")
            if not isinstance(start["comparison"], str):
                raise AssertionError(f"start[{index}] invalid comparison")
            actual_cost = start["cost"]
            if (cost is None) != (actual_cost is None):
                raise AssertionError(f"start[{index}] objective availability differs")
            if cost is not None:
                compare_numeric([cost], [actual_cost], f"start[{index}] cost")
        if [s["comparison"].lower() for s in starts] != expected["comparisons"]:
            raise AssertionError("AGH strict incumbent comparisons differ")


def check_case(case, actual):
    expected = python_reference(case)
    check_reference(expected, actual)
    if actual["placement"] is not None:
        placement = decode_placement(case.instance, actual["placement"])
        report = validate_placement(case.instance, placement, paper_version=case.version)
        if report.is_feasible != actual["feasible"]:
            raise AssertionError("C++ decisions fail independent Python feasibility classification")
        independent_objective = objective_array(report.objective_breakdown)
        if (independent_objective is None) != (actual["objective"] is None):
            raise AssertionError("independent objective availability differs")
        if independent_objective is not None:
            compare_numeric(independent_objective, actual["objective"], "independent objective")
    return expected


def replay_frozen(binary, directory, *, wsl=None, selectors=None):
    """Supplement live validation with expectations retained in committed goldens."""
    records = []
    for golden_path in sorted(directory.glob("*.json")):
        golden = json.loads(golden_path.read_text(encoding="utf-8"))
        name, method = golden["case"], golden["method"]
        if selectors and not any(label in name for label in selectors):
            continue
        transport_path = golden_path.with_suffix(".txt")
        transport = transport_path.read_text(encoding="utf-8")
        record = {"case": name, "method": method, "reference_source": "frozen_python_golden",
                  "input_sha256": hashlib.sha256(transport.encode()).hexdigest(),
                  "reference_sha256": hashlib.sha256(golden_path.read_bytes()).hexdigest()}
        try:
            actual, wall = run_cpp_transport(binary, method, transport, wsl=wsl)
            expected = golden["reference"]
            check_reference(expected, actual)
            record.update(passed=True, feasible=expected["feasible"], status=expected["status"],
                          cpp_wall_seconds=wall, cpp_algorithm_seconds=actual["algorithm_seconds"],
                          **numerical_difference(expected, actual))
        except (AssertionError, RuntimeError, ValueError, KeyError) as error:
            record.update(passed=False, error=str(error))
            print(f"FAIL frozen {name}: {error}", flush=True)
        records.append(record)
    if not records:
        raise ValueError(f"no matching frozen reference cases in {directory}")
    return records


def numerical_difference(expected, actual):
    """Report differences even when they are inside the parity tolerance."""
    pairs = []
    if expected["placement"] is not None:
        for name in ARRAY_NAMES:
            pairs.extend(zip(expected["placement"][name], actual["placement"][name], strict=True))
    if expected["objective"] is not None:
        pairs.extend(zip(expected["objective"], actual["objective"], strict=True))
    return {"compared_numeric_values": len(pairs),
            "bitwise_difference_count": sum(float(left).hex() != float(right).hex() for left, right in pairs),
            "max_absolute_difference": max((abs(left-right) for left, right in pairs), default=0.0)}


def verification_cases(random_count=6):
    """Trusted fixtures plus explicitly seeded, modest synthetic perturbations."""
    from test_gh import make_residual_instance, make_two_candidate_instance
    from test_gh_phase1 import make_loop_instance
    from test_agh_relocate import make_relocate_instance, make_relocate_state
    from test_agh_consolidation import make_consolidation_instance, make_consolidation_state

    cases = []
    fixtures = (
        ("minimal_literal", make_minimal_tiny_instance(), 0.8),
        ("minimal_coherent", make_coherent_tiny_instance(), 0.8),
        ("parallelism", make_parallelism_tradeoff_tiny_instance(), 0.8),
        ("heterogeneous_literal", make_heterogeneous_tiny_instance(), 0.8),
        ("heterogeneous_coherent", replace(make_heterogeneous_tiny_instance(),
                                           unit_convention=UnitConvention.COHERENT), 0.8),
        ("frozen_batch_d0039", make_two_candidate_instance(), 0.0),
        ("feasible_residual", make_residual_instance(), 0.0),
        ("phase1_loop", make_loop_instance(), 0.8),
        ("phase1_zero_cap", make_loop_instance(), 0.0),
    )
    for name, instance, beta in fixtures:
        for method in ("gh", "agh"):
            cases.append(ParityCase(f"{name}_{method}", instance, method, beta))
    for version in PaperVersion:
        base = make_minimal_tiny_instance() if version is PaperVersion.V1 else make_coherent_tiny_instance()
        instance = replace(base, horizon_hours=2.0,
                           queries=(replace(base.queries[0],
                                            max_unmet_fraction=1.0),), cost_budget_usd=0.1)
        cases.append(ParityCase(f"period_unmet_{version.value}", instance,
                                beta=0.0, version=version))
    for dims, load in (((4, 2, 2), 1.0), ((4, 3, 3), 200.0)):
        instance = replace(make_scaling_experiment_case(*dims, load_multiplier=load).instance,
                           unit_convention=UnitConvention.COHERENT)
        for method in ("gh", "agh"):
            cases.append(ParityCase(f"scaling_{dims}_{load}_{method}", instance, method))
    for seed in range(random_count):
        rng = Random(seed)
        instance = replace(make_scaling_experiment_case(3, 3, 2).instance,
                           unit_convention=UnitConvention.COHERENT)
        instance = replace(instance,
            queries=tuple(replace(q, arrival_rate_per_hour=q.arrival_rate_per_hour*rng.uniform(.5, 2),
                                  delay_slo_seconds=q.delay_slo_seconds*rng.uniform(.3, 1.5),
                                  error_slo=q.error_slo*rng.uniform(.5, 1.5))
                          for q in instance.queries),
            compute_delay_seconds_per_token={k: v*rng.uniform(.5, 1.5)
                                             for k, v in instance.compute_delay_seconds_per_token.items()})
        for method in ("gh", "agh"):
            cases.append(ParityCase(f"seeded_perturbation_{seed}_{method}", instance, method,
                                    seed=(-seed if seed % 2 else 2**65+seed)))
    for label, kwargs in (("improves", {}), ("worse", {"source_weight": 1, "destination_weight": 4}),
                          ("infeasible", {"destination_compute": 1e8}),
                          ("delay_improves", {"source_delay": .4, "destination_delay": .1})):
        instance = make_relocate_instance(**kwargs)
        cases.append(ParityCase(f"relocate_{label}", instance, "relocate",
                                placement=make_relocate_state(instance)))
    instance = make_consolidation_instance(("source", "destination"), query_ids=("q_0", "q_1"))
    for label, routes in (("whole_routes", {("q_0", "source"): .2, ("q_1", "source"): .3}),
                          ("zero_traffic", {("q_0", "destination"): .5}),
                          ("shared", {("q_0", "source"): .2, ("q_0", "destination"): .4})):
        state = make_consolidation_state(instance, routes)
        cases.append(ParityCase(f"consolidate_{label}", instance, "consolidate", placement=state))
    # Independently supplied v is deliberately inconsistent: validator parity
    # must detect it instead of repairing it to x*w.
    good = make_relocate_state(make_relocate_instance())
    bad = replace(good, auxiliary_products={k: 0.0 for k in good.auxiliary_products})
    cases.append(ParityCase("supplied_bad_auxiliary", make_relocate_instance(), "validate", placement=bad))
    return tuple(cases)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "cpp/build/release/pacs_serial")
    parser.add_argument("--wsl", help="run the Linux executable through this WSL distribution")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--export-dir", type=Path)
    parser.add_argument("--random-count", type=int, default=6)
    parser.add_argument("--skip-rng", action="store_true", help="skip explicit seeded shuffle checks")
    parser.add_argument("--case", action="append", help="select names containing this substring")
    frozen_mode = parser.add_mutually_exclusive_group()
    frozen_mode.add_argument("--frozen", action="store_true", help="also replay committed Python goldens")
    frozen_mode.add_argument("--frozen-only", action="store_true", help="replay only committed Python goldens")
    args = parser.parse_args()
    if args.random_count < 0:
        parser.error("random-count must be nonnegative")
    records = []
    start = perf_counter()
    for case in (() if args.frozen_only else verification_cases(args.random_count)):
        if args.case and not any(name in case.name for name in args.case):
            continue
        transport = serialize_case(case)
        if args.export_dir:
            args.export_dir.mkdir(parents=True, exist_ok=True)
            (args.export_dir / (case.name.replace(" ", "") + ".txt")).write_text(transport, encoding="utf-8")
        try:
            actual, wall = run_cpp(args.binary, case, wsl=args.wsl)
            expected = check_case(case, actual)
            if args.export_dir:
                golden = {"classification": "synthetic cross-language verification",
                          "case": case.name, "method": case.method,
                          "unit_convention": case.instance.unit_convention.value,
                          "paper_version": case.version.value,
                          "seed": case.seed, "reference": expected}
                (args.export_dir / (case.name.replace(" ", "") + ".json")).write_text(
                    json.dumps(golden, indent=2, allow_nan=False)+"\n", encoding="utf-8")
            records.append({"case": case.name, "method": case.method, "passed": True,
                            "reference_source": "live_python",
                            "feasible": expected["feasible"], "status": expected["status"],
                            "input_sha256": hashlib.sha256(transport.encode()).hexdigest(),
                            "cpp_wall_seconds": wall, "cpp_algorithm_seconds": actual["algorithm_seconds"],
                            **numerical_difference(expected, actual)})
        except (AssertionError, RuntimeError, ValueError, KeyError) as error:
            records.append({"case": case.name, "method": case.method, "passed": False,
                            "error": str(error)})
            print(f"FAIL {case.name}: {error}", flush=True)
    if not args.frozen_only and not args.skip_rng and not args.case:
        instance = replace(make_scaling_experiment_case(9, 2, 2).instance,
                           unit_convention=UnitConvention.COHERENT)
        for seed in (-37, 0, 37, 2**65+11, -(2**200)):
            for draw in (0, 3, 19):
                name = f"shuffle_seed{seed}_draw{draw}"
                try:
                    case = ParityCase(name, instance, "rng", seed=seed)
                    actual, wall = run_cpp(args.binary, case, wsl=args.wsl,
                                          extra_arguments=("--draw", str(draw)))
                    ordering = build_seeded_random_agh_ordering(instance.query_ids,
                                                                seed=seed, random_start_index=draw)
                    expected = [instance.query_ids.index(i) for i in ordering.query_ids]
                    if actual["order"] != expected:
                        raise AssertionError(f"shuffle: Python {expected} != C++ {actual['order']}")
                    records.append({"case": name, "method": "rng", "passed": True,
                                    "cpp_wall_seconds": wall})
                except (AssertionError, RuntimeError, ValueError, KeyError) as error:
                    records.append({"case": name, "method": "rng", "passed": False,
                                    "error": str(error)})
                    print(f"FAIL {name}: {error}", flush=True)
    if args.frozen or args.frozen_only:
        records.extend(replay_frozen(args.binary, ROOT / "cpp/tests/fixtures",
                                     wsl=args.wsl, selectors=args.case))
    passed = sum(r["passed"] for r in records)
    result = {"classification": "synthetic cross-language verification; not paper numerical replication",
              "python": platform.python_version(), "binary": str(args.binary.resolve()),
              "parity_atol": PARITY_ATOL, "parity_rtol": PARITY_RTOL,
              "reference_mode": "frozen_only" if args.frozen_only else "live_and_frozen" if args.frozen else "live",
              "elapsed_seconds": perf_counter()-start, "passed": passed,
              "total": len(records), "cases": records}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(f"C++ parity: {passed}/{len(records)} passed in {result['elapsed_seconds']:.3f}s")
    return 0 if records and passed == len(records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
