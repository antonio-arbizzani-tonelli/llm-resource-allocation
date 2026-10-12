"""Milestone-8.3 cross-method Stage-1 to Stage-2 closure evidence."""

import unittest
from dataclasses import dataclass, fields, replace
from unittest.mock import patch

import llm_resource_allocation.algorithms.agh as agh_module
import llm_resource_allocation.algorithms.gh as gh_module
import llm_resource_allocation.optimization.pdm_run as pdm_run_module
import llm_resource_allocation.optimization.stage2_integration as integration_module
from llm_resource_allocation.algorithms import (
    AGHResult,
    GHPhase1Config,
    GHResult,
    run_agh,
    run_gh,
)
from llm_resource_allocation.data import (
    make_minimal_tiny_instance,
    make_stage2_capacity_limited_case,
)
from llm_resource_allocation.math.objective import PaperVersion
from llm_resource_allocation.optimization.pdm_run import (
    PdmRunRecord,
    execute_and_record_pdm_run,
)
from llm_resource_allocation.optimization.problem_data import (
    PdmProblemData,
)
from llm_resource_allocation.optimization.solver import (
    SolverBackend,
    SolverConfig,
    SolverResult,
    SolverStatus,
)
from llm_resource_allocation.optimization.stage2_adapter import (
    Stage1Method,
    Stage1ToStage2FailureReason,
)
from llm_resource_allocation.optimization.stage2_integration import (
    Stage1Stage2EvaluationResult,
    Stage1Stage2EvaluationStatus,
    evaluate_stage1_result_under_scenario,
)
from llm_resource_allocation.optimization.stage2_problem_data import (
    Stage2FixedDeployment,
    Stage2ProblemData,
    Stage2RealizedScenario,
)
from llm_resource_allocation.validation.stage2 import Stage2ValidationReport


@dataclass(frozen=True, slots=True)
class _CrossMethodReferenceCase:
    """Retain one common problem/version/scenario and its three evaluations."""

    pdm_problem_data: PdmProblemData
    paper_version: PaperVersion
    realized_scenario: Stage2RealizedScenario
    sources: tuple[PdmRunRecord, GHResult, AGHResult]
    evaluations: tuple[
        Stage1Stage2EvaluationResult,
        Stage1Stage2EvaluationResult,
        Stage1Stage2EvaluationResult,
    ]


def _build_cross_method_reference_case() -> _CrossMethodReferenceCase:
    """Use real Stage-1 authorities and one hand-derived realized scenario."""

    instance = make_minimal_tiny_instance()
    pdm_data = PdmProblemData(instance)
    paper_version = PaperVersion.V2
    scenario = make_stage2_capacity_limited_case(
        paper_version
    ).realized_scenario
    config = GHPhase1Config(0.8)
    sources = (
        execute_and_record_pdm_run(
            pdm_data,
            SolverConfig(backend=SolverBackend.HIGHS),
            paper_version,
        ),
        run_gh(instance, config, paper_version=paper_version),
        run_agh(
            instance,
            config,
            random_seed=37,
            paper_version=paper_version,
        ),
    )
    evaluations = tuple(
        evaluate_stage1_result_under_scenario(
            source,
            pdm_data,
            scenario,
            paper_version=paper_version,
            solver_config=SolverConfig(backend=SolverBackend.HIGHS),
        )
        for source in sources
    )
    return _CrossMethodReferenceCase(
        pdm_problem_data=pdm_data,
        paper_version=paper_version,
        realized_scenario=scenario,
        sources=sources,
        evaluations=evaluations,
    )


