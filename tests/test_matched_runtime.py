"""Opt-in runtime campaign input, timing, parity and statistics contracts."""

from contextlib import redirect_stdout
from dataclasses import replace
import io
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from check_cpp_parity import ParityCase, make_coherent_tiny_instance, serialize_case
from extension_statistics import paired_ratio_bootstrap, quantile, timing_summary
import run_matched_runtime as matched


class ExtensionStatisticsTests(unittest.TestCase):
    def test_hand_derived_interpolated_quartiles(self):
        self.assertEqual(quantile([4, 1, 3, 2], 0.25), 1.75)
        self.assertEqual(quantile([4, 1, 3, 2], 0.75), 3.25)
        self.assertEqual(timing_summary([1, 2, 3, 4]), {
            "count": 4, "median_seconds": 2.5, "q1_seconds": 1.75,
            "q3_seconds": 3.25, "iqr_seconds": 1.5, "minimum_seconds": 1})

    def test_paired_resampling_preserves_an_exact_constant_ratio(self):
        result = paired_ratio_bootstrap([2, 4, 20, 40], [1, 2, 10, 20], seed=17, resamples=200)
        self.assertEqual(result["ratio_of_medians"], 2)
        self.assertEqual((result["ci95_low"], result["ci95_high"]), (2, 2))
        self.assertEqual(result["paired_round_count"], 4)

    def test_ratio_is_ratio_of_medians_and_bootstrap_is_reproducible(self):
        first = paired_ratio_bootstrap([2, 20, 200], [1, 2, 4], seed=23, resamples=200)
        self.assertEqual(first["ratio_of_medians"], 10)
        self.assertEqual(first, paired_ratio_bootstrap([2, 20, 200], [1, 2, 4], seed=23, resamples=200))

    def test_bad_timings_and_incomplete_pairs_are_rejected(self):
        for values in ([], [0], [-1], [True], [math.nan], [math.inf]):
            with self.subTest(values=values), self.assertRaises(ValueError):
                timing_summary(values)
        with self.assertRaises(ValueError):
            paired_ratio_bootstrap([1, 2], [1])


class MatchedPreparedInputTests(unittest.TestCase):
    def setUp(self):
        self.case = ParityCase("same prepared input", make_coherent_tiny_instance(), "agh", seed=-37)

    def test_full_domain_json_roundtrip_keeps_transport_bytewise(self):
        plain = json.loads(json.dumps(matched.case_record(self.case)))
        reconstructed = matched.case_from_record(plain)
        self.assertEqual(reconstructed.instance, self.case.instance)
        self.assertEqual(serialize_case(reconstructed), serialize_case(self.case))
        self.assertEqual(reconstructed.seed, -37)

    def test_matrix_has_both_methods_for_six_shape_load_pairs(self):
        cases = list(matched.workload_cases())
        self.assertEqual(len(cases), 12)
        self.assertEqual({case.instance.dimensions for case, _ in cases}, {(4, 2, 2), (8, 4, 4), (16, 4, 4)})
        self.assertEqual({load for _, load in cases}, {1, 200})
        self.assertEqual({case.method for case, _ in cases}, {"gh", "agh"})
        self.assertEqual({case.seed for case, _ in cases}, {37})

    def test_changed_numeric_input_is_rejected_before_algorithm_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            json_path, numeric_path = Path(temporary) / "input.json", Path(temporary) / "input.txt"
            matched.save_json(json_path, matched.case_record(self.case))
            numeric_path.write_text("wrong input", encoding="utf-8")
            with patch.object(matched, "make_python_runner") as runner:
                with self.assertRaisesRegex(ValueError, "bytewise"):
                    matched.python_worker(json_path, numeric_path)
                runner.assert_not_called()

    def test_timer_excludes_warmup_and_result_projection(self):
        events = []
        def runner():
            events.append("solve")
            return object()
        def clock():
            events.append("clock")
            return 10 if events.count("clock") == 1 else 12
        def project(case, result, *, evidence):
            events.append("project")
            return {"status": "completed"}
        with tempfile.TemporaryDirectory() as temporary:
            json_path, numeric_path = Path(temporary) / "input.json", Path(temporary) / "input.txt"
            matched.save_json(json_path, matched.case_record(self.case))
            numeric_path.write_text(serialize_case(self.case), encoding="utf-8", newline="")
            out = io.StringIO()
            with patch.object(matched, "make_python_runner", return_value=runner), \
                 patch.object(matched, "perf_counter", side_effect=clock), \
                 patch.object(matched, "python_projection", side_effect=project), redirect_stdout(out):
                matched.python_worker(json_path, numeric_path, warmup=True)
            self.assertEqual(events, ["solve", "clock", "solve", "clock", "project"])
            self.assertEqual(json.loads(out.getvalue())["core_seconds"], 2)

    def test_full_reference_rejects_one_ulp_despite_existing_parity_tolerance(self):
        expected = {"status": "completed", "placement": None, "objective": [1.0], "feasible": False}
        native = {**expected, "objective": [math.nextafter(1.0, 2.0)]}
        with self.assertRaisesRegex(AssertionError, "bitwise"):
            matched.verify_full_reference(expected, native)

    def test_old_interrupted_attempt_is_preserved_on_resume(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary) / "sample"
            base.mkdir()
            (base / "partial.json").write_text("partial", encoding="utf-8")
            self.assertEqual(matched.attempt_directory(base), base.with_name("sample_retry1"))
            self.assertEqual((base / "partial.json").read_text(), "partial")

    def test_resume_rejects_changed_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            source = output / "input.json"
            source.write_text("prepared", encoding="utf-8")
            prepared = {"source_sha256": {}, "binary": "fake", "binary_sha256": "binary",
                        "cases": [{"name": "case", "json": "input.json", "json_sha256": "old"}]}
            with patch.object(matched, "source_fingerprints", return_value={}), \
                 patch.object(matched, "sha256", side_effect=lambda path: "binary" if path.name == "fake" else "changed"):
                with self.assertRaisesRegex(ValueError, "prepared input changed"):
                    matched.verify_prepared(output, prepared)


if __name__ == "__main__":
    unittest.main()
