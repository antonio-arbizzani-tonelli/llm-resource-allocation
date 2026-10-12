"""Focused Milestone-10.2 controlled version-comparison tests."""

import unittest
from dataclasses import FrozenInstanceError, fields, replace

from llm_resource_allocation.data import (
    make_minimal_tiny_instance,
    make_stage2_capacity_limited_case,
)
from llm_resource_allocation.experiments import (
    BoundedScenarioExperimentPlan,
    CrossQuantityDependence,
    DelayRealizationTarget,
    DifferenceCause,
    DistributionFamily,
    DomainHandling,
    ExecutableScenarioSamplingPolicy,
    GeneratedScenarioRecord,
    PerturbationDirection,
    ProvenanceClass,
    QuantitySamplingPolicy,
    RngAlgorithm,
    SamplingScope,
    ScenarioQuantity,
    ScalarVersionComparison,
    SeedDerivation,
    VersionComparisonAxis,
    compare_bounded_version_paths,
    compare_objective_semantics,
    compare_protocol_semantics,
    evaluate_stage1_result_over_scenarios,
    generate_realized_scenario,
    run_bounded_scenario_experiment,
    v1_primary_scenario_protocol,
    v2_primary_scenario_protocol,
)
from llm_resource_allocation.math.objective import PaperVersion
from llm_resource_allocation.optimization.solver import SolverBackend, SolverConfig
from llm_resource_allocation.optimization.stage2_integration import (
    Stage1Stage2EvaluationStatus,
    evaluate_stage1_result_under_scenario,
)
from llm_resource_allocation.optimization.stage2_adapter import Stage1ToStage2FailureReason
from llm_resource_allocation.optimization.problem_data import PdmProblemData
from llm_resource_allocation.optimization.pdm_run import execute_and_record_pdm_run


def _quantity_policy(
    quantity: ScenarioQuantity,
    bounds: tuple[float, float],
    direction: PerturbationDirection,
    note: str,
) -> QuantitySamplingPolicy:
    return QuantitySamplingPolicy(
        quantity,
        DistributionFamily.UNIFORM,
        bounds,
        direction,
        SamplingScope.PER_ENTRY,
        DomainHandling.REJECT_INVALID_NO_CLIPPING,
        ProvenanceClass.ASSUMED,
        note,
    )


def _policy(
    paper_version: PaperVersion,
    protocol_id: str,
    policy_id: str,
    *,
    arrival_bounds: tuple[float, float],
    delay_bounds: tuple[float, float],
    error_bounds: tuple[float, float],
) -> ExecutableScenarioSamplingPolicy:
    delay_error_direction = (
        PerturbationDirection.SYMMETRIC
        if paper_version is PaperVersion.V1
        else PerturbationDirection.ADVERSE_ONLY
    )
    note = (
        "ASSUMED synthetic Milestone-10.2 policy; uniform per-entry independent "
        "streams, shared delay-component factors, and no clipping."
    )
    return ExecutableScenarioSamplingPolicy(
        policy_id,
        paper_version,
        protocol_id,
        ProvenanceClass.ASSUMED,
        RngAlgorithm.PYTHON_MT19937,
        SeedDerivation.SHA256_NAMESPACED_V1,
        CrossQuantityDependence.INDEPENDENT_STREAMS,
        DelayRealizationTarget.BOTH_SHARED,
        _quantity_policy(
            ScenarioQuantity.ARRIVAL_RATE,
            arrival_bounds,
            PerturbationDirection.SYMMETRIC,
            note,
        ),
        _quantity_policy(
            ScenarioQuantity.DELAY_COEFFICIENT,
            delay_bounds,
            delay_error_direction,
            note,
        ),
        _quantity_policy(
            ScenarioQuantity.EFFECTIVE_ERROR,
            error_bounds,
            delay_error_direction,
            note,
        ),
        note + " It is not either paper's unpublished sampler.",
    )


def _factor(record, quantity: ScenarioQuantity) -> float:
    return next(
        value
        for draw in record.evidence.draws
        if draw.quantity is quantity
        for _, value in draw.relative_factors
    )


def _comparison_problem_data() -> PdmProblemData:
    """Build the unchanged nominal fixture shared by the three comparisons."""

    base = make_minimal_tiny_instance()
    query = replace(base.queries[0], delay_slo_seconds=0.312)
    instance = replace(
        base,
        id="controlled_v1_v2_comparison",
        queries=(query,),
        horizon_hours=24.0,
        cost_budget_usd=100.0,
    )
    return PdmProblemData(instance)


