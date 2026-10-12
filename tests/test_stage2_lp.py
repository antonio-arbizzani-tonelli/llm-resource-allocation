"""Exact Stage-2 LP, strict transport, validation, and tiny optima."""

import unittest
from dataclasses import FrozenInstanceError, replace
from math import inf, nan
from unittest.mock import patch

import llm_resource_allocation.validation.stage2 as stage2_validation_module

from pyomo.environ import Var, value

from llm_resource_allocation.data import (
    make_minimal_tiny_instance,
    make_stage2_capacity_limited_case,
    make_stage2_delay_stress_pair,
    make_stage2_fully_served_case,
    make_stage2_two_route_case,
)
from llm_resource_allocation.math.objective import PaperVersion
from llm_resource_allocation.optimization.stage2_extraction import (
    RawStage2Solution,
    Stage2ModelLatticeMismatchError,
    Stage2Solution,
    Stage2SolutionNormalizationError,
    Stage2VariableFamily,
    Stage2VariableValueExtractionError,
    extract_raw_stage2_solution_from_pyomo,
    normalize_raw_stage2_solution,
    stage2_solution_identity,
)
from llm_resource_allocation.optimization.solver import (
    SolverBackend,
    SolverConfig,
    SolverStatus,
    require_solver_incumbent,
    solve_pyomo_model,
)
from llm_resource_allocation.optimization.stage2_problem_data import (
    Stage2FixedDeployment,
    Stage2ProblemData,
    Stage2RealizedScenario,
)
from llm_resource_allocation.optimization.problem_data import PdmProblemData
from llm_resource_allocation.optimization.pyomo_stage2 import build_stage2_pyomo_model
from llm_resource_allocation.validation.stage2 import (
    Stage2ConstraintFamily,
    Stage2ValidationTolerances,
    Stage2Validator,
    validate_stage2_solution,
)
from llm_resource_allocation.validation.objective_comparison import ObjectiveComparison


def _solve_and_validate(problem_data: Stage2ProblemData):
    """Compose lower-level 7.2 APIs only; this is not a public runner."""

    model = build_stage2_pyomo_model(problem_data)
    solver_result = solve_pyomo_model(model, SolverConfig(backend=SolverBackend.HIGHS))
    require_solver_incumbent(solver_result)
    raw = extract_raw_stage2_solution_from_pyomo(model, problem_data)
    solution = normalize_raw_stage2_solution(raw, problem_data)
    report = validate_stage2_solution(problem_data, solution)
    comparison = ObjectiveComparison(
        solver_result.objective_value,
        report.objective_breakdown.operational_objective,
    )
    return model, solver_result, raw, solution, report, comparison


def _solution(
    data: Stage2ProblemData,
    x: dict[tuple[str, str, str], float],
    u: dict[str, float],
) -> Stage2Solution:
    return Stage2Solution(stage2_solution_identity(data), x, u)


