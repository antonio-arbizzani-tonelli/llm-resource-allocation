"""Seeded-instance statistical units and opt-in scaling evidence contracts."""

import gzip
import hashlib
import json
import math
import random
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_instance_scaling as scaling


class InstanceScalingMatrixTests(unittest.TestCase):
    @staticmethod
    def cohort_specifications():
        return [{"shape": [16,4,4], "instance_seed": seed, "method": method,
                 "numeric_sha256": f"numeric-{seed}"}
                for seed in scaling.INSTANCE_SEEDS for method in ("gh", "agh")]

    def test_requested_dimensions_and_five_input_seeds_are_explicit(self):
        points = list(scaling.matrix_specifications())
        self.assertEqual(len(points), 90)
        self.assertEqual(len({(tuple(point["shape"]), point["instance_seed"]) for point in points}), 45)
        self.assertEqual({point["instance_seed"] for point in points}, {11, 23, 37, 41, 53})
        self.assertEqual({point["agh_seed"] for point in points}, {37})
        query = [point for point in points if "query" in point["families"]]
        menu = [point for point in points if "menu" in point["families"]]
        self.assertEqual(len(query), 60)
        self.assertEqual(len(menu), 40)
        self.assertEqual({point["shape"][0] for point in query}, {16, 32, 64, 128, 256, 384})
        self.assertEqual({tuple(point["shape"][1:]) for point in menu}, {(4, 4), (8, 4), (8, 8), (12, 12)})
        self.assertEqual({point["shape"][0] for point in menu}, {64})

    def test_overlap_is_measured_once(self):
        overlapping = [point for point in scaling.matrix_specifications() if len(point["families"]) == 2]
        self.assertEqual(len(overlapping), 10)
        self.assertTrue(all(point["shape"] == [64, 4, 4] for point in overlapping))

    def test_five_distinct_actual_inputs_are_repeatable_and_leave_global_rng_untouched(self):
        before = random.getstate()
        hashes = []
        for seed in scaling.INSTANCE_SEEDS:
            instance = scaling.seeded_instance((4,2,2),200.0,seed)
            self.assertEqual(instance, scaling.seeded_instance((4,2,2),200.0,seed))
            case = scaling.ParityCase("input_variability",instance,"gh",seed=37)
            hashes.append(hashlib.sha256(scaling.serialize_case(case).encode()).hexdigest())
        self.assertEqual(len(set(hashes)),5)
        self.assertEqual(random.getstate(),before)

    def test_duplicate_numeric_inputs_do_not_count_as_instance_variability(self):
        specifications = self.cohort_specifications()
        cohort = scaling.input_cohorts(specifications)
        self.assertEqual(cohort["16x4x4"]["distinct_numeric_inputs"],5)
        for spec in specifications:
            spec["numeric_sha256"] = "same-scientific-input"
        with self.assertRaisesRegex(ValueError,"five distinct numeric inputs"):
            scaling.input_cohorts(specifications)

    def test_different_method_inputs_are_rejected(self):
        specifications = self.cohort_specifications()
        specifications[0]["numeric_sha256"] = "changed-gh-input"
        with self.assertRaisesRegex(ValueError,"GH and AGH must share"):
            scaling.input_cohorts(specifications)

    def test_plan_mutation_blocks_resume_before_reading_scientific_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            plan = output/"PLAN.md"
            plan.write_text("original hypothesis",encoding="utf-8")
            prepared = {"plan_sha256":scaling.matched.sha256(plan)}
            plan.write_text("changed hypothesis",encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"PLAN changed after preparation"):
                scaling.verify_prepared(output,prepared)


class ClusteredScalingStatisticsTests(unittest.TestCase):
    @staticmethod
    def power_law_points():
        # Independent instance offsets; each cluster still has the exact y=C*x^2 law.
        return [{"size": size, "median_seconds": coefficient * size ** 2, "instance_seed": seed}
                for seed, coefficient in ((11, 1.0), (23, 2.0), (37, 3.0), (41, 4.0), (53, 5.0))
                for size in (2, 4, 8)]

    def test_hand_derived_power_law_exponent_and_cluster_count(self):
        result = scaling.clustered_log_fit(self.power_law_points(), resamples=200)
        self.assertAlmostEqual(result["exponent"], 2)
        self.assertAlmostEqual(result["ci95_exponent_low"], 2)
        self.assertAlmostEqual(result["ci95_exponent_high"], 2)
        self.assertEqual(result["cluster_count"], 5)
        self.assertEqual(result["instance_point_count"], 15)
        self.assertEqual(result["size_level_count"], 3)
        self.assertLess(result["r_squared_log_space"], 1)  # between-instance offsets remain in residuals

    def test_exact_same_power_law_has_r_squared_one(self):
        points = [(math.log(size), math.log(3 * size ** 2)) for size in (2, 4, 8, 16)]
        result = scaling.ordinary_log_fit(points)
        self.assertAlmostEqual(result["exponent"], 2)
        self.assertAlmostEqual(math.exp(result["log_intercept"]), 3)
        self.assertAlmostEqual(result["r_squared_log_space"], 1)

    def test_bootstrap_preserves_correlated_seed_grids_and_is_reproducible(self):
        points = self.power_law_points()
        self.assertEqual(scaling.clustered_log_fit(points, seed=7, resamples=200),
                         scaling.clustered_log_fit(points, seed=7, resamples=200))
        with self.assertRaisesRegex(ValueError, "complete common size grid"):
            scaling.clustered_log_fit(points[:-1], resamples=200)

    def test_invalid_runtime_and_constant_size_are_rejected(self):
        points = self.power_law_points()
        points[0]["median_seconds"] = 0
        with self.assertRaisesRegex(ValueError, "finite and positive"):
            scaling.clustered_log_fit(points, resamples=200)
        with self.assertRaisesRegex(ValueError, "distinct size"):
            scaling.ordinary_log_fit([(1, 2), (1, 3), (1, 4)])


