"""Focused tests for the Milestone-7.1 Stage-2 data boundary."""

import unittest
from dataclasses import FrozenInstanceError
from math import inf, nan

from llm_resource_allocation.data import (
    make_coherent_tiny_instance,
    make_heterogeneous_tiny_instance,
    make_minimal_tiny_instance,
)
from llm_resource_allocation.domain import InstanceValidationError
from llm_resource_allocation.math.routing import DecisionDomainError
from llm_resource_allocation.math.objective import PaperVersion
from llm_resource_allocation.optimization.stage2_problem_data import (
    Stage2FixedDeployment,
    Stage2ProblemData,
    Stage2RealizedScenario,
)
from llm_resource_allocation.optimization.problem_data import PdmProblemData


def _fixed_deployment(data) -> Stage2FixedDeployment:
    """Activate the first route on the first valid one-GPU configuration."""

    route = data.variable_lattices.route_keys[0]
    configuration = data.variable_lattices.configuration_keys[0]
    pair = configuration[:2]
    return Stage2FixedDeployment(
        admission_indicators={route: 1.0},
        configuration_selectors={configuration: 1.0},
        gpu_counts={pair: configuration[2] * configuration[3]},
    )


def _scenario(data, *, scenario_id: str = "scenario_1") -> Stage2RealizedScenario:
    """Build an explicit nominal-valued realization over the exact lattice."""

    instance = data.instance
    query_by_id = {query.id: query for query in instance.queries}
    tier_by_id = {tier.id: tier for tier in instance.gpu_tiers}
    return Stage2RealizedScenario(
        id=scenario_id,
        arrival_rates_per_hour={
            query_id: query_by_id[query_id].arrival_rate_per_hour
            for query_id in data.variable_lattices.unmet_keys
        },
        compute_delay_seconds_per_token={
            key: instance.compute_delay_seconds_per_token[key]
            for key in data.variable_lattices.route_keys
        },
        communication_delay_seconds_per_token={
            key: instance.communication_delay_seconds_per_token[key]
            for key in data.variable_lattices.route_keys
        },
        effective_errors={
            key: (
                instance.base_error_rate[key[:2]]
                * tier_by_id[key[2]].quantization_error_multiplier
            )
            for key in data.variable_lattices.route_keys
        },
    )


