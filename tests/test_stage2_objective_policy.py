"""Opt-in objective agreement changes classification, never scientific values."""

from dataclasses import replace
from math import inf, nan, ulp
import unittest
from unittest.mock import patch

from llm_resource_allocation.data import make_stage2_fully_served_case
from llm_resource_allocation.optimization.solver import SolverBackend, SolverConfig
from llm_resource_allocation.optimization.stage2_run import run_stage2, Stage2RunStatus
from llm_resource_allocation.validation.objective_comparison import ObjectiveComparison
import llm_resource_allocation.optimization.stage2_run as runner


class ObjectiveScalePolicyTests(unittest.TestCase):
    def test_three_ulps_at_large_scale_are_opt_in_only(self):
        value = 500_000_000.0
        observed = value + 3 * ulp(value)
        self.assertFalse(ObjectiveComparison(observed, value).agrees)
        scaled = ObjectiveComparison(observed, value, relative_tolerance=1e-12)
        self.assertTrue(scaled.agrees)
        self.assertEqual(scaled.solver_objective, observed)
        self.assertEqual(scaled.independent_objective, value)
        self.assertEqual(scaled.applied_tolerance, 1e-12 * observed)

    def test_threshold_is_maximum_not_sum_and_is_inclusive(self):
        self.assertTrue(ObjectiveComparison(8.0, 6.0, 2.0, 0.25).agrees)
        self.assertFalse(ObjectiveComparison(8.0, 5.0, 2.0, 0.25).agrees)
        self.assertTrue(ObjectiveComparison(-8.0, -6.0, 2.0, 0.25).agrees)
        self.assertEqual(ObjectiveComparison(0.0, 0.0).applied_tolerance, 1e-8)

    def test_mutation_of_at_least_one_part_per_million_is_rejected(self):
        # These are injected objective errors, not solver roundoff or new data.
        for value in (1.0, 1e8, -1e8):
            mutated = value * (1.0 + 2e-6)
            self.assertGreaterEqual(abs(mutated-value) / max(abs(mutated), abs(value)), 1e-6)
            self.assertFalse(ObjectiveComparison(mutated, value, relative_tolerance=1e-12).agrees)

    def test_relative_domain_and_applied_overflow_are_checked(self):
        for invalid in (-1.0, True, "1e-12", inf, nan):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                ObjectiveComparison(1.0, 1.0, relative_tolerance=invalid)
        with self.assertRaises(ValueError):
            ObjectiveComparison(1e308, 1e308, relative_tolerance=10.0)


class Stage2ScalePolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = make_stage2_fully_served_case()
        cls.config = SolverConfig(backend=SolverBackend.HIGHS)
        cls.valid = run_stage2(cls.data, cls.config)

    def recorded_run(self, solver_value, independent_value, **kwargs):
        report = self.valid.scientific_evidence.validation_report
        report = replace(report, objective_breakdown=replace(
            report.objective_breakdown, delay_penalty=independent_value,
            unmet_demand_penalty=0.0))
        with patch.object(runner, "solve_pyomo_model", return_value=replace(
            self.valid.solver_evidence.result, objective_value=solver_value)), \
             patch.object(runner, "extract_raw_stage2_solution_from_pyomo", return_value=self.valid.raw_solution), \
             patch.object(runner, "normalize_raw_stage2_solution", return_value=self.valid.solution), \
             patch.object(runner, "validate_stage2_solution", return_value=report):
            return run_stage2(self.data, self.config, **kwargs)

    def test_runner_reclassifies_only_under_explicit_relative_keyword(self):
        independent = 1e8
        observed = independent + 3 * ulp(independent)
        old = self.recorded_run(observed, independent)
        new = self.recorded_run(observed, independent, objective_relative_tolerance=1e-12)
        self.assertIs(old.status, Stage2RunStatus.OBJECTIVE_INCONSISTENT)
        self.assertIs(new.status, Stage2RunStatus.SUCCESS)
        self.assertEqual(old.solution, new.solution)
        self.assertEqual(old.scientific_evidence.validation_report, new.scientific_evidence.validation_report)
        self.assertEqual(new.scientific_evidence.objective_comparison.relative_tolerance, 1e-12)
        self.assertIs(self.recorded_run(independent*(1+2e-6), independent,
            objective_relative_tolerance=1e-12).status, Stage2RunStatus.OBJECTIVE_INCONSISTENT)

    def test_runner_rejects_bad_policy_before_solver(self):
        for invalid in (-1.0, True, inf, nan, "1e-12"):
            with self.subTest(invalid=invalid), patch.object(runner, "build_stage2_pyomo_model") as build:
                with self.assertRaises(ValueError):
                    run_stage2(self.data, objective_relative_tolerance=invalid)
                build.assert_not_called()


if __name__ == "__main__":
    unittest.main()
