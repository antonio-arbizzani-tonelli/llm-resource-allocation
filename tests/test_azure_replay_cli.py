"""Verify retained Azure replay evidence and a bounded CLI export.

The CLI input is a constructed constant-count profile, not Azure source data.
"""

import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import MappingProxyType, SimpleNamespace
import unittest

from llm_resource_allocation.experiments.azure_replay import (
    AzureReplayAggregate, AzureReplayFailure, ReplayQueryMetrics,
)
from scripts.run_azure_replay import (
    _plain, _presentation_timings, _source_evidence, _timing_row, _write_csv,
)


ROOT = Path(__file__).resolve().parents[1]


class AzureReplayExportTests(unittest.TestCase):
    """Keep scientific mapping keys, rejection reasons and empty-table meaning."""

    def test_derived_metrics_retain_the_previous_json_schema(self) -> None:
        query = ReplayQueryMetrics("q", 10.0, 0.25)
        self.assertEqual(_plain(query), {
            "query_id": "q", "arrival_rate_per_hour": 10.0,
            "unmet_fraction": 0.25, "served_fraction": 0.75, "violation": True,
        })
        aggregate = AzureReplayAggregate(2, 2, False, 6.0, 4, 1)
        self.assertEqual(_plain(aggregate), {
            "window_count": 2, "successful_window_count": 2, "full_day": False,
            "sum_window_model_cost": 6.0, "scenario_query_pair_count": 4,
            "violation_count": 1, "mean_window_model_cost": 3.0,
            "violation_rate": 0.25,
        })
        failed = AzureReplayAggregate(2, 1, False, None, None, None)
        self.assertIsNone(_plain(failed)["mean_window_model_cost"])
        self.assertIsNone(_plain(failed)["violation_rate"])

    def test_json_roundtrip_preserves_tuple_mapping_keys_and_real_zero(self) -> None:
        values = MappingProxyType({
            ("q_short", "m_accurate", "gpu_budget_int8"): 0.25,
            ("q_long", "m_compact", "gpu_fast_fp16"): 0.0,
        })
        retained = json.loads(json.dumps(_plain(values), allow_nan=False))
        restored = {tuple(item["key"]): item["value"] for item in retained}
        self.assertEqual(restored, dict(values))
        self.assertEqual(restored[("q_long", "m_compact", "gpu_fast_fp16")], 0.0)

    def test_refused_source_retains_failure_without_fabricated_placement(self) -> None:
        source = SimpleNamespace(
            construction_problem_data=SimpleNamespace(instance={"id": "fixture"}),
            forecast_multiplier=1.2,
            random_seed=37,
            source_result=None,
            accepted=False,
            failure=AzureReplayFailure("stage1", "RuntimeError", "source unavailable"),
            elapsed_seconds=0.125,
        )
        retained = json.loads(json.dumps(_source_evidence(source, "gh")))
        self.assertFalse(retained["accepted"])
        self.assertEqual(retained["failure"], {
            "boundary": "stage1", "error_type": "RuntimeError",
            "message": "source unavailable",
        })
        self.assertEqual(retained["forecast_multiplier"], 1.2)
        self.assertEqual(retained["construction_instance"], {"id": "fixture"})
        self.assertIsNone(retained["placement"])
        self.assertIsNone(retained["independent_validation"])
        self.assertEqual(retained["elapsed_seconds"], 0.125)

    def test_empty_query_table_replaces_previous_results_with_schema_only(self) -> None:
        columns = ["date", "method", "variant", "window_index", "query_id",
                   "arrival_rate_per_hour", "unmet_fraction", "served_fraction", "violation"]
        with tempfile.TemporaryDirectory(dir=ROOT, prefix=".azure-replay-test-") as temporary:
            path = Path(temporary) / "query_metrics.csv"
            path.write_text("date,query_id\nold-run,stale-query\n", encoding="utf-8")
            _write_csv(path, [], fieldnames=columns)
            with path.open(encoding="utf-8", newline="") as stream:
                reader = csv.DictReader(stream)
                self.assertEqual(reader.fieldnames, columns)
                self.assertEqual(list(reader), [])
            self.assertNotIn("stale-query", path.read_text(encoding="utf-8"))


