"""Focused Milestone-8.2 one-scenario Stage-1/Stage-2 integration tests."""

import unittest
from dataclasses import FrozenInstanceError, fields, replace
from unittest.mock import patch

import llm_resource_allocation.algorithms.agh as agh_module
import llm_resource_allocation.algorithms.gh as gh_module
import llm_resource_allocation.optimization.pdm_run as pdm_run_module
import llm_resource_allocation.optimization.stage2_integration as integration_module
import llm_resource_allocation.optimization.stage2_run as stage2_run_module
from llm_resource_allocation.algorithms import GHPhase1Config, run_agh, run_gh
from llm_resource_allocation.data import (
    make_minimal_tiny_instance,
    make_stage2_capacity_limited_case,
)
from llm_resource_allocation.optimization.solver import (
    SolverBackend,
    SolverConfig,
    SolverResult,
    SolverStatus,
)
from llm_resource_allocation.optimization.stage2_adapter import (
    Stage1Method,
    Stage1ToStage2AdapterError,
    Stage1ToStage2FailureReason,
)
from llm_resource_allocation.optimization.stage2_integration import (
    Stage1Stage2EvaluationFailure,
    Stage1Stage2EvaluationResult,
    Stage1Stage2EvaluationStatus,
    evaluate_stage1_result_under_scenario,
)
from llm_resource_allocation.optimization.stage2_problem_data import (
    Stage2FixedDeployment,
    Stage2RealizedScenario,
)
from llm_resource_allocation.optimization.stage2_run import (
    Stage2RunFailure,
    Stage2RunStatus,
)
from llm_resource_allocation.optimization.problem_data import PdmProblemData
from llm_resource_allocation.optimization.pdm_run import execute_and_record_pdm_run


