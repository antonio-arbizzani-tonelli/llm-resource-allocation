"""Focused Milestone-8.1 Stage-1 to Stage-2 adapter tests."""

import unittest
from dataclasses import FrozenInstanceError, fields, replace
from unittest.mock import patch

import llm_resource_allocation.algorithms.agh as agh_module
import llm_resource_allocation.algorithms.gh as gh_module
import llm_resource_allocation.optimization.pdm_run as pdm_run_module
import llm_resource_allocation.optimization.stage2_adapter as adapter_module
import llm_resource_allocation.optimization.stage2_run as stage2_run_module
from llm_resource_allocation.algorithms import (
    AGHCompletionStatus,
    GHPhase1Config,
    run_agh,
    run_gh,
)
from llm_resource_allocation.data import make_minimal_tiny_instance
from llm_resource_allocation.optimization.solver import SolverBackend, SolverConfig
from llm_resource_allocation.optimization.stage2_adapter import (
    Stage1Method,
    Stage1ToStage2AdapterError,
    Stage1ToStage2DeploymentEvidence,
    Stage1ToStage2FailureReason,
    stage2_fixed_deployment_from_stage1,
)
from llm_resource_allocation.optimization.stage2_problem_data import Stage2FixedDeployment
from llm_resource_allocation.optimization.problem_data import PdmProblemData
from llm_resource_allocation.optimization.pdm_run import execute_and_record_pdm_run


