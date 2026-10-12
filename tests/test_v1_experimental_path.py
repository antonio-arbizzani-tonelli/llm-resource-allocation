"""Focused Milestone-10.1 executable-v1 protocol and isolation tests."""

import unittest
from dataclasses import replace
from math import fsum

from llm_resource_allocation.data import make_minimal_tiny_instance
from llm_resource_allocation.experiments import (
    BoundedScenarioExperimentPlan,
    CrossQuantityDependence,
    DelayRealizationTarget,
    DistributionFamily,
    DomainHandling,
    ExecutableScenarioSamplingPolicy,
    PerturbationDirection,
    ProvenanceClass,
    QuantitySamplingPolicy,
    RngAlgorithm,
    SamplingScope,
    ScenarioQuantity,
    ScenarioSamplingPolicyError,
    SeedDerivation,
    SpecificationAvailability,
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
) -> QuantitySamplingPolicy:
    return QuantitySamplingPolicy(
        quantity,
        DistributionFamily.UNIFORM,
        bounds,
        direction,
        SamplingScope.PER_ENTRY,
        DomainHandling.REJECT_INVALID_NO_CLIPPING,
        ProvenanceClass.ASSUMED,
        "Explicit synthetic Milestone-10.1 reference/isolation assumption.",
    )


def _v1_synthetic_policy() -> ExecutableScenarioSamplingPolicy:
    protocol = v1_primary_scenario_protocol()
    return ExecutableScenarioSamplingPolicy(
        "synthetic-bounded-v1-reference",
        PaperVersion.V1,
        protocol.protocol_id,
        ProvenanceClass.ASSUMED,
        RngAlgorithm.PYTHON_MT19937,
        SeedDerivation.SHA256_NAMESPACED_V1,
        CrossQuantityDependence.INDEPENDENT_STREAMS,
        DelayRealizationTarget.BOTH_SHARED,
        _quantity_policy(
            ScenarioQuantity.ARRIVAL_RATE,
            (-0.20, 0.20),
            PerturbationDirection.SYMMETRIC,
        ),
        _quantity_policy(
            ScenarioQuantity.DELAY_COEFFICIENT,
            (-0.25, 0.25),
            PerturbationDirection.SYMMETRIC,
        ),
        _quantity_policy(
            ScenarioQuantity.EFFECTIVE_ERROR,
            (-0.25, 0.25),
            PerturbationDirection.SYMMETRIC,
        ),
        (
            "ASSUMED synthetic v1 reference only: uniform per-entry independent "
            "streams and shared delay-component factors over the full published "
            "support; this is not the unpublished paper sampler."
        ),
    )


def _v2_synthetic_policy() -> ExecutableScenarioSamplingPolicy:
    protocol = v2_primary_scenario_protocol()
    return ExecutableScenarioSamplingPolicy(
        "synthetic-v2-version-isolation",
        PaperVersion.V2,
        protocol.protocol_id,
        ProvenanceClass.ASSUMED,
        RngAlgorithm.PYTHON_MT19937,
        SeedDerivation.SHA256_NAMESPACED_V1,
        CrossQuantityDependence.INDEPENDENT_STREAMS,
        DelayRealizationTarget.BOTH_SHARED,
        _quantity_policy(
            ScenarioQuantity.ARRIVAL_RATE,
            (-0.20, 0.20),
            PerturbationDirection.SYMMETRIC,
        ),
        _quantity_policy(
            ScenarioQuantity.DELAY_COEFFICIENT,
            (0.0, 0.10),
            PerturbationDirection.ADVERSE_ONLY,
        ),
        _quantity_policy(
            ScenarioQuantity.EFFECTIVE_ERROR,
            (0.0, 0.10),
            PerturbationDirection.ADVERSE_ONLY,
        ),
        "ASSUMED synthetic v2 policy used only to test version isolation.",
    )


def _by_quantity(protocol, quantity: ScenarioQuantity):
    return next(item for item in protocol.perturbations if item.quantity is quantity)