class AzureReplayTimingTests(unittest.TestCase):
    """Use known call durations to distinguish calls from reused placements."""

    def test_static_source_is_timed_once_while_operation_is_timed_each_window(self) -> None:
        source = SimpleNamespace(accepted=True, elapsed_seconds=4.0)
        windows = tuple(SimpleNamespace(
            candidate=None, incumbent_before=source, selected_source=source,
            candidate_forecast_evaluation=None, incumbent_forecast_evaluation=None,
            operation=SimpleNamespace(elapsed_seconds=elapsed),
        ) for elapsed in (0.1, 0.2, 0.3))
        result = SimpleNamespace(static_source=source, windows=windows)
        timings = _timing_row(result, 5.5)
        self.assertEqual(timings["stage1_attempt_count"], 1)
        self.assertEqual(timings["stage1_accepted_count"], 1)
        self.assertEqual(timings["stage1_total_seconds"], 4.0)
        self.assertEqual(timings["stage1_median_seconds"], 4.0)
        self.assertEqual(timings["forecast_stage2_eval_count"], 0)
        self.assertEqual(timings["operational_stage2_eval_count"], 3)
        self.assertAlmostEqual(timings["operational_stage2_total_seconds"], 0.6)
        self.assertAlmostEqual(timings["orchestration_seconds"], 0.9)

    def test_rolling_timings_include_rejected_construction_and_failed_operation(self) -> None:
        sources = tuple(SimpleNamespace(accepted=accepted, elapsed_seconds=elapsed)
                        for accepted, elapsed in ((True, 1.0), (False, 8.0), (True, 3.0)))
        windows = (
            SimpleNamespace(candidate=sources[0],
                candidate_forecast_evaluation=SimpleNamespace(elapsed_seconds=0.1),
                incumbent_forecast_evaluation=None,
                operation=SimpleNamespace(successful=True, elapsed_seconds=0.4)),
            SimpleNamespace(candidate=sources[1], candidate_forecast_evaluation=None,
                incumbent_forecast_evaluation=SimpleNamespace(elapsed_seconds=0.2),
                operation=SimpleNamespace(successful=False, elapsed_seconds=0.6)),
            SimpleNamespace(candidate=sources[2],
                candidate_forecast_evaluation=SimpleNamespace(elapsed_seconds=0.3),
                incumbent_forecast_evaluation=SimpleNamespace(elapsed_seconds=0.4),
                operation=SimpleNamespace(successful=True, elapsed_seconds=0.8)),
        )
        timings = _timing_row(SimpleNamespace(static_source=None, windows=windows), 16.0)
        self.assertEqual(timings["stage1_attempt_count"], 3)
        self.assertEqual(timings["stage1_accepted_count"], 2)
        self.assertEqual(timings["stage1_total_seconds"], 12.0)
        self.assertEqual(timings["stage1_median_seconds"], 3.0)
        self.assertEqual(timings["forecast_stage2_eval_count"], 4)
        self.assertAlmostEqual(timings["forecast_stage2_total_seconds"], 1.0)
        self.assertEqual(timings["operational_stage2_eval_count"], 3)
        self.assertAlmostEqual(timings["operational_stage2_total_seconds"], 1.8)
        self.assertAlmostEqual(timings["orchestration_seconds"], 1.2)

    def test_presentation_aggregates_days_and_uses_individual_attempt_median(self) -> None:
        rows = [
            {"method": "gh", "variant": "rolling", "window_count": 2,
             "replay_time_seconds": 2.0, "forecast_stage2_total_seconds": 0.02,
             "operational_stage2_total_seconds": 0.2, "orchestration_seconds": 1.679},
            {"method": "gh", "variant": "rolling", "window_count": 1,
             "replay_time_seconds": 3.0, "forecast_stage2_total_seconds": 0.03,
             "operational_stage2_total_seconds": 0.3, "orchestration_seconds": 2.668},
        ]
        sources = [{"method": "gh", "variant": "rolling", "accepted": accepted,
                    "elapsed_seconds": elapsed}
                   for accepted, elapsed in ((True, 0.001), (False, 0.1), (True, 0.002))]
        summary, = _presentation_timings(rows, sources)
        self.assertEqual(summary["day_count"], 2)
        self.assertEqual(summary["window_count"], 3)
        self.assertEqual(summary["replay_total_seconds"], 5.0)
        self.assertEqual(summary["stage1_attempt_count"], 3)
        self.assertEqual(summary["stage1_accepted_count"], 2)
        self.assertEqual(summary["stage1_median_milliseconds"], 2.0)
        self.assertAlmostEqual(summary["stage1_total_seconds"], 0.103)
        self.assertAlmostEqual(summary["forecast_stage2_total_seconds"], 0.05)
        self.assertAlmostEqual(summary["operational_stage2_total_seconds"], 0.5)