class Stage2PyomoStructureTests(unittest.TestCase):
    """Verify direct transcription and the LP-only decision boundary."""

    def test_only_x_and_u_are_continuous_decision_variables(self) -> None:
        data = make_stage2_two_route_case()
        model = build_stage2_pyomo_model(data)
        variables = tuple(component.local_name for component in model.component_objects(Var))

        self.assertEqual(variables, ("x", "u"))
        self.assertTrue(all(variable.is_continuous() for variable in model.x.values()))
        self.assertTrue(all(variable.is_continuous() for variable in model.u.values()))
        for forbidden in ("y", "z", "w", "q", "v"):
            self.assertFalse(hasattr(model, forbidden))

    def test_eq_12b_through_12f_row_counts_follow_authoritative_lattices(self) -> None:
        data = make_stage2_two_route_case()
        model = build_stage2_pyomo_model(data)

        self.assertEqual(tuple(model.query_ids), data.unmet_keys)
        self.assertEqual(tuple(model.route_keys), data.routing_keys)
        self.assertEqual(
            tuple(model.model_tier_keys),
            data.pdm_problem_data.variable_lattices.model_tier_keys,
        )
        self.assertEqual(len(model.demand_balance), 1)
        self.assertEqual(len(model.compute_capacity), 2)
        self.assertEqual(len(model.delay_slo), 1)
        self.assertEqual(len(model.error_slo), 1)
        self.assertEqual(len(model.routing_mask), 2)

    def test_realized_coefficients_drive_named_eq_12c_12d_12e_expressions(self) -> None:
        nominal, stressed = make_stage2_delay_stress_pair()
        nominal_model = build_stage2_pyomo_model(nominal)
        stressed_model = build_stage2_pyomo_model(stressed)
        route = nominal.routing_keys[0]
        pair = route[1:]
        for model in (nominal_model, stressed_model):
            model.x[route].set_value(1.0)
            model.u[route[0]].set_value(0.0)

        self.assertAlmostEqual(value(nominal_model.processing_delay[route[0]]), 0.25)
        self.assertAlmostEqual(value(stressed_model.processing_delay[route[0]]), 0.50)
        self.assertAlmostEqual(value(nominal_model.weighted_error[route[0]]), 0.05)
        self.assertAlmostEqual(value(nominal_model.required_compute[pair]), 0.03)

        capacity = make_stage2_capacity_limited_case()
        capacity_model = build_stage2_pyomo_model(capacity)
        capacity_model.x[route].set_value(1.0)
        self.assertAlmostEqual(value(capacity_model.required_compute[pair]), 40500.0)

    def test_d_0067_excludes_visible_realized_c3_from_objective(self) -> None:
        data = make_stage2_fully_served_case()
        model = build_stage2_pyomo_model(data)
        route = data.routing_keys[0]
        model.x[route].set_value(1.0)
        model.u[route[0]].set_value(0.0)

        self.assertAlmostEqual(value(model.delay_penalty), 0.0031)
        self.assertEqual(value(model.unmet_penalty), 0.0)
        self.assertAlmostEqual(value(model.operational_objective), 0.0031)
        self.assertAlmostEqual(value(model.realized_data_storage_cost), 3e-8)
        self.assertAlmostEqual(value(model.objective), 0.0031)

    def test_builder_rejects_non_stage2_data(self) -> None:
        with self.assertRaises(TypeError):
            build_stage2_pyomo_model(None)  # type: ignore[arg-type]


class Stage2ExtractionTests(unittest.TestCase):
    """Protect dense raw extraction and domain-only normalization."""

    def setUp(self) -> None:
        self.data = make_stage2_fully_served_case()
        self.model = build_stage2_pyomo_model(self.data)
        self.route = self.data.routing_keys[0]
        self.query_id = self.data.unmet_keys[0]

    def test_uninitialized_value_is_rejected_with_family_and_key(self) -> None:
        with self.assertRaises(Stage2VariableValueExtractionError) as caught:
            extract_raw_stage2_solution_from_pyomo(self.model, self.data)
        self.assertIs(caught.exception.family, Stage2VariableFamily.X)
        self.assertEqual(caught.exception.semantic_key, self.route)

    def test_missing_family_is_rejected_as_lattice_mismatch(self) -> None:
        self.model.x[self.route].set_value(1.0)
        self.model.del_component(self.model.u)
        with self.assertRaises(Stage2ModelLatticeMismatchError) as caught:
            extract_raw_stage2_solution_from_pyomo(self.model, self.data)
        self.assertIs(caught.exception.family, Stage2VariableFamily.U)
        self.assertEqual(caught.exception.missing_keys, (self.query_id,))

    def test_nonfinite_model_value_is_rejected(self) -> None:
        self.model.x[self.route].set_value(inf, skip_validation=True)
        self.model.u[self.query_id].set_value(0.0)
        with self.assertRaises(Stage2VariableValueExtractionError):
            extract_raw_stage2_solution_from_pyomo(self.model, self.data)

    def test_normalization_clips_only_tolerance_scale_bound_noise(self) -> None:
        raw = RawStage2Solution(
            x={self.route: 1.0 + 1e-10},
            u={self.query_id: -1e-10},
        )
        normalized = normalize_raw_stage2_solution(raw, self.data)

        self.assertEqual(normalized.routing_fractions[self.route], 1.0)
        self.assertEqual(normalized.unmet_fractions[self.query_id], 0.0)
        with self.assertRaises(TypeError):
            normalized.routing_fractions[self.route] = 0.0
        with self.assertRaises(FrozenInstanceError):
            normalized.identity = stage2_solution_identity(self.data)

    def test_normalization_rejects_large_bounds_missing_keys_and_nonfinite(self) -> None:
        cases = (
            RawStage2Solution({self.route: 1.0 + 1e-6}, {self.query_id: 0.0}),
            RawStage2Solution({}, {self.query_id: 0.0}),
            RawStage2Solution({self.route: nan}, {self.query_id: 0.0}),
        )
        for raw in cases:
            with self.subTest(raw=raw), self.assertRaises(
                Stage2SolutionNormalizationError
            ):
                normalize_raw_stage2_solution(raw, self.data)

    def test_extraction_copies_values_and_attaches_no_live_model(self) -> None:
        self.model.x[self.route].set_value(0.8)
        self.model.u[self.query_id].set_value(0.2)
        raw = extract_raw_stage2_solution_from_pyomo(self.model, self.data)
        solution = normalize_raw_stage2_solution(raw, self.data)
        self.model.x[self.route].set_value(0.0)

        self.assertEqual(raw.x[self.route], 0.8)
        self.assertEqual(solution.routing_fractions[self.route], 0.8)
        self.assertFalse(hasattr(raw, "model"))
        self.assertFalse(hasattr(solution, "model"))


