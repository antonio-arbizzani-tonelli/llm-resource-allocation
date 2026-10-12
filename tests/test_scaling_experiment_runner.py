"""Integration checks for campaign exports against retained scientific evidence."""

from contextlib import redirect_stdout
from dataclasses import replace
import csv
import gzip
import io
import json
from pathlib import Path
import shutil
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

from llm_resource_allocation.experiments.azure_replay import run_azure_replay
from llm_resource_allocation.optimization.solver import SolverBackend
from scripts import run_scaling_experiment as runner
from scripts.run_azure_replay import _plain


class ScalingExperimentRunnerTests(unittest.TestCase):
    """Exercise generic nominal inputs, accepted LPs and operational failures."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.root = runner.ROOT / "results" / f"scaling_worker_test_{uuid4().hex}"
        if not cls.root.resolve().is_relative_to((runner.ROOT / "results").resolve()):
            raise RuntimeError("Test workspace must stay within the repository results directory")
        cls.root.mkdir()
        cls.addClassCleanup(shutil.rmtree, cls.root)
        cls.results = {}
        for case_id, dimensions, load, method, variant, counts in (
            ("tiny", [2, 2, 2], 1, "p_dm", "static", [1] * 288),
            ("larger", [4, 4, 5], 1, "gh", "rolling", [1] * 288),
            ("overload", [2, 2, 2], 100000, "gh", "static", [4, 4] + [1] * 286),
        ):
            total = sum(counts)
            profile = {
                "classification": "REAL_TRACE_COUNTS_WITHOUT_SCIENTIFIC_CALIBRATION",
                "days": [{"date": "2024-05-14", "request_count": total,
                    "windows": [{"index": index, "request_count": count,
                                 "daily_multiplier": count * 288 / total}
                                for index, count in enumerate(counts)]}],
            }
            runner.save(cls.root / "results/azure_trace/profiles.json", profile)
            spec = dict(case_id=case_id, family="integration_fixture", dimensions=dimensions,
                        load_multiplier=load, delay_slo_multiplier=1, budget_multiplier=1)
            config = dict(case_specs=[spec], azure_solver_limit_seconds=5)
            job = dict(job_id=case_id, case_id=case_id, date="2024-05-14",
                       method=method, variant=variant, seed=37, window_count=2, pilot=True)
            captured = []

            def retain_result(windows, settings, **kwargs):
                # The historical campaign selects Gurobi; this export check
                # exercises the same scientific path with the base backend.
                portable_settings = replace(
                    settings,
                    solver_config=replace(settings.solver_config, backend=SolverBackend.HIGHS),
                )
                result = run_azure_replay(windows, portable_settings, **kwargs)
                captured.append(result)
                return result

            with patch.object(runner, "ROOT", cls.root), \
                    patch.object(sys, "path", [str(Path(runner.__file__).resolve().parent), *sys.path]), \
                    patch("llm_resource_allocation.experiments.azure_replay.run_azure_replay",
                          side_effect=retain_result), redirect_stdout(io.StringIO()):
                runner.azure_worker(config, cls.root / "output", job)
            target = cls.root / "output/azure" / case_id
            with gzip.open(target / "evidence.jsonl.gz", "rt", encoding="utf-8") as stream:
                evidence = [json.loads(line) for line in stream]
            with (target / "windows.csv").open(encoding="utf-8", newline="") as stream:
                window_rows = list(csv.DictReader(stream))
            with (target / "query_metrics.csv").open(encoding="utf-8", newline="") as stream:
                query_rows = list(csv.DictReader(stream))
            cls.results[case_id] = dict(
                result=captured[-1], spec=spec,
                summary=json.loads((target / "summary.json").read_text(encoding="utf-8")),
                evidence=evidence, windows=window_rows, queries=query_rows,
            )

    def test_partial_pilot_keeps_original_window_and_count_evidence(self) -> None:
        case = self.results["tiny"]
        summary = case["summary"]
        self.assertTrue(summary["pilot"])
        self.assertFalse(summary["full_day"])
        self.assertEqual(summary["window_count"], 2)
        self.assertEqual(summary["successful_window_count"], 2)
        self.assertEqual(summary["scenario_query_pair_count"], 4)
        self.assertEqual([row["window_index"] for row in case["windows"]], ["0", "1"])
        self.assertEqual([row["request_count"] for row in case["windows"]], ["1", "1"])
        self.assertEqual(summary["model_score_horizon_hours"], 2)
        self.assertEqual(summary["instance_provenance"]["classification"], "ASSUMED")

    def test_arbitrary_larger_instance_reaches_worker_and_exports_same_inputs(self) -> None:
        case = self.results["larger"]
        result = case["result"]
        self.assertEqual(result.nominal_problem_data.instance.dimensions, (4, 4, 5))
        self.assertEqual(case["summary"]["dimensions"], [4, 4, 5])
        self.assertEqual(case["summary"]["successful_window_count"], 2)
        self.assertEqual(len(case["queries"]), 8)
        sources = [row for row in case["evidence"] if row["kind"] == "stage1_source"]
        self.assertEqual(len(sources), 2)
        for row, window in zip(sources, result.windows, strict=True):
            self.assertTrue(row["accepted"])
            self.assertEqual(row["construction_instance"],
                             _plain(window.candidate.construction_problem_data.instance))
            self.assertEqual(len(row["construction_instance"]["queries"]), 4)
            self.assertEqual(len(row["construction_instance"]["models"]), 4)
            self.assertEqual(len(row["construction_instance"]["gpu_tiers"]), 5)

    def test_successful_export_rows_retain_independent_lp_validation(self) -> None:
        for identity in ("tiny", "larger"):
            case = self.results[identity]
            exported = [row for row in case["evidence"] if row["kind"] == "stage2_evaluation"]
            actual = []
            for window in case["result"].windows:
                for evaluation in (window.candidate_forecast_evaluation,
                                   window.incumbent_forecast_evaluation, window.operation):
                    if evaluation is not None:
                        self.assertTrue(evaluation.successful)
                        self.assertTrue(evaluation.evaluation_result.stage2_run_record.independently_feasible)
                        actual.append(evaluation.evaluation_result.stage2_run_record)
            self.assertEqual(len(exported), len(actual))
            for row, record in zip(exported, actual, strict=True):
                self.assertTrue(row["successful"])
                self.assertIsNone(row["failure"])
                self.assertEqual(row["stage2_run_record"], _plain(record))
                self.assertIsNotNone(row["stage2_run_record"]["scientific_evidence"]["validation_report"])

    def test_overload_failure_is_exported_without_fabricated_cost_or_query_metrics(self) -> None:
        case = self.results["overload"]
        summary = case["summary"]
        self.assertEqual(summary["successful_window_count"], 0)
        for name in ("mean_window_model_cost", "sum_window_model_cost",
                     "scenario_query_pair_count", "violation_count", "violation_rate"):
            self.assertIsNone(summary[name])
        self.assertEqual(case["queries"], [])
        for row in case["windows"]:
            self.assertEqual(row["successful"], "False")
            self.assertEqual(row["model_cost"], "")
            self.assertTrue(row["failure"])
        failures = [row for row in case["evidence"] if row["kind"] == "stage2_evaluation"]
        self.assertEqual(len(failures), 2)
        for row in failures:
            self.assertFalse(row["successful"])
            self.assertIsNotNone(row["failure"])
            self.assertIsNotNone(row["stage2_run_record"]["failure"])
            self.assertEqual(row["stage2_run_record"]["solver_evidence"]["result"]["status"],
                             "infeasible")


if __name__ == "__main__":
    unittest.main()
