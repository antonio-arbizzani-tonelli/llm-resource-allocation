"""Complete single-scenario Stage-2 runner and typed failure evidence."""

import inspect
import unittest
from collections.abc import Mapping
from dataclasses import FrozenInstanceError, fields, is_dataclass, replace
from unittest.mock import patch

from pyomo.core.base.component import Component

import llm_resource_allocation.optimization.stage2_run as run_module
from llm_resource_allocation.data import (
    make_stage2_capacity_limited_case,
    make_stage2_fully_served_case,
)
from llm_resource_allocation.optimization.solver import (
    SolverBackend,
    SolverConfig,
    SolverResult,
    SolverStatus,
)
from llm_resource_allocation.optimization.stage2_run import (
    Stage2RunRecord,
    Stage2RunStatus,
    run_stage2,
)
from llm_resource_allocation.optimization.stage2_extraction import (
    Stage2SolutionNormalizationError,
    Stage2VariableFamily,
    Stage2VariableValueExtractionError,
)
from llm_resource_allocation.validation.stage2 import (
    Stage2ObjectiveBreakdown,
    Stage2ValidationDiagnostic,
)


class Stage2SuccessfulRunTests(unittest.TestCase):
    """Exercise the real build-to-independent-validation path."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.data = make_stage2_fully_served_case()
        cls.record = run_stage2(cls.data, solver_config=SolverConfig(backend=SolverBackend.HIGHS))

    def test_hand_derived_end_to_end_optimum_is_successful(self) -> None:
        record = self.record
        route = self.data.routing_keys[0]

        self.assertIsInstance(record, Stage2RunRecord)
        self.assertIs(record.status, Stage2RunStatus.SUCCESS)
        self.assertTrue(record.successful)
        self.assertTrue(record.solver_evidence.result.has_incumbent)
        self.assertIs(record.solver_evidence.result.status, SolverStatus.OPTIMAL)
        self.assertTrue(record.independently_feasible)
        self.assertTrue(record.objective_agrees)
        self.assertEqual(record.solution.routing_fractions[route], 1.0)
        self.assertEqual(record.solution.unmet_fractions[route[0]], 0.0)
        self.assertAlmostEqual(record.operational_objective, 0.0031)

    def test_identity_and_fixed_deployment_are_exact_detached_evidence(self) -> None:
        identity = self.record.identity
        fixed = self.record.fixed_deployment

        self.assertEqual(identity.instance_id, self.data.instance.id)
        self.assertEqual(identity.scenario_id, self.data.realized_scenario.id)
        self.assertIs(identity.paper_version, self.data.paper_version)
        self.assertEqual(identity.route_keys, self.data.routing_keys)
        self.assertEqual(identity.unmet_keys, self.data.unmet_keys)
        self.assertEqual(
            dict(fixed.admission_indicators),
            dict(self.data.fixed_deployment.admission_indicators),
        )
        self.assertEqual(
            dict(fixed.configuration_selectors),
            dict(self.data.fixed_deployment.configuration_selectors),
        )
        self.assertEqual(
            dict(fixed.gpu_counts),
            dict(self.data.fixed_deployment.gpu_counts),
        )
        self.assertEqual(
            dict(fixed.derived_deployment_indicators),
            dict(self.data.derived_deployment_indicators),
        )
        self.assertIsNot(
            fixed.admission_indicators,
            self.data.fixed_deployment.admission_indicators,
        )

    def test_d_0067_keeps_realized_c3_separate_from_c4_plus_c5(self) -> None:
        evidence = self.record.scientific_evidence
        breakdown = evidence.objective_breakdown

        self.assertIs(breakdown, evidence.validation_report.objective_breakdown)
        self.assertAlmostEqual(breakdown.delay_penalty, 0.0031)
        self.assertEqual(breakdown.unmet_demand_penalty, 0.0)
        self.assertAlmostEqual(self.record.operational_objective, 0.0031)
        self.assertAlmostEqual(self.record.realized_data_storage_cost, 3e-8)
        self.assertAlmostEqual(self.record.reported_variable_cost, 0.00310003)
        self.assertAlmostEqual(
            self.record.solver_evidence.result.objective_value,
            self.record.operational_objective,
        )

    def test_validator_receives_the_exact_stored_normalized_solution(self) -> None:
        original = run_module.validate_stage2_solution
        validated: list[object] = []

        def capture(problem_data, solution, tolerances):
            validated.append(solution)
            return original(problem_data, solution, tolerances)

        with patch.object(
            run_module, "validate_stage2_solution", side_effect=capture
        ):
            record = run_stage2(self.data, solver_config=SolverConfig(backend=SolverBackend.HIGHS))

        self.assertTrue(record.successful)
        self.assertEqual(len(validated), 1)
        self.assertIs(validated[0], record.solution)
        self.assertIs(
            record.solution.identity.paper_version,
            record.identity.paper_version,
        )

    def test_existing_authorities_are_called_once_in_exact_pipeline_order(self) -> None:
        order: list[str] = []
        names = (
            "build_stage2_pyomo_model",
            "solve_pyomo_model",
            "require_solver_incumbent",
            "extract_raw_stage2_solution_from_pyomo",
            "normalize_raw_stage2_solution",
            "validate_stage2_solution",
        )
        originals = {name: getattr(run_module, name) for name in names}
        original_comparison_init = run_module.ObjectiveComparison.__init__

        def wrapper(name):
            def call(*args, **kwargs):
                order.append(name)
                return originals[name](*args, **kwargs)

            return call

        def construct_comparison(instance, *args, **kwargs):
            order.append("ObjectiveComparison")
            original_comparison_init(instance, *args, **kwargs)

        patches = [
            patch.object(run_module, name, side_effect=wrapper(name))
            for name in names
        ]
        patches.append(
            patch.object(
                run_module.ObjectiveComparison,
                "__init__",
                autospec=True,
                side_effect=construct_comparison,
            )
        )
        for active_patch in patches:
            active_patch.start()
        try:
            record = run_stage2(self.data, solver_config=SolverConfig(backend=SolverBackend.HIGHS))
        finally:
            for active_patch in reversed(patches):
                active_patch.stop()

        self.assertTrue(record.successful)
        self.assertEqual(order, [*names, "ObjectiveComparison"])

    def test_solver_metadata_is_retained_but_not_feasibility_authority(self) -> None:
        original_result = self.record.solver_evidence.result
        unknown_result = replace(
            original_result,
            status=SolverStatus.UNKNOWN,
            termination_condition="unknown_with_incumbent",
        )
        altered = replace(
            self.record,
            solver_evidence=replace(
                self.record.solver_evidence,
                result=unknown_result,
            ),
        )

        self.assertTrue(altered.successful)
        self.assertIs(altered.solver_evidence.result.status, SolverStatus.UNKNOWN)
        self.assertTrue(altered.independently_feasible)
        self.assertTrue(altered.objective_agrees)

    def test_repeated_run_is_deterministic_except_elapsed_metadata(self) -> None:
        repeated = run_stage2(self.data, solver_config=SolverConfig(backend=SolverBackend.HIGHS))

        self.assertIs(repeated.status, self.record.status)
        self.assertEqual(repeated.solution, self.record.solution)
        self.assertEqual(repeated.identity, self.record.identity)
        self.assertEqual(
            repeated.solver_evidence.result.objective_value,
            self.record.solver_evidence.result.objective_value,
        )
        self.assertEqual(
            repeated.scientific_evidence.objective_breakdown,
            self.record.scientific_evidence.objective_breakdown,
        )

    def test_record_is_deeply_immutable_and_contains_no_pyomo_component(self) -> None:
        with self.assertRaises(FrozenInstanceError):
            self.record.status = Stage2RunStatus.VALIDATION_FAILED
        with self.assertRaises(TypeError):
            self.record.solution.unmet_fractions[self.data.unmet_keys[0]] = 1.0
        with self.assertRaises(TypeError):
            self.record.fixed_deployment.gpu_counts[
                next(iter(self.record.fixed_deployment.gpu_counts))
            ] = 0.0

        seen: set[int] = set()

        def assert_plain(value) -> None:
            self.assertNotIsInstance(value, Component)
            value_id = id(value)
            if value_id in seen:
                return
            seen.add(value_id)
            if is_dataclass(value) and not isinstance(value, type):
                for descriptor in fields(value):
                    assert_plain(getattr(value, descriptor.name))
            elif isinstance(value, Mapping):
                for key, item in value.items():
                    assert_plain(key)
                    assert_plain(item)
            elif isinstance(value, (tuple, list, set, frozenset)):
                for item in value:
                    assert_plain(item)

        assert_plain(self.record)


class Stage2FailedRunTests(unittest.TestCase):
    """Require an auditable typed stop at every post-solve boundary."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.data = make_stage2_capacity_limited_case()
        cls.valid = run_stage2(cls.data, solver_config=SolverConfig(backend=SolverBackend.HIGHS))

    @staticmethod
    def _no_incumbent_result() -> SolverResult:
        return SolverResult(
            backend=SolverConfig(backend=SolverBackend.HIGHS).backend,
            status=SolverStatus.INFEASIBLE,
            termination_condition="infeasible",
            has_incumbent=False,
            objective_value=None,
            best_bound=None,
            relative_gap=None,
            solve_time_seconds=0.0,
            raw_status_metadata={"test": "no_incumbent"},
        )

    def test_unusable_solver_result_returns_typed_failure_without_solution(self) -> None:
        result = self._no_incumbent_result()
        with patch.object(run_module, "solve_pyomo_model", return_value=result), patch.object(
            run_module, "extract_raw_stage2_solution_from_pyomo"
        ) as extract:
            record = run_stage2(self.data, SolverConfig(backend=SolverBackend.HIGHS))

        self.assertIs(record.status, Stage2RunStatus.SOLVER_NO_USABLE_SOLUTION)
        self.assertFalse(record.successful)
        self.assertIs(record.solver_evidence.result, result)
        self.assertIsNone(record.raw_solution)
        self.assertIsNone(record.solution)
        self.assertIsNone(record.scientific_evidence.validation_report)
        self.assertIsNone(record.scientific_evidence.objective_breakdown)
        self.assertIsNotNone(record.failure)
        extract.assert_not_called()

    def test_extraction_failure_is_typed_and_stops_before_normalization(self) -> None:
        route = self.data.routing_keys[0]
        error = Stage2VariableValueExtractionError(
            Stage2VariableFamily.X,
            route,
            None,
            "test extraction failure",
        )
        with patch.object(
            run_module,
            "solve_pyomo_model",
            return_value=self.valid.solver_evidence.result,
        ), patch.object(
            run_module, "extract_raw_stage2_solution_from_pyomo", side_effect=error
        ), patch.object(run_module, "normalize_raw_stage2_solution") as normalize:
            record = run_stage2(self.data, solver_config=SolverConfig(backend=SolverBackend.HIGHS))

        self.assertIs(record.status, Stage2RunStatus.EXTRACTION_FAILED)
        self.assertEqual(record.failure.error_type, type(error).__name__)
        self.assertIsNone(record.raw_solution)
        self.assertIsNone(record.solution)
        normalize.assert_not_called()

    def test_normalization_failure_retains_raw_only(self) -> None:
        error = Stage2SolutionNormalizationError(
            Stage2VariableFamily.X,
            self.data.routing_keys[0],
            1.1,
            "test domain",
            1e-9,
        )
        with patch.object(
            run_module,
            "solve_pyomo_model",
            return_value=self.valid.solver_evidence.result,
        ), patch.object(
            run_module,
            "extract_raw_stage2_solution_from_pyomo",
            return_value=self.valid.raw_solution,
        ), patch.object(
            run_module, "normalize_raw_stage2_solution", side_effect=error
        ), patch.object(run_module, "validate_stage2_solution") as validate:
            record = run_stage2(self.data, solver_config=SolverConfig(backend=SolverBackend.HIGHS))

        self.assertIs(record.status, Stage2RunStatus.NORMALIZATION_FAILED)
        self.assertIs(record.raw_solution, self.valid.raw_solution)
        self.assertIsNone(record.solution)
        self.assertEqual(record.failure.error_type, type(error).__name__)
        validate.assert_not_called()

    def test_invalid_independent_report_cannot_produce_success(self) -> None:
        invalid_report = replace(
            self.valid.scientific_evidence.validation_report,
            decision_domain_diagnostic=Stage2ValidationDiagnostic(
                False,
                "InjectedInvalidSolution",
                "test independent rejection",
            ),
        )
        with patch.object(
            run_module,
            "solve_pyomo_model",
            return_value=self.valid.solver_evidence.result,
        ), patch.object(
            run_module,
            "extract_raw_stage2_solution_from_pyomo",
            return_value=self.valid.raw_solution,
        ), patch.object(
            run_module,
            "normalize_raw_stage2_solution",
            return_value=self.valid.solution,
        ), patch.object(
            run_module, "validate_stage2_solution", return_value=invalid_report
        ), patch.object(
            run_module.ObjectiveComparison, "__init__", autospec=True
        ) as compare:
            record = run_stage2(self.data, solver_config=SolverConfig(backend=SolverBackend.HIGHS))

        self.assertIs(record.status, Stage2RunStatus.VALIDATION_FAILED)
        self.assertIs(record.solution, self.valid.solution)
        self.assertFalse(record.independently_feasible)
        self.assertFalse(record.objective_agrees)
        self.assertIs(record.scientific_evidence.validation_report, invalid_report)
        compare.assert_not_called()

    def test_objective_disagreement_cannot_produce_success(self) -> None:
        valid_report = self.valid.scientific_evidence.validation_report
        original = valid_report.objective_breakdown
        inconsistent_report = replace(
            valid_report,
            objective_breakdown=Stage2ObjectiveBreakdown(
                delay_penalty=original.delay_penalty + 1.0,
                unmet_demand_penalty=original.unmet_demand_penalty,
                realized_data_storage_cost=original.realized_data_storage_cost,
            ),
        )
        with patch.object(
            run_module,
            "solve_pyomo_model",
            return_value=self.valid.solver_evidence.result,
        ), patch.object(
            run_module,
            "extract_raw_stage2_solution_from_pyomo",
            return_value=self.valid.raw_solution,
        ), patch.object(
            run_module,
            "normalize_raw_stage2_solution",
            return_value=self.valid.solution,
        ), patch.object(
            run_module,
            "validate_stage2_solution",
            return_value=inconsistent_report,
        ):
            record = run_stage2(self.data, solver_config=SolverConfig(backend=SolverBackend.HIGHS))

        self.assertIs(record.status, Stage2RunStatus.OBJECTIVE_INCONSISTENT)
        self.assertTrue(record.independently_feasible)
        self.assertFalse(record.objective_agrees)
        self.assertIsNotNone(record.scientific_evidence.objective_comparison)
        self.assertEqual(
            record.failure.error_type,
            "Stage2ObjectiveConsistencyError",
        )


class Stage2RunnerScopeTests(unittest.TestCase):
    """Protect the thin public orchestration boundary."""

    def test_invalid_runner_inputs_are_rejected_before_build(self) -> None:
        data = make_stage2_fully_served_case()
        cases = (
            ((None,), {}),
            ((data,), {"solver_config": "highs"}),
            ((data,), {"normalization_tolerances": 0.0}),
            ((data,), {"validation_tolerances": 0.0}),
        )
        for args, kwargs in cases:
            with self.subTest(args=args, kwargs=kwargs), patch.object(
                run_module, "build_stage2_pyomo_model"
            ) as build, self.assertRaises(TypeError):
                run_stage2(*args, **kwargs)
            build.assert_not_called()

    def test_runner_contains_no_stage1_or_scenario_or_aggregation_execution(self) -> None:
        source = inspect.getsource(run_module)
        for forbidden in (
            "execute_and_record_pdm_run(",
            "run_gh(",
            "run_agh(",
            "Stage2RealizedScenario(",
            "random.",
            "expected_cost",
            "violation_rate",
            "scenario_generation",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