class Stage2IndependentValidationTests(unittest.TestCase):
    """Exercise every independent equation and evidence boundary."""

    def test_wrong_tolerance_type_is_rejected_before_domain_short_circuit(self) -> None:
        data = make_stage2_fully_served_case()
        route = data.routing_keys[0]
        for x in (1.0, 1.1):
            solution = _solution(data, {route: x}, {route[0]: 0.0})
            for invalid in (False, 0, 0.0, "", {}, [], True, object()):
                with self.subTest(x=x, tolerances=invalid):
                    with self.assertRaisesRegex(TypeError, "tolerances must be"):
                        validate_stage2_solution(data, solution, invalid)

    def test_none_uses_defaults_and_explicit_tolerances_are_retained(self) -> None:
        data = make_stage2_fully_served_case()
        route = data.routing_keys[0]
        for x in (1.0, 1.1):
            with self.subTest(x=x):
                solution = _solution(data, {route: x}, {route[0]: 0.0})
                default = validate_stage2_solution(data, solution)
                explicit_none = validate_stage2_solution(data, solution, None)
                self.assertEqual(default, explicit_none)
                self.assertEqual(default.tolerances, Stage2ValidationTolerances())

                tolerances = Stage2ValidationTolerances(demand_balance=1e-8)
                configured = validate_stage2_solution(data, solution, tolerances)
                self.assertIs(configured.tolerances, tolerances)

    def test_hand_feasible_solution_has_exact_objective_and_realized_c3(self) -> None:
        data = make_stage2_fully_served_case()
        route = data.routing_keys[0]
        report = validate_stage2_solution(
            data, _solution(data, {route: 1.0}, {route[0]: 0.0})
        )

        self.assertTrue(report.is_feasible)
        self.assertEqual(report.violations, ())
        self.assertAlmostEqual(report.processing_delays_seconds[route[0]], 0.31)
        self.assertAlmostEqual(report.objective_breakdown.operational_objective, 0.0031)
        self.assertAlmostEqual(report.objective_breakdown.realized_data_storage_cost, 3e-8)
        self.assertAlmostEqual(report.objective_breakdown.reported_variable_cost, 0.00310003)

    def test_corrupted_solutions_expose_each_equation_family(self) -> None:
        full = make_stage2_fully_served_case()
        full_route = full.routing_keys[0]
        capacity = make_stage2_capacity_limited_case()
        stressed = make_stage2_delay_stress_pair()[1]
        masked = make_stage2_two_route_case(mask_fast_route=True)
        slow, fast = masked.routing_keys

        error_scenario = Stage2RealizedScenario(
            "error_stress",
            full.realized_scenario.arrival_rates_per_hour,
            full.realized_scenario.compute_delay_seconds_per_token,
            full.realized_scenario.communication_delay_seconds_per_token,
            {full_route: 0.2},
        )
        error_data = Stage2ProblemData(
            full.pdm_problem_data,
            full.fixed_deployment,
            error_scenario,
            full.paper_version,
        )
        cases = (
            (
                full,
                _solution(full, {full_route: 0.5}, {full_route[0]: 0.2}),
                Stage2ConstraintFamily.DEMAND_BALANCE,
            ),
            (
                capacity,
                _solution(capacity, {full_route: 1.0}, {full_route[0]: 0.0}),
                Stage2ConstraintFamily.COMPUTE_CAPACITY,
            ),
            (
                stressed,
                _solution(stressed, {full_route: 1.0}, {full_route[0]: 0.0}),
                Stage2ConstraintFamily.DELAY_SLO,
            ),
            (
                error_data,
                _solution(error_data, {full_route: 1.0}, {full_route[0]: 0.0}),
                Stage2ConstraintFamily.ERROR_SLO,
            ),
            (
                masked,
                _solution(masked, {slow: 0.9, fast: 0.1}, {slow[0]: 0.0}),
                Stage2ConstraintFamily.ROUTING_MASK,
            ),
        )
        for data, solution, family in cases:
            with self.subTest(family=family):
                report = validate_stage2_solution(data, solution)
                self.assertFalse(report.is_feasible)
                self.assertIn(family, report.violated_families)

    def test_domain_and_identity_errors_short_circuit(self) -> None:
        data = make_stage2_fully_served_case()
        route = data.routing_keys[0]
        valid = _solution(data, {route: 1.0}, {route[0]: 0.0})
        invalid_domain = _solution(data, {route: 1.1}, {route[0]: 0.0})
        domain_report = validate_stage2_solution(data, invalid_domain)
        self.assertEqual(
            domain_report.violated_families,
            (Stage2ConstraintFamily.DECISION_DOMAINS,),
        )
        self.assertIsNone(domain_report.objective_breakdown)

        other = make_stage2_fully_served_case(PaperVersion.V1)
        identity_report = validate_stage2_solution(other, valid)
        self.assertEqual(
            identity_report.violated_families,
            (Stage2ConstraintFamily.SOLUTION_IDENTITY,),
        )

    def test_invalid_fixed_context_is_rejected_at_public_construction(self) -> None:
        data = make_stage2_fully_served_case()
        pair = data.pdm_problem_data.variable_lattices.model_tier_keys[0]
        invalid = replace(data.fixed_deployment, gpu_counts={pair: 2.0})
        with self.assertRaises(ValueError):
            replace(data, fixed_deployment=invalid)
        with self.assertRaises(FrozenInstanceError):
            data.derived_deployment_indicators = {pair: 0.0}
        with self.assertRaises(TypeError):
            data.derived_deployment_indicators[pair] = 0.0

    def test_validator_reuses_context_but_checks_each_new_solution(self) -> None:
        data = make_stage2_fully_served_case()
        route = data.routing_keys[0]
        valid = _solution(data, {route: 1.0}, {route[0]: 0.0})
        invalid = _solution(data, {route: 1.1}, {route[0]: 0.0})
        with (
            patch.object(Stage2ProblemData, "__init__",
                         side_effect=AssertionError("immutable context must not be reconstructed")),
            patch.object(stage2_validation_module, "_realized_configuration_delays",
                         wraps=stage2_validation_module._realized_configuration_delays) as delays,
        ):
            validator = Stage2Validator(data)
            first = validator.validate(valid)
            second = validator.validate(invalid)
            third = validator.validate(valid)
        self.assertTrue(first.is_feasible)
        self.assertEqual(second.violated_families, (Stage2ConstraintFamily.DECISION_DOMAINS,))
        self.assertIsNone(second.objective_breakdown)
        self.assertEqual(first, third)
        self.assertIs(second.violations, second.violations)
        self.assertEqual(delays.call_count, 1)

    def test_versioned_c5_reuses_d_0067_authority(self) -> None:
        base = make_minimal_tiny_instance()
        instance = replace(base, horizon_hours=2.0)
        pdm = PdmProblemData(instance)
        route = pdm.variable_lattices.route_keys[0]
        configuration = pdm.variable_lattices.configuration_keys[0]
        fixed = Stage2FixedDeployment(
            {route: 1.0}, {configuration: 1.0}, {configuration[:2]: 1.0}
        )
        scenario = Stage2RealizedScenario(
            "versioned_c5",
            {route[0]: 10.0},
            {route: 0.1},
            {route: 0.01},
            {route: 0.05},
        )
        v1 = Stage2ProblemData(pdm, fixed, scenario, PaperVersion.V1)
        v2 = Stage2ProblemData(pdm, fixed, scenario, PaperVersion.V2)
        v1_report = validate_stage2_solution(
            v1, _solution(v1, {route: 0.8}, {route[0]: 0.2})
        )
        v2_report = validate_stage2_solution(
            v2, _solution(v2, {route: 0.8}, {route[0]: 0.2})
        )

        self.assertAlmostEqual(v1_report.objective_breakdown.unmet_demand_penalty, 1.0)
        self.assertAlmostEqual(v2_report.objective_breakdown.unmet_demand_penalty, 2.0)
        self.assertAlmostEqual(
            v2_report.objective_breakdown.delay_penalty,
            v1_report.objective_breakdown.delay_penalty,
        )