def _protocol_control_record(
    problem_data: PdmProblemData,
    paper_version: PaperVersion,
) -> GeneratedScenarioRecord:
    """Generate one existing synthetic control with its native version policy."""

    if paper_version is PaperVersion.V1:
        protocol = v1_primary_scenario_protocol()
        policy_id = "v1-protocol-control"
        delay_error_bounds = (-0.25, 0.25)
    else:
        protocol = v2_primary_scenario_protocol()
        policy_id = "v2-protocol-control"
        delay_error_bounds = (0.0, 0.10)
    policy = _policy(
        paper_version,
        protocol.protocol_id,
        policy_id,
        arrival_bounds=(0.0, 0.0),
        delay_bounds=delay_error_bounds,
        error_bounds=delay_error_bounds,
    )
    return generate_realized_scenario(
        problem_data,
        protocol,
        policy,
        seed=0,
        scenario_id="protocol-control",
    )


class ObjectiveVersionComparisonTests(unittest.TestCase):
    """Verify objective semantics under identical nominal and realized inputs."""

    def test_scalar_delta_is_derived_from_retained_values(self) -> None:
        comparison = ScalarVersionComparison(2.0, 5.0)
        self.assertEqual(comparison.absolute_delta, 3.0)
        self.assertEqual(replace(comparison, v2_value=1.0).absolute_delta, 1.0)
        self.assertNotIn("absolute_delta", {field.name for field in fields(comparison)})

    @classmethod
    def setUpClass(cls) -> None:
        cls.problem_data = _comparison_problem_data()
        cls.v1_source = execute_and_record_pdm_run(
            cls.problem_data,
            SolverConfig(backend=SolverBackend.HIGHS),
            PaperVersion.V1,
        )
        cls.v2_source = execute_and_record_pdm_run(
            cls.problem_data,
            SolverConfig(backend=SolverBackend.HIGHS),
            PaperVersion.V2,
        )

        cls.identical_scenario = (
            make_stage2_capacity_limited_case().realized_scenario
        )
        cls.objective_v1 = evaluate_stage1_result_under_scenario(
            cls.v1_source,
            cls.problem_data,
            cls.identical_scenario,
            paper_version=PaperVersion.V1,
            solver_config=SolverConfig(backend=SolverBackend.HIGHS),
        )
        cls.objective_v2 = evaluate_stage1_result_under_scenario(
            cls.v2_source,
            cls.problem_data,
            cls.identical_scenario,
            paper_version=PaperVersion.V2,
            solver_config=SolverConfig(backend=SolverBackend.HIGHS),
        )
        cls.objective_comparison = compare_objective_semantics(
            cls.objective_v1,
            cls.objective_v2,
        )

    def test_objective_only_controls_are_exact(self) -> None:
        comparison = self.objective_comparison
        self.assertIs(comparison.axis, VersionComparisonAxis.OBJECTIVE_SEMANTICS)
        self.assertEqual(comparison.causes, (DifferenceCause.OBJECTIVE_SEMANTICS,))
        self.assertTrue(comparison.controls.nominal_problem_same_identity)
        self.assertTrue(comparison.controls.fixed_deployment_equivalent)
        self.assertTrue(comparison.controls.realized_scenarios_same_identity)
        self.assertIs(self.objective_v1.realized_scenario, self.objective_v2.realized_scenario)
        self.assertEqual(self.objective_v1.fixed_deployment, self.objective_v2.fixed_deployment)

    def test_objective_only_raw_components_isolate_v1_v2_c5(self) -> None:
        metrics = self.objective_comparison.stage2_metrics
        self.assertAlmostEqual(metrics.c3.v1_value, 0.7776)
        self.assertAlmostEqual(metrics.c3.v2_value, 0.7776)
        self.assertAlmostEqual(metrics.c4.v1_value, 0.00248)
        self.assertAlmostEqual(metrics.c4.v2_value, 0.00248)
        self.assertAlmostEqual(metrics.c5.v1_value, 1.0)
        self.assertAlmostEqual(metrics.c5.v2_value, 24.0)
        self.assertAlmostEqual(metrics.c5.absolute_delta, 23.0)
        self.assertAlmostEqual(metrics.operational_objective.absolute_delta, 23.0)
        self.assertAlmostEqual(metrics.reporting_total.absolute_delta, 23.0)

    def test_objective_only_decisions_and_independent_feasibility_match(self) -> None:
        metrics = self.objective_comparison.stage2_metrics
        self.assertEqual(metrics.v1_decision.routing_fractions, metrics.v2_decision.routing_fractions)
        self.assertEqual(metrics.v1_decision.unmet_fractions, metrics.v2_decision.unmet_fractions)
        self.assertAlmostEqual(metrics.v1_decision.unmet_fractions["q_text"], 0.2)
        self.assertTrue(metrics.v1_decision.independently_feasible)
        self.assertTrue(metrics.v2_decision.independently_feasible)

    def test_objective_comparison_rejects_an_uncontrolled_scenario(self) -> None:
        generated = _protocol_control_record(self.problem_data, PaperVersion.V2)
        other = evaluate_stage1_result_under_scenario(
            self.v2_source,
            self.problem_data,
            generated.realized_scenario,
            paper_version=PaperVersion.V2,
            solver_config=SolverConfig(backend=SolverBackend.HIGHS),
        )
        with self.assertRaisesRegex(ValueError, "identical scenario"):
            compare_objective_semantics(
                self.objective_v1,
                other,
            )

    def test_version_isolation_rejects_both_crossed_source_directions(self) -> None:
        for source, version in (
            (self.v1_source, PaperVersion.V2),
            (self.v2_source, PaperVersion.V1),
        ):
            rejected = evaluate_stage1_result_under_scenario(
                source,
                self.problem_data,
                self.identical_scenario,
                paper_version=version,
                solver_config=SolverConfig(backend=SolverBackend.HIGHS),
            )
            self.assertIs(
                rejected.status,
                Stage1Stage2EvaluationStatus.STAGE1_SOURCE_REJECTED,
            )
            self.assertIs(
                rejected.failure.adapter_reason,
                Stage1ToStage2FailureReason.SOURCE_VERSION_MISMATCH,
            )
            self.assertIsNone(rejected.stage2_problem_data)

    def test_comparison_evidence_is_immutable(self) -> None:
        with self.assertRaises(FrozenInstanceError):
            self.objective_comparison.axis = VersionComparisonAxis.PROTOCOL_SEMANTICS
        with self.assertRaises(TypeError):
            self.objective_comparison.stage2_metrics.v1_decision.unmet_fractions[
                "q_text"
            ] = 0.0


