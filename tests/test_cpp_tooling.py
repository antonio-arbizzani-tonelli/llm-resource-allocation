"""Regression checks for cross-language evidence and profiling conventions."""

from copy import deepcopy
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_cpp_parity as parity
import profile_cpp as profiling


def golden(name):
    return json.loads((ROOT / "cpp/tests/fixtures" / f"{name}.json").read_text(encoding="utf-8"))


def native_projection(reference):
    """Build transport-shaped test evidence from a retained Python golden."""
    actual = deepcopy(reference)
    if "orders" in reference:
        actual["starts"] = [
            {"order": order, "counter": counter, "cost": cost, "comparison": comparison}
            for order, counter, cost, comparison in zip(
                reference["orders"], reference["counters"], reference["costs"],
                reference["comparisons"], strict=True)
        ]
    actual["algorithm_seconds"] = 1.0
    return actual


class CppParityEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.expected = golden("minimal_coherent_agh")["reference"]
        self.actual = native_projection(self.expected)
        self.case = parity.ParityCase("minimal_coherent_agh", parity.make_coherent_tiny_instance(), "agh")

    def check(self, actual):
        with patch.object(parity, "python_reference", return_value=self.expected):
            return parity.check_case(self.case, actual)

    def test_complete_start_evidence_and_independent_validation_pass(self):
        self.assertEqual(self.check(self.actual), self.expected)

    def test_each_missing_cost_is_rejected(self):
        for index in range(len(self.actual["starts"])):
            with self.subTest(index=index):
                actual = deepcopy(self.actual)
                del actual["starts"][index]["cost"]
                with self.assertRaisesRegex(AssertionError, "missing mandatory cost"):
                    self.check(actual)

    def test_each_missing_comparison_is_rejected(self):
        for index in range(len(self.actual["starts"])):
            with self.subTest(index=index):
                actual = deepcopy(self.actual)
                del actual["starts"][index]["comparison"]
                with self.assertRaisesRegex(AssertionError, "missing mandatory comparison"):
                    self.check(actual)

    def test_omitting_all_costs_and_comparisons_cannot_skip_checks(self):
        for start in self.actual["starts"]:
            del start["cost"]
            del start["comparison"]
        with self.assertRaisesRegex(AssertionError, "missing mandatory cost"):
            self.check(self.actual)

    def test_corrupted_cost_is_rejected(self):
        self.actual["starts"][1]["cost"] += 1
        with self.assertRaisesRegex(AssertionError, r"start\[1\] cost"):
            self.check(self.actual)

    def test_corrupted_incumbent_comparison_is_rejected(self):
        self.actual["starts"][1]["comparison"] = "strict_improvement"
        with self.assertRaisesRegex(AssertionError, "strict incumbent comparisons"):
            self.check(self.actual)

    def test_null_incumbent_comparison_is_rejected(self):
        self.actual["starts"][1]["comparison"] = None
        with self.assertRaisesRegex(AssertionError, "invalid comparison"):
            self.check(self.actual)

    def test_unavailable_cost_requires_explicit_null(self):
        expected = golden("frozen_batch_d0039_agh")["reference"]
        actual = native_projection(expected)
        parity.check_reference(expected, actual)
        self.assertTrue(all(start["cost"] is None for start in actual["starts"]))
        del actual["starts"][0]["cost"]
        with self.assertRaisesRegex(AssertionError, "missing mandatory cost"):
            parity.check_reference(expected, actual)

    def test_frozen_replay_uses_committed_expectations_without_live_python(self):
        directory = ROOT / "cpp/tests/fixtures"
        projections = {path.stem: native_projection(json.loads(path.read_text(encoding="utf-8"))["reference"])
                       for path in directory.glob("*.json")}

        def execute(binary, method, transport, **options):
            matches = [path for path in directory.glob("*.txt")
                       if path.read_text(encoding="utf-8") == transport and path.stem.endswith("_" + method)]
            self.assertEqual(len(matches), 1)
            return projections[matches[0].stem], 2.0

        with patch.object(parity, "run_cpp_transport", side_effect=execute), \
                patch.object(parity, "python_reference", side_effect=AssertionError("live authority called")):
            records = parity.replay_frozen(Path("unused"), directory)
        self.assertEqual(len(records), 4)
        self.assertTrue(all(record["passed"] for record in records))
        self.assertTrue(all(record["reference_source"] == "frozen_python_golden" for record in records))
        self.assertTrue(all(record["bitwise_difference_count"] == 0 for record in records))

    def test_frozen_replay_rejects_drift_and_supports_case_selection(self):
        self.actual["starts"][1]["cost"] += 1
        with patch.object(parity, "run_cpp_transport", return_value=(self.actual, 2.0)), redirect_stdout(io.StringIO()):
            records = parity.replay_frozen(Path("unused"), ROOT / "cpp/tests/fixtures",
                                           selectors=["minimal_coherent_agh"])
        self.assertEqual(len(records), 1)
        self.assertFalse(records[0]["passed"])
        self.assertIn("cost", records[0]["error"])

    def test_empty_frozen_selection_is_an_error(self):
        with self.assertRaisesRegex(ValueError, "no matching frozen"):
            parity.replay_frozen(Path("unused"), ROOT / "cpp/tests/fixtures", selectors=["absent"])