class Stage1Stage2IntegrationTests(unittest.TestCase):
    """Protect exact delegation, identities, outcomes, and scope boundaries."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.instance = make_minimal_tiny_instance()
        cls.pdm_data = PdmProblemData(cls.instance)
        cls.gh_config = GHPhase1Config(0.8)
        cls.scenario = make_stage2_capacity_limited_case().realized_scenario
        cls.pdm_result = execute_and_record_pdm_run(
            cls.pdm_data,
            SolverConfig(backend=SolverBackend.HIGHS),
        )
        cls.gh_result = run_gh(cls.instance, cls.gh_config)
        cls.agh_result = run_agh(
            cls.instance,
            cls.gh_config,
            random_seed=37,
        )
        cls.sources = (
            cls.pdm_result,
            cls.gh_result,
            cls.agh_result,
        )
        cls.results = tuple(
            evaluate_stage1_result_under_scenario(
                source,
                cls.pdm_data,
                cls.scenario,
                solver_config=SolverConfig(backend=SolverBackend.HIGHS),
            )
            for source in cls.sources
        )

    def _evaluate(self, source):
        return evaluate_stage1_result_under_scenario(
            source,
            self.pdm_data,
            self.scenario,
            solver_config=SolverConfig(backend=SolverBackend.HIGHS),
        )

    def test_valid_pdm_result_runs_one_explicit_scenario_successfully(self) -> None:
        result = self.results[0]

        self.assertIsInstance(result, Stage1Stage2EvaluationResult)
        self.assertTrue(result.successful)
        self.assertIs(result.status, Stage1Stage2EvaluationStatus.SUCCESS)
        self.assertIs(result.stage1_method, Stage1Method.P_DM)
        self.assertTrue(result.stage2_run_record.successful)

    def test_valid_gh_result_runs_one_explicit_scenario_successfully(self) -> None:
        result = self.results[1]

        self.assertTrue(result.successful)
        self.assertIs(result.stage1_method, Stage1Method.GH)
        self.assertTrue(result.stage2_run_record.successful)

    def test_valid_agh_result_runs_one_explicit_scenario_successfully(self) -> None:
        result = self.results[2]

        self.assertTrue(result.successful)
        self.assertIs(result.stage1_method, Stage1Method.AGH)
        self.assertTrue(result.stage2_run_record.successful)

    def test_all_methods_use_equivalent_canonical_fixed_deployments(self) -> None:
        fixed = tuple(result.fixed_deployment for result in self.results)

        self.assertTrue(
            all(isinstance(item, Stage2FixedDeployment) for item in fixed)
        )
        self.assertEqual(fixed[0], fixed[1])
        self.assertEqual(fixed[1], fixed[2])

    def test_pipeline_authorities_are_invoked_once_in_exact_order(self) -> None:
        order: list[str] = []
        original_adapter = integration_module.stage2_fixed_deployment_from_stage1
        original_builder = integration_module.Stage2ProblemData._from_validated_deployment

        def retained_run_record(*args, **kwargs):
            # Trace integration construction separately from runner revalidation.
            return self.results[1].stage2_run_record

        def wrap(label, function):
            def call(*args, **kwargs):
                order.append(label)
                return function(*args, **kwargs)

            return call

        with patch.object(
            integration_module,
            "stage2_fixed_deployment_from_stage1",
            side_effect=wrap("adapter", original_adapter),
        ) as adapter, patch.object(
            integration_module.Stage2ProblemData,
            "_from_validated_deployment",
            side_effect=wrap("problem_data", original_builder),
        ) as builder, patch.object(
            integration_module,
            "run_stage2",
            side_effect=wrap("run_stage2", retained_run_record),
        ) as runner:
            result = self._evaluate(self.gh_result)

        self.assertTrue(result.successful)
        self.assertEqual(order, ["adapter", "problem_data", "run_stage2"])
        adapter.assert_called_once_with(self.gh_result, self.pdm_data)
        builder.assert_called_once_with(
            self.pdm_data,
            result.adapter_evidence.fixed_deployment,
            result.adapter_evidence._derived_deployment_indicators,
            self.scenario,
            result.paper_version,
        )
        runner.assert_called_once_with(
            result.stage2_problem_data,
            solver_config=SolverConfig(backend=SolverBackend.HIGHS),
            normalization_tolerances=None,
            validation_tolerances=None,
        )

    def test_exact_fixed_values_reach_stage2_problem_data_and_run_record(self) -> None:
        for result in self.results:
            placement = result.source_final_placement
            fixed = result.fixed_deployment
            data = result.stage2_problem_data
            run_fixed = result.stage2_run_record.fixed_deployment
            self.assertIs(data.fixed_deployment, fixed)
            self.assertEqual(fixed.admission_indicators, placement.admission_indicators)
            self.assertEqual(
                fixed.configuration_selectors,
                placement.configuration_selectors,
            )
            self.assertEqual(fixed.gpu_counts, placement.gpu_counts)
            self.assertEqual(
                run_fixed.admission_indicators,
                fixed.admission_indicators,
            )
            self.assertEqual(
                run_fixed.configuration_selectors,
                fixed.configuration_selectors,
            )
            self.assertEqual(run_fixed.gpu_counts, fixed.gpu_counts)

    def test_realized_scenario_changes_x_u_without_changing_deployment(self) -> None:
        route = self.pdm_data.variable_lattices.route_keys[0]
        query_id = self.pdm_data.variable_lattices.unmet_keys[0]

        for result in self.results:
            stage1 = result.source_final_placement
            stage2 = result.stage2_run_record.solution
            self.assertEqual(stage1.routing_fractions[route], 1.0)
            self.assertEqual(stage1.unmet_fractions[query_id], 0.0)
            self.assertEqual(stage2.routing_fractions[route], 0.8)
            self.assertEqual(stage2.unmet_fractions[query_id], 0.2)
            self.assertEqual(
                result.fixed_deployment.admission_indicators,
                stage1.admission_indicators,
            )
            self.assertFalse(hasattr(result.fixed_deployment, "routing_fractions"))
            self.assertFalse(hasattr(result.fixed_deployment, "unmet_fractions"))

    def test_explicit_scenario_and_source_objects_are_preserved_by_identity(self) -> None:
        for source, result in zip(self.sources, self.results, strict=True):
            self.assertIs(result.source_result, source)
            self.assertIs(result.adapter_evidence.source_result, source)
            self.assertIs(
                result.source_final_placement,
                result.adapter_evidence.source_final_placement,
            )
            self.assertIs(result.realized_scenario, self.scenario)
            self.assertIs(
                result.stage2_problem_data.realized_scenario,
                self.scenario,
            )
            self.assertEqual(
                result.stage2_run_record.identity.scenario_id,
                self.scenario.id,
            )

    def test_integrated_evidence_is_immutable(self) -> None:
        result = self.results[2]

        with self.assertRaises(FrozenInstanceError):
            result.status = Stage1Stage2EvaluationStatus.STAGE2_RUN_FAILED
        with self.assertRaises(TypeError):
            result.realized_scenario.arrival_rates_per_hour["q_text"] = 1.0
        with self.assertRaises(TypeError):
            result.fixed_deployment.gpu_counts[
                next(iter(result.fixed_deployment.gpu_counts))
            ] = 0.0

    def test_repeated_evaluation_is_scientifically_deterministic(self) -> None:
        first = self.results[1]
        repeated = self._evaluate(self.gh_result)

        self.assertIs(repeated.status, first.status)
        self.assertEqual(repeated.adapter_evidence, first.adapter_evidence)
        self.assertEqual(repeated.stage2_problem_data, first.stage2_problem_data)
        self.assertEqual(
            repeated.stage2_run_record.solution,
            first.stage2_run_record.solution,
        )
        self.assertEqual(
            repeated.stage2_run_record.scientific_evidence,
            first.stage2_run_record.scientific_evidence,
        )
        self.assertEqual(
            repeated.stage2_run_record.solver_evidence.result.objective_value,
            first.stage2_run_record.solver_evidence.result.objective_value,
        )

    def test_invalid_stage1_source_returns_typed_rejection(self) -> None:
        solver_objective = (
            self.pdm_result.scientific_evidence.objective_comparison.independent_objective
            + 1.0
        )
        comparison = replace(
            self.pdm_result.scientific_evidence.objective_comparison,
            solver_objective=solver_objective,
            absolute_tolerance=0.0,
        )
        unaccepted = replace(
            self.pdm_result,
            scientific_evidence=replace(
                self.pdm_result.scientific_evidence,
                objective_comparison=comparison,
            ),
            solver_evidence=replace(
                self.pdm_result.solver_evidence,
                result=replace(
                    self.pdm_result.solver_evidence.result,
                    objective_value=solver_objective,
                ),
            ),
        )

        result = self._evaluate(unaccepted)

        self.assertIs(
            result.status,
            Stage1Stage2EvaluationStatus.STAGE1_SOURCE_REJECTED,
        )
        self.assertFalse(result.successful)
        self.assertIs(result.source_result, unaccepted)
        self.assertIsInstance(result.failure, Stage1Stage2EvaluationFailure)
        self.assertIs(
            result.failure.adapter_reason,
            Stage1ToStage2FailureReason.STAGE1_RESULT_NOT_ACCEPTED,
        )
        self.assertIsNone(result.adapter_evidence)
        self.assertIsNone(result.stage2_problem_data)
        self.assertIsNone(result.stage2_run_record)

    def test_adapter_failure_is_typed_and_stops_before_problem_construction(self) -> None:
        error = Stage1ToStage2AdapterError(
            Stage1ToStage2FailureReason.SOURCE_IDENTITY_MISMATCH,
            "injected adapter failure",
        )
        with patch.object(
            integration_module,
            "stage2_fixed_deployment_from_stage1",
            side_effect=error,
        ) as adapter, patch.object(
            integration_module.Stage2ProblemData, "_from_validated_deployment"
        ) as builder, patch.object(integration_module, "run_stage2") as runner:
            result = self._evaluate(self.gh_result)

        adapter.assert_called_once_with(self.gh_result, self.pdm_data)
        builder.assert_not_called()
        runner.assert_not_called()
        self.assertIs(result.status, Stage1Stage2EvaluationStatus.ADAPTER_FAILED)
        self.assertIs(result.failure.adapter_reason, error.reason)

    def test_problem_data_failure_preserves_completed_adapter_evidence(self) -> None:
        invalid_scenario = Stage2RealizedScenario(
            id="missing_values",
            arrival_rates_per_hour={},
            compute_delay_seconds_per_token={},
            communication_delay_seconds_per_token={},
            effective_errors={},
        )

        result = evaluate_stage1_result_under_scenario(
            self.gh_result,
            self.pdm_data,
            invalid_scenario,
            solver_config=SolverConfig(backend=SolverBackend.HIGHS),
        )

        self.assertIs(
            result.status,
            Stage1Stage2EvaluationStatus.PROBLEM_DATA_CONSTRUCTION_FAILED,
        )
        self.assertIsNotNone(result.adapter_evidence)
        self.assertIsNone(result.stage2_problem_data)
        self.assertIsNone(result.stage2_run_record)
        self.assertIsInstance(result.failure, Stage1Stage2EvaluationFailure)
        self.assertIsNone(result.failure.adapter_reason)

    def test_stage2_failure_is_retained_exactly_without_repair(self) -> None:
        solver_result = SolverResult(
            backend=SolverConfig(backend=SolverBackend.HIGHS).backend,
            status=SolverStatus.INFEASIBLE,
            termination_condition="infeasible",
            has_incumbent=False,
            objective_value=None,
            best_bound=None,
            relative_gap=None,
            solve_time_seconds=0.0,
            raw_status_metadata={"test": "integration_no_incumbent"},
        )
        with patch.object(
            stage2_run_module,
            "solve_pyomo_model",
            return_value=solver_result,
        ):
            result = self._evaluate(self.agh_result)

        self.assertIs(
            result.status,
            Stage1Stage2EvaluationStatus.STAGE2_RUN_FAILED,
        )
        self.assertIs(
            result.stage2_run_record.status,
            Stage2RunStatus.SOLVER_NO_USABLE_SOLUTION,
        )
        self.assertIsInstance(result.failure, Stage2RunFailure)
        self.assertIs(result.failure, result.stage2_run_record.failure)
        self.assertIs(result.stage2_run_record.solver_evidence.result, solver_result)
        self.assertIsNotNone(result.adapter_evidence)
        self.assertIsNotNone(result.stage2_problem_data)
        self.assertIsNone(result.stage2_run_record.solution)

    def test_integration_never_reruns_a_stage1_algorithm(self) -> None:
        forbidden = AssertionError("integration attempted Stage-1 execution")
        with patch.object(
            pdm_run_module,
            "execute_and_record_pdm_run",
            side_effect=forbidden,
        ), patch.object(gh_module, "run_gh", side_effect=forbidden), patch.object(
            agh_module, "run_agh", side_effect=forbidden
        ):
            for source in self.sources:
                self.assertTrue(self._evaluate(source).successful)

    def test_result_is_singular_and_integration_generates_no_scenario(self) -> None:
        field_names = {
            field.name for field in fields(Stage1Stage2EvaluationResult)
        }

        self.assertIn("realized_scenario", field_names)
        self.assertNotIn("scenarios", field_names)
        self.assertNotIn("expected_cost", field_names)
        self.assertNotIn("violation_rate", field_names)
        self.assertFalse(
            any(name.startswith("make_") for name in vars(integration_module))
        )


if __name__ == "__main__":
    unittest.main()