class Stage2BoundaryTests(unittest.TestCase):
    """Protect the fixed-deployment plus realized-scenario composition."""

    def test_coherent_stage1_preserves_the_current_unit_contract(self):
        data = PdmProblemData(make_coherent_tiny_instance())
        operational = Stage2ProblemData(data, _fixed_deployment(data), _scenario(data))
        self.assertIs(operational.instance, data.instance)
        self.assertTrue(operational.instance.uses_coherent_units)

    def setUp(self) -> None:
        self.pdm_data = PdmProblemData(make_minimal_tiny_instance())
        self.fixed = _fixed_deployment(self.pdm_data)
        self.scenario = _scenario(self.pdm_data)

    def test_shared_instance_and_exact_x_u_lattices_are_preserved(self) -> None:
        data = Stage2ProblemData(
            self.pdm_data, self.fixed, self.scenario
        )

        self.assertIs(data.pdm_problem_data, self.pdm_data)
        self.assertIs(data.instance, self.pdm_data.instance)
        self.assertIs(
            data.routing_keys, self.pdm_data.variable_lattices.route_keys
        )
        self.assertIs(data.unmet_keys, self.pdm_data.variable_lattices.unmet_keys)
        self.assertEqual(data.paper_version, PaperVersion.V2)

    def test_fixed_deployment_contains_no_stage2_decisions(self) -> None:
        self.assertFalse(hasattr(self.fixed, "routing_fractions"))
        self.assertFalse(hasattr(self.fixed, "unmet_fractions"))
        self.assertEqual(
            set(self.fixed.__slots__),
            {"admission_indicators", "configuration_selectors", "gpu_counts"},
        )

    def test_q_is_derived_from_w_and_cannot_be_supplied_or_changed(self) -> None:
        data = Stage2ProblemData(
            self.pdm_data,
            self.fixed,
            self.scenario,
            PaperVersion.V1,
        )
        pair = self.pdm_data.variable_lattices.model_tier_keys[0]

        self.assertEqual(data.derived_deployment_indicators[pair], 1.0)
        self.assertEqual(data.paper_version, PaperVersion.V1)
        with self.assertRaises(TypeError):
            data.derived_deployment_indicators[pair] = 0.0
        with self.assertRaises(FrozenInstanceError):
            data.paper_version = PaperVersion.V2

    def test_fixed_and_realized_inputs_are_copied_and_read_only(self) -> None:
        route = self.pdm_data.variable_lattices.route_keys[0]
        z = {route: 1.0}
        arrivals = {self.pdm_data.instance.query_ids[0]: 10.0}
        fixed = Stage2FixedDeployment(
            z,
            self.fixed.configuration_selectors,
            self.fixed.gpu_counts,
        )
        scenario = Stage2RealizedScenario(
            "scenario_copy",
            arrivals,
            self.scenario.compute_delay_seconds_per_token,
            self.scenario.communication_delay_seconds_per_token,
            self.scenario.effective_errors,
        )
        z[route] = 0.0
        arrivals[self.pdm_data.instance.query_ids[0]] = 99.0

        self.assertEqual(fixed.admission_indicators[route], 1.0)
        self.assertEqual(scenario.arrival_rates_per_hour["q_text"], 10.0)
        with self.assertRaises(TypeError):
            fixed.admission_indicators[route] = 0.0
        with self.assertRaises(TypeError):
            scenario.arrival_rates_per_hour["q_text"] = 1.0

    def test_realized_values_preserve_canonical_units_and_domains(self) -> None:
        route = self.pdm_data.variable_lattices.route_keys[0]
        scenario = Stage2RealizedScenario(
            "scenario_units",
            {"q_text": 12.5},
            {route: 0.125},
            {route: 0.0075},
            # Effective error is dimensionless and deliberately not clipped.
            {route: 1.2},
        )
        data = Stage2ProblemData(self.pdm_data, self.fixed, scenario)

        self.assertEqual(data.realized_scenario.arrival_rates_per_hour["q_text"], 12.5)
        self.assertEqual(
            data.realized_scenario.compute_delay_seconds_per_token[route],
            0.125,
        )
        self.assertEqual(data.realized_scenario.effective_errors[route], 1.2)

    def test_sparse_known_fixed_entries_retain_existing_zero_semantics(self) -> None:
        heterogeneous = PdmProblemData(make_heterogeneous_tiny_instance())
        data = Stage2ProblemData(
            heterogeneous,
            _fixed_deployment(heterogeneous),
            _scenario(heterogeneous),
        )

        self.assertEqual(len(data.derived_deployment_indicators), 4)
        self.assertEqual(sum(data.derived_deployment_indicators.values()), 1.0)

    def test_unknown_fixed_keys_are_rejected(self) -> None:
        cases = (
            Stage2FixedDeployment(
                {("unknown", "m_small", "gpu_basic_fp16"): 1.0},
                self.fixed.configuration_selectors,
                self.fixed.gpu_counts,
            ),
            Stage2FixedDeployment(
                self.fixed.admission_indicators,
                {("m_small", "gpu_basic_fp16", 99, 1): 1.0},
                self.fixed.gpu_counts,
            ),
            Stage2FixedDeployment(
                self.fixed.admission_indicators,
                self.fixed.configuration_selectors,
                {("m_small", "unknown"): 1.0},
            ),
        )
        for fixed in cases:
            with self.subTest(fixed=fixed), self.assertRaises(DecisionDomainError):
                Stage2ProblemData(self.pdm_data, fixed, self.scenario)

    def test_invalid_fixed_domains_are_rejected_by_shared_authorities(self) -> None:
        route = self.pdm_data.variable_lattices.route_keys[0]
        configuration = self.pdm_data.variable_lattices.configuration_keys[0]
        pair = configuration[:2]
        cases = (
            Stage2FixedDeployment({route: 0.5}, {configuration: 1.0}, {pair: 1.0}),
            Stage2FixedDeployment({route: 1.0}, {configuration: 0.5}, {pair: 1.0}),
            Stage2FixedDeployment({route: 1.0}, {configuration: 1.0}, {pair: 1.5}),
        )
        for fixed in cases:
            with self.subTest(fixed=fixed), self.assertRaises(DecisionDomainError):
                Stage2ProblemData(self.pdm_data, fixed, self.scenario)

    def test_multiple_fixed_configurations_are_rejected(self) -> None:
        route = self.pdm_data.variable_lattices.route_keys[0]
        configurations = self.pdm_data.variable_lattices.configuration_keys
        pair = configurations[0][:2]
        fixed = Stage2FixedDeployment(
            {route: 1.0},
            {configurations[0]: 1.0, configurations[1]: 1.0},
            {pair: 3.0},
        )
        with self.assertRaises(DecisionDomainError):
            Stage2ProblemData(self.pdm_data, fixed, self.scenario)

    def test_fixed_y_must_equal_the_gpu_count_implied_by_w(self) -> None:
        pair = self.pdm_data.variable_lattices.model_tier_keys[0]
        inconsistent = Stage2FixedDeployment(
            self.fixed.admission_indicators,
            self.fixed.configuration_selectors,
            {pair: 2.0},
        )
        with self.assertRaisesRegex(DecisionDomainError, "fixed y\\*"):
            Stage2ProblemData(self.pdm_data, inconsistent, self.scenario)

    def test_fixed_z_requires_a_deployment_derived_from_w(self) -> None:
        inconsistent = Stage2FixedDeployment(
            self.fixed.admission_indicators,
            {},
            {},
        )
        with self.assertRaisesRegex(DecisionDomainError, "fixed z\\*"):
            Stage2ProblemData(self.pdm_data, inconsistent, self.scenario)

    def test_realized_scenario_requires_exact_shared_lattices(self) -> None:
        missing_arrival = Stage2RealizedScenario(
            "missing",
            {},
            self.scenario.compute_delay_seconds_per_token,
            self.scenario.communication_delay_seconds_per_token,
            self.scenario.effective_errors,
        )
        extra_errors = dict(self.scenario.effective_errors)
        extra_errors[("q_text", "m_small", "unknown")] = 0.1
        extra_error = Stage2RealizedScenario(
            "extra",
            self.scenario.arrival_rates_per_hour,
            self.scenario.compute_delay_seconds_per_token,
            self.scenario.communication_delay_seconds_per_token,
            extra_errors,
        )
        for scenario in (missing_arrival, extra_error):
            with self.subTest(scenario=scenario), self.assertRaises(
                InstanceValidationError
            ):
                Stage2ProblemData(self.pdm_data, self.fixed, scenario)

    def test_invalid_realized_numbers_are_rejected_without_normalization(self) -> None:
        route = self.pdm_data.variable_lattices.route_keys[0]
        cases = (
            Stage2RealizedScenario(
                "negative_arrival",
                {"q_text": -1.0},
                {route: 0.1},
                {route: 0.01},
                {route: 0.05},
            ),
            Stage2RealizedScenario(
                "nan_delay",
                {"q_text": 10.0},
                {route: nan},
                {route: 0.01},
                {route: 0.05},
            ),
            Stage2RealizedScenario(
                "infinite_error",
                {"q_text": 10.0},
                {route: 0.1},
                {route: 0.01},
                {route: inf},
            ),
            Stage2RealizedScenario(
                "boolean_delay",
                {"q_text": 10.0},
                {route: 0.1},
                {route: True},
                {route: 0.05},
            ),
        )
        for scenario in cases:
            with self.subTest(scenario=scenario), self.assertRaises(
                InstanceValidationError
            ):
                Stage2ProblemData(self.pdm_data, self.fixed, scenario)

    def test_invalid_boundary_types_and_version_are_rejected(self) -> None:
        with self.assertRaises(TypeError):
            Stage2ProblemData(None, self.fixed, self.scenario)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            Stage2ProblemData(self.pdm_data, None, self.scenario)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            Stage2ProblemData(self.pdm_data, self.fixed, None)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            Stage2ProblemData(
                self.pdm_data,
                self.fixed,
                self.scenario,
                "v2",  # type: ignore[arg-type]
            )


if __name__ == "__main__":
    unittest.main()