class CppProfilingTests(unittest.TestCase):
    def test_individual_python_timings_keep_both_samples(self):
        runner = Mock()
        with patch.object(profiling, "perf_counter", side_effect=[0.0, 1.0, 1.0, 10.0]):
            seconds = profiling.measure_python_calls(runner, 2)
        self.assertEqual(seconds, [1.0, 9.0])
        self.assertEqual(runner.call_count, 2)

    def test_inner_repeats_compare_minimum_with_minimum(self):
        case = parity.ParityCase("mock_gh", parity.make_coherent_tiny_instance())
        fingerprints = {"source_sha256": {"source": "a"}, "binary_sha256": "b"}
        actual = {"algorithm_seconds": 1.0, "repeat_seconds": [1.0, 9.0]}
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            output = Path(temporary)
            arguments = ["profile_cpp.py", "--output", str(output), "--repeats", "1", "--inner-repeat", "2"]
            with patch.object(sys, "argv", arguments), \
                    patch.object(profiling, "profile_cases", return_value=[case]), \
                    patch.object(profiling, "capture_metadata", return_value=deepcopy(fingerprints)), \
                    patch.object(profiling, "capture_fingerprints", return_value=fingerprints), \
                    patch.object(profiling, "run_cpp", return_value=(actual, 20.0)), \
                    patch.object(profiling, "check_case", return_value={"feasible": True, "objective": [1.0]}), \
                    patch.object(profiling, "make_python_runner", return_value=Mock()), \
                    patch.object(profiling, "perf_counter", side_effect=[0.0, 1.0, 1.0, 10.0]), \
                    redirect_stdout(io.StringIO()):
                profiling.main()
            result = json.loads((output / "profile.json").read_text(encoding="utf-8"))
        record = result["cases"][0]
        self.assertEqual(record["python_min_seconds"], 1.0)
        self.assertEqual(record["cpp_core_min_seconds"], 1.0)
        self.assertEqual(record["python_over_cpp_core"], 1.0)
        self.assertEqual(record["samples"][0]["python_repeat_seconds"], [1.0, 9.0])
        self.assertTrue(result["metadata"]["fingerprints_verified_unchanged"])

    def test_changed_source_or_binary_fingerprints_are_rejected(self):
        before = {"source_sha256": {"source.cpp": "a"}, "binary_sha256": "b", "gprof_binary_sha256": "c"}
        changes = (
            {**before, "source_sha256": {"source.cpp": "x"}},
            {**before, "source_sha256": {"source.cpp": "a", "added.cpp": "d"}},
            {**before, "source_sha256": {}},
            {**before, "binary_sha256": "x"},
            {**before, "gprof_binary_sha256": "x"},
        )
        for after in changes:
            with self.subTest(after=after), self.assertRaisesRegex(RuntimeError, "changed during"):
                profiling.verify_fingerprints(before, after)
        profiling.verify_fingerprints(before, deepcopy(before))

    def test_capture_fingerprints_rehashes_source_and_executables(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            (directory / "cpp").mkdir()
            (directory / "scripts").mkdir()
            (directory / "cpp/Makefile").write_text("make", encoding="utf-8")
            (directory / "scripts/check_cpp_parity.py").write_text("parity", encoding="utf-8")
            (directory / "scripts/profile_cpp.py").write_text("profile", encoding="utf-8")
            binary = directory / "native"
            binary.write_bytes(b"before")
            args = SimpleNamespace(binary=binary, gprof_binary=None)
            with patch.object(profiling, "ROOT", directory):
                before = profiling.capture_fingerprints(args)
                binary.write_bytes(b"after")
                after = profiling.capture_fingerprints(args)
        self.assertEqual(before["binary_sha256"], hashlib.sha256(b"before").hexdigest())
        self.assertNotEqual(before["binary_sha256"], after["binary_sha256"])

    def test_old_gmon_cannot_substitute_for_new_profile(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            output = Path(temporary)
            (output / "gprof").mkdir()
            (output / "gprof/gmon.out").write_bytes(b"stale")
            args = SimpleNamespace(output=output, gprof_binary=Path("unused"), gprof_repeat=2,
                                   wsl=None, gprof_tool="gprof")
            with patch.object(profiling, "run_cpp", return_value=({"algorithm_seconds": 1.0}, 2.0)), \
                    patch.object(profiling, "command_output") as report:
                with self.assertRaisesRegex(RuntimeError, "produced no nonempty gmon.out"):
                    profiling.gprof_profile(args, SimpleNamespace(name="mock"))
            report.assert_not_called()

    def test_each_gprof_run_has_fresh_directory_and_recorded_gmon(self):
        def execute(binary, case, *, cwd, **options):
            self.assertFalse((cwd / "gmon.out").exists())
            (cwd / "gmon.out").write_bytes(b"new profile")
            return {"algorithm_seconds": 1.0}, 2.0

        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            output = Path(temporary)
            args = SimpleNamespace(output=output, gprof_binary=output / "native", gprof_repeat=2,
                                   wsl=None, gprof_tool="gprof")
            with patch.object(profiling, "run_cpp", side_effect=execute), \
                    patch.object(profiling, "command_output", return_value="flat profile"):
                first = profiling.gprof_profile(args, SimpleNamespace(name="mock"))
                second = profiling.gprof_profile(args, SimpleNamespace(name="mock"))
            self.assertNotEqual(first["report"], second["report"])
            self.assertTrue((output / first["report"]).is_file())
            self.assertTrue(first["fresh_directory"])
            self.assertEqual(first["gmon_sha256"], hashlib.sha256(b"new profile").hexdigest())


if __name__ == "__main__":
    unittest.main()
