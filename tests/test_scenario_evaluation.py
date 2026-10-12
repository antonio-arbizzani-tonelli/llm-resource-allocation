"""Focused Milestone-9.3 deterministic multi-scenario evaluation tests."""

import unittest
from dataclasses import FrozenInstanceError, replace
from unittest.mock import patch

import llm_resource_allocation.algorithms.agh as agh_module
import llm_resource_allocation.algorithms.gh as gh_module
import llm_resource_allocation.experiments.scenario_evaluation as evaluation_module
import llm_resource_allocation.experiments.scenario_generation as generation_module
import llm_resource_allocation.optimization.pdm_run as pdm_run_module
import llm_resource_allocation.optimization.stage2_adapter as adapter_module
import llm_resource_allocation.optimization.stage2_integration as integration_module
import llm_resource_allocation.optimization.stage2_problem_data as stage2_data_module
import llm_resource_allocation.optimization.stage2_run as stage2_run_module
from llm_resource_allocation.algorithms import GHPhase1Config, run_agh, run_gh
from llm_resource_allocation.data import (
    make_minimal_tiny_instance,
    make_stage2_capacity_limited_case,
    make_stage2_fully_served_case,
)
from llm_resource_allocation.experiments import (
    MultiScenarioEvaluationResult,
    MultiScenarioEvaluationStatus,
    UNMET_FRACTION_VIOLATION_THRESHOLD,
    evaluate_stage1_result_over_scenarios,
    is_unmet_fraction_violation,
)
from llm_resource_allocation.math.objective import PaperVersion
from llm_resource_allocation.optimization.solver import SolverBackend, SolverConfig
from llm_resource_allocation.optimization.stage2_integration import Stage1Stage2EvaluationStatus
from llm_resource_allocation.optimization.problem_data import PdmProblemData
from llm_resource_allocation.optimization.pdm_run import execute_and_record_pdm_run


