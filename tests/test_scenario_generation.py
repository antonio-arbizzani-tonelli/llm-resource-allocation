"""Focused tests for the Milestone-9.2 single-scenario generator."""

import random
import sys
import unittest
from dataclasses import FrozenInstanceError, replace
from unittest.mock import patch

from llm_resource_allocation.data import (
    make_heterogeneous_tiny_instance,
    make_minimal_tiny_instance,
)
from llm_resource_allocation.experiments import (
    CrossQuantityDependence,
    DelayRealizationTarget,
    DistributionFamily,
    DomainHandling,
    ExecutableScenarioSamplingPolicy,
    GeneratedScenarioDomainError,
    GeneratedScenarioRecord,
    IncompleteScenarioSamplingPolicyError,
    PerturbationDirection,
    ProvenanceClass,
    QuantitySamplingPolicy,
    RngAlgorithm,
    SamplingScope,
    ScenarioQuantity,
    ScenarioSamplingPolicyError,
    SeedDerivation,
    generate_realized_scenario,
    v2_primary_scenario_protocol,
)
from llm_resource_allocation.math.objective import PaperVersion
from llm_resource_allocation.math.error import compute_effective_error
from llm_resource_allocation.optimization.problem_data import PdmProblemData


def _quantity_policy(
    quantity: ScenarioQuantity,
    bounds: tuple[float, float],
    direction: PerturbationDirection,
    scope: SamplingScope,
) -> QuantitySamplingPolicy:
    """Return an explicit synthetic-test assumption, never a paper default."""

    return QuantitySamplingPolicy(
        quantity,
        DistributionFamily.UNIFORM,
        bounds,
        direction,
        scope,
        DomainHandling.REJECT_INVALID_NO_CLIPPING,
        ProvenanceClass.ASSUMED,
        "Synthetic verification-only uniform draw convention.",
    )


def _policy(
    *,
    arrival_scope: SamplingScope = SamplingScope.PER_QUERY,
    delay_scope: SamplingScope = SamplingScope.PER_ENTRY,
    error_scope: SamplingScope = SamplingScope.PER_ENTRY,
    delay_target: DelayRealizationTarget = DelayRealizationTarget.BOTH_SHARED,
) -> ExecutableScenarioSamplingPolicy:
    protocol = v2_primary_scenario_protocol()
    return ExecutableScenarioSamplingPolicy(
        "synthetic-test-v2-uniform-policy",
        PaperVersion.V2,
        protocol.protocol_id,
        ProvenanceClass.ASSUMED,
        RngAlgorithm.PYTHON_MT19937,
        SeedDerivation.SHA256_NAMESPACED_V1,
        CrossQuantityDependence.INDEPENDENT_STREAMS,
        delay_target,
        _quantity_policy(
            ScenarioQuantity.ARRIVAL_RATE,
            (-0.20, 0.20),
            PerturbationDirection.SYMMETRIC,
            arrival_scope,
        ),
        _quantity_policy(
            ScenarioQuantity.DELAY_COEFFICIENT,
            (0.0, 0.10),
            PerturbationDirection.ADVERSE_ONLY,
            delay_scope,
        ),
        _quantity_policy(
            ScenarioQuantity.EFFECTIVE_ERROR,
            (0.0, 0.25),
            PerturbationDirection.ADVERSE_ONLY,
            error_scope,
        ),
        (
            "Synthetic verification policy: uniform arrivals on audited support; "
            "explicit assumed delay/error bounds and independent streams."
        ),
    )


