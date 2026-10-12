"""Hand-derived and real-solver checks for the explicit Azure replay policy."""

from dataclasses import FrozenInstanceError, fields, replace
import random
import unittest
from unittest.mock import patch

import llm_resource_allocation.experiments.azure_replay as replay
from scripts.run_azure_replay import _plain
from llm_resource_allocation.algorithms.gh import run_gh
from llm_resource_allocation.data.tiny_instances import (
    make_heterogeneous_tiny_instance, make_minimal_tiny_instance,
)
from llm_resource_allocation.optimization.problem_data import PdmProblemData
from llm_resource_allocation.optimization.solver import SolverBackend, SolverConfig
from llm_resource_allocation.optimization.stage2_adapter import Stage1Method
from llm_resource_allocation.optimization.stage2_integration import Stage1Stage2EvaluationStatus


class AzureReplayPolicyTests(unittest.TestCase):
    """Verify arithmetic, causal policy and input domains without solver calls."""

    def test_ewma_has_hand_derived_next_forecasts(self) -> None:
        forecast = 1.0
        used = []
        for observed in (2.0, 0.0, 3.0):
            used.append(forecast)
            forecast = replay.update_ewma_forecast(forecast, observed, 0.2)
        for actual, expected in zip(used, (1.0, 1.2, 0.96), strict=True):
            self.assertAlmostEqual(actual, expected)
        self.assertAlmostEqual(forecast, 1.368)

    def test_scaling_changes_only_arrivals_and_identity(self) -> None:
        original = make_heterogeneous_tiny_instance()
        scaled = replay.scale_instance_arrivals(original, 2.5, instance_id="azure_test")
        self.assertEqual(tuple(q.arrival_rate_per_hour for q in scaled.queries), (30.0, 10.0))
        self.assertEqual(tuple(q.arrival_rate_per_hour for q in original.queries), (12.0, 4.0))
        restored = replace(scaled, id=original.id, queries=tuple(
            replace(query, arrival_rate_per_hour=nominal.arrival_rate_per_hour)
            for query, nominal in zip(scaled.queries, original.queries, strict=True)
        ))
        self.assertEqual(restored, original)
        self.assertEqual(scaled.horizon_hours, 2.0)
        self.assertEqual(tuple(q.max_unmet_fraction for q in scaled.queries), (0.10, 0.05))

    def test_realization_scales_all_arrivals_and_keeps_delay_error(self) -> None:
        data = PdmProblemData(make_heterogeneous_tiny_instance())
        scenario = replay.make_replay_scenario(data, 0.25, "azure-scenario")
        self.assertEqual(dict(scenario.arrival_rates_per_hour), {"q_short": 3.0, "q_long": 1.0})
        self.assertEqual(scenario.compute_delay_seconds_per_token,
                         data.instance.compute_delay_seconds_per_token)
        self.assertEqual(scenario.communication_delay_seconds_per_token,
                         data.instance.communication_delay_seconds_per_token)
        # q_short/compact has e_base=.06 and INT8 mu=1.15.
        self.assertAlmostEqual(scenario.effective_errors[
            ("q_short", "m_compact", "gpu_budget_int8")], 0.069)
        self.assertAlmostEqual(scenario.effective_errors[
            ("q_short", "m_compact", "gpu_fast_fp16")], 0.06)

    def test_keep_best_is_strict_and_preserves_exact_ties(self) -> None:
        self.assertTrue(replay.should_replace_incumbent(2.0, 3.0))
        self.assertFalse(replay.should_replace_incumbent(3.0, 3.0))
        self.assertFalse(replay.should_replace_incumbent(4.0, 3.0))
        self.assertTrue(replay.should_replace_incumbent(3.0 - 1e-12, 3.0))

    def test_failed_candidate_never_replaces_and_failed_incumbent_can_be_replaced(self) -> None:
        self.assertFalse(replay.should_replace_incumbent(None, 3.0))
        self.assertFalse(replay.should_replace_incumbent(None, None))
        self.assertTrue(replay.should_replace_incumbent(3.0, None))

    def test_invalid_window_values_are_rejected(self) -> None:
        for index, multiplier in ((True, 1.0), (-1, 1.0), (288, 1.0), (0, -1.0),
                                  (0, float("nan")), (0, True)):
            with self.subTest(index=index, multiplier=multiplier), self.assertRaises(ValueError):
                replay.AzureReplayWindow(index, multiplier)
        for count in (True, -1, 2.5):
            with self.subTest(count=count), self.assertRaises(ValueError):
                replay.AzureReplayWindow(0, 1.0, count)

    def test_invalid_policy_values_are_rejected(self) -> None:
        config = replay.AzureReplayConfig(Stage1Method.GH, replay.AzureReplayVariant.ROLLING)
        for updates in ({"ewma_alpha": 0.0}, {"ewma_alpha": 1.1}, {"random_seed": True},
                        {"initial_forecast_multiplier": -1.0}, {"solver_config": "highs"}):
            with self.subTest(updates=updates), self.assertRaises((TypeError, ValueError)):
                replace(config, **updates)

    def test_empty_duplicate_or_reversed_windows_are_rejected(self) -> None:
        config = replay.AzureReplayConfig(Stage1Method.GH, replay.AzureReplayVariant.STATIC)
        zero, one = replay.AzureReplayWindow(0, 1.0), replay.AzureReplayWindow(1, 1.0)
        for windows in ((), (zero, zero), (one, zero)):
            with self.subTest(windows=windows), self.assertRaises(ValueError):
                replay.run_azure_replay(windows, config)