class Stage1ToStage2AdapterTests(unittest.TestCase):
    """Protect accepted-source selection, exact copying, and scope isolation."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.instance = make_minimal_tiny_instance()
        cls.problem_data = PdmProblemData(cls.instance)
        cls.config = GHPhase1Config(0.8)
        cls.pdm_result = execute_and_record_pdm_run(
            cls.problem_data, SolverConfig(backend=SolverBackend.HIGHS)
        )
        cls.gh_result = run_gh(cls.instance, cls.config)
        cls.agh_result = run_agh(cls.instance, cls.config, random_seed=37)

        infeasible_instance = replace(
            cls.instance,
            queries=(replace(cls.instance.queries[0], error_slo=0.0),),
        )
        cls.no_incumbent_agh = run_agh(
            infeasible_instance,
            cls.config,
            random_seed=41,
        )
        if (
            cls.no_incumbent_agh.completion_status
            is not AGHCompletionStatus.NO_FEASIBLE_INCUMBENT
        ):
            raise AssertionError("fixture must produce no valid AGH incumbent")

    def _convert(self, source):
        return stage2_fixed_deployment_from_stage1(source, self.problem_data)

    def test_valid_pdm_result_produces_canonical_fixed_deployment(self) -> None:
        evidence = self._convert(self.pdm_result)

        self.assertIsInstance(evidence, Stage1ToStage2DeploymentEvidence)
        self.assertIsInstance(evidence.fixed_deployment, Stage2FixedDeployment)
        self.assertIs(evidence.method, Stage1Method.P_DM)
        self.assertIs(evidence.source_result, self.pdm_result)
        self.assertIs(evidence.source_identity, self.pdm_result.identity)
        self.assertIs(evidence.source_final_placement, self.pdm_result.solution)
        self.assertIs(evidence.pdm_problem_data, self.problem_data)

    def test_valid_gh_result_produces_same_boundary_type(self) -> None:
        evidence = self._convert(self.gh_result)

        self.assertIsInstance(evidence.fixed_deployment, Stage2FixedDeployment)
        self.assertIs(evidence.method, Stage1Method.GH)
        self.assertIs(evidence.source_result, self.gh_result)
        self.assertIs(evidence.source_identity, self.gh_result.identity)
        self.assertIs(
            evidence.source_final_placement,
            self.gh_result.placement_decisions,
        )

    def test_valid_agh_result_produces_same_boundary_type(self) -> None:
        evidence = self._convert(self.agh_result)

        self.assertIsInstance(evidence.fixed_deployment, Stage2FixedDeployment)
        self.assertIs(evidence.method, Stage1Method.AGH)
        self.assertIs(evidence.source_result, self.agh_result)
        self.assertIs(
            evidence.source_identity,
            self.agh_result.final_incumbent.gh_result.identity,
        )
        self.assertIs(
            evidence.source_final_placement,
            self.agh_result.final_placement,
        )

    def test_exact_y_z_w_values_and_lattice_order_are_preserved(self) -> None:
        lattices = self.problem_data.variable_lattices
        for source in (self.pdm_result, self.gh_result, self.agh_result):
            evidence = self._convert(source)
            placement = evidence.source_final_placement
            fixed = evidence.fixed_deployment
            self.assertEqual(
                fixed.admission_indicators, placement.admission_indicators
            )
            self.assertEqual(
                fixed.configuration_selectors,
                placement.configuration_selectors,
            )
            self.assertEqual(fixed.gpu_counts, placement.gpu_counts)
            self.assertIsNot(
                fixed.admission_indicators, placement.admission_indicators
            )
            self.assertIsNot(
                fixed.configuration_selectors,
                placement.configuration_selectors,
            )
            self.assertIsNot(fixed.gpu_counts, placement.gpu_counts)
            self.assertEqual(tuple(fixed.admission_indicators), lattices.route_keys)
            self.assertEqual(
                tuple(fixed.configuration_selectors),
                lattices.configuration_keys,
            )
            self.assertEqual(tuple(fixed.gpu_counts), lattices.model_tier_keys)

    def test_equivalent_stage1_results_produce_equivalent_fixed_content(self) -> None:
        fixed_deployments = tuple(
            self._convert(source).fixed_deployment
            for source in (self.pdm_result, self.gh_result, self.agh_result)
        )

        self.assertEqual(fixed_deployments[0], fixed_deployments[1])
        self.assertEqual(fixed_deployments[1], fixed_deployments[2])

    def test_fixed_boundary_has_only_z_w_y_and_no_x_u_or_q(self) -> None:
        fixed = self._convert(self.gh_result).fixed_deployment

        self.assertEqual(
            tuple(field.name for field in fields(Stage2FixedDeployment)),
            (
                "admission_indicators",
                "configuration_selectors",
                "gpu_counts",
            ),
        )
        for forbidden in (
            "routing_fractions",
            "unmet_fractions",
            "deployment_indicators",
        ):
            self.assertFalse(hasattr(fixed, forbidden))

    def test_source_and_resulting_evidence_remain_immutable(self) -> None:
        source_before = self.agh_result
        evidence = self._convert(self.agh_result)
        fixed = evidence.fixed_deployment

        self.assertEqual(self.agh_result, source_before)
        self.assertIs(evidence.source_result, self.agh_result)
        with patch.object(
            adapter_module,
            "_extract_accepted_source",
            side_effect=AssertionError("reading evidence must not revalidate the source"),
        ):
            self.assertIs(
                evidence.source_identity,
                self.agh_result.final_incumbent.gh_result.identity,
            )
            self.assertIs(evidence.source_final_placement, self.agh_result.final_placement)
        with self.assertRaises(FrozenInstanceError):
            evidence.method = Stage1Method.GH
        with self.assertRaises(FrozenInstanceError):
            fixed.gpu_counts = {}
        with self.assertRaises(TypeError):
            fixed.gpu_counts[next(iter(fixed.gpu_counts))] = 0

    def test_repeated_conversion_is_deterministic(self) -> None:
        first = self._convert(self.agh_result)
        second = self._convert(self.agh_result)

        self.assertEqual(first, second)
        self.assertIs(first.source_result, second.source_result)
        self.assertIs(
            first.source_final_placement,
            second.source_final_placement,
        )

    def test_unaccepted_pdm_result_cannot_produce_deployment(self) -> None:
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

        with self.assertRaises(Stage1ToStage2AdapterError) as caught:
            self._convert(unaccepted)
        self.assertIs(
            caught.exception.reason,
            Stage1ToStage2FailureReason.STAGE1_RESULT_NOT_ACCEPTED,
        )

    def test_agh_no_valid_incumbent_cannot_produce_deployment(self) -> None:
        with self.assertRaises(Stage1ToStage2AdapterError) as caught:
            self._convert(self.no_incumbent_agh)
        self.assertIs(
            caught.exception.reason,
            Stage1ToStage2FailureReason.NO_VALID_AGH_INCUMBENT,
        )

    def test_structurally_incompatible_result_is_rejected_without_inference(self) -> None:
        routing = replace(
            self.pdm_result.solution.routing_decisions,
            admission_indicators={},
        )
        parallelism = replace(
            self.pdm_result.solution.parallelism_decisions,
            routing_decisions=routing,
        )
        incompatible = replace(
            self.pdm_result,
            solution=replace(
                self.pdm_result.solution,
                parallelism_decisions=parallelism,
            ),
        )

        with self.assertRaises(Stage1ToStage2AdapterError) as caught:
            self._convert(incompatible)
        self.assertIs(
            caught.exception.reason,
            Stage1ToStage2FailureReason.STRUCTURALLY_INCOMPATIBLE_RESULT,
        )

    def test_invalid_fixed_values_use_existing_stage2_validation(self) -> None:
        selectors = dict(self.pdm_result.solution.configuration_selectors)
        selectors[next(iter(selectors))] = 2
        parallelism = replace(
            self.pdm_result.solution.parallelism_decisions,
            configuration_selectors=selectors,
        )
        invalid = replace(
            self.pdm_result,
            solution=replace(
                self.pdm_result.solution,
                parallelism_decisions=parallelism,
            ),
        )

        with self.assertRaises(Stage1ToStage2AdapterError) as caught:
            self._convert(invalid)
        self.assertIs(
            caught.exception.reason,
            Stage1ToStage2FailureReason.INVALID_FIXED_DEPLOYMENT,
        )
        self.assertIsNotNone(caught.exception.__cause__)

    def test_shared_problem_identity_mismatch_is_rejected(self) -> None:
        other_data = PdmProblemData(replace(self.instance, id="other"))

        with self.assertRaises(Stage1ToStage2AdapterError) as caught:
            stage2_fixed_deployment_from_stage1(self.gh_result, other_data)
        self.assertIs(
            caught.exception.reason,
            Stage1ToStage2FailureReason.SOURCE_IDENTITY_MISMATCH,
        )

    def test_unsupported_result_type_has_narrow_typed_failure(self) -> None:
        with self.assertRaises(Stage1ToStage2AdapterError) as caught:
            self._convert(object())
        self.assertIs(
            caught.exception.reason,
            Stage1ToStage2FailureReason.UNSUPPORTED_RESULT_TYPE,
        )

    def test_conversion_invokes_no_stage_runner_or_stage1_algorithm(self) -> None:
        forbidden = AssertionError("adapter attempted execution")
        with patch.object(
            stage2_run_module, "run_stage2", side_effect=forbidden
        ), patch.object(
            pdm_run_module, "execute_and_record_pdm_run", side_effect=forbidden
        ), patch.object(
            gh_module, "run_gh", side_effect=forbidden
        ), patch.object(
            agh_module, "run_agh", side_effect=forbidden
        ):
            for source in (self.pdm_result, self.gh_result, self.agh_result):
                self.assertIsInstance(
                    self._convert(source).fixed_deployment,
                    Stage2FixedDeployment,
                )

    def test_adapter_evidence_contains_no_scenario_or_experiment_state(self) -> None:
        evidence_fields = {
            field.name for field in fields(Stage1ToStage2DeploymentEvidence)
        }

        self.assertNotIn("realized_scenario", evidence_fields)
        self.assertNotIn("scenario", evidence_fields)
        self.assertFalse(hasattr(adapter_module, "Stage2RealizedScenario"))


if __name__ == "__main__":
    unittest.main()
