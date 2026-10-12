"""Evidence and measurement contracts for larger-instance profiling."""

from copy import deepcopy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import os
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import profile_large_instances as profiling
from check_cpp_parity import ParityCase, serialize_case
from llm_resource_allocation.data import make_coherent_tiny_instance


def observed():
    return {"status": "completed", "feasible": True, "objective": [1.0, 2.0, 3.0, 4.0, 5.0],
            "placement": None, "residuals": [], "algorithm_seconds": 1.0, "repeat_seconds": [1.0]}


def sample_gprof():
    symbol = profiling.VALIDATE_SYMBOL
    return f"""Flat profile:

Each sample counts as 0.01 seconds.
  %   cumulative   self              self     total
 time   seconds   seconds    calls  ms/call  ms/call  name
 70.00      1.40     1.40   400000     0.00     0.00  {symbol}::{{lambda(...)#1}}::operator()(...) const
 10.00      1.60     0.20      200     1.00     6.50  {symbol}
 20.00      2.00     0.40                             _init

Call graph (explanation follows)
[3]     65.0    0.20    1.10     200         {symbol} [3]
"""


class LargeWorkloadTests(unittest.TestCase):
    def test_fixed_dimension_load_units_seed_and_method_matrix(self):
        cases = profiling.workload_cases()
        self.assertEqual([case.instance.dimensions for case in cases],
                         [(16, 4, 4), (16, 4, 4), (32, 4, 4), (32, 4, 4), (64, 4, 4), (64, 4, 4)])
        self.assertEqual([case.method for case in cases], ["gh", "agh"] * 3)
        self.assertTrue(all(case.instance.uses_coherent_units for case in cases))
        self.assertTrue(all(case.seed == 37 and case.version.value == "v2" for case in cases))
        self.assertEqual(cases[0].instance, cases[1].instance)
        self.assertEqual(serialize_case(cases[0]), serialize_case(profiling.workload_cases()[0]))

    def test_configured_seed_and_load_are_retained_in_transport(self):
        cases = profiling.workload_cases((2,), seed=2**65 + 11, load=100.0)
        self.assertEqual(cases[0].seed, 2**65 + 11)
        self.assertIn(str(2**65 + 11), serialize_case(cases[0]))
        default = profiling.workload_cases((2,), load=200.0)[0]
        self.assertEqual(default.instance.queries[0].arrival_rate_per_hour,
                         2 * cases[0].instance.queries[0].arrival_rate_per_hour)

    def test_invalid_workload_assumptions_fail_before_execution(self):
        for counts in ((), (16, 16), (True,), (1,), (16.0,)):
            with self.subTest(counts=counts), self.assertRaises(ValueError):
                profiling.workload_cases(counts)
        for load in (0, -1, float("nan"), float("inf"), True):
            with self.subTest(load=load), self.assertRaises(ValueError):
                profiling.workload_cases((2,), load=load)
        with self.assertRaisesRegex(ValueError, "explicit integer"):
            profiling.workload_cases((2,), seed=True)


