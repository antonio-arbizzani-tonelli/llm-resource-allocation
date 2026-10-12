"""Milestone-9.4 bounded experimental-protocol closure tests."""

import ast
import inspect
import random
import unittest
from dataclasses import FrozenInstanceError, fields, replace
from math import fsum
from unittest.mock import patch

import llm_resource_allocation.experiments.bounded_experiment as bounded_module
from llm_resource_allocation.algorithms import GHPhase1Config, run_agh, run_gh
from llm_resource_allocation.data import make_minimal_tiny_instance
from llm_resource_allocation.experiments import (
    BoundedExperimentStatus,
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
    SeedDerivation,
    run_bounded_scenario_experiment,
    v2_primary_scenario_protocol,
)
from llm_resource_allocation.math.objective import PaperVersion
from llm_resource_allocation.optimization.solver import SolverBackend, SolverConfig
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
        "Explicit synthetic Milestone-9 closure fixture assumption.",
    )


def _synthetic_policy() -> ExecutableScenarioSamplingPolicy:
    protocol = v2_primary_scenario_protocol()
    return ExecutableScenarioSamplingPolicy(
        "synthetic-bounded-v2-reference",
        PaperVersion.V2,
        protocol.protocol_id,
        ProvenanceClass.ASSUMED,
        RngAlgorithm.PYTHON_MT19937,
        SeedDerivation.SHA256_NAMESPACED_V1,
        CrossQuantityDependence.INDEPENDENT_STREAMS,
        DelayRealizationTarget.BOTH_SHARED,
        _quantity_policy(
            ScenarioQuantity.ARRIVAL_RATE,
            (-0.01, 0.01),
            PerturbationDirection.SYMMETRIC,
        ),
        _quantity_policy(
            ScenarioQuantity.DELAY_COEFFICIENT,
            (0.0, 0.025),
            PerturbationDirection.ADVERSE_ONLY,
        ),
        _quantity_policy(
            ScenarioQuantity.EFFECTIVE_ERROR,
            (0.0, 0.01),
            PerturbationDirection.ADVERSE_ONLY,
        ),
        (
            "ASSUMED synthetic reference only: uniform independent streams, "
            "explicit small supports, and shared delay-component factors."
        ),
    )