class ScenarioGenerationTests(unittest.TestCase):
    """Freeze policy completeness, local RNG, mapping, and domain invariants."""

    def setUp(self) -> None:
        self.problem_data = PdmProblemData(
            make_heterogeneous_tiny_instance()
        )
        self.protocol = v2_primary_scenario_protocol()
        self.policy = _policy()

    def generate(
        self,
        *,
        policy: ExecutableScenarioSamplingPolicy | None = None,
        seed: int = 41,
        scenario_id: str = "synthetic-scenario-0",
    ) -> GeneratedScenarioRecord:
        return generate_realized_scenario(
            self.problem_data,
            self.protocol,
            self.policy if policy is None else policy,
            seed=seed,
            scenario_id=scenario_id,
        )

    def test_audited_protocol_and_executable_policy_are_distinct(self) -> None:
        self.assertNotIsInstance(self.policy, type(self.protocol))
        delay = next(
            item
            for item in self.protocol.perturbations
            if item.quantity is ScenarioQuantity.DELAY_COEFFICIENT
        )
        self.assertIsNone(delay.executable_relative_bounds)
        self.assertEqual(self.policy.delay.relative_bounds, (0.0, 0.10))
        self.assertEqual(self.policy.provenance, ProvenanceClass.ASSUMED)

    def test_incomplete_policy_fails_instead_of_inferencing_protocol_none(self) -> None:
        incomplete = replace(self.policy, delay=None)
        with self.assertRaisesRegex(
            IncompleteScenarioSamplingPolicyError, "missing executable delay"
        ):
            self.generate(policy=incomplete)

    def test_same_input_policy_seed_and_identity_are_exactly_reproducible(self) -> None:
        first = self.generate()
        second = self.generate()
        self.assertEqual(first, second)
        self.assertEqual(first.evidence.draws, second.evidence.draws)

    def test_seed_and_scenario_identity_both_affect_local_streams(self) -> None:
        baseline = self.generate()
        different_seed = self.generate(seed=42)
        different_identity = self.generate(scenario_id="synthetic-scenario-1")
        self.assertNotEqual(baseline.realized_scenario, different_seed.realized_scenario)
        self.assertNotEqual(baseline.realized_scenario, different_identity.realized_scenario)
        self.assertNotEqual(
            baseline.evidence.draws[0].derived_seed,
            different_identity.evidence.draws[0].derived_seed,
        )

    def test_global_random_state_is_unchanged(self) -> None:
        state_before = random.getstate()
        self.generate()
        self.assertEqual(random.getstate(), state_before)

    def test_nominal_problem_and_all_nominal_mappings_remain_unchanged(self) -> None:
        instance = self.problem_data.instance
        snapshot = (
            instance.queries,
            dict(instance.compute_delay_seconds_per_token),
            dict(instance.communication_delay_seconds_per_token),
            dict(instance.base_error_rate),
        )
        self.generate()
        self.assertEqual(instance.queries, snapshot[0])
        self.assertEqual(dict(instance.compute_delay_seconds_per_token), snapshot[1])
        self.assertEqual(
            dict(instance.communication_delay_seconds_per_token), snapshot[2]
        )
        self.assertEqual(dict(instance.base_error_rate), snapshot[3])

    def test_realized_mappings_preserve_canonical_semantic_order(self) -> None:
        record = self.generate()
        scenario = record.realized_scenario
        lattices = self.problem_data.variable_lattices
        self.assertEqual(tuple(scenario.arrival_rates_per_hour), lattices.unmet_keys)
        self.assertEqual(
            tuple(scenario.compute_delay_seconds_per_token), lattices.route_keys
        )
        self.assertEqual(
            tuple(scenario.communication_delay_seconds_per_token),
            lattices.route_keys,
        )
        self.assertEqual(tuple(scenario.effective_errors), lattices.route_keys)
        self.assertEqual(record.evidence.semantic_query_order, lattices.unmet_keys)
        self.assertEqual(record.evidence.semantic_route_order, lattices.route_keys)

    def test_arrivals_obey_explicit_uniform_support_within_audited_bounds(self) -> None:
        scenario = self.generate().realized_scenario
        nominal = {query.id: query.arrival_rate_per_hour for query in self.problem_data.instance.queries}
        for query_id, realized in scenario.arrival_rates_per_hour.items():
            relative = realized / nominal[query_id] - 1.0
            self.assertGreaterEqual(relative, -0.20)
            self.assertLessEqual(relative, 0.20)

    def test_delay_and_error_are_adverse_only_with_policy_owned_bounds(self) -> None:
        record = self.generate()
        scenario = record.realized_scenario
        instance = self.problem_data.instance
        tiers = {tier.id: tier for tier in instance.gpu_tiers}
        for key in self.problem_data.variable_lattices.route_keys:
            compute_relative = (
                scenario.compute_delay_seconds_per_token[key]
                / instance.compute_delay_seconds_per_token[key]
                - 1.0
            )
            communication_relative = (
                scenario.communication_delay_seconds_per_token[key]
                / instance.communication_delay_seconds_per_token[key]
                - 1.0
            )
            nominal_error = compute_effective_error(
                instance.base_error_rate[key[:2]],
                tiers[key[2]].quantization_error_multiplier,
            )
            error_relative = scenario.effective_errors[key] / nominal_error - 1.0
            self.assertGreaterEqual(compute_relative, 0.0)
            self.assertLessEqual(compute_relative, 0.10)
            self.assertAlmostEqual(compute_relative, communication_relative)
            self.assertGreaterEqual(error_relative, 0.0)
            self.assertLessEqual(error_relative, 0.25)

    def test_delay_target_mapping_is_explicit_and_obeyed(self) -> None:
        compute_only = _policy(
            delay_target=DelayRealizationTarget.COMPUTE_ONLY
        )
        scenario = self.generate(policy=compute_only).realized_scenario
        instance = self.problem_data.instance
        self.assertEqual(
            dict(scenario.communication_delay_seconds_per_token),
            dict(instance.communication_delay_seconds_per_token),
        )
        self.assertNotEqual(
            dict(scenario.compute_delay_seconds_per_token),
            dict(instance.compute_delay_seconds_per_token),
        )

    def test_independent_delay_component_mapping_uses_distinct_streams(self) -> None:
        independent = _policy(
            delay_target=DelayRealizationTarget.BOTH_INDEPENDENT
        )
        record = self.generate(policy=independent)
        compute_draw, communication_draw = record.evidence.draws[1:3]
        self.assertEqual(compute_draw.stream_id, "delay-compute")
        self.assertEqual(communication_draw.stream_id, "delay-communication")
        self.assertNotEqual(compute_draw.derived_seed, communication_draw.derived_seed)
        self.assertNotEqual(
            compute_draw.relative_factors,
            communication_draw.relative_factors,
        )

    def test_global_and_per_entry_scopes_have_distinct_shared_draw_semantics(self) -> None:
        global_policy = _policy(error_scope=SamplingScope.GLOBAL)
        entry_policy = _policy(error_scope=SamplingScope.PER_ENTRY)
        global_record = self.generate(policy=global_policy)
        entry_record = self.generate(policy=entry_policy)
        global_error_draw = global_record.evidence.draws[-1]
        entry_error_draw = entry_record.evidence.draws[-1]
        self.assertEqual(
            len({factor for _, factor in global_error_draw.relative_factors}), 1
        )
        self.assertGreater(
            len({factor for _, factor in entry_error_draw.relative_factors}), 1
        )

    def test_per_query_scope_shares_route_draws_only_within_query(self) -> None:
        policy = _policy(delay_scope=SamplingScope.PER_QUERY)
        record = self.generate(policy=policy)
        delay_draw = record.evidence.draws[1]
        by_query: dict[str, set[float]] = {}
        for key, factor in delay_draw.relative_factors:
            self.assertIsInstance(key, tuple)
            by_query.setdefault(key[0], set()).add(factor)
        self.assertTrue(all(len(factors) == 1 for factors in by_query.values()))
        self.assertGreater(len({next(iter(factors)) for factors in by_query.values()}), 1)

    def test_direction_and_domain_policy_contradictions_fail_before_drawing(self) -> None:
        invalid_delay = replace(self.policy.delay, relative_bounds=(-0.01, 0.10))
        invalid = replace(self.policy, delay=invalid_delay)
        with self.assertRaisesRegex(
            ScenarioSamplingPolicyError, "adverse-only bounds"
        ):
            self.generate(policy=invalid)

        paper_claim = replace(self.policy, provenance=ProvenanceClass.PAPER_SPECIFIED)
        with self.assertRaisesRegex(
            ScenarioSamplingPolicyError, "cannot claim paper-specified"
        ):
            self.generate(policy=paper_claim)

        missing_domain_rule = replace(
            self.policy,
            arrival=replace(self.policy.arrival, domain_handling=None),
        )
        with self.assertRaisesRegex(
            IncompleteScenarioSamplingPolicyError, "domain_handling"
        ):
            self.generate(policy=missing_domain_rule)

    def test_reject_invalid_domain_policy_performs_no_hidden_repair(self) -> None:
        base = make_minimal_tiny_instance()
        route = next(iter(base.compute_delay_seconds_per_token))
        extreme = replace(
            base,
            id="synthetic-overflow-domain-case",
            compute_delay_seconds_per_token={route: sys.float_info.max},
        )
        problem_data = PdmProblemData(extreme)
        delay = replace(self.policy.delay, relative_bounds=(0.10, 0.10))
        policy = replace(
            self.policy,
            delay=delay,
            delay_realization_target=DelayRealizationTarget.COMPUTE_ONLY,
        )
        with self.assertRaisesRegex(
            GeneratedScenarioDomainError, "must be finite"
        ):
            generate_realized_scenario(
                problem_data,
                self.protocol,
                policy,
                seed=1,
                scenario_id="overflow-must-fail",
            )

    def test_returned_scenario_and_reproducibility_evidence_are_immutable(self) -> None:
        record = self.generate()
        query_id = self.problem_data.variable_lattices.unmet_keys[0]
        with self.assertRaises(TypeError):
            record.realized_scenario.arrival_rates_per_hour[query_id] = 0.0
        with self.assertRaises(FrozenInstanceError):
            record.evidence.seed = 0
        self.assertRegex(record.evidence.python_runtime_version, r"^3\.14\.")

    def test_one_call_returns_one_scenario_without_invoking_any_method_or_solver(self) -> None:
        with (
            patch("llm_resource_allocation.algorithms.run_gh") as run_gh,
            patch("llm_resource_allocation.algorithms.run_agh") as run_agh,
            patch("llm_resource_allocation.optimization.pdm_run.execute_and_record_pdm_run") as run_pdm,
            patch("llm_resource_allocation.optimization.stage2_run.run_stage2") as run_stage2,
        ):
            record = self.generate()
        self.assertIsInstance(record, GeneratedScenarioRecord)
        self.assertEqual(record.realized_scenario.id, "synthetic-scenario-0")
        self.assertEqual(self.protocol.scenario_count, 500)
        self.assertFalse(hasattr(record, "scenarios"))
        for mocked in (run_gh, run_agh, run_pdm, run_stage2):
            mocked.assert_not_called()


if __name__ == "__main__":
    unittest.main()
