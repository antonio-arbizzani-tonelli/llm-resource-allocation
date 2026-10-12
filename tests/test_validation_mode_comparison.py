"""Focused contracts for rotated measurements and probe observations."""

from copy import deepcopy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import compare_validation_modes as comparison
from profile_large_instances import save_evidence, save_json, sha256


def actual(setting, *, rows=32, minimum=0):
    value = {"status": "completed", "feasible": True, "objective": [1.0], "placement": None,
             "residuals": [], "algorithm_seconds": 1.0, "repeat_seconds": [1.0]}
    if setting.mode is None:
        return value
    grain = setting.mode == "omp" and rows < minimum
    region = setting.mode == "omp" and not grain
    team = setting.threads if region else 1
    samples = [{"seconds": seconds, "mccormick_rows": rows, "actual_threads": team,
                "region_entered": region, "nested_fallback": False, "grain_fallback": grain,
                "succeeded": True} for seconds in (0.1, 0.2)]
    value["validation_statistics"] = {"calls": 2, "failed_calls": 0, "seconds_total": 0.3,
        "minimum_seconds": 0.1, "median_seconds": 0.15, "maximum_seconds": 0.2,
        "parallel_region_calls": 2 if region else 0, "calls_with_parallel_team": 2 if team > 1 else 0,
        "nested_fallback_calls": 0, "grain_fallback_calls": 2 if grain else 0,
        "observed_teams": [team], "repeat_call_offsets": [0, 2], "samples": samples}
    value["validation_execution"] = {"mode": setting.mode, "requested_threads": setting.threads,
                                      "minimum_mccormick_rows": minimum}
    value["phase_seconds"] = {"input_parse": 0.01, "algorithm": [1.0], "result_destruction": [0.02]}
    return value


class VariantAndOrderTests(unittest.TestCase):
    def test_same_probe_variant_flags_include_mode_threads_and_grain(self):
        settings = comparison.variants(comparison.DEFAULT_VARIANTS)
        self.assertEqual(settings[0].arguments(400), [])
        self.assertEqual(settings[-1].arguments(400), ["--validation-mode", "omp", "--validation-threads", "8",
                                                      "--validation-min-rows", "400"])

    def test_controls_unknown_modes_and_duplicates_are_checked(self):
        for names in ((), ("serial",), ("append",), ("serial", "append", "serial"),
                      ("serial", "append", "omp0"), ("serial", "append", "gpu")):
            with self.subTest(names=names), self.assertRaises(ValueError):
                comparison.variants(names)

    def test_rotation_is_deterministic_and_preserves_each_setting(self):
        settings = comparison.variants(("serial", "append", "slots", "omp4"))
        self.assertEqual([s.name for s in comparison.round_order(settings, 0)], ["serial", "append", "slots", "omp4"])
        self.assertEqual([s.name for s in comparison.round_order(settings, 1)], ["serial", "omp4", "slots", "append"])
        self.assertEqual([s.name for s in comparison.round_order(settings, 2)], ["slots", "omp4", "serial", "append"])
        for index in range(8):
            self.assertEqual(set(comparison.round_order(settings, index)), set(settings))

    def test_minima_and_medians_are_independent_and_serial_has_no_observed_team(self):
        samples = [{"cpp_core_seconds": value, "process_wall_seconds": 10 - value, "observer_check": None}
                   for value in (1.0, 3.0, 2.0)]
        summary = comparison.summarize(samples)
        self.assertEqual(summary["core_min_seconds"], 1)
        self.assertEqual(summary["core_median_seconds"], 2)
        self.assertEqual(summary["process_min_seconds"], 7)
        self.assertEqual(summary["process_median_seconds"], 8)
        self.assertEqual(summary["observed_teams"], [])


class ProbeObservationTests(unittest.TestCase):
    def check(self, value, setting, *, minimum=0):
        return comparison.validate_observer(value, setting, minimum, 32)

    def test_append_slots_omp_one_and_parallel_teams_are_checked(self):
        for setting in comparison.variants(comparison.DEFAULT_VARIANTS):
            with self.subTest(setting=setting):
                checked = self.check(actual(setting), setting)
                if setting.mode:
                    self.assertEqual(checked["calls"], 2)
                else:
                    self.assertIsNone(checked)

    def test_configured_grain_fallback_is_checked_and_retained(self):
        setting = comparison.Variant("omp4", "omp", 4)
        checked = self.check(actual(setting, minimum=33), setting, minimum=33)
        self.assertEqual(checked["grain_fallback_calls"], 2)
        self.assertEqual(checked["observed_teams"], [1])

    def test_mismatched_flags_fail_before_speedup_is_reported(self):
        setting = comparison.Variant("omp4", "omp", 4)
        for field, value in (("mode", "append"), ("requested_threads", 2),
                             ("minimum_mccormick_rows", 999), ("requested_threads", True)):
            supplied = actual(setting)
            supplied["validation_execution"][field] = value
            with self.subTest(field=field), self.assertRaises(AssertionError):
                self.check(supplied, setting)

    def test_wrong_calls_offsets_aggregate_durations_and_team_summary_are_rejected(self):
        setting = comparison.Variant("omp4", "omp", 4)
        for field, value in (("calls", 1), ("calls", True), ("repeat_call_offsets", [0, 1]),
                             ("repeat_call_offsets", [False, 2]), ("observed_teams", [2]),
                             ("parallel_region_calls", 1), ("seconds_total", 0.5),
                             ("median_seconds", float("nan"))):
            supplied = actual(setting)
            supplied["validation_statistics"][field] = value
            with self.subTest(field=field), self.assertRaises(AssertionError):
                self.check(supplied, setting)

    def test_bad_per_call_duration_rows_flags_failures_and_teams_are_rejected(self):
        setting = comparison.Variant("omp4", "omp", 4)
        for field, value in (("seconds", 0.0), ("seconds", float("nan")), ("mccormick_rows", 33),
                             ("actual_threads", 5), ("actual_threads", True), ("nested_fallback", True),
                             ("grain_fallback", True), ("region_entered", False), ("succeeded", False),
                             ("succeeded", 1)):
            supplied = actual(setting)
            supplied["validation_statistics"]["samples"][0][field] = value
            with self.subTest(field=field), self.assertRaises(AssertionError):
                self.check(supplied, setting)

    def test_serial_control_cannot_accidentally_use_probe(self):
        with self.assertRaisesRegex(AssertionError, "unexpectedly contains"):
            self.check(actual(comparison.Variant("append", "append")), comparison.Variant("serial", None))

    def test_row_count_comes_from_frozen_menu(self):
        transport = "PACS_GH_AGH 1\n2 3 2 1 2\nparameters\nquery\nquery\nmodel\nmodel\nmodel\n8 9 10 2\n8 9 10 4\n"
        self.assertEqual(comparison.mccormick_row_count(transport), 4 * 2 * 3 * 6)