class CompressedScalingEvidenceTests(unittest.TestCase):
    def test_metadata_write_failure_preserves_original_worker_stdout(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            destination = output/"raw/worker"
            raw = b'{"partial":'
            def producer(actual_directory,command,*,timeout):
                actual_directory.mkdir(parents=True)
                (actual_directory/"stdout.json").write_bytes(raw)
                (actual_directory/"stderr.txt").write_bytes(b"failure")
                return {"status":"failed","stdout_sha256":hashlib.sha256(raw).hexdigest(),
                        "stderr_sha256":hashlib.sha256(b"failure").hexdigest()},None
            with patch.object(scaling.matched,"retained_invocation",side_effect=producer), \
                 patch.object(scaling.matched,"save_json",side_effect=OSError("interrupted metadata write")):
                with self.assertRaisesRegex(OSError,"interrupted metadata write"):
                    scaling.retain_invocation(output,destination,["worker"],timeout=5)
            self.assertEqual((destination/"stdout.json").read_bytes(),raw)
            self.assertEqual(gzip.decompress((destination/"stdout.json.gz").read_bytes()),raw)

    def test_compression_retains_original_failure_bytes_and_both_hashes(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            destination = output / "raw" / "worker"
            raw = b'{"partial":'
            def producer(actual_directory, command, *, timeout):
                actual_directory.mkdir(parents=True)
                (actual_directory / "stdout.json").write_bytes(raw)
                (actual_directory / "stderr.txt").write_bytes(b"failure")
                return {"status": "failed", "stdout_sha256": hashlib.sha256(raw).hexdigest(),
                        "stderr_sha256": hashlib.sha256(b"failure").hexdigest()}, None
            with patch.object(scaling.matched, "retained_invocation", side_effect=producer):
                record, actual = scaling.retain_invocation(output, destination, ["worker"], timeout=5)
            self.assertIsNone(actual)
            compressed = destination / "stdout.json.gz"
            self.assertEqual(gzip.decompress(compressed.read_bytes()), raw)
            self.assertEqual(record["stdout_uncompressed_sha256"], hashlib.sha256(raw).hexdigest())
            self.assertEqual(record["stdout_sha256"], hashlib.sha256(compressed.read_bytes()).hexdigest())
            self.assertFalse((destination / "stdout.json").exists())

    def test_retry_does_not_overwrite_prior_attempt(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            destination = output / "raw" / "worker"
            destination.mkdir(parents=True)
            (destination / "old.txt").write_text("retained", encoding="utf-8")
            raw = b'{"core_seconds":1}'
            def producer(actual_directory, command, *, timeout):
                actual_directory.mkdir(parents=True)
                (actual_directory / "stdout.json").write_bytes(raw)
                (actual_directory / "stderr.txt").write_bytes(b"")
                return {"status": "completed", "stdout_sha256": hashlib.sha256(raw).hexdigest(),
                        "stderr_sha256": hashlib.sha256(b"").hexdigest()}, json.loads(raw)
            with patch.object(scaling.matched, "retained_invocation", side_effect=producer):
                record, _ = scaling.retain_invocation(output, destination, ["worker"], timeout=5)
            self.assertEqual(record["directory"], "raw/worker_retry1")
            self.assertEqual((destination / "old.txt").read_text(), "retained")
            self.assertEqual(scaling.retained_stdout(output, record), {"core_seconds": 1})


class ScalingBudgetTests(unittest.TestCase):
    def test_worker_timeout_never_exceeds_remaining_coordinator_time(self):
        with patch.object(scaling,"perf_counter",return_value=41.0):
            self.assertEqual(scaling.budgeted_timeout(0.0,50.0,180.0),9.0)
            self.assertEqual(scaling.budgeted_timeout(0.0,50.0,3.0),3.0)
        with patch.object(scaling,"perf_counter",return_value=60.0):
            self.assertEqual(scaling.budgeted_timeout(0.0,50.0,180.0),0.0)

    def test_resume_projection_excludes_finished_samples(self):
        prepared = {"cases":[{"name":"a"},{"name":"b"}]}
        status = {"repeats":3,"warm":{
            "a":{"process_wall_seconds":2.0,"independent_validation_seconds":1.0},
            "b":{"process_wall_seconds":4.0,"independent_validation_seconds":2.0}},
            "samples":{"a/repeat00":{},"b/repeat00":{},"b/repeat01":{}}}
        self.assertEqual(scaling.projected_pending_work(prepared,status),12.0)
        status["samples"]={f"{name}/repeat{repeat:02d}":{} for name in ("a","b") for repeat in range(3)}
        self.assertEqual(scaling.projected_pending_work(prepared,status),0.0)


if __name__ == "__main__":
    unittest.main()