class LargeMeasurementTests(unittest.TestCase):
    def test_individual_samples_and_unattributed_wall_have_explicit_scope(self):
        actual = observed()
        actual["repeat_seconds"] = [1.0, 9.0]
        result = profiling.measurement(actual, 20.0, repeat=2)
        self.assertEqual(result["cpp_core_seconds"], 1.0)
        self.assertEqual(result["cpp_repeat_seconds"], [1.0, 9.0])
        self.assertEqual(result["unattributed_process_minus_core_seconds"], 10.0)

    def test_invalid_samples_or_different_minimum_are_rejected(self):
        for value in (float("nan"), float("inf"), 0.0, -1.0, True):
            actual = observed()
            actual["repeat_seconds"] = [value]
            with self.subTest(value=value), self.assertRaises(AssertionError):
                profiling.measurement(actual, 2.0)
        actual = observed()
        actual["algorithm_seconds"] = 2.0
        with self.assertRaisesRegex(AssertionError, "minimum individual"):
            profiling.measurement(actual, 3.0)
        with self.assertRaisesRegex(AssertionError, "repeat count"):
            profiling.measurement(observed(), 3.0, repeat=2)

    def test_instrumentation_is_excluded_explicitly_and_retained_in_samples(self):
        actual = observed()
        actual.update(phase_seconds={"parse": 0.1, "destroy": 0.2},
                      validation_statistics={"calls": 5, "mean_seconds": 0.01},
                      validation_execution={"mode": "omp", "threads": 4})
        self.assertEqual(profiling.science_projection(actual), profiling.science_projection(observed()))
        sample = profiling.measurement(actual, 3.0)
        for field in ("phase_seconds", "validation_statistics", "validation_execution"):
            self.assertEqual(sample[field], actual[field])
        actual["new_unknown_evidence"] = 1
        self.assertIn("new_unknown_evidence", profiling.science_projection(actual))

    def test_nonfinite_phase_seconds_are_rejected(self):
        actual = observed()
        actual["phase_seconds"] = {"parse": float("nan")}
        with self.assertRaisesRegex(AssertionError, "phase_seconds"):
            profiling.measurement(actual, 3.0)

    def test_per_repeat_phase_arrays_match_algorithm_samples_and_ownership_destruction(self):
        actual = observed()
        actual["repeat_seconds"] = [1.0, 2.0]
        actual["phase_seconds"] = {"algorithm": [1.0, 2.0], "result_destruction": [0.01, 0.02],
                                   "scientific_json_format": 0.03, "input_parse": 0.04,
                                   "input_destruction": 0.0, "observed_body_before_write": 3.1}
        sample = profiling.measurement(actual, 4.0, repeat=2)
        self.assertEqual(sample["phase_seconds"], actual["phase_seconds"])

    def test_invalid_phase_array_values_counts_or_nested_objects_are_rejected(self):
        for phases in ({"algorithm": [2.0]}, {"algorithm": 1.0},
                       {"result_destruction": []}, {"result_destruction": [0.1, 0.2]},
                       {"result_destruction": 0.1}, {"result_destruction": [float("nan")]},
                       {"result_destruction": [-0.1]}, {"result_destruction": [True]},
                       {"input_parse": {"seconds": 0.1}}, {"input_parse": [[0.1]]}):
            actual = observed()
            actual["phase_seconds"] = phases
            with self.subTest(phases=phases), self.assertRaises(AssertionError):
                profiling.measurement(actual, 3.0)

    def test_summary_checks_retained_residuals_and_status_bitwise(self):
        full = observed()
        full["placement"] = {"x": [1.0]}
        full["gh_trace"] = {"queries": [1]}
        full["residuals"] = [{"slack": 0.0}]
        compact = observed()
        compact["residuals"] = [{"slack": 0.0}]
        profiling.verify_summary(full, compact)
        compact["residuals"][0]["slack"] = -0.0
        with self.assertRaisesRegex(AssertionError, "bitwise"):
            profiling.verify_summary(full, compact)


