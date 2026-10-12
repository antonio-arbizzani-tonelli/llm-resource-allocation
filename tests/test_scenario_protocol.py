"""Focused structural tests for the Milestone-9.1 protocol specification."""

import inspect
import random
import unittest
from dataclasses import FrozenInstanceError
from unittest.mock import patch

from llm_resource_allocation.experiments import (
    PerturbationDirection,
    ProtocolKind,
    ProvenanceClass,
    ScenarioProtocolSpec,
    ScenarioQuantity,
    SpecificationAvailability,
    v1_primary_scenario_protocol,
    v2_delay_error_stress_protocol,
    v2_primary_scenario_protocol,
)
from llm_resource_allocation.math.objective import PaperVersion


def _by_quantity(protocol: ScenarioProtocolSpec, quantity: ScenarioQuantity):
    return next(item for item in protocol.perturbations if item.quantity is quantity)


class ScenarioProtocolSpecificationTests(unittest.TestCase):
    """Protect audited facts, explicit gaps, and the no-execution boundary."""

    def test_specifications_are_deeply_immutable(self) -> None:
        protocol = v2_primary_scenario_protocol()
        with self.assertRaises(FrozenInstanceError):
            protocol.scenario_count = 42
        with self.assertRaises(FrozenInstanceError):
            protocol.perturbations[0].distribution_family = "uniform"

    def test_version_identity_and_scenario_count_are_explicit(self) -> None:
        v2 = v2_primary_scenario_protocol()
        v1 = v1_primary_scenario_protocol()
        self.assertEqual((v2.paper_version, v2.scenario_count), (PaperVersion.V2, 500))
        self.assertEqual((v1.paper_version, v1.scenario_count), (PaperVersion.V1, 500))

    def test_unavailable_sampler_details_have_no_hidden_defaults(self) -> None:
        parameters = inspect.signature(ScenarioProtocolSpec).parameters.values()
        self.assertTrue(all(item.default is inspect.Parameter.empty for item in parameters))
        primary = v2_primary_scenario_protocol()
        self.assertIsNone(primary.random_seed_policy)
        self.assertIsNone(primary.repetition_policy)
        self.assertIsNone(primary.same_realizations_across_methods)
        for perturbation in primary.perturbations:
            self.assertIsNone(perturbation.distribution_family)
            self.assertIsNone(perturbation.independence_or_correlation)
            self.assertIsNone(perturbation.clipping_or_domain_rule)
            self.assertEqual(perturbation.availability, SpecificationAvailability.PARTIAL)

    def test_v2_ambiguous_delay_error_range_is_not_made_executable(self) -> None:
        primary = v2_primary_scenario_protocol()
        for quantity in (ScenarioQuantity.DELAY_COEFFICIENT, ScenarioQuantity.EFFECTIVE_ERROR):
            item = _by_quantity(primary, quantity)
            self.assertEqual(item.direction, PerturbationDirection.ADVERSE_ONLY)
            self.assertEqual(item.reported_magnitude, "inflated above nominal by up to 10-25%")
            self.assertIsNone(item.executable_relative_bounds)

    def test_v2_primary_and_stress_protocols_cannot_be_conflated(self) -> None:
        primary = v2_primary_scenario_protocol()
        stress = v2_delay_error_stress_protocol()
        self.assertEqual(primary.kind, ProtocolKind.PRIMARY_UNCERTAINTY)
        self.assertEqual(stress.kind, ProtocolKind.DELAY_ERROR_STRESS)
        self.assertEqual(primary.scenario_count, 500)
        self.assertIsNone(stress.scenario_count)
        self.assertEqual(primary.deterministic_multipliers, ())
        self.assertEqual(stress.deterministic_multipliers, (1.0, 1.2, 1.5))
        self.assertIsNone(primary.strict_unmet_fraction_cap)
        self.assertEqual(stress.strict_unmet_fraction_cap, 0.02)

    def test_v1_and_v2_delay_error_directionality_remain_different(self) -> None:
        v1 = v1_primary_scenario_protocol()
        v2 = v2_primary_scenario_protocol()
        for quantity in (ScenarioQuantity.DELAY_COEFFICIENT, ScenarioQuantity.EFFECTIVE_ERROR):
            older = _by_quantity(v1, quantity)
            newer = _by_quantity(v2, quantity)
            self.assertEqual(older.direction, PerturbationDirection.SYMMETRIC)
            self.assertEqual(older.executable_relative_bounds, (-0.25, 0.25))
            self.assertEqual(newer.direction, PerturbationDirection.ADVERSE_ONLY)
            self.assertIsNone(newer.executable_relative_bounds)
        self.assertEqual(
            _by_quantity(v1, ScenarioQuantity.ARRIVAL_RATE).executable_relative_bounds,
            _by_quantity(v2, ScenarioQuantity.ARRIVAL_RATE).executable_relative_bounds,
        )

    def test_provenance_and_page_evidence_survive_inspection(self) -> None:
        primary = v2_primary_scenario_protocol()
        self.assertEqual(primary.field_provenance[0].classification, ProvenanceClass.PAPER_SPECIFIED)
        self.assertEqual(primary.evidence[0].paper_version, PaperVersion.V2)
        self.assertEqual(primary.evidence[0].pdf_page, 10)
        arrivals = _by_quantity(primary, ScenarioQuantity.ARRIVAL_RATE)
        self.assertEqual(
            {item.classification for item in arrivals.field_provenance},
            {ProvenanceClass.PAPER_SPECIFIED, ProvenanceClass.DERIVED},
        )

    def test_factories_do_not_use_rng_or_execute_any_scientific_method(self) -> None:
        with (
            patch.object(random, "random") as random_draw,
            patch.object(random, "uniform") as uniform_draw,
            patch("llm_resource_allocation.algorithms.run_gh") as run_gh,
            patch("llm_resource_allocation.algorithms.run_agh") as run_agh,
            patch("llm_resource_allocation.optimization.pdm_run.execute_and_record_pdm_run") as run_pdm,
            patch("llm_resource_allocation.optimization.stage2_run.run_stage2") as run_stage2,
        ):
            protocols = (
                v2_primary_scenario_protocol(),
                v2_delay_error_stress_protocol(),
                v1_primary_scenario_protocol(),
            )
        self.assertEqual(len(protocols), 3)
        for mocked in (random_draw, uniform_draw, run_gh, run_agh, run_pdm, run_stage2):
            mocked.assert_not_called()


if __name__ == "__main__":
    unittest.main()