class BoundedExperimentClosureTests(unittest.TestCase):
    """Exercise the complete policy-to-independent-aggregate chain."""

    @classmethod
    def setUpClass(cls) -> None:
        base = make_minimal_tiny_instance()
        query = replace(base.queries[0], delay_slo_seconds=0.312)
        cls.instance = replace(
            base,
            id="bounded_v2_synthetic_reference",
            queries=(query,),
        )
        cls.problem_data = PdmProblemData(cls.instance)
        cls.source = execute_and_record_pdm_run(
            cls.problem_data,
            SolverConfig(backend=SolverBackend.HIGHS),
            PaperVersion.V2,
        )
        cls.protocol = v2_primary_scenario_protocol()
        cls.policy = _synthetic_policy()
        cls.plan = BoundedScenarioExperimentPlan(
            ("bounded-0", "bounded-1", "bounded-2", "bounded-3"),
            1,
        )
        cls.result = run_bounded_scenario_experiment(
            cls.source,
            cls.problem_data,
            cls.protocol,
            cls.policy,
            cls.plan,
            solver_config=SolverConfig(backend=SolverBackend.HIGHS),
        )

    def _run(self, *, plan=None, policy=None, source=None):
        return run_bounded_scenario_experiment(
            self.source if source is None else source,
            self.problem_data,
            self.protocol,
            self.policy if policy is None else policy,
            self.plan if plan is None else plan,
            solver_config=SolverConfig(backend=SolverBackend.HIGHS),
        )

    def test_complete_policy_generation_evaluation_aggregation_chain(self) -> None:
        result = self.result
        evaluation = result.evaluation_result

        self.assertTrue(result.successful)
        self.assertIs(result.status, BoundedExperimentStatus.SUCCESS)
        self.assertEqual(len(result.generation_attempts), 4)
        self.assertEqual(len(result.generated_records), 4)
        self.assertTrue(evaluation.successful)
        self.assertEqual(len(evaluation.per_scenario), 4)
        self.assertAlmostEqual(
            evaluation.aggregate.expected_total_cost,
            1.0432043828742592,
        )
        self.assertEqual(evaluation.aggregate.violation_count, 2)
        self.assertEqual(evaluation.aggregate.scenario_query_pair_count, 4)
        self.assertEqual(evaluation.aggregate.violation_rate, 0.5)

    def test_scenario_count_identity_and_order_are_retained_end_to_end(self) -> None:
        self.assertEqual(
            tuple(item.scenario_id for item in self.result.generation_attempts),
            self.plan.scenario_ids,
        )
        self.assertEqual(
            tuple(
                item.realized_scenario.id
                for item in self.result.evaluation_result.per_scenario
            ),
            self.plan.scenario_ids,
        )
        for attempt, per_scenario in zip(
            self.result.generation_attempts,
            self.result.evaluation_result.per_scenario,
            strict=True,
        ):
            self.assertIs(
                attempt.generated_record.realized_scenario,
                per_scenario.realized_scenario,
            )

    def test_same_inputs_are_scientifically_reproducible(self) -> None:
        repeated = self._run()
        first_evaluation = self.result.evaluation_result
        repeated_evaluation = repeated.evaluation_result

        self.assertEqual(repeated.generated_records, self.result.generated_records)
        self.assertEqual(repeated_evaluation.aggregate, first_evaluation.aggregate)
        self.assertEqual(
            tuple(item.unmet_fractions for item in repeated_evaluation.per_scenario),
            tuple(item.unmet_fractions for item in first_evaluation.per_scenario),
        )
        self.assertEqual(
            tuple(item.objective_breakdown for item in repeated_evaluation.per_scenario),
            tuple(item.objective_breakdown for item in first_evaluation.per_scenario),
        )

    def test_different_explicit_seed_changes_generated_evidence(self) -> None:
        changed_plan = replace(self.plan, master_seed=6)
        changed = self._run(plan=changed_plan)

        self.assertTrue(changed.successful)
        self.assertNotEqual(changed.generated_records, self.result.generated_records)
        self.assertNotEqual(
            tuple(record.evidence.draws for record in changed.generated_records),
            tuple(record.evidence.draws for record in self.result.generated_records),
        )

    def test_global_rng_state_is_untouched(self) -> None:
        before = random.getstate()
        self._run()
        self.assertEqual(random.getstate(), before)

    def test_fixed_deployment_is_constant_but_operational_x_u_vary(self) -> None:
        evidence = self.result.evaluation_result.per_scenario
        baseline_fixed = evidence[0].fixed_deployment
        unmet = tuple(item.unmet_fractions["q_text"] for item in evidence)
        routing = tuple(
            tuple(item.evaluation_result.stage2_run_record.solution.routing_fractions.values())
            for item in evidence
        )

        self.assertTrue(all(item.fixed_deployment == baseline_fixed for item in evidence))
        self.assertGreater(len(set(unmet)), 1)
        self.assertGreater(len(set(routing)), 1)

    def test_every_scenario_has_independent_validation_evidence(self) -> None:
        for item in self.result.evaluation_result.per_scenario:
            self.assertTrue(item.successful)
            self.assertTrue(item.independently_feasible)
            self.assertIsNotNone(item.independent_validation_report)
            self.assertTrue(item.independent_validation_report.is_feasible)

    def test_aggregate_equals_explicit_evidence_recomputation(self) -> None:
        evidence = self.result.evaluation_result.per_scenario
        aggregate = self.result.evaluation_result.aggregate
        count = len(evidence)
        mean_c3 = fsum(item.c3 for item in evidence) / count
        mean_c4 = fsum(item.c4 for item in evidence) / count
        mean_c5 = fsum(item.c5 for item in evidence) / count
        unmet = tuple(
            value for item in evidence for value in item.unmet_fractions.values()
        )

        self.assertEqual(aggregate.mean_c3, mean_c3)
        self.assertEqual(aggregate.mean_c4, mean_c4)
        self.assertEqual(aggregate.mean_c5, mean_c5)
        self.assertEqual(
            aggregate.expected_total_cost,
            aggregate.deterministic_stage1_cost + mean_c3 + mean_c4 + mean_c5,
        )
        explicit_violations = sum(value > 0.01 for value in unmet)
        self.assertEqual(aggregate.violation_count, explicit_violations)
        self.assertEqual(aggregate.scenario_query_pair_count, len(unmet))
        self.assertEqual(aggregate.violation_rate, explicit_violations / len(unmet))

    def test_policy_is_explicitly_assumed_and_not_paper_exact(self) -> None:
        self.assertIs(self.policy.provenance, ProvenanceClass.ASSUMED)
        for quantity_policy in (
            self.policy.arrival,
            self.policy.delay,
            self.policy.effective_error,
        ):
            self.assertIs(quantity_policy.provenance, ProvenanceClass.ASSUMED)
        self.assertIn("synthetic", self.policy.assumption_note.lower())
        self.assertNotIn("paper-exact", self.policy.assumption_note.lower())

    def test_primary_runner_has_no_stress_rolling_or_azure_logic(self) -> None:
        tree = ast.parse(inspect.getsource(bounded_module))
        dependencies: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                dependencies.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                dependencies.append(node.module or "")
                dependencies.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.Call):
                dependencies.append(ast.unparse(node.func))
        for dependency in dependencies:
            with self.subTest(dependency=dependency):
                self.assertFalse(
                    any(
                        forbidden in dependency.lower()
                        for forbidden in (
                            "v2_delay_error_stress_protocol",
                            "rolling",
                            "azure",
                        )
                    ),
                    "primary runner must not import or call other protocols",
                )

    def test_plan_structurally_accepts_500_without_executing_it(self) -> None:
        scenario_ids = tuple(f"structural-{index}" for index in range(500))
        plan = BoundedScenarioExperimentPlan(scenario_ids, 5)

        self.assertEqual(plan.scenario_count, 500)
        self.assertEqual(len(plan.scenario_ids), 500)

    def test_generation_failure_is_retained_without_partial_evaluation(self) -> None:
        incomplete = replace(self.policy, delay=None)
        with patch.object(
            bounded_module,
            "evaluate_stage1_result_over_scenarios",
            side_effect=AssertionError("partial generation must not be evaluated"),
        ) as evaluator:
            result = self._run(policy=incomplete)

        self.assertIs(result.status, BoundedExperimentStatus.GENERATION_FAILED)
        self.assertIsNone(result.evaluation_result)
        self.assertEqual(len(result.generation_failures), self.plan.scenario_count)
        self.assertEqual(
            tuple(item.scenario_id for item in result.generation_failures),
            self.plan.scenario_ids,
        )
        self.assertEqual(len(result.generated_records), 0)
        evaluator.assert_not_called()

    def test_evaluation_failure_is_retained_without_partial_aggregate(self) -> None:
        result = self._run(source=object())

        self.assertIs(result.status, BoundedExperimentStatus.EVALUATION_FAILED)
        self.assertIsNotNone(result.evaluation_result)
        self.assertFalse(result.evaluation_result.successful)
        self.assertIsNone(result.evaluation_result.aggregate)
        self.assertEqual(
            len(result.evaluation_result.failures),
            self.plan.scenario_count,
        )

    def test_existing_authorities_are_composed_once_per_planned_item(self) -> None:
        original_generator = bounded_module.generate_realized_scenario
        original_evaluator = bounded_module.evaluate_stage1_result_over_scenarios
        with patch.object(
            bounded_module,
            "generate_realized_scenario",
            wraps=original_generator,
        ) as generator, patch.object(
            bounded_module,
            "evaluate_stage1_result_over_scenarios",
            wraps=original_evaluator,
        ) as evaluator:
            result = self._run()

        self.assertTrue(result.successful)
        self.assertEqual(generator.call_count, self.plan.scenario_count)
        evaluator.assert_called_once()

    def test_plan_and_experiment_evidence_are_immutable(self) -> None:
        with self.assertRaises(FrozenInstanceError):
            self.plan.master_seed = 2
        with self.assertRaises(FrozenInstanceError):
            self.result.status = BoundedExperimentStatus.EVALUATION_FAILED
        with self.assertRaises(FrozenInstanceError):
            self.result.generation_attempts[0].scenario_id = "changed"

    def test_plan_rejects_empty_scenario_ids(self) -> None:
        with self.assertRaises(ValueError):
            BoundedScenarioExperimentPlan((), 1)

    def test_plan_count_is_derived_from_retained_ids(self) -> None:
        plan = BoundedScenarioExperimentPlan(("one", "two"), 1)
        self.assertEqual(plan.scenario_count, 2)
        self.assertNotIn("scenario_count", {field.name for field in fields(plan)})
        shortened = replace(plan, scenario_ids=("one",))
        self.assertEqual(shortened.scenario_count, 1)