class ProtocolVersionComparisonTests(unittest.TestCase):
    """Verify protocol effects under one common source and objective version."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.problem_data = _comparison_problem_data()
        cls.v2_source = execute_and_record_pdm_run(
            cls.problem_data,
            SolverConfig(backend=SolverBackend.HIGHS),
            PaperVersion.V2,
        )

        cls.v1_protocol_record = _protocol_control_record(
            cls.problem_data, PaperVersion.V1
        )
        cls.v2_protocol_record = _protocol_control_record(
            cls.problem_data, PaperVersion.V2
        )
        cls.protocol_v1_under_common_objective = (
            evaluate_stage1_result_over_scenarios(
                cls.v2_source,
                cls.problem_data,
                (cls.v1_protocol_record.realized_scenario,),
                paper_version=PaperVersion.V2,
                solver_config=SolverConfig(backend=SolverBackend.HIGHS),
            )
        )
        cls.protocol_v2_under_common_objective = (
            evaluate_stage1_result_over_scenarios(
                cls.v2_source,
                cls.problem_data,
                (cls.v2_protocol_record.realized_scenario,),
                paper_version=PaperVersion.V2,
                solver_config=SolverConfig(backend=SolverBackend.HIGHS),
            )
        )
        cls.protocol_comparison = compare_protocol_semantics(
            (cls.v1_protocol_record,),
            (cls.v2_protocol_record,),
            cls.protocol_v1_under_common_objective,
            cls.protocol_v2_under_common_objective,
        )

    def test_protocol_case_preserves_direction_support_and_assumptions(self) -> None:
        evidence = self.protocol_comparison.protocol_evidence
        self.assertIs(evidence.v1_policy.provenance, ProvenanceClass.ASSUMED)
        self.assertIs(evidence.v2_policy.provenance, ProvenanceClass.ASSUMED)
        by_quantity = {item.quantity: item for item in evidence.quantity_comparisons}
        for quantity in (
            ScenarioQuantity.DELAY_COEFFICIENT,
            ScenarioQuantity.EFFECTIVE_ERROR,
        ):
            item = by_quantity[quantity]
            self.assertIs(item.v1_direction, PerturbationDirection.SYMMETRIC)
            self.assertIs(item.v2_direction, PerturbationDirection.ADVERSE_ONLY)
            self.assertEqual(item.v1_executable_support, (-0.25, 0.25))
            self.assertEqual(item.v2_executable_support, (0.0, 0.10))

    def test_protocol_case_has_beneficial_v1_and_adverse_v2_delay_error(self) -> None:
        for quantity in (
            ScenarioQuantity.DELAY_COEFFICIENT,
            ScenarioQuantity.EFFECTIVE_ERROR,
        ):
            self.assertLess(_factor(self.v1_protocol_record, quantity), 0.0)
            self.assertGreater(_factor(self.v2_protocol_record, quantity), 0.0)
        self.assertEqual(
            _factor(self.v1_protocol_record, ScenarioQuantity.ARRIVAL_RATE),
            0.0,
        )
        self.assertEqual(
            _factor(self.v2_protocol_record, ScenarioQuantity.ARRIVAL_RATE),
            0.0,
        )

    def test_protocol_outputs_use_one_common_objective_and_fixed_deployment(self) -> None:
        comparison = self.protocol_comparison
        self.assertIs(comparison.axis, VersionComparisonAxis.PROTOCOL_SEMANTICS)
        self.assertIs(comparison.controls.common_stage2_objective_version, PaperVersion.V2)
        self.assertTrue(comparison.controls.fixed_deployment_equivalent)
        self.assertIn(DifferenceCause.PROTOCOL_SUPPORT_DIRECTION, comparison.causes)
        self.assertIn(DifferenceCause.SCENARIO_REALIZATION, comparison.causes)
        self.assertNotIn(DifferenceCause.OBJECTIVE_SEMANTICS, comparison.causes)
        self.assertNotIn(DifferenceCause.COMBINED_NOT_ISOLATED, comparison.causes)
        metrics = comparison.aggregate_metrics
        self.assertEqual(metrics.v1_scenario_count, 1)
        self.assertEqual(metrics.v2_scenario_count, 1)
        self.assertNotEqual(metrics.v1_decisions[0].unmet_fractions, metrics.v2_decisions[0].unmet_fractions)

    def test_same_seed_is_retained_only_as_reproduction_metadata(self) -> None:
        left = self.v1_protocol_record.evidence
        right = self.v2_protocol_record.evidence
        self.assertEqual(left.seed, right.seed)
        self.assertNotEqual(left.sampling_policy.policy_id, right.sampling_policy.policy_id)
        self.assertNotEqual(left.draws, right.draws)
        self.assertIn("not used as a matching criterion", self.protocol_comparison.controls.description)

    def test_protocol_comparison_rejects_crossed_generated_versions(self) -> None:
        """Version controls belong to the public comparison input boundary."""

        with self.assertRaisesRegex(ValueError, "retain their version"):
            compare_protocol_semantics(
                (self.v2_protocol_record,),
                (self.v1_protocol_record,),
                self.protocol_v2_under_common_objective,
                self.protocol_v1_under_common_objective,
            )

    def test_protocol_comparison_rejects_a_mixed_generated_sequence(self) -> None:
        """Each controlled side must use the same explicit protocol and policy."""

        with self.assertRaisesRegex(ValueError, "one exact protocol and policy"):
            compare_protocol_semantics(
                (self.v1_protocol_record, self.v2_protocol_record),
                (self.v2_protocol_record,),
                self.protocol_v1_under_common_objective,
                self.protocol_v2_under_common_objective,
            )


class BoundedVersionComparisonTests(unittest.TestCase):
    """Verify complete native version paths and their combined differences."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.problem_data = _comparison_problem_data()
        cls.v1_source = execute_and_record_pdm_run(
            cls.problem_data,
            SolverConfig(backend=SolverBackend.HIGHS),
            PaperVersion.V1,
        )
        cls.v2_source = execute_and_record_pdm_run(
            cls.problem_data,
            SolverConfig(backend=SolverBackend.HIGHS),
            PaperVersion.V2,
        )

        cls.v1_protocol = v1_primary_scenario_protocol()
        cls.v2_protocol = v2_primary_scenario_protocol()
        cls.v1_end_policy = _policy(
            PaperVersion.V1,
            cls.v1_protocol.protocol_id,
            "v1-end-to-end",
            arrival_bounds=(-0.20, 0.20),
            delay_bounds=(-0.25, 0.25),
            error_bounds=(-0.25, 0.25),
        )
        cls.v2_end_policy = _policy(
            PaperVersion.V2,
            cls.v2_protocol.protocol_id,
            "v2-end-to-end",
            arrival_bounds=(-0.20, 0.20),
            delay_bounds=(0.0, 0.10),
            error_bounds=(0.0, 0.10),
        )
        cls.v1_plan = BoundedScenarioExperimentPlan(
            ("v1-end-0", "v1-end-1", "v1-end-2"),
            101,
        )
        cls.v2_plan = BoundedScenarioExperimentPlan(
            ("v2-end-0", "v2-end-1", "v2-end-2"),
            202,
        )
        cls.v1_bounded = run_bounded_scenario_experiment(
            cls.v1_source,
            cls.problem_data,
            cls.v1_protocol,
            cls.v1_end_policy,
            cls.v1_plan,
            paper_version=PaperVersion.V1,
            solver_config=SolverConfig(backend=SolverBackend.HIGHS),
        )
        cls.v2_bounded = run_bounded_scenario_experiment(
            cls.v2_source,
            cls.problem_data,
            cls.v2_protocol,
            cls.v2_end_policy,
            cls.v2_plan,
            paper_version=PaperVersion.V2,
            solver_config=SolverConfig(backend=SolverBackend.HIGHS),
        )
        cls.end_to_end_comparison = compare_bounded_version_paths(
            cls.v1_bounded,
            cls.v2_bounded,
        )

    def test_end_to_end_paths_retain_both_complete_native_evidence_chains(self) -> None:
        comparison = self.end_to_end_comparison
        self.assertIs(comparison.axis, VersionComparisonAxis.COMBINED_END_TO_END)
        self.assertIs(comparison.v1_evidence, self.v1_bounded)
        self.assertIs(comparison.v2_evidence, self.v2_bounded)
        self.assertTrue(self.v1_bounded.successful)
        self.assertTrue(self.v2_bounded.successful)
        self.assertIs(self.v1_bounded.paper_version, PaperVersion.V1)
        self.assertIs(self.v2_bounded.paper_version, PaperVersion.V2)
        self.assertIs(
            self.v1_bounded.evaluation_result.source_result,
            self.v1_source,
        )
        self.assertIs(
            self.v2_bounded.evaluation_result.source_result,
            self.v2_source,
        )

    def test_end_to_end_metrics_expose_raw_values_before_deltas(self) -> None:
        metrics = self.end_to_end_comparison.aggregate_metrics
        left = self.v1_bounded.evaluation_result.aggregate
        right = self.v2_bounded.evaluation_result.aggregate
        self.assertEqual(metrics.v1_scenario_count, 3)
        self.assertEqual(metrics.v2_scenario_count, 3)
        self.assertEqual(metrics.expected_total_cost.v1_value, left.expected_total_cost)
        self.assertEqual(metrics.expected_total_cost.v2_value, right.expected_total_cost)
        self.assertEqual(
            metrics.expected_total_cost.absolute_delta,
            abs(right.expected_total_cost - left.expected_total_cost),
        )
        self.assertFalse(hasattr(metrics.expected_total_cost, "relative_delta"))
        self.assertEqual(metrics.mean_c3.v1_value, left.mean_c3)
        self.assertEqual(metrics.mean_c4.v2_value, right.mean_c4)
        self.assertEqual(metrics.mean_c5.v1_value, left.mean_c5)
        self.assertEqual(metrics.violation_rate.v2_value, right.violation_rate)

    def test_end_to_end_mixed_deltas_are_not_overattributed(self) -> None:
        comparison = self.end_to_end_comparison
        self.assertIn(DifferenceCause.OBJECTIVE_SEMANTICS, comparison.causes)
        self.assertIn(DifferenceCause.PROTOCOL_SUPPORT_DIRECTION, comparison.causes)
        self.assertIn(DifferenceCause.SCENARIO_REALIZATION, comparison.causes)
        self.assertIn(DifferenceCause.COMBINED_NOT_ISOLATED, comparison.causes)
        if comparison.controls.fixed_deployment_equivalent:
            self.assertNotIn(DifferenceCause.FIXED_DEPLOYMENT, comparison.causes)
        else:
            self.assertIn(DifferenceCause.FIXED_DEPLOYMENT, comparison.causes)


if __name__ == "__main__":
    unittest.main()