class Stage2CrossMethodClosureTests(unittest.TestCase):
    """Prove the final common-pipeline invariant without new orchestration."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.case = _build_cross_method_reference_case()

    def test_common_case_has_three_accepted_distinct_sources(self) -> None:
        pdm, gh, agh = self.case.sources
        evaluations = self.case.evaluations

        self.assertIsInstance(pdm, PdmRunRecord)
        self.assertTrue(pdm.accepted_run)
        self.assertTrue(gh.algorithm_completed)
        self.assertTrue(gh.independently_feasible)
        self.assertTrue(agh.completed)
        self.assertEqual(
            tuple(result.stage1_method for result in evaluations),
            (Stage1Method.P_DM, Stage1Method.GH, Stage1Method.AGH),
        )
        self.assertEqual(len({id(source) for source in self.case.sources}), 3)
        self.assertEqual(
            len(
                {
                    id(result.adapter_evidence.source_identity)
                    for result in evaluations
                }
            ),
            3,
        )

    def test_all_paths_share_problem_version_and_exact_scenario(self) -> None:
        for result in self.case.evaluations:
            self.assertTrue(result.successful)
            self.assertIs(
                result.pdm_problem_data,
                self.case.pdm_problem_data,
            )
            self.assertIs(result.paper_version, self.case.paper_version)
            self.assertIs(
                result.realized_scenario,
                self.case.realized_scenario,
            )
            self.assertIs(
                result.stage2_problem_data.realized_scenario,
                self.case.realized_scenario,
            )

    def test_fixed_deployment_and_problem_data_are_equivalent(self) -> None:
        baseline = self.case.evaluations[0]
        baseline_data = baseline.stage2_problem_data
        baseline_fixed = baseline.fixed_deployment

        self.assertIsInstance(baseline_fixed, Stage2FixedDeployment)
        self.assertIsInstance(baseline_data, Stage2ProblemData)
        for result in self.case.evaluations[1:]:
            fixed = result.fixed_deployment
            data = result.stage2_problem_data
            self.assertEqual(fixed, baseline_fixed)
            self.assertEqual(data, baseline_data)
            self.assertEqual(
                data.derived_deployment_indicators,
                baseline_data.derived_deployment_indicators,
            )
            self.assertEqual(data.routing_keys, baseline_data.routing_keys)
            self.assertEqual(data.unmet_keys, baseline_data.unmet_keys)

    def test_stage1_x_u_remain_source_only_and_stage2_reoptimizes_them(self) -> None:
        route = self.case.pdm_problem_data.variable_lattices.route_keys[0]
        query_id = self.case.pdm_problem_data.variable_lattices.unmet_keys[0]
        fixed_field_names = tuple(
            descriptor.name for descriptor in fields(Stage2FixedDeployment)
        )

        self.assertEqual(
            fixed_field_names,
            ("admission_indicators", "configuration_selectors", "gpu_counts"),
        )
        for result in self.case.evaluations:
            source = result.source_final_placement
            operational = result.stage2_run_record.solution
            self.assertEqual(source.routing_fractions[route], 1.0)
            self.assertEqual(source.unmet_fractions[query_id], 0.0)
            self.assertEqual(operational.routing_fractions[route], 0.8)
            self.assertEqual(operational.unmet_fractions[query_id], 0.2)
            self.assertIsNot(
                operational.routing_fractions,
                source.routing_fractions,
            )
            self.assertIsNot(
                operational.unmet_fractions,
                source.unmet_fractions,
            )

    def test_stage2_x_u_are_equivalent_under_existing_transport_tolerance(self) -> None:
        baseline = self.case.evaluations[0].stage2_run_record
        for result in self.case.evaluations[1:]:
            record = result.stage2_run_record
            tolerance = max(
                baseline.scientific_evidence.normalization_tolerances.bound_clipping,
                record.scientific_evidence.normalization_tolerances.bound_clipping,
            )
            for key, expected in baseline.solution.routing_fractions.items():
                self.assertLessEqual(
                    abs(record.solution.routing_fractions[key] - expected),
                    tolerance,
                )
            for key, expected in baseline.solution.unmet_fractions.items():
                self.assertLessEqual(
                    abs(record.solution.unmet_fractions[key] - expected),
                    tolerance,
                )

    def test_objective_c3_and_independent_validation_are_equivalent(self) -> None:
        baseline = self.case.evaluations[0].stage2_run_record
        baseline_breakdown = baseline.scientific_evidence.objective_breakdown

        for result in self.case.evaluations:
            record = result.stage2_run_record
            report = record.scientific_evidence.validation_report
            comparison = record.scientific_evidence.objective_comparison
            breakdown = record.scientific_evidence.objective_breakdown
            self.assertIsInstance(report, Stage2ValidationReport)
            self.assertTrue(report.is_feasible)
            self.assertEqual(report.violated_families, ())
            self.assertLessEqual(
                abs(
                    breakdown.operational_objective
                    - baseline_breakdown.operational_objective
                ),
                comparison.absolute_tolerance,
            )
            self.assertEqual(
                breakdown.realized_data_storage_cost,
                baseline_breakdown.realized_data_storage_cost,
            )
            self.assertLessEqual(
                abs(
                    record.reported_variable_cost
                    - baseline.reported_variable_cost
                ),
                comparison.absolute_tolerance,
            )

    def test_solver_and_scientific_evidence_remain_separate(self) -> None:
        for result in self.case.evaluations:
            record = result.stage2_run_record
            solver_result = record.solver_evidence.result
            report = record.scientific_evidence.validation_report
            comparison = record.scientific_evidence.objective_comparison
            self.assertIsInstance(solver_result, SolverResult)
            self.assertIs(solver_result.status, SolverStatus.OPTIMAL)
            self.assertIsNot(solver_result, report)
            self.assertTrue(record.independently_feasible)
            self.assertTrue(record.objective_agrees)
            self.assertEqual(
                solver_result.objective_value,
                comparison.solver_objective,
            )
            self.assertEqual(
                record.operational_objective,
                comparison.independent_objective,
            )

    def test_failed_source_is_isolated_without_fallback_or_repair(self) -> None:
        pdm_source = self.case.sources[0]
        solver_objective = (
            pdm_source.scientific_evidence.objective_comparison.independent_objective
            + 1.0
        )
        comparison = replace(
            pdm_source.scientific_evidence.objective_comparison,
            solver_objective=solver_objective,
            absolute_tolerance=0.0,
        )
        invalid_source = replace(
            pdm_source,
            scientific_evidence=replace(
                pdm_source.scientific_evidence,
                objective_comparison=comparison,
            ),
            solver_evidence=replace(
                pdm_source.solver_evidence,
                result=replace(
                    pdm_source.solver_evidence.result,
                    objective_value=solver_objective,
                ),
            ),
        )
        sources_before = self.case.sources
        data_before = self.case.pdm_problem_data
        scenario_before = self.case.realized_scenario
        forbidden = AssertionError("failed source triggered fallback or execution")

        with patch.object(
            integration_module.Stage2ProblemData,
            "__init__",
            autospec=True,
            side_effect=forbidden,
        ) as builder, patch.object(
            integration_module,
            "run_stage2",
            side_effect=forbidden,
        ) as runner, patch.object(
            pdm_run_module,
            "execute_and_record_pdm_run",
            side_effect=forbidden,
        ), patch.object(gh_module, "run_gh", side_effect=forbidden), patch.object(
            agh_module,
            "run_agh",
            side_effect=forbidden,
        ):
            rejected = evaluate_stage1_result_under_scenario(
                invalid_source,
                self.case.pdm_problem_data,
                self.case.realized_scenario,
                paper_version=self.case.paper_version,
                solver_config=SolverConfig(backend=SolverBackend.HIGHS),
            )

        self.assertIs(
            rejected.status,
            Stage1Stage2EvaluationStatus.STAGE1_SOURCE_REJECTED,
        )
        self.assertIs(rejected.source_result, invalid_source)
        self.assertIsNone(rejected.adapter_evidence)
        self.assertIsNone(rejected.stage2_problem_data)
        self.assertIsNone(rejected.stage2_run_record)
        self.assertIs(
            rejected.failure.adapter_reason,
            Stage1ToStage2FailureReason.STAGE1_RESULT_NOT_ACCEPTED,
        )
        self.assertFalse(invalid_source.accepted_run)
        builder.assert_not_called()
        runner.assert_not_called()
        self.assertEqual(self.case.sources, sources_before)
        self.assertIs(self.case.pdm_problem_data, data_before)
        self.assertIs(self.case.realized_scenario, scenario_before)

    def test_repeated_cross_method_evaluations_are_scientifically_deterministic(
        self,
    ) -> None:
        for source, expected in zip(
            self.case.sources,
            self.case.evaluations,
            strict=True,
        ):
            repeated = evaluate_stage1_result_under_scenario(
                source,
                self.case.pdm_problem_data,
                self.case.realized_scenario,
                paper_version=self.case.paper_version,
                solver_config=SolverConfig(backend=SolverBackend.HIGHS),
            )
            self.assertIs(repeated.status, expected.status)
            self.assertIs(repeated.source_result, expected.source_result)
            self.assertEqual(repeated.fixed_deployment, expected.fixed_deployment)
            self.assertEqual(
                repeated.stage2_run_record.solution,
                expected.stage2_run_record.solution,
            )
            self.assertEqual(
                repeated.stage2_run_record.scientific_evidence,
                expected.stage2_run_record.scientific_evidence,
            )
            self.assertEqual(
                repeated.stage2_run_record.solver_evidence.result.objective_value,
                expected.stage2_run_record.solver_evidence.result.objective_value,
            )


if __name__ == "__main__":
    unittest.main()
