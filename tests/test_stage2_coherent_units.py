"""Hand-derived realized-demand costs and fixed-deployment coherent LP checks."""

from dataclasses import replace
import unittest

from pyomo.environ import Var, value

from llm_resource_allocation.algorithms import GHPhase1Config, run_agh, run_gh
from llm_resource_allocation.data import make_coherent_tiny_instance
from llm_resource_allocation.domain import UnitConvention
from llm_resource_allocation.math.objective import PaperVersion
from llm_resource_allocation.optimization.pdm_run import execute_and_record_pdm_run
from llm_resource_allocation.optimization.problem_data import PdmProblemData
from llm_resource_allocation.optimization.pyomo_stage2 import build_stage2_pyomo_model
from llm_resource_allocation.optimization.solver import SolverBackend, SolverConfig
from llm_resource_allocation.optimization.stage2_extraction import (
    Stage2Solution, stage2_solution_identity,
)
from llm_resource_allocation.optimization.stage2_integration import (
    evaluate_stage1_result_under_scenario,
)
from llm_resource_allocation.optimization.stage2_problem_data import (
    Stage2FixedDeployment, Stage2ProblemData, Stage2RealizedScenario,
)
from llm_resource_allocation.optimization.stage2_run import run_stage2
from llm_resource_allocation.validation.stage2 import validate_stage2_solution


ROUTE = ("q_text", "m_small", "gpu_basic_fp16")
PAIR = ROUTE[1:]
HIGHS = SolverConfig(backend=SolverBackend.HIGHS)


def coherent_problem(*, arrivals=12.0, horizon=3.0, residency=2.0):
    """Nominal load is 600; realized load is 1200 against capacity 600."""

    base = make_coherent_tiny_instance()
    query = replace(
        base.queries[0], arrival_rate_per_hour=6.0,
        input_tokens=60.0, output_tokens=40.0,
        storage_gb_per_token=0.002, delay_slo_seconds=0.1,
        delay_penalty_usd_per_millisecond_query=0.02,
        unmet_penalty_usd_per_hour=100.0, max_unmet_fraction=0.5,
    )
    instance = replace(
        base, id="coherent_stage2_hand_case", queries=(query,),
        models=(replace(base.models[0], weight_gb=4.0),),
        gpu_tiers=(replace(base.gpu_tiers[0],
                           compute_throughput_tflops=5.0 / 27.0,
                           tensor_parallel_degrees=(1,)),),
        compute_gflop_per_token={ROUTE: 1000.0},
        compute_delay_seconds_per_token={ROUTE: 0.001},
        communication_delay_seconds_per_token={ROUTE: 0.0},
        horizon_hours=horizon, data_residency_hours=residency,
        storage_price_usd_per_gb_hour=0.25, cost_budget_usd=200.0,
    )
    pdm_data = PdmProblemData(instance)
    fixed = Stage2FixedDeployment(
        {ROUTE: 1.0}, {(*PAIR, 1, 1): 1.0}, {PAIR: 1.0},
    )
    scenario = Stage2RealizedScenario(
        "realized_load", {"q_text": arrivals}, {ROUTE: 0.001},
        {ROUTE: 0.0}, {ROUTE: 0.05},
    )
    return Stage2ProblemData(pdm_data, fixed, scenario)


def half_served_solution(data):
    return Stage2Solution(
        stage2_solution_identity(data), {ROUTE: 0.5}, {"q_text": 0.5},
    )