class AzureReplayCliTests(unittest.TestCase):
    """Check one operational window through actual GH, Stage 2 and file export."""

    def test_configured_partial_pilot_retains_forecast_and_source_provenance(self) -> None:
        if importlib.util.find_spec("matplotlib") is None:
            self.skipTest("optional matplotlib is unavailable")
        config = json.loads((ROOT / "configs/azure_replay.json").read_text(encoding="utf-8"))
        config.update(dates=["2024-05-14"], methods=["gh"], variants=["rolling"],
                      ewma_alpha=0.5, initial_forecast_multiplier=1.2)
        profile = {
            "classification": "REAL_TRACE_COUNTS_WITHOUT_SCIENTIFIC_CALIBRATION",
            "source_manifest": {"source": "constructed test input; not real Azure data"},
            "days": [{
                "date": "2024-05-14", "request_count": 28800,
                "windows": [{"index": index, "daily_multiplier": 1.0, "request_count": 100}
                            for index in range(288)],
            }],
        }
        with tempfile.TemporaryDirectory(dir=ROOT, prefix=".azure-replay-test-") as temporary:
            directory = Path(temporary)
            config_path, profile_path = directory / "config.json", directory / "profiles.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            profile_path.write_text(json.dumps(profile), encoding="utf-8")
            output = directory / "output"
            completed = subprocess.run(
                [sys.executable, "-B", str(ROOT / "scripts/run_azure_replay.py"),
                 "--profiles", str(profile_path), "--config", str(config_path),
                 "--output", str(output), "--window-limit", "1", "--warmup-windows", "3"],
                cwd=ROOT, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
            with (output / "summary.csv").open(encoding="utf-8", newline="") as stream:
                summary = list(csv.DictReader(stream))
            self.assertEqual(len(summary), 1)
            self.assertEqual(summary[0]["full_day"], "False")
            self.assertEqual(summary[0]["window_count"], "1")
            self.assertEqual(summary[0]["successful_window_count"], "1")
            with (output / "windows.csv").open(encoding="utf-8", newline="") as stream:
                windows = list(csv.DictReader(stream))
            self.assertEqual(len(windows), 1)
            self.assertAlmostEqual(float(windows[0]["forecast_multiplier"]), 1.2)
            self.assertAlmostEqual(float(windows[0]["next_forecast_multiplier"]), 1.1)
            report = (output / "report.md").read_text(encoding="utf-8")
            self.assertIn("alpha=0.5", report)
            self.assertIn("inizializzata a 1.2", report)
            self.assertIn("Non è una replica della Tabella 5", report)
            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["window_limit"], 1)
            self.assertEqual(manifest["configuration"]["ewma_alpha"], 0.5)
            snapshot = output / manifest["source_snapshot"]
            self.assertIn("src/llm_resource_allocation/experiments/azure_replay.py",
                          manifest["source_sha256"])
            for relative, expected in manifest["source_sha256"].items():
                self.assertEqual(hashlib.sha256((snapshot / relative).read_bytes()).hexdigest(),
                                 expected, relative)
            evidence = [json.loads(line) for line in
                        (output / "evidence.jsonl").read_text(encoding="utf-8").splitlines()]
            source, operation = evidence
            self.assertEqual(source["kind"], "stage1_source")
            self.assertTrue(source["accepted"])
            self.assertEqual(operation["kind"], "operational_window")
            self.assertEqual(operation["selected_source_id"], source["source_id"])
            self.assertEqual(operation["stage2_run_record"]["status"], "success")
            with (output / "timing_summary.csv").open(encoding="utf-8", newline="") as stream:
                timing, = csv.DictReader(stream)
            self.assertEqual(timing["method"], "gh")
            self.assertEqual(timing["variant"], "rolling")
            # Requested warmup=3 is limited to the one available window;
            # that excluded call must not increase the measured counts.
            self.assertEqual(timing["stage1_attempt_count"], "1")
            self.assertEqual(timing["stage1_accepted_count"], "1")
            self.assertEqual(timing["forecast_stage2_eval_count"], "1")
            self.assertEqual(timing["operational_stage2_eval_count"], "1")
            for field, value in timing.items():
                if field.endswith("seconds"):
                    self.assertGreaterEqual(float(value), 0.0, field)
            with (output / "stage1_timings.csv").open(encoding="utf-8", newline="") as stream:
                stage1, = csv.DictReader(stream)
            self.assertGreaterEqual(float(stage1["elapsed_seconds"]), 0.0)
            with (output / "evaluation_timings.csv").open(encoding="utf-8", newline="") as stream:
                evaluations = list(csv.DictReader(stream))
            self.assertEqual(len(evaluations), 2)
            for evaluation in evaluations:
                self.assertGreaterEqual(float(evaluation["elapsed_seconds"]), 0.0)
            with (output / "timing_presentation.csv").open(encoding="utf-8", newline="") as stream:
                presentation, = csv.DictReader(stream)
            self.assertEqual(presentation["day_count"], "1")
            self.assertEqual(presentation["stage1_attempt_count"], "1")
            self.assertAlmostEqual(float(presentation["replay_total_seconds"]),
                                   float(timing["replay_time_seconds"]))
            self.assertAlmostEqual(float(presentation["stage1_median_milliseconds"]),
                                   1000 * float(stage1["elapsed_seconds"]))
            self.assertIn("timing_policy", manifest)
            self.assertEqual(manifest["excluded_warmups"][0]["window_count"], 1)
            self.assertGreater((output / "runtime_comparison.png").stat().st_size, 0)
            self.assertGreater((output / "runtime_comparison.svg").stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