class DeterministicMultiScenarioEvaluationTests(unittest.TestCase):
    """Protect delegation, evidence, failure, and aggregation semantics."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.instance = make_minimal_tiny_instance()
        cls.pdm_data = PdmProblemData(cls.instance)
        cls.source = execute_and_record_pdm_run(
            cls.pdm_data,
            SolverConfig(backend=SolverBackend.HIGHS),
            PaperVersion.V2,
        )
        cls.full = make_stage2_fully_served_case().realized_scenario
        cls.limited = make_stage2_capacity_limited_case().realized_scenario
        cls.scenarios = (cls.full, cls.limited)
        cls.result = evaluate_stage1_result_over_scenarios(
            cls.source,
            cls.pdm_data,
            cls.scenarios,
            paper_version=PaperVersion.V2,
            solver_config=SolverConfig(backend=SolverBackend.HIGHS),
        )

    def test_two_scenario_hand_derived_cost_aggregation(self) -> None:
        result = self.result
        aggregate = result.aggregate

        self.assertIsInstance(result, MultiScenarioEvaluationResult)
        self.assertTrue(result.successful)
        self.assertIs(result.status, MultiScenarioEvaluationStatus.SUCCESS)
        self.assertAlmostEqual(aggregate.deterministic_c1, 1.0)
        self.assertAlmostEqual(aggregate.deterministic_c2, 0.001)
        self.assertAlmostEqual(aggregate.deterministic_stage1_cost, 1.001)
        self.assertAlmostEqual(aggregate.mean_c3, 0.016200015)
        self.assertAlmostEqual(aggregate.mean_c4, 0.00279)
        self.assertAlmostEqual(aggregate.mean_c5, 0.5)
        self.assertAlmostEqual(aggregate.mean_operational_cost, 0.50279)
        self.assertAlmostEqual(aggregate.mean_reporting_cost, 0.518990015)
        self.assertAlmostEqual(aggregate.expected_total_cost, 1.519990015)
        self.assertEqual(aggregate.mean_realized_c3, aggregate.mean_c3)
        self.assertEqual(aggregate.mean_realized_c4, aggregate.mean_c4)
        self.assertEqual(aggregate.mean_realized_c5, aggregate.mean_c5)
        self.assertEqual(
            aggregate.mean_realized_operational_cost,
            aggregate.mean_operational_cost,
        )
        self.assertEqual(
            aggregate.mean_realized_reporting_cost,
            aggregate.mean_reporting_cost,
        )

    def test_per_scenario_evidence_forwards_existing_authorities(self) -> None:
        expected = (
            (3e-8, 0.0031, 0.0, 0.0031, 0.00310003, -0.0),
            (0.0324, 0.00248, 1.0, 1.00248, 1.03488, 0.2),
        )
        for index, (item, values) in enumerate(
            zip(self.result.per_scenario, expected, strict=True)
        ):
            c3, c4, c5, operational, reporting, unmet = values
            self.assertEqual(item.scenario_index, index)
            self.assertIs(item.realized_scenario, self.scenarios[index])
            self.assertIs(
                item.evaluation_result.realized_scenario,
                self.scenarios[index],
            )
            self.assertTrue(item.successful)
            self.assertTrue(item.independently_feasible)
            self.assertIs(
                item.independent_validation_report,
                item.evaluation_result.stage2_run_record.scientific_evidence.validation_report,
            )
            self.assertAlmostEqual(item.c3, c3)
            self.assertAlmostEqual(item.c4, c4)
            self.assertAlmostEqual(item.c5, c5)
            self.assertAlmostEqual(item.operational_cost, operational)
            self.assertAlmostEqual(item.reporting_contribution, reporting)
            self.assertAlmostEqual(item.unmet_fractions["q_text"], unmet)

    def test_strict_violation_threshold_and_pair_denominator(self) -> None:
        threshold = UNMET_FRACTION_VIOLATION_THRESHOLD

        self.assertFalse(is_unmet_fraction_violation(threshold - 1e-12))
        self.assertFalse(is_unmet_fraction_violation(threshold))
        self.assertTrue(is_unmet_fraction_violation(threshold + 1e-12))
        self.assertEqual(self.result.aggregate.violation_threshold, 0.01)
        self.assertEqual(self.result.aggregate.violation_count, 1)
        self.assertEqual(self.result.aggregate.scenario_query_pair_count, 2)
        self.assertEqual(self.result.aggregate.violation_rate, 0.5)

    def test_input_order_and_exact_scenario_references_are_preserved(self) -> None:
        reordered = (self.limited, self.full)
        result = evaluate_stage1_result_over_scenarios(
            self.source,
            self.pdm_data,
            reordered,
            solver_config=SolverConfig(backend=SolverBackend.HIGHS),
        )

        self.assertEqual(
            tuple(item.realized_scenario.id for item in result.per_scenario),
            ("capacity_limited", "fully_served"),
        )
        self.assertTrue(
            all(
                item.realized_scenario is scenario
                for item, scenario in zip(result.per_scenario, reordered, strict=True)
            )
        )

    def test_prepared_source_is_reused_for_each_supplied_scenario(self) -> None:
        original = evaluation_module._evaluate_prepared_stage2_source
        with patch.object(
            evaluation_module,
            "_evaluate_prepared_stage2_source",
            wraps=original,
        ) as delegate:
            result = evaluate_stage1_result_over_scenarios(
                self.source,
                self.pdm_data,
                self.scenarios,
                paper_version=PaperVersion.V2,
                solver_config=SolverConfig(backend=SolverBackend.HIGHS),
            )

        self.assertTrue(result.successful)
        self.assertEqual(delegate.call_count, 2)
        prepared = delegate.call_args_list[0].args[0]
        self.assertIs(prepared.source_result, self.source)
        self.assertIs(prepared.pdm_problem_data, self.pdm_data)
        self.assertIs(delegate.call_args_list[1].args[0], prepared)
        self.assertEqual(
            tuple(item.args[1] for item in delegate.call_args_list), self.scenarios
        )
        self.assertIs(
            result.per_scenario[0].evaluation_result.adapter_evidence,
            result.per_scenario[1].evaluation_result.adapter_evidence,
        )

    def test_one_failure_makes_batch_all_or_nothing_but_keeps_all_evidence(self) -> None:
        invalid = replace(
            self.full,
            id="invalid_missing_arrival",
            arrival_rates_per_hour={},
        )
        scenarios = (self.full, invalid, self.limited)
        original = evaluation_module._evaluate_prepared_stage2_source
        with patch.object(
            evaluation_module,
            "_evaluate_prepared_stage2_source",
            wraps=original,
        ) as delegate:
            result = evaluate_stage1_result_over_scenarios(
                self.source,
                self.pdm_data,
                scenarios,
                solver_config=SolverConfig(backend=SolverBackend.HIGHS),
            )

        self.assertFalse(result.successful)
        self.assertIs(
            result.status,
            MultiScenarioEvaluationStatus.SCENARIO_EVALUATION_FAILED,
        )
        self.assertIsNone(result.aggregate)
        self.assertEqual(delegate.call_count, 3)
        self.assertEqual(len(result.per_scenario), 3)
        self.assertEqual(len(result.failures), 1)
        self.assertEqual(result.failures[0].scenario_index, 1)
        self.assertIs(result.failures[0].realized_scenario, invalid)
        self.assertIs(
            result.failures[0].evaluation_result,
            result.per_scenario[1].evaluation_result,
        )
        self.assertIs(
            result.per_scenario[1].integrated_status,
            Stage1Stage2EvaluationStatus.PROBLEM_DATA_CONSTRUCTION_FAILED,
        )
        self.assertTrue(result.per_scenario[0].successful)
        self.assertFalse(result.per_scenario[1].successful)
        self.assertTrue(result.per_scenario[2].successful)

    def test_same_fixed_stage1_deployment_is_used_for_every_scenario(self) -> None:
        baseline = self.result.per_scenario[0].fixed_deployment
        self.assertTrue(
            all(item.fixed_deployment == baseline for item in self.result.per_scenario)
        )
        self.assertIs(self.result.source_result, self.source)
        self.assertTrue(
            all(
                item.evaluation_result.source_result is self.source
                for item in self.result.per_scenario
            )
        )

    def test_batch_checks_fixed_deployment_once_and_each_scenario_solution(self) -> None:
        with (
            patch.object(integration_module, "stage2_fixed_deployment_from_stage1",
                         wraps=integration_module.stage2_fixed_deployment_from_stage1) as adapter,
            patch.object(adapter_module, "validate_stage2_fixed_deployment",
                         wraps=adapter_module.validate_stage2_fixed_deployment) as fixed,
            patch.object(stage2_data_module, "validate_stage2_fixed_deployment",
                         side_effect=AssertionError("prepared deployment must not be rechecked")),
            patch.object(stage2_data_module, "validate_stage2_realized_scenario",
                         wraps=stage2_data_module.validate_stage2_realized_scenario) as scenario,
            patch.object(stage2_run_module, "validate_stage2_solution",
                         wraps=stage2_run_module.validate_stage2_solution) as solution,
        ):
            result = evaluate_stage1_result_over_scenarios(
                self.source, self.pdm_data, self.scenarios,
                solver_config=SolverConfig(backend=SolverBackend.HIGHS),
            )
        self.assertTrue(result.successful)
        self.assertEqual(adapter.call_count, 1)
        self.assertEqual(fixed.call_count, 1)
        self.assertEqual(scenario.call_count, 2)
        self.assertEqual(solution.call_count, 2)

    def test_batch_does_not_generate_scenarios_use_rng_or_rerun_stage1(self) -> None:
        with patch.object(
            generation_module,
            "generate_realized_scenario",
            side_effect=AssertionError("generator must not run"),
        ) as generator, patch.object(
            pdm_run_module,
            "execute_and_record_pdm_run",
            side_effect=AssertionError("P_DM must not rerun"),
        ) as pdm, patch.object(
            gh_module,
            "run_gh",
            side_effect=AssertionError("GH must not rerun"),
        ) as gh, patch.object(
            agh_module,
            "run_agh",
            side_effect=AssertionError("AGH must not rerun"),
        ) as agh:
            result = evaluate_stage1_result_over_scenarios(
                self.source,
                self.pdm_data,
                self.scenarios,
                solver_config=SolverConfig(backend=SolverBackend.HIGHS),
            )

        self.assertTrue(result.successful)
        generator.assert_not_called()
        pdm.assert_not_called()
        gh.assert_not_called()
        agh.assert_not_called()

    def test_inputs_outputs_and_nested_evidence_are_immutable(self) -> None:
        with self.assertRaises(FrozenInstanceError):
            self.result.status = MultiScenarioEvaluationStatus.SCENARIO_EVALUATION_FAILED
        with self.assertRaises(FrozenInstanceError):
            self.result.aggregate.mean_c3 = 0.0
        with self.assertRaises(FrozenInstanceError):
            self.result.per_scenario[0].scenario_index = 9
        with self.assertRaises(TypeError):
            self.result.per_scenario[0].unmet_fractions["q_text"] = 1.0

    def test_empty_and_non_sequence_inputs_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            evaluate_stage1_result_over_scenarios(
                self.source,
                self.pdm_data,
                (),
                solver_config=SolverConfig(backend=SolverBackend.HIGHS),
            )
        with self.assertRaises(TypeError):
            evaluate_stage1_result_over_scenarios(
                self.source,
                self.pdm_data,
                iter(self.scenarios),
                solver_config=SolverConfig(backend=SolverBackend.HIGHS),
            )


class CrossMethodMultiScenarioEvaluationTests(unittest.TestCase):
    """Prove P_DM, GH, and AGH use the same batch protocol."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.instance = make_minimal_tiny_instance()
        cls.pdm_data = PdmProblemData(cls.instance)
        config = GHPhase1Config(0.8)
        cls.sources = (
            execute_and_record_pdm_run(cls.pdm_data, SolverConfig(backend=SolverBackend.HIGHS)),
            run_gh(cls.instance, config),
            run_agh(cls.instance, config, random_seed=37),
        )
        cls.scenarios = (
            make_stage2_fully_served_case().realized_scenario,
            make_stage2_capacity_limited_case().realized_scenario,
        )
        cls.results = tuple(
            evaluate_stage1_result_over_scenarios(
                source,
                cls.pdm_data,
                cls.scenarios,
                solver_config=SolverConfig(backend=SolverBackend.HIGHS),
            )
            for source in cls.sources
        )

    def test_equivalent_deployments_produce_equivalent_aggregates(self) -> None:
        baseline = self.results[0]
        self.assertTrue(all(result.successful for result in self.results))
        for result in self.results[1:]:
            self.assertEqual(result.aggregate, baseline.aggregate)
            self.assertEqual(
                tuple(item.fixed_deployment for item in result.per_scenario),
                tuple(item.fixed_deployment for item in baseline.per_scenario),
            )
            self.assertEqual(
                tuple(item.unmet_fractions for item in result.per_scenario),
                tuple(item.unmet_fractions for item in baseline.per_scenario),
            )


if __name__ == "__main__":
    unittest.main()