class Stage2HighsReferenceTests(unittest.TestCase):
    """Match HiGHS LP optima to independent hand-derived expectations."""

    def test_fully_served_single_route_optimum(self) -> None:
        data = make_stage2_fully_served_case()
        _, result, _, solution, report, comparison = _solve_and_validate(data)
        route = data.routing_keys[0]

        self.assertIs(result.status, SolverStatus.OPTIMAL)
        self.assertEqual(solution.routing_fractions[route], 1.0)
        self.assertEqual(solution.unmet_fractions[route[0]], 0.0)
        self.assertAlmostEqual(result.objective_value, 0.0031)
        self.assertTrue(report.is_feasible)
        self.assertTrue(comparison.agrees)

    def test_capacity_limited_exact_optimum(self) -> None:
        data = make_stage2_capacity_limited_case()
        _, result, _, solution, report, comparison = _solve_and_validate(data)
        route = data.routing_keys[0]

        self.assertAlmostEqual(solution.routing_fractions[route], 0.8)
        self.assertAlmostEqual(solution.unmet_fractions[route[0]], 0.2)
        self.assertAlmostEqual(result.objective_value, 1.00248)
        self.assertAlmostEqual(
            report.compute_capacity_diagnostics[0].required_compute,
            32400.0,
        )
        self.assertTrue(report.is_feasible)
        self.assertTrue(comparison.agrees)

    def test_fixed_mask_forces_attractive_route_to_zero(self) -> None:
        data = make_stage2_two_route_case(mask_fast_route=True)
        _, result, _, solution, report, comparison = _solve_and_validate(data)
        slow, fast = data.routing_keys

        self.assertEqual(solution.routing_fractions[fast], 0.0)
        self.assertEqual(solution.routing_fractions[slow], 1.0)
        self.assertAlmostEqual(result.objective_value, 0.0031)
        self.assertTrue(report.is_feasible)
        self.assertTrue(comparison.agrees)

    def test_two_route_known_optimum_uses_fast_capacity_then_slow_route(self) -> None:
        data = make_stage2_two_route_case()
        _, result, _, solution, report, comparison = _solve_and_validate(data)
        slow, fast = data.routing_keys

        self.assertAlmostEqual(solution.routing_fractions[fast], 0.6)
        self.assertAlmostEqual(solution.routing_fractions[slow], 0.4)
        self.assertEqual(solution.unmet_fractions[slow[0]], 0.0)
        self.assertAlmostEqual(result.objective_value, 0.0016)
        self.assertTrue(report.is_feasible)
        self.assertTrue(comparison.agrees)

    def test_realized_delay_stress_changes_x_u_without_changing_deployment(self) -> None:
        nominal, stressed = make_stage2_delay_stress_pair()
        nominal_run = _solve_and_validate(nominal)
        stressed_run = _solve_and_validate(stressed)
        route = nominal.routing_keys[0]

        self.assertIs(nominal.fixed_deployment, stressed.fixed_deployment)
        self.assertEqual(nominal_run[3].routing_fractions[route], 1.0)
        self.assertEqual(nominal_run[3].unmet_fractions[route[0]], 0.0)
        self.assertAlmostEqual(stressed_run[3].routing_fractions[route], 0.5)
        self.assertAlmostEqual(stressed_run[3].unmet_fractions[route[0]], 0.5)
        self.assertTrue(nominal_run[4].is_feasible)
        self.assertTrue(stressed_run[4].is_feasible)
        self.assertEqual(
            nominal.fixed_deployment.configuration_selectors,
            stressed.fixed_deployment.configuration_selectors,
        )

    def test_repeated_solve_is_deterministic_in_status_objective_and_solution(self) -> None:
        data = make_stage2_two_route_case()
        first = _solve_and_validate(data)
        second = _solve_and_validate(data)

        self.assertIs(first[1].status, second[1].status)
        self.assertEqual(first[1].objective_value, second[1].objective_value)
        self.assertEqual(first[3], second[3])
        self.assertTrue(first[4].is_feasible)
        self.assertTrue(second[4].is_feasible)


if __name__ == "__main__":
    unittest.main()
