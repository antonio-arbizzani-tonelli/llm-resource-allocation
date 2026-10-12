"""Hand-derived sensitivity metrics and recoverable campaign boundaries."""

from contextlib import redirect_stdout
from copy import deepcopy
from dataclasses import replace
import gzip
import io
import json
from pathlib import Path
import random
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import run_nightly_campaign as campaign
import run_stage2_stress as stress_runner
import summarize_nightly_campaign as summary
import profile_large_instances as profiling
from llm_resource_allocation.data import make_coherent_tiny_instance
from llm_resource_allocation.experiments.stress_grid import StressGrid, iter_stress_scenarios, make_stress_scenario, service_observations


class StressGridTests(unittest.TestCase):
    def test_hand_derived_mapping_and_deterministic_order(self):
        instance = make_coherent_tiny_instance()
        original_rng = random.getstate()
        points = list(iter_stress_scenarios(instance, StressGrid([0.8, 1.2], [1, 1.5])))
        self.assertEqual([(a, s) for a, s, _ in points], [(0.8, 1), (0.8, 1.5), (1.2, 1), (1.2, 1.5)])
        scenario = points[-1][2]
        route = (instance.query_ids[0], instance.model_ids[0], instance.gpu_tier_ids[0])
        self.assertAlmostEqual(scenario.arrival_rates_per_hour[instance.query_ids[0]], 12)
        self.assertAlmostEqual(scenario.compute_delay_seconds_per_token[route], 0.15)
        self.assertAlmostEqual(scenario.communication_delay_seconds_per_token[route], 0.015)
        self.assertAlmostEqual(scenario.effective_errors[route], 0.075)
        self.assertEqual(scenario.id, "arrival_01_stress_01")
        self.assertEqual(random.getstate(), original_rng)
        self.assertEqual(instance.compute_delay_seconds_per_token[route], 0.1)

    def test_invalid_or_duplicate_factors_and_owned_sequences(self):
        for arrivals, factors in (([], [1]), ([1, 1], [1]), ([True], [1]), ([-1], [1]),
                                  ([1], [0.9]), ([1], [float("nan")]), ([float("inf")], [1])):
            with self.subTest(arrivals=arrivals, factors=factors), self.assertRaises(ValueError):
                StressGrid(arrivals, factors)
        values = [1, 1.2]
        grid = StressGrid(values, [1])
        values.append(2)
        self.assertEqual(grid.scenario_count, 2)

    def test_hand_service_rates_changed_assignment_and_strict_threshold(self):
        instance = make_coherent_tiny_instance()
        i, j, k = instance.query_ids[0], instance.model_ids[0], instance.gpu_tier_ids[0]
        scenario = make_stress_scenario(instance, 1.2, 1, "hand")
        nominal = SimpleNamespace(routing_fractions={(i, j, k): 1}, unmet_fractions={i: 0})
        decision = SimpleNamespace(routing_fractions={(i, j, k): 0.8}, unmet_fractions={i: 0.2})
        metrics = service_observations(instance, scenario, decision, nominal)
        self.assertAlmostEqual(metrics["served_requests_per_hour"], 9.6)
        self.assertAlmostEqual(metrics["demand_weighted_unmet_fraction"], 0.2)
        self.assertAlmostEqual(metrics["mean_changed_assignment_fraction"], 0.2)
        self.assertEqual(metrics["unmet_over_1pct_query_fraction"], 1)
        decision.unmet_fractions = {i: 0.01}
        self.assertEqual(service_observations(instance, scenario, decision, nominal)["unmet_over_1pct_query_fraction"], 0)
        zero = make_stress_scenario(instance, 0, 1, "zero")
        self.assertIsNone(service_observations(instance, zero, decision, nominal)["demand_weighted_unmet_fraction"])