class Stage2CoherentUnitsTests(unittest.TestCase):
    def test_model_and_validator_match_realized_arrival_hand_values(self):
        data = coherent_problem()
        model = build_stage2_pyomo_model(data)
        model.x[ROUTE].set_value(0.5)
        model.u["q_text"].set_value(0.5)
        report = validate_stage2_solution(data, half_served_solution(data))
        self.assertTrue(report.is_feasible)
        self.assertIs(report.unit_convention, UnitConvention.COHERENT)
        self.assertEqual(report.data_residency_hours, 2.0)
        # C4=.02 USD/ms/request *50 ms/request *12 requests/h *3 h=36.
        # C5=3 h *100 USD/h *.5=150.
        # C3=3 h *.25 USD/GB/h *2 h *.002 GB/token *100 *12 *.5=1.8.
        costs = report.objective_breakdown
        for expression, actual, expected in (
            (model.delay_penalty, costs.delay_penalty, 36.0),
            (model.unmet_penalty, costs.unmet_demand_penalty, 150.0),
            (model.realized_data_storage_cost, costs.realized_data_storage_cost, 1.8),
            (model.objective, costs.operational_objective, 186.0),
        ):
            self.assertAlmostEqual(value(expression), expected)
            self.assertAlmostEqual(actual, expected)
        self.assertAlmostEqual(costs.reported_variable_cost, 187.8)
        self.assertAlmostEqual(report.compute_capacity_diagnostics[0].required_compute, 600.0)
        self.assertAlmostEqual(report.compute_capacity_diagnostics[0].available_compute, 600.0)
        self.assertEqual(tuple(c.local_name for c in model.component_objects(Var)), ("x", "u"))
        for excluded in ("memory_capacity", "storage_capacity", "budget"):
            self.assertFalse(hasattr(model, excluded))

    def test_realized_arrivals_horizon_and_residency_scale_only_owned_costs(self):
        for arrivals, horizon, residency, c4, c3, c5 in (
            (6.0, 3.0, 2.0, 18.0, 0.9, 150.0),
            (12.0, 6.0, 2.0, 72.0, 3.6, 300.0),
            (12.0, 3.0, 0.0, 36.0, 0.0, 150.0),
            (12.0, 3.0, 4.0, 36.0, 3.6, 150.0),
        ):
            with self.subTest(arrivals=arrivals, horizon=horizon, residency=residency):
                data = coherent_problem(arrivals=arrivals, horizon=horizon, residency=residency)
                report = validate_stage2_solution(data, half_served_solution(data))
                model = build_stage2_pyomo_model(data)
                model.x[ROUTE].set_value(0.5)
                model.u["q_text"].set_value(0.5)
                for actual, expression, expected in (
                    (report.objective_breakdown.delay_penalty, model.delay_penalty, c4),
                    (report.objective_breakdown.realized_data_storage_cost, model.realized_data_storage_cost, c3),
                    (report.objective_breakdown.unmet_demand_penalty, model.unmet_penalty, c5),
                ):
                    self.assertAlmostEqual(actual, expected)
                    self.assertAlmostEqual(value(expression), expected)

    def test_capacity_limited_optimum_is_independently_accepted(self):
        record = run_stage2(coherent_problem(), solver_config=HIGHS)
        self.assertTrue(record.successful)
        self.assertTrue(record.independently_feasible)
        self.assertTrue(record.objective_agrees)
        # 1200*x<=600; serving costs 72*x while dropping costs 300*(1-x).
        self.assertAlmostEqual(record.solution.routing_fractions[ROUTE], 0.5)
        self.assertAlmostEqual(record.solution.unmet_fractions["q_text"], 0.5)
        self.assertAlmostEqual(record.operational_objective, 186.0)

    def test_zero_realized_arrivals_have_no_delay_or_data_cost(self):
        record = run_stage2(coherent_problem(arrivals=0.0), solver_config=HIGHS)
        self.assertTrue(record.successful)
        self.assertAlmostEqual(record.solution.routing_fractions[ROUTE], 1.0)
        self.assertAlmostEqual(record.solution.unmet_fractions["q_text"], 0.0)
        self.assertEqual(record.operational_objective, 0.0)
        self.assertEqual(record.realized_data_storage_cost, 0.0)

    def test_coherent_v1_is_rejected_at_the_problem_boundary(self):
        data = coherent_problem()
        with self.assertRaisesRegex(ValueError, "coherent units require"):
            Stage2ProblemData(data.pdm_problem_data, data.fixed_deployment,
                              data.realized_scenario, PaperVersion.V1)
        with self.assertRaisesRegex(ValueError, "coherent units require"):
            Stage2ProblemData._from_validated_deployment(
                data.pdm_problem_data, data.fixed_deployment,
                data.derived_deployment_indicators, data.realized_scenario, PaperVersion.V1,
            )

    def test_literal_costs_ignore_new_residency_and_arrival_delay_factors(self):
        coherent = coherent_problem()
        literal_instance = replace(coherent.instance, unit_convention=UnitConvention.LITERAL_PAPER)
        data = Stage2ProblemData(PdmProblemData(literal_instance),
                                coherent.fixed_deployment, coherent.realized_scenario)
        model = build_stage2_pyomo_model(data)
        model.x[ROUTE].set_value(0.5)
        model.u["q_text"].set_value(0.5)
        costs = validate_stage2_solution(data, half_served_solution(data)).objective_breakdown
        self.assertEqual(costs.delay_penalty, 0.02 * 0.05)
        self.assertAlmostEqual(costs.realized_data_storage_cost, 0.9)
        self.assertEqual(value(model.delay_penalty), costs.delay_penalty)
        self.assertEqual(value(model.realized_data_storage_cost), costs.realized_data_storage_cost)

    def test_all_accepted_coherent_stage1_methods_share_operational_boundary(self):
        data = coherent_problem()
        instance = data.instance
        config = GHPhase1Config(budget_fraction=0.8)
        sources = (
            execute_and_record_pdm_run(data.pdm_problem_data, HIGHS),
            run_gh(instance, config),
            run_agh(instance, config, random_seed=37),
        )
        for source in sources:
            with self.subTest(method=type(source).__name__):
                evaluation = evaluate_stage1_result_under_scenario(
                    source, data.pdm_problem_data, data.realized_scenario,
                    solver_config=HIGHS,
                )
                self.assertTrue(evaluation.successful)
                self.assertIs(evaluation.source_result, source)
                fixed = evaluation.fixed_deployment
                self.assertEqual(dict(fixed.gpu_counts), {PAIR: 1.0})
                run = evaluation.stage2_run_record
                self.assertTrue(run.independently_feasible)
                self.assertAlmostEqual(run.solution.routing_fractions[ROUTE], 0.5)
                self.assertAlmostEqual(run.solution.unmet_fractions["q_text"], 0.5)
                self.assertAlmostEqual(run.operational_objective, 186.0)


if __name__ == "__main__":
    unittest.main()