class CommonGeneratedScenarioMethodologyTests(unittest.TestCase):
    """Verify controlled common scenarios without claiming paper semantics."""

    @classmethod
    def setUpClass(cls) -> None:
        instance = make_minimal_tiny_instance()
        cls.problem_data = PdmProblemData(instance)
        config = GHPhase1Config(0.8)
        cls.sources = (
            execute_and_record_pdm_run(cls.problem_data, SolverConfig(backend=SolverBackend.HIGHS)),
            run_gh(instance, config),
            run_agh(instance, config, random_seed=37),
        )
        cls.protocol = v2_primary_scenario_protocol()
        cls.policy = _synthetic_policy()
        cls.plan = BoundedScenarioExperimentPlan(
            ("common-generated-0", "common-generated-1"),
            991,
        )
        cls.results = tuple(
            run_bounded_scenario_experiment(
                source,
                cls.problem_data,
                cls.protocol,
                cls.policy,
                cls.plan,
                solver_config=SolverConfig(backend=SolverBackend.HIGHS),
            )
            for source in cls.sources
        )

    def test_same_generated_sequence_can_control_pdm_gh_and_agh(self) -> None:
        baseline = self.results[0]
        self.assertTrue(all(result.successful for result in self.results))
        for result in self.results[1:]:
            self.assertEqual(result.generated_records, baseline.generated_records)
            self.assertEqual(
                tuple(
                    item.realized_scenario.id
                    for item in result.evaluation_result.per_scenario
                ),
                self.plan.scenario_ids,
            )


if __name__ == "__main__":
    unittest.main()