class CampaignPlanTests(unittest.TestCase):
    def setUp(self):
        self.config = campaign.load_configuration(ROOT / "configs/nightly_campaign.json")

    def test_default_plan_and_explicit_backend_override(self):
        jobs = campaign.campaign_jobs(self.config)
        self.assertEqual(len(jobs), 52)
        self.assertEqual([sum(job["kind"] == kind for job in jobs) for kind in ("stress", "serial", "openmp")], [40, 9, 3])
        self.assertEqual(len({job["id"] for job in jobs}), 52)
        self.assertEqual(StressGrid(self.config["arrival_factors"], self.config["stress_factors"]).scenario_count, 50)
        alternate = campaign.load_configuration(ROOT / "configs/nightly_campaign.json", "highs")
        self.assertEqual(alternate["backend"], "highs")
        self.assertNotEqual(campaign.configuration_digest(alternate), campaign.configuration_digest(self.config))

    def test_configuration_and_protected_output_boundaries(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            path = Path(temporary) / "config.json"
            for field, value in (("stage2_shapes", [[2, 2, 2], [2, 2, 2]]), ("backend", "unknown"),
                                 ("gh_budget_fraction", 0.9), ("job_timeout_seconds", 0),
                                 ("stage2_methods", ["gh", "gh"]), ("openmp_threads", [True])):
                config = {**self.config, field: value}
                path.write_text(json.dumps(config), encoding="utf-8")
                with self.subTest(field=field), self.assertRaises(ValueError):
                    campaign.load_configuration(path)
        for path in (ROOT, ROOT / "src/out", ROOT / "cpp/build/run", ROOT / "configs/out"):
            with self.assertRaises(ValueError):
                campaign.output_directory(path)
        self.assertEqual(campaign.output_directory(ROOT / "results/nightly"), ROOT / "results/nightly")

    def test_joint_dimensions_preserve_defaults_and_transport(self):
        original = profiling.workload_cases((2,))
        self.assertEqual(original[0].instance.dimensions, (2, 4, 4))
        cases = profiling.workload_cases((2,), model_count=3, tier_count=5)
        self.assertEqual([case.instance.dimensions for case in cases], [(2, 3, 5)] * 2)
        self.assertTrue(cases[0].name.startswith("2x3x5"))
        with self.assertRaises(ValueError):
            profiling.workload_cases((2,), model_count=1)

    def test_frozen_sources_binaries_and_config_detect_independent_tampering(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            output = Path(temporary)
            snapshot = output / "snapshot"
            (snapshot / "cpp/build/release").mkdir(parents=True)
            (snapshot / "cpp/Makefile").write_text("build", encoding="utf-8")
            (snapshot / "src").mkdir()
            source = snapshot / "src/domain.py"
            source.write_text("original", encoding="utf-8")
            for name in ("pacs_serial", "pacs_campaign"):
                (snapshot / "cpp/build/release" / name).write_bytes(b"binary")
            campaign.save_json(snapshot / "configs/nightly_campaign.json", self.config)
            manifest = {"source_sha256": campaign.source_inventory(snapshot),
                        "configuration_sha256": campaign.configuration_digest(self.config),
                        "binary_sha256": {name: campaign.digest(snapshot / "cpp/build/release" / name) for name in ("pacs_serial", "pacs_campaign")}}
            campaign.save_json(output / "snapshot_manifest.json", manifest)
            self.assertEqual(campaign.verify_snapshot(output, self.config), snapshot)
            source.write_text("changed", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "sources"):
                campaign.verify_snapshot(output, self.config)
            source.write_text("original", encoding="utf-8")
            binary = snapshot / "cpp/build/release/pacs_serial"
            binary.write_bytes(b"changed")
            with self.assertRaisesRegex(RuntimeError, "binaries"):
                campaign.verify_snapshot(output, self.config)
            binary.write_bytes(b"binary")
            campaign.save_json(snapshot / "configs/nightly_campaign.json", {**self.config, "backend": "highs"})
            with self.assertRaisesRegex(RuntimeError, "configuration"):
                campaign.verify_snapshot(output, self.config)


class CampaignExecutionTests(unittest.TestCase):
    def setUp(self):
        self.config = campaign.load_configuration(ROOT / "configs/nightly_campaign.json")
        self.job = {"id": "small", "kind": "stress", "shape": [2, 2, 2], "load": 1, "method": "gh", "seed": 37}

    def exercise(self, output, wait_error=None):
        (output / "logs").mkdir(exist_ok=True)
        worker = Mock(returncode=0)
        worker.wait.side_effect = wait_error
        def command(job, config, snapshot, destination, wsl):
            campaign.save_json(destination / "result.json", {"complete": True})
            return ["unused"]
        with patch.object(campaign, "job_command", side_effect=command), \
                patch.object(campaign.subprocess, "Popen", return_value=worker) as launch, \
                patch.object(campaign, "verify_snapshot"), patch.object(campaign, "terminate_worker") as terminate, \
                redirect_stdout(io.StringIO()):
            try:
                result = campaign.run_jobs(output, self.config, [self.job], output / "snapshot", None)
            except KeyboardInterrupt:
                result = "interrupted"
        return result, launch.call_count, terminate.call_count

    def test_completed_resume_skips_worker_and_rejects_changed_evidence(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            output = Path(temporary)
            self.assertEqual(self.exercise(output), ("completed", 1, 0))
            self.assertEqual(self.exercise(output), ("completed", 0, 0))
            (output / "jobs/small/result.json").write_text("edited", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "evidence changed"):
                self.exercise(output)

    def test_timeout_preserves_attempt_and_resume_uses_new_directory(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            output = Path(temporary)
            self.assertEqual(self.exercise(output, subprocess.TimeoutExpired("worker", 1)), ("incomplete", 1, 1))
            self.assertEqual(self.exercise(output), ("completed", 1, 0))
            history = json.loads((output / "jobs.json").read_text())
            self.assertEqual([item["status"] for item in history], ["timeout", "completed"])
            self.assertNotEqual(history[0]["output"], history[1]["output"])

    def test_interrupt_clears_active_state_and_preserves_attempt(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            output = Path(temporary)
            self.assertEqual(self.exercise(output, KeyboardInterrupt), ("interrupted", 1, 1))
            state = json.loads((output / "status.json").read_text())
            self.assertEqual(state["status"], "interrupted")
            self.assertIsNone(state["active_job"])

    def test_exhausted_budget_launches_no_worker(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            output = Path(temporary)
            with patch.object(campaign, "perf_counter", side_effect=[0, 20000]), \
                    patch.object(campaign, "verify_snapshot"), patch.object(campaign.subprocess, "Popen") as launch, \
                    redirect_stdout(io.StringIO()):
                self.assertEqual(campaign.run_jobs(output, self.config, [self.job], output / "snapshot", None), "incomplete")
            launch.assert_not_called()


class StressWorkerTests(unittest.TestCase):
    def test_short_real_highs_path_retains_independent_evidence(self):
        config = campaign.load_configuration(ROOT / "configs/nightly_campaign.json", "highs")
        config.update(arrival_factors=[1, 1.2], stress_factors=[1])
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary, redirect_stdout(io.StringIO()):
            output = Path(temporary)
            result = stress_runner.run_stress_case(config, (2, 2, 2), 1, "gh", 37, output)
            self.assertTrue(result["complete"] and result["stage1_accepted"])
            self.assertEqual(result["accepted_scenario_count"], 2)
            self.assertIsNotNone(result["aggregate"])
            self.assertTrue(all(item["objective_agrees"] and item["independently_feasible"] for item in result["attempts"]))
            evidence = json.loads(gzip.decompress((output / result["attempts"][0]["evidence"]).read_bytes()))
            self.assertIn("frozen_routing_validation", evidence)

    def test_failed_operational_run_has_no_quality_or_full_grid_aggregate(self):
        config = campaign.load_configuration(ROOT / "configs/nightly_campaign.json", "highs")
        config.update(arrival_factors=[1], stress_factors=[1])
        failure = SimpleNamespace(successful=False, status=SimpleNamespace(value="no_incumbent"),
                                  solver_evidence=SimpleNamespace(result=SimpleNamespace(status=SimpleNamespace(value="infeasible"))),
                                  objective_agrees=False, independently_feasible=False)
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary, redirect_stdout(io.StringIO()), \
                patch.object(stress_runner, "run_stage2", return_value=failure), \
                patch.object(stress_runner, "save_scientific_evidence", return_value="stub"):
            result = stress_runner.run_stress_case(config, (2, 2, 2), 1, "gh", 37, Path(temporary))
        self.assertEqual(result["accepted_scenario_count"], 0)
        self.assertIsNone(result["attempts"][0]["quality"])
        self.assertIsNone(result["aggregate"])


class CampaignSummaryTests(unittest.TestCase):
    def test_hand_derived_statistics_keep_median_and_minimum_distinct(self):
        stats = summary.duration_statistics([7, 1, 5, 3])
        self.assertEqual(stats, {"count": 4, "minimum_seconds": 1, "median_seconds": 4,
                                "q1_seconds": 2.5, "q3_seconds": 5.5, "iqr_seconds": 3})
        with self.assertRaises(ValueError):
            summary.duration_statistics([])

    def test_prepared_report_contains_coverage_and_no_measurements(self):
        config = campaign.load_configuration(ROOT / "configs/nightly_campaign.json")
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            output = Path(temporary)
            campaign.save_json(output / "plan.json", {"jobs": campaign.campaign_jobs(config)})
            campaign.save_json(output / "status.json", {"status": "prepared"})
            campaign.save_json(output / "snapshot_manifest.json", {"configuration_sha256": campaign.configuration_digest(config)})
            report = summary.summarize(output)
            self.assertEqual(len(report["coverage"]), 52)
            self.assertTrue(all(item["status"] == "not_run" for item in report["coverage"]))
            self.assertEqual(report["stress_scenarios"], [])
            self.assertEqual(report["serial_profiles"], [])
            self.assertIn("No experimental measurements exist yet", (output / "report.md").read_text())


if __name__ == "__main__":
    unittest.main()
