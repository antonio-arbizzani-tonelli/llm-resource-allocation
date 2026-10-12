"""Check benchmark evidence/aggregation against hand-checkable scientific data."""

from dataclasses import replace
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4

from scripts.run_synthetic_benchmark import capture_source_snapshot

import llm_resource_allocation.experiments.synthetic_benchmark as benchmark
from llm_resource_allocation.data.synthetic_benchmark_instances import make_synthetic_benchmark_cases
from llm_resource_allocation.math.objective import ObjectiveBreakdown
from llm_resource_allocation.math.objective import PaperVersion
from llm_resource_allocation.optimization.solver import SolverBackend, SolverStatus
from llm_resource_allocation.validation.placement import validate_placement


class SyntheticBenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.case = make_synthetic_benchmark_cases(())[0]
        cls.config = benchmark.SyntheticBenchmarkConfig(
            seeds=(37,), query_counts=(), warmup_repeats=0, backend=SolverBackend.HIGHS)
        cls.runs = benchmark.run_synthetic_benchmark(cls.config, (cls.case,))

    def test_internal_report_cache_does_not_change_artifact_schema(self) -> None:
        report = benchmark._plain(self.runs[0].validation)
        self.assertNotIn("_violations", report)

    def test_common_minimal_case_has_hand_derived_values_and_fresh_validation(self) -> None:
        self.assertEqual(tuple(run.method for run in self.runs), ("P_DM", "GH", "AGH"))
        for run in self.runs:
            self.assertTrue(run.completed)
            self.assertTrue(run.accepted)
            self.assertTrue(run.independently_feasible)
            self.assertEqual(run.objective.gpu_rental_cost, 1.0)
            self.assertEqual(run.objective.model_storage_cost, 0.001)
            self.assertAlmostEqual(run.objective.data_storage_cost, 0.00000003)
            self.assertAlmostEqual(run.objective.delay_penalty, 0.0031)
            self.assertEqual(run.objective.unmet_demand_penalty, 0.0)
            self.assertAlmostEqual(run.objective.total, 1.00410003)
            self.assertEqual(validate_placement(self.case.instance, run.placement, self.config.paper_version), run.validation)

    def test_gap_requires_accepted_optimal_matching_nonzero_reference(self) -> None:
        baseline, gh, _ = self.runs
        self.assertAlmostEqual(benchmark.objective_gap_percent(gh, baseline), 0.0)
        self.assertIsNone(benchmark.objective_gap_percent(gh, None))
        self.assertIsNone(benchmark.objective_gap_percent(replace(gh, accepted=False), baseline))
        self.assertIsNone(benchmark.objective_gap_percent(replace(gh, repeat=2), baseline))
        self.assertIsNone(benchmark.objective_gap_percent(gh, replace(baseline, solver=replace(baseline.solver, status=SolverStatus.FEASIBLE))))
        zero_report = replace(baseline.validation, objective_breakdown=ObjectiveBreakdown(0, 0, 0, 0, 0))
        self.assertIsNone(benchmark.objective_gap_percent(gh, replace(baseline, validation=zero_report)))
        other_version = replace(gh.validation, paper_version=PaperVersion.V1)
        self.assertIsNone(benchmark.objective_gap_percent(replace(gh, validation=other_version), baseline))

    def test_gap_retains_signed_arithmetic_without_clipping(self) -> None:
        baseline, gh, _ = self.runs
        report = replace(baseline.validation, objective_breakdown=ObjectiveBreakdown(10, 0, 0, 0, 0))
        baseline = replace(baseline, validation=report)
        report = replace(gh.validation, objective_breakdown=ObjectiveBreakdown(9, 0, 0, 0, 0))
        self.assertEqual(benchmark.objective_gap_percent(replace(gh, validation=report), baseline), -10.0)

    def test_summary_keeps_failed_attempt_timing_excludes_its_quality_and_warmups(self) -> None:
        baseline = replace(self.runs[0], elapsed_seconds=1.0)
        rejected = replace(baseline, repeat=1, accepted=False, elapsed_seconds=3.0)
        warmup = replace(baseline, repeat=-1, elapsed_seconds=100.0)
        self.assertTrue(benchmark._plain(warmup)["is_warmup"])
        self.assertFalse(benchmark._plain(baseline)["is_warmup"])
        rows = benchmark.summarize_benchmark((warmup, baseline, rejected), (self.case,))
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["run_count"], 2)
        self.assertEqual(row["accepted_count"], 1)
        self.assertEqual(row["time_median_seconds"], 2.0)
        self.assertEqual((row["time_q1_seconds"], row["time_q3_seconds"]), (1.5, 2.5))
        self.assertEqual(row["objective_median"], baseline.objective.total)
        self.assertEqual(row["gap_count"], 1)

    def test_exception_is_recorded_and_remaining_methods_still_run(self) -> None:
        with patch.object(benchmark, "execute_and_record_pdm_run", side_effect=RuntimeError("no result")):
            runs = benchmark.run_synthetic_benchmark(self.config, (self.case,))
        failed = runs[0]
        self.assertEqual(len(runs), 3)
        self.assertFalse(failed.accepted)
        self.assertIsNone(failed.objective)
        self.assertEqual((failed.error_type, failed.error_message), ("RuntimeError", "no result"))
        rows = benchmark.summarize_benchmark(runs, (self.case,))
        self.assertEqual(rows[0]["accepted_count"], 0)
        self.assertIsNone(rows[0]["objective_median"])
        self.assertTrue(runs[1].accepted)
        self.assertTrue(runs[2].accepted)
        self.assertIsNone(rows[1]["gap_median_percent"])

    def test_warmups_and_rotating_order_preserve_input_and_seed(self) -> None:
        config = replace(self.config, seeds=(37, 41), warmup_repeats=1)
        seen = []
        def run_one(case, selected_config, method, repeat, seed):
            seen.append((case, method, repeat, seed, repeat < 0))
            return replace(self.runs[0], method=method, repeat=repeat, seed=seed)
        with patch.object(benchmark, "_run_one", side_effect=run_one):
            runs = benchmark.run_synthetic_benchmark(config, (self.case,))
        self.assertEqual(len(runs), 9)
        self.assertTrue(all(item[0] is self.case for item in seen))
        self.assertEqual(tuple(item[1] for item in seen[6:]), ("GH", "AGH", "P_DM"))
        self.assertEqual(tuple(run.seed for run in runs), (37,) * 6 + (41,) * 3)
        self.assertEqual(sum(run.is_warmup for run in runs), 3)

    def test_elapsed_measurement_covers_public_runner(self) -> None:
        with patch.object(benchmark, "perf_counter", side_effect=(10.0, 10.25)):
            run = benchmark._run_one(self.case, self.config, "GH", 0, 37)
        self.assertEqual(run.elapsed_seconds, 0.25)

    def test_config_validation_rejects_invalid_parameters(self) -> None:
        for values in ({"seeds": ()}, {"seeds": (True,)}, {"warmup_repeats": -1},
                       {"query_counts": (2, 2)}, {"gh_budget_fraction": 1.1},
                       {"solver_time_limit_seconds": float("nan")}, {"solver_time_limit_seconds": 0}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                benchmark.SyntheticBenchmarkConfig(**values)

    def test_no_solver_incumbent_is_distinct_and_not_given_a_quality_value(self) -> None:
        case = replace(self.case, instance=replace(self.case.instance, cost_budget_usd=0.0))
        run = benchmark._run_one(case, self.config, "P_DM", 0, 37)
        self.assertEqual(run.status, "no_solver_incumbent")
        self.assertEqual(run.error_type, "NoSolverIncumbentError")
        self.assertFalse(run.accepted)
        self.assertIsNone(run.solver)
        self.assertIsNone(run.objective)

    def test_empty_duplicate_cases_are_rejected(self) -> None:
        for cases in ((), (self.case, self.case)):
            with self.assertRaises(ValueError):
                benchmark.run_synthetic_benchmark(self.config, cases)

    def test_source_snapshot_survives_later_live_file_changes(self) -> None:
        directory = Path(__file__).resolve().parents[1] / f".benchmark-test-{uuid4().hex}"
        source = directory / "live/src/example.py"
        source.parent.mkdir(parents=True)
        source.write_text("value = 1\n", encoding="utf-8")
        try:
            snapshot = capture_source_snapshot(directory / "output", directory / "live", "{}")
            source.write_text("value = 2\n", encoding="utf-8")
            self.assertEqual((snapshot / "src/example.py").read_text(encoding="utf-8"), "value = 1\n")
            self.assertEqual((snapshot / "configs/synthetic_benchmark.json").read_text(encoding="utf-8"), "{}")
        finally:
            self.assertTrue(directory.resolve().is_relative_to(Path(__file__).resolve().parents[1]))
            for path in sorted(directory.rglob("*"), key=lambda p: len(p.parts), reverse=True):
                if path.is_file():
                    path.unlink()
                else:
                    path.rmdir()
            directory.rmdir()

    def test_export_preserves_tensors_provenance_and_query_metrics(self) -> None:
        directory = Path(__file__).resolve().parents[1] / f".benchmark-test-{uuid4().hex}"
        directory.mkdir()
        try:
            rows = benchmark.write_benchmark_results(directory, self.config, (self.case,), self.runs, Path(__file__).resolve().parents[1])
            self.assertEqual(len(rows), 3)
            manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["classification"], "SYNTHETIC_REFERENCE_BENCHMARK")
            self.assertEqual(manifest["config"]["seeds"], [37])
            instance = manifest["cases"][0]["instance"]
            self.assertEqual(instance["base_error_rate"], [{"key": ["q_text", "m_small"], "value": 0.05}])
            evidence = [json.loads(line) for line in (directory / "evidence.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(evidence), 3)
            self.assertTrue(evidence[0]["accepted"])
            self.assertEqual(evidence[0]["placement"]["auxiliary_products"][0]["key"][:3], ["q_text", "m_small", "gpu_basic_fp16"])
            query_csv = (directory / "query_metrics.csv").read_text(encoding="utf-8")
            self.assertIn("modeled_weighted_error,error_slo", query_csv)
            self.assertEqual(len(query_csv.splitlines()), 4)
            self.assertIn("backend highs", (directory / "report.md").read_text(encoding="utf-8"))
            failure = replace(self.runs[0], accepted=False, placement=None, validation=None)
            benchmark.write_benchmark_results(directory, self.config, (self.case,), (failure,), Path(__file__).resolve().parents[1])
            self.assertFalse((directory / "query_metrics.csv").exists())
        finally:
            for child in directory.iterdir():
                child.unlink()
            directory.rmdir()


if __name__ == "__main__":
    unittest.main()