class ExecutableV1ExperimentalPathTests(unittest.TestCase):
    """Exercise v1 protocol -> generation -> repeated Stage 2 -> aggregate."""

    @classmethod
    def setUpClass(cls) -> None:
        base = make_minimal_tiny_instance()
        query = replace(base.queries[0], delay_slo_seconds=0.312)
        cls.instance = replace(
            base,
            id="bounded_v1_synthetic_reference",
            queries=(query,),
        )
        cls.problem_data = PdmProblemData(cls.instance)
        cls.source = execute_and_record_pdm_run(
            cls.problem_data,
            SolverConfig(backend=SolverBackend.HIGHS),
            PaperVersion.V1,
        )
        cls.protocol = v1_primary_scenario_protocol()
        cls.policy = _v1_synthetic_policy()
        cls.plan = BoundedScenarioExperimentPlan(
            ("v1-bounded-0", "v1-bounded-1", "v1-bounded-2", "v1-bounded-3"),
            1,
        )
        cls.result = run_bounded_scenario_experiment(
            cls.source,
            cls.problem_data,
            cls.protocol,
            cls.policy,
            cls.plan,
            paper_version=PaperVersion.V1,
            solver_config=SolverConfig(backend=SolverBackend.HIGHS),
        )

    def test_v1_protocol_records_paper_facts_and_unavailable_sampler_fields(self) -> None:
        self.assertIs(self.protocol.paper_version, PaperVersion.V1)
        self.assertEqual(self.protocol.scenario_count, 500)
        expected = {
            ScenarioQuantity.ARRIVAL_RATE: (-0.20, 0.20),
            ScenarioQuantity.DELAY_COEFFICIENT: (-0.25, 0.25),
            ScenarioQuantity.EFFECTIVE_ERROR: (-0.25, 0.25),
        }
        for quantity, bounds in expected.items():
            item = _by_quantity(self.protocol, quantity)
            self.assertIs(item.direction, PerturbationDirection.SYMMETRIC)
            self.assertEqual(item.executable_relative_bounds, bounds)
            self.assertIs(item.availability, SpecificationAvailability.PARTIAL)
            self.assertIsNone(item.distribution_family)
            self.assertIsNone(item.sampling_scope)
            self.assertIsNone(item.independence_or_correlation)
            self.assertIsNone(item.clipping_or_domain_rule)
            self.assertEqual(
                {entry.classification for entry in item.field_provenance},
                {ProvenanceClass.PAPER_SPECIFIED, ProvenanceClass.DERIVED},
            )
        self.assertIsNone(self.protocol.random_seed_policy)
        self.assertIsNone(self.protocol.repetition_policy)
        self.assertIsNone(self.protocol.same_realizations_across_methods)

    def test_assumed_policy_uses_exact_v1_support_without_claiming_paper_sampler(self) -> None:
        self.assertIs(self.policy.provenance, ProvenanceClass.ASSUMED)
        self.assertEqual(self.policy.arrival.relative_bounds, (-0.20, 0.20))
        self.assertEqual(self.policy.delay.relative_bounds, (-0.25, 0.25))
        self.assertEqual(self.policy.effective_error.relative_bounds, (-0.25, 0.25))
        self.assertIn("not the unpublished paper sampler", self.policy.assumption_note)

    def test_complete_v1_chain_preserves_scenario_identity_and_version(self) -> None:
        self.assertTrue(self.result.successful)
        evaluation = self.result.evaluation_result
        self.assertIs(self.result.paper_version, PaperVersion.V1)
        self.assertIs(evaluation.paper_version, PaperVersion.V1)
        self.assertEqual(
            tuple(item.realized_scenario.id for item in evaluation.per_scenario),
            self.plan.scenario_ids,
        )
        for generated, evaluated in zip(
            self.result.generated_records,
            evaluation.per_scenario,
            strict=True,
        ):
            self.assertIs(generated.realized_scenario, evaluated.realized_scenario)
            self.assertIs(
                evaluated.evaluation_result.stage2_problem_data.paper_version,
                PaperVersion.V1,
            )
            self.assertIs(
                evaluated.evaluation_result.stage2_run_record.identity.paper_version,
                PaperVersion.V1,
            )

    def test_symmetric_support_has_both_below_and_above_nominal_draws(self) -> None:
        factors = {
            quantity: []
            for quantity in (
                ScenarioQuantity.ARRIVAL_RATE,
                ScenarioQuantity.DELAY_COEFFICIENT,
                ScenarioQuantity.EFFECTIVE_ERROR,
            )
        }
        for record in self.result.generated_records:
            for draw in record.evidence.draws:
                factors[draw.quantity].extend(value for _, value in draw.relative_factors)
        for quantity, values in factors.items():
            bounds = _by_quantity(
                self.protocol, quantity
            ).executable_relative_bounds
            self.assertTrue(all(bounds[0] <= value <= bounds[1] for value in values))
            self.assertTrue(any(value < 0.0 for value in values))
            self.assertTrue(any(value > 0.0 for value in values))

    def test_fixed_deployment_is_constant_while_v1_operational_decisions_vary(self) -> None:
        evidence = self.result.evaluation_result.per_scenario
        fixed = evidence[0].fixed_deployment
        self.assertTrue(all(item.fixed_deployment == fixed for item in evidence))
        self.assertGreater(
            len(set(item.unmet_fractions["q_text"] for item in evidence)),
            1,
        )
        self.assertGreater(
            len(
                {
                    tuple(
                        item.evaluation_result.stage2_run_record.solution.routing_fractions.values()
                    )
                    for item in evidence
                }
            ),
            1,
        )

    def test_every_v1_stage2_run_has_independent_versioned_c3_c4_c5_evidence(self) -> None:
        penalty = self.instance.queries[0].unmet_penalty_usd_per_hour
        for item in self.result.evaluation_result.per_scenario:
            self.assertTrue(item.successful)
            self.assertTrue(item.independently_feasible)
            self.assertTrue(item.independent_validation_report.is_feasible)
            self.assertAlmostEqual(
                item.c5,
                penalty * item.unmet_fractions["q_text"],
            )
            self.assertAlmostEqual(item.operational_cost, item.c4 + item.c5)
            self.assertAlmostEqual(
                item.reporting_contribution,
                item.c3 + item.c4 + item.c5,
            )

    def test_v1_reference_aggregate_is_hand_checkable_and_strict(self) -> None:
        evaluation = self.result.evaluation_result
        aggregate = evaluation.aggregate
        count = self.plan.scenario_count
        mean_c3 = fsum(item.c3 for item in evaluation.per_scenario) / count
        mean_c4 = fsum(item.c4 for item in evaluation.per_scenario) / count
        mean_c5 = fsum(item.c5 for item in evaluation.per_scenario) / count
        unmet = tuple(
            item.unmet_fractions["q_text"] for item in evaluation.per_scenario
        )
        violations = sum(value > 0.01 for value in unmet)

        self.assertAlmostEqual(aggregate.mean_c3, mean_c3)
        self.assertAlmostEqual(aggregate.mean_c4, mean_c4)
        self.assertAlmostEqual(aggregate.mean_c5, mean_c5)
        self.assertAlmostEqual(
            aggregate.expected_total_cost,
            1.1382209285309408,
        )
        self.assertEqual(aggregate.violation_count, violations)
        self.assertEqual(violations, 2)
        self.assertEqual(aggregate.scenario_query_pair_count, 4)
        self.assertEqual(aggregate.violation_rate, 0.5)

    def test_v1_reference_is_reproducible(self) -> None:
        repeated = run_bounded_scenario_experiment(
            self.source,
            self.problem_data,
            self.protocol,
            self.policy,
            self.plan,
            paper_version=PaperVersion.V1,
            solver_config=SolverConfig(backend=SolverBackend.HIGHS),
        )
        self.assertEqual(repeated.generated_records, self.result.generated_records)
        self.assertEqual(
            repeated.evaluation_result.aggregate,
            self.result.evaluation_result.aggregate,
        )

    def test_v1_source_cannot_be_evaluated_under_v2_objective_semantics(self) -> None:
        scenario = self.result.generated_records[0].realized_scenario
        rejected = evaluate_stage1_result_under_scenario(
            self.source,
            self.problem_data,
            scenario,
            paper_version=PaperVersion.V2,
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
        self.assertIsNone(rejected.stage2_run_record)

    def test_v1_bounded_execution_requires_explicit_v1_selection(self) -> None:
        with self.assertRaisesRegex(ValueError, "protocol and experiment"):
            run_bounded_scenario_experiment(
                self.source,
                self.problem_data,
                self.protocol,
                self.policy,
                self.plan,
                solver_config=SolverConfig(backend=SolverBackend.HIGHS),
            )

    def test_v1_policy_cannot_validate_against_v2_protocol(self) -> None:
        with self.assertRaises(ScenarioSamplingPolicyError):
            generate_realized_scenario(
                self.problem_data,
                v2_primary_scenario_protocol(),
                self.policy,
                seed=1,
                scenario_id="cross-version-rejected",
            )

    def test_same_seed_does_not_make_v1_and_v2_generation_equivalent(self) -> None:
        v1 = generate_realized_scenario(
            self.problem_data,
            self.protocol,
            self.policy,
            seed=7,
            scenario_id="same-seed-isolation",
        )
        v2_protocol = v2_primary_scenario_protocol()
        v2 = generate_realized_scenario(
            self.problem_data,
            v2_protocol,
            _v2_synthetic_policy(),
            seed=7,
            scenario_id="same-seed-isolation",
        )
        self.assertIs(v1.evidence.protocol.paper_version, PaperVersion.V1)
        self.assertIs(v2.evidence.protocol.paper_version, PaperVersion.V2)
        self.assertNotEqual(self.protocol.protocol_id, v2_protocol.protocol_id)
        self.assertNotEqual(v1.evidence.draws, v2.evidence.draws)
        self.assertNotEqual(v1.realized_scenario, v2.realized_scenario)
        for quantity in (
            ScenarioQuantity.DELAY_COEFFICIENT,
            ScenarioQuantity.EFFECTIVE_ERROR,
        ):
            self.assertIs(
                _by_quantity(v2_protocol, quantity).direction,
                PerturbationDirection.ADVERSE_ONLY,
            )
            self.assertIsNone(
                _by_quantity(v2_protocol, quantity).executable_relative_bounds
            )


if __name__ == "__main__":
    unittest.main()