class GprofEvidenceTests(unittest.TestCase):
    def test_exact_validator_symbol_is_distinguished_from_dominant_lambda(self):
        result = profiling.parse_gprof(sample_gprof(), 4)
        self.assertEqual(result["validate_calls"], 200)
        self.assertEqual(result["validate_calls_per_algorithm"], 50)
        self.assertEqual(result["total_sampled_seconds"], 2.0)
        self.assertEqual(result["validate_flat_self_seconds"], 0.2)
        self.assertAlmostEqual(result["validate_flat_self_seconds_per_call"], 0.001)
        self.assertAlmostEqual(result["validate_inclusive_propagated_seconds_per_call"], 0.0065)
        self.assertEqual(result["sample_interval_seconds"], 0.01)
        self.assertIn("not direct", result["grain_estimate_authority"])

    def test_mismatched_callgraph_count_is_not_reported_as_grain(self):
        report = sample_gprof().replace("1.10     200", "1.10     201")
        with self.assertRaisesRegex(ValueError, "matching exact validator"):
            profiling.parse_gprof(report, 4)

    def test_missing_exact_function_row_cannot_use_lambda_calls(self):
        lines = sample_gprof().splitlines()
        report = "\n".join(line for line in lines if "0.20      200" not in line)
        with self.assertRaisesRegex(ValueError, "exact validator call-count"):
            profiling.parse_gprof(report, 4)

    def test_profile_uses_fresh_directories_until_sample_target_is_reached(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            args = SimpleNamespace(output=Path(temporary), profile_binary=Path("profile"),
                                   gprof_repeat=1, gprof_target_seconds=1.2, wsl=None,
                                   timeout=600, omp_wait_policy="active")
            directories = []

            def execute(binary, method, transport, **kwargs):
                directory = kwargs["cwd"]
                directories.append(directory)
                self.assertFalse((directory / "gmon.out").exists())
                (directory / "gmon.out").write_bytes(b"fresh gmon")
                actual = observed()
                actual["repeat_seconds"] = [1.0] * kwargs["repeat"]
                return actual, float(kwargs["repeat"] + 2)

            insufficient = sample_gprof().replace("1.40", "0.20").replace("1.60", "0.40").replace("2.00", "0.60")
            with patch.object(profiling, "run_transport", side_effect=execute), \
                    patch.object(profiling, "command_output", side_effect=[insufficient, sample_gprof()]):
                profile = profiling.profile_case(args, SimpleNamespace(name="tiny_agh", method="agh"),
                                                 "transport", 1.0, observed())
            self.assertEqual(len(directories), 2)
            self.assertNotEqual(directories[0], directories[1])
            self.assertTrue(profile["target_reached"])
            self.assertEqual(profile["selected"]["total_sampled_seconds"], 2.0)
            self.assertGreater(profile["selected"]["repetitions"], 1)


class ChildEnvironmentTests(unittest.TestCase):
    def test_native_environment_is_child_scoped(self):
        original = os.environ.copy()
        process = SimpleNamespace(returncode=0, stdout=json.dumps(observed()).encode(), stderr=b"")
        with patch.object(profiling.subprocess, "run", return_value=process) as execute:
            actual, _ = profiling.run_transport(Path("binary"), "agh", "transport", omp_wait_policy="passive")
        self.assertEqual(actual, observed())
        self.assertEqual(execute.call_args.kwargs["env"]["OMP_WAIT_POLICY"], "PASSIVE")
        self.assertEqual(execute.call_args.kwargs["env"]["OMP_DYNAMIC"], "FALSE")
        self.assertEqual(dict(os.environ), original)

    def test_wsl_env_prefix_precedes_binary_without_parent_environment_changes(self):
        process = SimpleNamespace(returncode=0, stdout=json.dumps(observed()).encode(), stderr=b"")
        command = ["wsl", "-d", "Ubuntu", "--exec", "/tmp/binary", "agh", "--repeat", "1"]
        with patch.object(profiling, "executable_command", return_value=command), \
                patch.object(profiling.subprocess, "run", return_value=process) as execute:
            profiling.run_transport(Path("binary"), "agh", "transport", wsl="Ubuntu")
        supplied = execute.call_args.args[0]
        self.assertEqual(supplied[4], "env")
        self.assertIn("OMP_WAIT_POLICY=ACTIVE", supplied)
        self.assertIn("OMP_PROC_BIND=close", supplied)
        self.assertGreater(supplied.index("/tmp/binary"), supplied.index("env"))
        self.assertIsNone(execute.call_args.kwargs["env"])


class LargerFingerprintTests(unittest.TestCase):
    def test_snapshot_authority_inputs_and_binaries_are_fingerprinted(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            root = Path(temporary)
            (root / "src").mkdir()
            (root / "scripts").mkdir()
            for name in ("check_cpp_parity.py", "check_openmp_campaign.py"):
                (root / "scripts" / name).write_text("tool", encoding="utf-8")
            (root / "src/domain.py").write_text("domain", encoding="utf-8")
            snapshot = root / "frozen"
            snapshot.mkdir()
            (snapshot / "core.cpp").write_text("original", encoding="utf-8")
            binary = root / "serial"
            binary.write_bytes(b"binary")
            input_path = root / "instance.txt"
            input_path.write_text("transport", encoding="utf-8")
            args = SimpleNamespace(baseline_source_dir=snapshot, binary=binary, profile_binary=None)
            with patch.object(profiling, "ROOT", root):
                before = profiling.fingerprints(args, [input_path])
                # An unrelated live prototype is not the declared compiled source.
                (root / "live.cpp").write_text("prototype", encoding="utf-8")
                profiling.verify_fingerprints(before, profiling.fingerprints(args, [input_path]))
                (snapshot / "core.cpp").write_text("changed", encoding="utf-8")
                with self.assertRaisesRegex(RuntimeError, "changed during"):
                    profiling.verify_fingerprints(before, profiling.fingerprints(args, [input_path]))
                (snapshot / "core.cpp").write_text("original", encoding="utf-8")
                input_path.write_text("changed transport", encoding="utf-8")
                with self.assertRaises(RuntimeError):
                    profiling.verify_fingerprints(before, profiling.fingerprints(args, [input_path]))
                input_path.write_text("transport", encoding="utf-8")
                binary.write_bytes(b"other executable")
                with self.assertRaises(RuntimeError):
                    profiling.verify_fingerprints(before, profiling.fingerprints(args, [input_path]))

    def test_source_inventory_is_required(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            args = SimpleNamespace(baseline_source_dir=Path(temporary), binary=Path("unused"), profile_binary=None)
            with self.assertRaisesRegex(ValueError, r"no C\+\+ source"):
                profiling.fingerprints(args, [])


class LargerStagedRunTests(unittest.TestCase):
    def args(self, directory, *, mode="baseline"):
        source = directory / "snapshot"
        source.mkdir(exist_ok=True)
        (source / "core.cpp").write_text("frozen core", encoding="utf-8")
        binary = directory / "binary"
        binary.write_bytes(b"executable")
        return SimpleNamespace(mode=mode, baseline_source_dir=source, binary=binary,
                               profile_binary=None, output=directory / mode,
                               baseline_output=directory / "baseline", wsl=None,
                               query_counts=[2], seed=37, load=200.0, repeats=3, timeout=600,
                               gprof_repeat=None, gprof_target_seconds=1.2,
                               build_description="test compiler flags", candidate_label="test", omp_wait_policy="active",
                               extra_argument=[])

    def test_reference_is_run_once_then_candidate_uses_retained_goldens(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            root = Path(temporary)
            args = self.args(root)
            case = ParityCase("tiny_gh", make_coherent_tiny_instance())
            expected = {key: observed()[key] for key in ("status", "feasible", "objective", "placement")}
            with patch.object(profiling, "workload_cases", return_value=[case]), \
                    patch.object(profiling, "runtime_metadata", return_value={}), \
                    patch.object(profiling, "run_transport", return_value=(observed(), 3.0)), \
                    patch.object(profiling, "check_case", return_value=expected) as reference, \
                    redirect_stdout(io.StringIO()):
                baseline = profiling.baseline(args)
            self.assertEqual(reference.call_count, 1)
            self.assertEqual(baseline["cases"][0]["reference_calls"], 1)
            self.assertEqual(len(baseline["cases"][0]["samples"]), 3)
            self.assertTrue(baseline["fingerprints_verified_unchanged"])
            replay = self.args(root, mode="candidate")
            replay.output.mkdir()
            replay.extra_argument = ["--validation-mode", "omp", "--validation-threads", "4"]
            instrumented = observed()
            instrumented.update(phase_seconds={"parse": 0.1}, validation_statistics={"calls": 1},
                                validation_execution={"threads": 4})
            with patch.object(profiling, "runtime_metadata", return_value={}), \
                    patch.object(profiling, "run_transport", return_value=(instrumented, 3.0)) as execute, \
                    patch.object(profiling, "check_case", side_effect=AssertionError("Python executed twice")), \
                    redirect_stdout(io.StringIO()):
                candidate = profiling.candidate(replay)
            self.assertTrue(candidate["complete"])
            self.assertTrue(candidate["cases"][0]["full_bitwise_parity"])
            self.assertEqual(candidate["cases"][0]["reference_calls"], 0)
            self.assertEqual(candidate["cases"][0]["core_speedup"], 1)
            self.assertTrue(all(call.kwargs["extra_arguments"] == replay.extra_argument
                                for call in execute.call_args_list))

    def test_candidate_rejects_corrupted_frozen_input_before_executing(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            root = Path(temporary)
            args = self.args(root)
            case = ParityCase("tiny_gh", make_coherent_tiny_instance())
            expected = {key: observed()[key] for key in ("status", "feasible", "objective", "placement")}
            with patch.object(profiling, "workload_cases", return_value=[case]), \
                    patch.object(profiling, "runtime_metadata", return_value={}), \
                    patch.object(profiling, "run_transport", return_value=(observed(), 3.0)), \
                    patch.object(profiling, "check_case", return_value=expected), redirect_stdout(io.StringIO()):
                profiling.baseline(args)
            (args.output / "inputs/tiny_gh.txt").write_text("corrupted", encoding="utf-8")
            replay = self.args(root, mode="candidate")
            with patch.object(profiling, "runtime_metadata", return_value={}), \
                    patch.object(profiling, "run_transport") as execute:
                with self.assertRaisesRegex(RuntimeError, "checksum differs"):
                    profiling.candidate(replay)
            execute.assert_not_called()

    def test_cli_requires_preserved_baseline_and_valid_sample_target(self):
        required = ["--binary", "binary", "--baseline-source-dir", "snapshot", "--output", "candidate",
                    "--build-description", "flags"]
        for extra in (["--mode", "candidate"], ["--gprof-target-seconds", "0.5"], ["--repeats", "0"],
                      ["--query-counts", "16", "16"]):
            with self.subTest(extra=extra), redirect_stdout(io.StringIO()), \
                    patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit):
                profiling.parse_args([*required, *extra])
        args = profiling.parse_args([*required, "--mode", "candidate", "--baseline-output", "baseline",
                                    "--extra-argument=--validation-mode", "--extra-argument=omp"])
        self.assertEqual(args.extra_argument, ["--validation-mode", "omp"])


if __name__ == "__main__":
    unittest.main()