class PairedStagedTests(unittest.TestCase):
    def fixture(self, directory):
        base = directory / "baseline"
        base.mkdir()
        transport = "PACS_GH_AGH 1\n2 2 2 1 2\nparameters\nquery\nquery\nmodel\nmodel\n8 9 10 1\n8 9 10 1\n"
        input_path = base / "inputs/tiny_gh.txt"
        input_path.parent.mkdir()
        input_path.write_text(transport, encoding="utf-8")
        supplied = actual(comparison.Variant("serial", None))
        expected = {key: supplied[key] for key in ("status", "feasible", "objective", "placement")}
        golden_path = base / "goldens/tiny_gh.json"
        save_json(golden_path, {"reference": expected})
        evidence_path = base / "evidence/tiny_gh.json.gz"
        save_evidence(evidence_path, supplied)
        record = {"case": "tiny_gh", "method": "gh", "dimensions": [2, 2, 2],
                  "input": "inputs/tiny_gh.txt", "input_sha256": sha256(input_path),
                  "python_golden": "goldens/tiny_gh.json", "python_golden_sha256": sha256(golden_path),
                  "full_cpp_evidence": "evidence/tiny_gh.json.gz", "full_cpp_evidence_sha256": sha256(evidence_path)}
        save_json(base / "profile.json", {"mode": "baseline", "complete": True, "cases": [record]})
        snapshots, binaries = [], []
        for name in ("serial", "probe"):
            source = directory / (name + "_source")
            source.mkdir()
            (source / "core.cpp").write_text("frozen", encoding="utf-8")
            binary = directory / name
            binary.write_bytes(b"executable")
            snapshots.append(source)
            binaries.append(binary)
        return SimpleNamespace(baseline_output=base, serial_source_dir=snapshots[0], probe_source_dir=snapshots[1],
            serial_binary=binaries[0], probe_binary=binaries[1], output=directory / "comparison", wsl=None,
            query_counts=[2], methods=["gh"], variants=["serial", "append", "omp4"], rounds=3,
            minimum_mccormick_rows=0, omp_wait_policy="active", timeout=600, build_description="flags")

    def test_rotated_run_keeps_baseline_fixed_and_checks_all_warm_and_timed_evidence(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            args = self.fixture(Path(temporary))
            original_sha = sha256(args.baseline_output / "profile.json")
            calls = []

            def execute(binary, method, transport, **kwargs):
                flags = kwargs["extra_arguments"]
                if not flags:
                    setting = comparison.Variant("serial", None)
                    self.assertEqual(binary, args.serial_binary)
                else:
                    mode, threads = flags[1], int(flags[3])
                    setting = comparison.Variant(mode + str(threads) if mode == "omp" else mode, mode, threads)
                    self.assertEqual(binary, args.probe_binary)
                calls.append((setting.name, kwargs["summary"], kwargs["repeat"]))
                return actual(setting), 3.0

            with patch.object(comparison, "runtime_metadata", return_value={}), \
                    patch.object(comparison, "run_transport", side_effect=execute), redirect_stdout(io.StringIO()):
                result = comparison.compare(args)
            self.assertTrue(result["complete"])
            self.assertTrue(result["fingerprints_verified_unchanged"])
            self.assertEqual(sha256(args.baseline_output / "profile.json"), original_sha)
            self.assertEqual(len(calls), 12)
            self.assertEqual(sum(not summary for _, summary, _ in calls), 3)
            self.assertTrue(all(repeat == 1 for _, _, repeat in calls))
            self.assertEqual([name for name, _, _ in calls[3:6]], ["serial", "append", "omp4"])
            self.assertEqual([name for name, _, _ in calls[6:9]], ["serial", "omp4", "append"])
            self.assertTrue(all(variant["core_median_speedup_vs_append"] == 1 for variant in result["cases"][0]["variants"]))

    def test_corrupted_frozen_artifact_is_rejected_without_a_child_call(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            args = self.fixture(Path(temporary))
            (args.baseline_output / "inputs/tiny_gh.txt").write_text("corrupted", encoding="utf-8")
            with patch.object(comparison, "run_transport") as execute:
                with self.assertRaisesRegex(RuntimeError, "checksum differs"):
                    comparison.compare(args)
            execute.assert_not_called()

    def test_baseline_directory_and_children_cannot_be_output_targets(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            args = self.fixture(Path(temporary))
            for output in (args.baseline_output, args.baseline_output / "comparison"):
                args.output = output
                with self.assertRaisesRegex(ValueError, "outside the preserved"):
                    comparison.load_records(args)


if __name__ == "__main__":
    unittest.main()
