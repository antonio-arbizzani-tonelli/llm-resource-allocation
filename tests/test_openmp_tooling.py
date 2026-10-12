"""Scientific evidence and timing contracts for independent OpenMP campaigns."""

from copy import deepcopy
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_openmp_campaign as campaign
import profile_openmp as profiling
from check_cpp_parity import ParityCase, make_coherent_tiny_instance


def measurement(schedule="static", threads=4, actual_threads=4, seconds=(1.0, 9.0)):
    return {"schedule": schedule, "requested_threads": threads, "actual_threads": actual_threads,
            "campaign_seconds": min(seconds), "repeat_seconds": list(seconds),
            "repeat_threads": [actual_threads] * len(seconds), "cases": []}


class OpenMPMeasurementTests(unittest.TestCase):
    def test_minimum_duration_and_observed_team_are_validated(self):
        actual = measurement(actual_threads=2)
        campaign.validate_measurement(actual, schedule="static", threads=4, repeat=2)
        result = profiling.scaling_statistics(4.0, [actual])
        self.assertEqual(result, {"actual_threads": 2, "campaign_min_seconds": 1.0,
                                  "speedup": 4.0, "efficiency": 2.0})

    def test_inner_repeat_minimum_is_never_replaced_by_mean(self):
        sample = measurement(seconds=(1.0, 9.0))
        result = profiling.scaling_statistics(1.0, [sample, measurement(seconds=(2.0, 8.0))])
        self.assertEqual(result["speedup"], 1.0)
        self.assertEqual(result["efficiency"], 0.25)

    def test_invalid_durations_are_rejected(self):
        for duration in (0.0, -1.0, float("nan"), float("inf"), True, "1"):
            with self.subTest(duration=duration):
                actual = measurement()
                actual["repeat_seconds"][0] = duration
                with self.assertRaisesRegex(AssertionError, "finite and positive"):
                    campaign.validate_measurement(actual, schedule="static", threads=4, repeat=2)

    def test_team_size_contract_rejects_invalid_values(self):
        for team in (0, 5, True, 2.0):
            with self.subTest(team=team), self.assertRaisesRegex(AssertionError, "actual_threads"):
                campaign.validate_measurement(measurement(actual_threads=team), schedule="static", threads=4, repeat=2)

    def test_serial_cannot_claim_multiple_actual_threads(self):
        with self.assertRaisesRegex(AssertionError, "serial campaign"):
            campaign.validate_measurement(measurement("serial", 4, 2), schedule="serial", threads=4, repeat=2)

    def test_schedule_repeat_count_and_minimum_mismatch_are_rejected(self):
        actual = measurement()
        with self.assertRaisesRegex(AssertionError, "configuration"):
            campaign.validate_measurement(actual, schedule="dynamic", threads=4, repeat=2)
        with self.assertRaisesRegex(AssertionError, "count differs"):
            campaign.validate_measurement(actual, schedule="static", threads=4, repeat=1)
        actual["campaign_seconds"] = 5.0
        with self.assertRaisesRegex(AssertionError, "minimum individual"):
            campaign.validate_measurement(actual, schedule="static", threads=4, repeat=2)

    def test_scaling_rejects_changed_team_and_empty_samples(self):
        with self.assertRaisesRegex(ValueError, "team changed"):
            profiling.scaling_statistics(1.0, [measurement(), measurement(actual_threads=2)])
        with self.assertRaisesRegex(ValueError, "nonempty"):
            profiling.scaling_statistics(1.0, [])

    def test_per_repeat_team_evidence_matches_minimum_duration_call(self):
        actual = measurement(seconds=(9.0, 1.0), actual_threads=2)
        actual["repeat_threads"] = [4, 2]
        campaign.validate_measurement(actual, schedule="static", threads=4, repeat=2)
        actual["actual_threads"] = 4
        with self.assertRaisesRegex(AssertionError, "minimum-duration repeat"):
            campaign.validate_measurement(actual, schedule="static", threads=4, repeat=2)

    def test_invalid_repeat_team_count_and_values_are_rejected(self):
        for teams, message in (([4], "count differs"), ([4, 0], "bounded positive"),
                               ([4, True], "bounded positive")):
            actual = measurement()
            actual["repeat_threads"] = teams
            with self.subTest(teams=teams), self.assertRaisesRegex(AssertionError, message):
                campaign.validate_measurement(actual, schedule="static", threads=4, repeat=2)

    def test_changed_inner_repeat_team_invalidates_stable_scaling(self):
        actual = measurement()
        actual["repeat_threads"] = [4, 2]
        with self.assertRaisesRegex(ValueError, "team changed"):
            profiling.scaling_statistics(1.0, [actual])


class OpenMPEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.case = ParityCase("case with spaces", make_coherent_tiny_instance())
        self.expected = {"status": "algorithm_1_completed", "feasible": True,
                         "objective": [1.0, 0.0], "placement": {"x": [0.0]},
                         "residuals": [["budget", -1.0]], "gh_trace": {"queries": []}}
        self.actual = {"cases": [{"name": self.case.name, "method": self.case.method, **deepcopy(self.expected)}]}

    def test_complete_evidence_accepts_identical_projection(self):
        campaign.verify_cases([self.case], [self.expected], self.actual)

    def test_missing_residual_evidence_cannot_be_skipped(self):
        del self.actual["cases"][0]["residuals"]
        with self.assertRaisesRegex(AssertionError, "keys differ"):
            campaign.verify_cases([self.case], [self.expected], self.actual)

    def test_residual_and_trace_mismatch_are_detected(self):
        self.actual["cases"][0]["residuals"][0][1] = -2.0
        with self.assertRaisesRegex(AssertionError, "residuals"):
            campaign.verify_cases([self.case], [self.expected], self.actual)
        self.actual["cases"][0]["residuals"][0][1] = -1.0
        self.actual["cases"][0]["gh_trace"]["queries"] = [0]
        with self.assertRaisesRegex(AssertionError, "gh_trace"):
            campaign.verify_cases([self.case], [self.expected], self.actual)

    def test_signed_zero_and_boolean_numeric_substitution_are_detected(self):
        with self.assertRaisesRegex(AssertionError, "bitwise numeric"):
            campaign.verify_bitwise([0.0], [-0.0])
        with self.assertRaisesRegex(AssertionError, "invalid numeric"):
            campaign.verify_bitwise([1.0], [True])
        with self.assertRaisesRegex(AssertionError, "evidence mismatch"):
            campaign.verify_bitwise(True, 1)

    def test_manifest_order_and_case_count_are_checked(self):
        self.actual["cases"][0]["name"] = "different"
        with self.assertRaisesRegex(AssertionError, "manifest order"):
            campaign.verify_cases([self.case], [self.expected], self.actual)
        with self.assertRaisesRegex(AssertionError, "case count"):
            campaign.verify_cases([self.case], [self.expected], {"cases": []})

    def test_summary_retains_status_feasibility_and_objective(self):
        self.actual["cases"][0] = {"name": self.case.name, "method": self.case.method,
                                  **{key: self.expected[key] for key in ("status", "feasible", "objective")}}
        campaign.verify_cases([self.case], [self.expected], self.actual, summary=True)
        self.actual["cases"][0]["feasible"] = False
        with self.assertRaisesRegex(AssertionError, "feasible"):
            campaign.verify_cases([self.case], [self.expected], self.actual, summary=True)

    def test_manifest_retains_paths_spaces_and_original_seed(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            path = campaign.write_manifest([self.case], Path(temporary) / "inputs with spaces")
            text = path.read_text(encoding="utf-8")
            self.assertIn('gh "case with spaces"', text)
            self.assertIn("PACS_CAMPAIGN 1\n1\n", text)
            self.assertEqual((path.parent / "000_gh.txt").read_text(encoding="utf-8"), campaign.serialize_case(self.case))

    def test_std_quoted_encoder_preserves_unicode_controls_quotes_and_backslashes(self):
        # Hand-written transport expectation: only quotation and escape
        # characters gain an escape; the newline and accents remain literal.
        self.assertEqual(campaign.quoted_token('café "GH" \\ route\nétude\t\r'),
                         '"café \\"GH\\" \\\\ route\nétude\t\r"')

    def test_manifest_writes_accented_name_and_path_without_json_escapes(self):
        special = ParityCase('café "GH" \\ route\nétude\r', make_coherent_tiny_instance())
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            path = campaign.write_manifest([special], Path(temporary) / "résultats avec espaces")
            text = path.read_bytes().decode("utf-8")
            self.assertIn('gh "café \\"GH\\" \\\\ route\nétude\r"', text)
            self.assertIn("résultats avec espaces", text)
            self.assertNotIn("\\u00e9", text)
            self.assertNotIn("route\\n", text)
            self.assertTrue((path.parent / "000_gh.txt").is_file())

    def test_invocation_preserves_literal_carriage_return_in_manifest(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            path = Path(temporary) / "manifest.txt"
            expected = 'PACS_CAMPAIGN 1\n0\n"café\r\n"\n'.encode("utf-8")
            path.write_bytes(expected)
            response = SimpleNamespace(returncode=0, stdout=json.dumps(measurement()).encode("utf-8"), stderr=b"")
            with patch.object(campaign.subprocess, "run", return_value=response) as run:
                campaign.run_campaign(Path("native"), path, schedule="static", threads=4, repeat=2)
            self.assertEqual(run.call_args.kwargs["input"], expected)
            self.assertNotIn("text", run.call_args.kwargs)
            self.assertNotIn("encoding", run.call_args.kwargs)

    def test_binary_pipe_error_decodes_diagnostic_without_losing_failure(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            path = Path(temporary) / "manifest.txt"
            path.write_bytes(b"invalid")
            response = SimpleNamespace(returncode=2, stdout=b"", stderr=b"bad UTF-8 \xff")
            with patch.object(campaign.subprocess, "run", return_value=response):
                with self.assertRaisesRegex(RuntimeError, "campaign exited 2: bad UTF-8"):
                    campaign.run_campaign(Path("native"), path, schedule="serial", threads=1)

    def test_verification_fixture_contains_repeated_and_large_signed_seeds(self):
        cases = campaign.campaign_verification_cases()
        seeds = [case.seed for case in cases[-4:]]
        self.assertEqual(seeds, [37, 37, -37, 2**65 + 11])
        self.assertEqual(campaign.serialize_case(cases[-4]), campaign.serialize_case(cases[-3]))
        self.assertTrue(any(case.method == "gh" for case in cases))
        self.assertEqual(cases[0].name, 'café "AGH"\nverification')

    def test_wsl_environment_is_scoped_to_child_command(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            manifest = Path(temporary) / "manifest.txt"
            manifest.write_text("PACS_CAMPAIGN 1\n0\n", encoding="utf-8")
            response = SimpleNamespace(returncode=0, stdout=json.dumps(measurement()), stderr="")
            old = os.environ.get("OMP_DYNAMIC")
            with patch.object(campaign.subprocess, "run", return_value=response) as run:
                campaign.run_campaign(Path("native"), manifest, schedule="static", threads=4, repeat=2, wsl="Ubuntu")
            command = run.call_args.args[0]
            self.assertIn("env", command)
            self.assertIn("OMP_DYNAMIC=FALSE", command)
            self.assertEqual(os.environ.get("OMP_DYNAMIC"), old)


class OpenMPProfilingTests(unittest.TestCase):
    def test_workloads_have_fixed_distinct_seeded_jobs_and_clustered_cost(self):
        workloads = profiling.campaign_workloads(8, seed=-37, seed_step=3)
        self.assertEqual([case.seed for case in workloads["uniform"]], [-37, -34, -31, -28, -25, -22, -19, -16])
        self.assertEqual([case.method for case in workloads["mixed"]], ["agh"] * 6 + ["gh"] * 2)
        self.assertTrue(all(case.instance.dimensions == (16, 4, 4) for case in workloads["uniform"]))
        with self.assertRaisesRegex(ValueError, "multiple of four"):
            profiling.campaign_workloads(3)

    def test_changed_inputs_sources_and_binaries_invalidate_measurement(self):
        before = {"source_sha256": {"worker.cpp": "a"}, "input_sha256": {"manifest": "b"},
                  "binary_sha256": "c", "serial_binary_sha256": "d"}
        for key in before:
            changed = deepcopy(before)
            changed[key] = "different"
            with self.subTest(key=key), self.assertRaisesRegex(RuntimeError, "changed during"):
                profiling.verify_fingerprints(before, changed)
        profiling.verify_fingerprints(before, deepcopy(before))

    def test_rotated_rounds_retain_raw_evidence_and_correct_scaling(self):
        cases = tuple(ParityCase(f"case_{index}", make_coherent_tiny_instance(), "agh") for index in range(4))
        reference = {"status": "complete", "feasible": True, "objective": [1.0], "placement": None,
                     "residuals": [], "starts": []}
        calls = []

        def execute(binary, manifest, *, schedule, threads, repeat=1, summary=False, **options):
            calls.append((schedule, threads, summary))
            value = measurement(schedule, threads, threads if schedule != "serial" else 1,
                                seconds=(2.0 / threads,) * repeat)
            projected = {key: reference[key] for key in ("status", "feasible", "objective")} if summary else reference
            value["cases"] = [{"name": case.name, "method": case.method, **deepcopy(projected)} for case in cases]
            return value, 20.0

        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            output = Path(temporary)
            args = ["profile_openmp.py", "--output", str(output), "--repeats", "2", "--threads", "1", "2"]
            with patch.object(sys, "argv", args), \
                    patch.object(profiling, "campaign_workloads", return_value={"uniform": cases}), \
                    patch.object(profiling, "serial_references", return_value=[deepcopy(reference) for _ in cases]), \
                    patch.object(profiling, "fingerprints", return_value={"binary_sha256": "same"}), \
                    patch.object(profiling, "metadata", return_value={}), \
                    patch.object(profiling, "run_campaign", side_effect=execute), redirect_stdout(io.StringIO()):
                self.assertEqual(profiling.main(), 0)
            result = json.loads((output / "profile.json").read_text(encoding="utf-8"))
            record = result["workloads"][0]
            self.assertEqual(len(record["warm_verified_runs"]), 5)
            self.assertEqual(len(record["execution_order"]), 10)
            self.assertNotEqual(record["execution_order"][:5], record["execution_order"][5:])
            scaled = next(item for item in record["scaling"] if item["schedule"] == "dynamic" and item["requested_threads"] == 2)
            self.assertEqual(scaled["speedup"], 2.0)
            self.assertEqual(scaled["efficiency"], 1.0)
            self.assertTrue(result["metadata"]["fingerprints_verified_unchanged"])
            self.assertTrue(all((output / sample["evidence"]).is_file() for sample in scaled["samples"]))
        self.assertEqual(sum(not summary for _, _, summary in calls), 5)
        self.assertEqual(sum(summary for _, _, summary in calls), 10)


if __name__ == "__main__":
    unittest.main()