class AzureReplayIntegrationTests(unittest.TestCase):
    """Use all three unchanged Stage-1 methods and the independently checked LP."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.solver_config = SolverConfig(backend=SolverBackend.HIGHS)
        cls.windows = tuple(replay.AzureReplayWindow(index, multiplier, count)
                            for index, (multiplier, count) in enumerate(
                                ((1.0, 100), (1.2, 120), (0.8, 80))))
        cls.results = {}
        for method in Stage1Method:
            for variant in replay.AzureReplayVariant:
                cls.results[method, variant] = replay.run_azure_replay(
                    cls.windows, replay.AzureReplayConfig(
                        method, variant, solver_config=cls.solver_config))

    def test_all_methods_and_variants_use_independently_accepted_operations(self) -> None:
        for key, result in self.results.items():
            with self.subTest(key=key):
                self.assertTrue(result.successful)
                self.assertEqual(result.aggregate.successful_window_count, 3)
                self.assertEqual(result.aggregate.scenario_query_pair_count, 6)
                self.assertFalse(result.aggregate.full_day)
                self.assertEqual(result.classification, "REAL_AZURE_TRACE_SYNTHETIC_INSTANCE_REPLAY")
                for window in result.windows:
                    operation = window.operation
                    self.assertTrue(operation.source.accepted)
                    self.assertTrue(operation.evaluation_result.stage2_run_record.independently_feasible)
                    self.assertEqual(len(window.query_metrics), 2)
                    self.assertIs(operation.evaluation_result.source_result, operation.source.source_result)
                    self.assertIs(operation.evaluation_result.pdm_problem_data,
                                  operation.source.construction_problem_data)
                    self.assertIs(operation.scenario, window.realized_scenario)

    def test_static_source_is_constructed_once_and_retained(self) -> None:
        for method in Stage1Method:
            result = self.results[method, replay.AzureReplayVariant.STATIC]
            self.assertEqual(result.static_source.forecast_multiplier, 1.0)
            for window in result.windows:
                self.assertIs(window.selected_source, result.static_source)
                self.assertIsNone(window.candidate)
                self.assertEqual(window.forecast_multiplier, 1.0)

    def test_rolling_forecasts_use_only_previous_observations(self) -> None:
        # Observations 1,1.2,.8 give forecasts 1,1,1.04; final forecast=.992.
        for method in Stage1Method:
            result = self.results[method, replay.AzureReplayVariant.ROLLING]
            for window, expected in zip(result.windows, (1.0, 1.0, 1.04), strict=True):
                self.assertAlmostEqual(window.forecast_multiplier, expected)
                self.assertAlmostEqual(window.candidate.forecast_multiplier, expected)
                rates = window.candidate.construction_problem_data.instance.queries
                self.assertAlmostEqual(rates[0].arrival_rate_per_hour, 12.0 * expected)
                self.assertAlmostEqual(rates[1].arrival_rate_per_hour, 4.0 * expected)
            self.assertAlmostEqual(result.windows[-1].next_forecast_multiplier, 0.992)

    def test_rolling_comparison_shares_forecast_but_preserves_construction_data(self) -> None:
        for method in Stage1Method:
            result = self.results[method, replay.AzureReplayVariant.ROLLING]
            first = result.windows[0].selected_source
            third = result.windows[2]
            self.assertIs(third.candidate_forecast_evaluation.scenario,
                          third.incumbent_forecast_evaluation.scenario)
            self.assertIs(third.incumbent_forecast_evaluation.source, first)
            self.assertEqual(first.forecast_multiplier, 1.0)
            self.assertIs(third.incumbent_forecast_evaluation.evaluation_result.pdm_problem_data,
                          first.construction_problem_data)
            self.assertIs(third.selected_source, first)
            self.assertIs(third.selection, replay.ReplaySelection.KEEP_INCUMBENT)
            self.assertEqual(third.candidate_forecast_evaluation.full_model_cost,
                             third.incumbent_forecast_evaluation.full_model_cost)
            self.assertEqual(tuple(window.candidate.random_seed for window in result.windows), (37, 37, 37))

    def test_cost_and_aggregation_match_hand_derived_fixed_placement(self) -> None:
        # m_accurate on one budget GPU serves both queries at TP=PP=1.
        # C1=2*.5=1; C2=2*.001*(6+6)=.024.
        # D_short=.30*(2+2)+.03*2=1.26; D_long=.36*(6+4)+.03*4=3.72.
        # C4=.01*1.26+.02*3.72=.087; u=0 makes C5 zero.
        # C3=2*.001*(1e-6*4*12+3e-6*10*4)*multiplier=3.36e-7*multiplier.
        for key, result in self.results.items():
            with self.subTest(key=key):
                for window, multiplier in zip(result.windows, (1.0, 1.2, 0.8), strict=True):
                    self.assertAlmostEqual(window.model_cost, 1.111 + 3.36e-7 * multiplier)
                    self.assertEqual(tuple(metric.unmet_fraction for metric in window.query_metrics), (0.0, 0.0))
                self.assertAlmostEqual(result.aggregate.mean_window_model_cost, 1.111000336)
                self.assertAlmostEqual(result.aggregate.sum_window_model_cost, 3.333001008)
                self.assertEqual(result.aggregate.violation_count, 0)
                self.assertEqual(result.nominal_problem_data.instance.horizon_hours, 2.0)

    def test_complete_day_aggregation_is_288_times_window_mean(self) -> None:
        reference = self.results[Stage1Method.GH, replay.AzureReplayVariant.STATIC].windows[0]
        windows = tuple(replace(reference, window=replay.AzureReplayWindow(index, 1.0))
                        for index in range(288))
        aggregate = replay.aggregate_replay_windows(windows)
        self.assertTrue(aggregate.full_day)
        self.assertEqual(aggregate.window_count, 288)
        self.assertAlmostEqual(aggregate.sum_window_model_cost,
                               288 * 1.111000336)
        self.assertAlmostEqual(aggregate.mean_window_model_cost, 1.111000336)
        self.assertEqual(aggregate.scenario_query_pair_count, 576)

    def test_failed_operation_is_preserved_and_suppresses_aggregate(self) -> None:
        result = replay.run_azure_replay(
            (replay.AzureReplayWindow(0, 1e7), replay.AzureReplayWindow(1, 1.0)),
            replay.AzureReplayConfig(Stage1Method.P_DM, replay.AzureReplayVariant.STATIC,
                                     solver_config=self.solver_config),
        )
        self.assertFalse(result.successful)
        self.assertEqual(tuple(window.successful for window in result.windows), (False, True))
        self.assertIs(result.windows[0].operation.evaluation_result.status,
                      Stage1Stage2EvaluationStatus.STAGE2_RUN_FAILED)
        self.assertIsNotNone(result.windows[0].operation.evaluation_result.stage2_run_record.failure)
        self.assertIsNotNone(result.windows[0].operation.failure)
        self.assertIn("infeasible", result.windows[0].operation.failure.message)
        self.assertEqual(result.aggregate.successful_window_count, 1)
        self.assertIsNone(result.aggregate.mean_window_model_cost)
        self.assertIsNone(result.aggregate.sum_window_model_cost)
        self.assertIsNone(result.aggregate.violation_rate)

    def test_failed_candidate_keeps_previous_source_and_retains_failure(self) -> None:
        calls = 0
        def reject_second(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("declared candidate failure")
            return run_gh(*args, **kwargs)
        with patch.object(replay, "run_gh", side_effect=reject_second):
            result = replay.run_azure_replay(
                self.windows[:2], replay.AzureReplayConfig(
                    Stage1Method.GH, replay.AzureReplayVariant.ROLLING,
                    solver_config=self.solver_config))
        self.assertTrue(result.successful)
        second = result.windows[1]
        self.assertFalse(second.candidate.accepted)
        self.assertEqual(second.candidate.failure.message, "declared candidate failure")
        self.assertIs(second.selected_source, result.windows[0].selected_source)
        self.assertIs(second.selection, replay.ReplaySelection.KEEP_INCUMBENT)
        self.assertIsNone(second.candidate_forecast_evaluation)

    def _capacity_transition_instance(self):
        # At nominal lambda=10 and r=3, 1,080,000 GFLOP/token gives exactly
        # 32,400 TFLOP/hour load, equal to one GPU's available capacity.
        # phi=20 makes two GPUs preferable to paying u=.2 under forecast1.25.
        base = make_minimal_tiny_instance()
        return replace(
            base, id="azure_capacity_transition",
            queries=(replace(base.queries[0], unmet_penalty_usd_per_hour=20.0),),
            compute_gflop_per_token={key: 1080000.0 for key in base.compute_gflop_per_token},
        )

    def test_strict_forecast_improvement_changes_source_using_real_lp_scores(self) -> None:
        result = replay.run_azure_replay(
            (replay.AzureReplayWindow(0, 2.0), replay.AzureReplayWindow(1, 2.0)),
            replay.AzureReplayConfig(Stage1Method.P_DM, replay.AzureReplayVariant.ROLLING,
                                     ewma_alpha=0.25, solver_config=self.solver_config),
            instance=self._capacity_transition_instance(),
        )
        first, second = result.windows
        self.assertIs(second.selection, replay.ReplaySelection.STRICT_IMPROVEMENT)
        self.assertIsNot(second.selected_source, first.selected_source)
        self.assertIs(second.selected_source, second.candidate)
        self.assertAlmostEqual(second.forecast_multiplier, 1.25)
        # Incumbent x=.8,u=.2: C1+C2=1.001, C4=.00248, C5=4,
        # and C3=3e-8. Candidate TP=2 has C1+C2=2.001,
        # D_cfg=.16, C4=.0016,C5=0,C3=3.75e-8.
        self.assertAlmostEqual(second.incumbent_forecast_evaluation.full_model_cost, 5.00348003)
        self.assertAlmostEqual(second.candidate_forecast_evaluation.full_model_cost, 2.0026000375)
        self.assertTrue(second.successful)
        # The first realized 2x load exceeded the first source's cap; preserve it.
        self.assertFalse(first.successful)
        self.assertIsNone(result.aggregate.sum_window_model_cost)

    def test_infeasible_incumbent_forecast_is_replaced_and_failure_retained(self) -> None:
        result = replay.run_azure_replay(
            (replay.AzureReplayWindow(0, 2.0), replay.AzureReplayWindow(1, 2.0)),
            replay.AzureReplayConfig(Stage1Method.P_DM, replay.AzureReplayVariant.ROLLING,
                                     ewma_alpha=0.5, solver_config=self.solver_config),
            instance=self._capacity_transition_instance(),
        )
        second = result.windows[1]
        self.assertIs(second.selection, replay.ReplaySelection.INCUMBENT_FORECAST_FAILED)
        self.assertFalse(second.incumbent_forecast_evaluation.successful)
        self.assertIn("infeasible", second.incumbent_forecast_evaluation.failure.message)
        self.assertTrue(second.candidate_forecast_evaluation.successful)
        self.assertIs(second.selected_source, second.candidate)
        self.assertTrue(second.successful)

    def test_absent_initial_source_does_not_fabricate_operation(self) -> None:
        with patch.object(replay, "run_gh", side_effect=RuntimeError("no candidate")):
            result = replay.run_azure_replay(
                self.windows[:1], replay.AzureReplayConfig(
                    Stage1Method.GH, replay.AzureReplayVariant.ROLLING,
                    solver_config=self.solver_config))
        window = result.windows[0]
        self.assertIs(window.selection, replay.ReplaySelection.NO_ACCEPTED_SOURCE)
        self.assertIsNone(window.operation)
        self.assertEqual(window.query_metrics, ())
        self.assertIsNone(result.aggregate.sum_window_model_cost)
        self.assertEqual(window.candidate.failure.message, "no candidate")

    def test_result_is_immutable_and_does_not_mutate_global_rng(self) -> None:
        before = random.getstate()
        result = replay.run_azure_replay(
            self.windows[:1], replay.AzureReplayConfig(
                Stage1Method.AGH, replay.AzureReplayVariant.ROLLING,
                solver_config=self.solver_config))
        self.assertEqual(random.getstate(), before)
        with self.assertRaises(FrozenInstanceError):
            result.windows[0].forecast_multiplier = 2.0

    def test_stage1_fake_clock_includes_scaling_runner_and_acceptance(self) -> None:
        reference = self.results[Stage1Method.GH, replay.AzureReplayVariant.STATIC]
        events = []
        clock_values = iter((10.0, 12.5))
        real_scale = replay.scale_instance_arrivals
        real_adapter = replay.stage2_fixed_deployment_from_stage1
        def clock():
            events.append("clock")
            return next(clock_values)
        def scale(*args, **kwargs):
            events.append("scale")
            return real_scale(*args, **kwargs)
        def runner(*args, **kwargs):
            events.append("runner")
            return reference.static_source.source_result
        def adapter(*args, **kwargs):
            events.append("acceptance")
            return real_adapter(*args, **kwargs)
        with (patch.object(replay, "perf_counter", side_effect=clock),
              patch.object(replay, "scale_instance_arrivals", side_effect=scale),
              patch.object(replay, "run_gh", side_effect=runner),
              patch.object(replay, "stage2_fixed_deployment_from_stage1", side_effect=adapter)):
            attempt = replay._construct_source(reference.nominal_problem_data, 1.0, -1,
                                                reference.config)
        self.assertEqual(events, ["clock", "scale", "runner", "acceptance", "clock"])
        self.assertEqual(attempt.elapsed_seconds, 2.5)
        self.assertTrue(attempt.accepted)
        self.assertIs(attempt.source_result, reference.static_source.source_result)
        self.assertEqual(attempt.construction_problem_data.instance,
                         reference.static_source.construction_problem_data.instance)

    def test_rejected_stage1_outcomes_keep_elapsed_time_and_original_failure(self) -> None:
        reference = self.results[Stage1Method.GH, replay.AzureReplayVariant.STATIC]
        # An execution exception and acceptance rejection both remain timed attempts.
        for boundary in ("runner", "acceptance"):
            with self.subTest(boundary=boundary):
                runner_args = ({"side_effect": RuntimeError("runner rejected")} if boundary == "runner"
                               else {"return_value": reference.static_source.source_result})
                adapter_args = ({"side_effect": RuntimeError("acceptance rejected")}
                                if boundary == "acceptance" else
                                {"wraps": replay.stage2_fixed_deployment_from_stage1})
                with (patch.object(replay, "perf_counter", side_effect=(20.0, 21.25)),
                      patch.object(replay, "run_gh", **runner_args),
                      patch.object(replay, "stage2_fixed_deployment_from_stage1", **adapter_args)):
                    attempt = replay._construct_source(reference.nominal_problem_data, 1.0, -1,
                                                        reference.config)
                self.assertFalse(attempt.accepted)
                self.assertEqual(attempt.elapsed_seconds, 1.25)
                self.assertEqual(attempt.failure.message, f"{boundary} rejected")
                if boundary == "acceptance":
                    self.assertIs(attempt.source_result, reference.static_source.source_result)
                else:
                    self.assertIsNone(attempt.source_result)

    def test_successful_stage2_fake_clock_preserves_integrated_scientific_evidence(self) -> None:
        reference = self.results[Stage1Method.GH, replay.AzureReplayVariant.STATIC]
        original = reference.windows[0].operation
        with (patch.object(replay, "perf_counter", side_effect=(100.0, 100.75)),
              patch.object(replay, "_evaluate_prepared_stage2_source",
                           return_value=original.evaluation_result) as integration):
            timed = replay._evaluate_source(original.source, original.scenario, reference.config)
        self.assertEqual(timed.elapsed_seconds, 0.75)
        self.assertTrue(timed.successful)
        self.assertIs(timed.evaluation_result, original.evaluation_result)
        self.assertIs(timed.source, original.source)
        self.assertIs(timed.scenario, original.scenario)
        self.assertEqual(timed.full_model_cost, original.full_model_cost)
        integration.assert_called_once()
        prepared, scenario = integration.call_args.args
        self.assertIs(prepared.source_result, original.source.source_result)
        self.assertIs(prepared.pdm_problem_data, original.source.construction_problem_data)
        self.assertIs(prepared.adapter_evidence, original.source._adapter_evidence)
        self.assertIs(scenario, original.scenario)
        self.assertEqual(integration.call_args.kwargs,
                         {"solver_config": reference.config.solver_config})

    def test_raised_stage2_failure_keeps_elapsed_time(self) -> None:
        reference = self.results[Stage1Method.GH, replay.AzureReplayVariant.STATIC]
        original = reference.windows[0].operation
        with (patch.object(replay, "perf_counter", side_effect=(30.0, 32.125)),
              patch.object(replay, "_evaluate_prepared_stage2_source",
                           side_effect=RuntimeError("integration failed"))):
            timed = replay._evaluate_source(original.source, original.scenario, reference.config)
        self.assertEqual(timed.elapsed_seconds, 2.125)
        self.assertFalse(timed.successful)
        self.assertIsNone(timed.evaluation_result)
        self.assertEqual(timed.failure.message, "integration failed")
        self.assertIs(timed.source, original.source)
        self.assertIs(timed.scenario, original.scenario)

    def test_returned_stage2_failure_keeps_elapsed_time_and_full_solver_evidence(self) -> None:
        failed_run = replay.run_azure_replay(
            (replay.AzureReplayWindow(0, 1e7),),
            replay.AzureReplayConfig(Stage1Method.GH, replay.AzureReplayVariant.STATIC,
                                     solver_config=self.solver_config),
        )
        original = failed_run.windows[0].operation
        with (patch.object(replay, "perf_counter", side_effect=(200.0, 204.0)),
              patch.object(replay, "_evaluate_prepared_stage2_source",
                           return_value=original.evaluation_result)):
            timed = replay._evaluate_source(original.source, original.scenario, failed_run.config)
        self.assertFalse(timed.successful)
        self.assertEqual(timed.elapsed_seconds, 4.0)
        self.assertIs(timed.evaluation_result, original.evaluation_result)
        self.assertEqual(timed.failure, original.failure)
        self.assertIn("infeasible", timed.failure.message)

    def test_timing_fields_are_serializable_evidence_and_validate_domains(self) -> None:
        reference = self.results[Stage1Method.GH, replay.AzureReplayVariant.STATIC]
        records = (reference.static_source, reference.windows[0].operation)
        for record in records:
            with self.subTest(record=type(record).__name__):
                timed = replace(record, elapsed_seconds=0.125)
                serialized_fields = {field.name: getattr(timed, field.name) for field in fields(timed)}
                self.assertEqual(serialized_fields["elapsed_seconds"], 0.125)
                for invalid in (-0.1, True, float("nan"), float("inf"), "0.2"):
                    with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                        replace(record, elapsed_seconds=invalid)

    def test_static_source_retains_one_adapter_across_operational_windows(self) -> None:
        with patch.object(
            replay, "stage2_fixed_deployment_from_stage1",
            wraps=replay.stage2_fixed_deployment_from_stage1,
        ) as adapter:
            result = replay.run_azure_replay(
                self.windows[:2],
                replay.AzureReplayConfig(Stage1Method.GH, replay.AzureReplayVariant.STATIC,
                                         solver_config=self.solver_config),
            )
        self.assertTrue(result.successful)
        self.assertEqual(adapter.call_count, 1)
        evidence = result.static_source._adapter_evidence
        for window in result.windows:
            self.assertIs(window.operation.evaluation_result.adapter_evidence, evidence)
            self.assertIs(window.operation.evaluation_result.pdm_problem_data,
                          result.static_source.construction_problem_data)

    def test_repeated_cost_reads_reuse_source_fixed_cost(self) -> None:
        original = self.results[Stage1Method.GH, replay.AzureReplayVariant.STATIC].windows[0].operation
        expected = original.full_model_cost
        with (
            patch.object(replay, "compute_gpu_rental_cost",
                         side_effect=AssertionError("C1 is already computed for the source")),
            patch.object(replay, "compute_model_storage_cost",
                         side_effect=AssertionError("C2 is already computed for the source")),
        ):
            self.assertEqual(original.full_model_cost, expected)
            self.assertEqual(original.full_model_cost, expected)

    def test_internal_reuse_context_is_excluded_from_artifact_schema(self) -> None:
        result = self.results[Stage1Method.GH, replay.AzureReplayVariant.STATIC]
        source = _plain(result.static_source)
        self.assertTrue(source["accepted"])
        self.assertNotIn("_adapter_evidence", source)
        self.assertNotIn("_fixed_model_cost", source)
        report = _plain(result.windows[0].operation.evaluation_result.stage2_run_record.scientific_evidence.validation_report)
        self.assertNotIn("_violations", report)


if __name__ == "__main__":
    unittest.main()
