"""Hand-derived input tests for the controlled multidimensional scaling family."""

from dataclasses import replace
import unittest

from llm_resource_allocation.data.scaling_experiment_instances import (
    make_scaling_experiment_case,
)
from llm_resource_allocation.data.tiny_instances import make_heterogeneous_tiny_instance
from llm_resource_allocation.domain.validation import validate_problem_instance


class ScalingExperimentInstanceTests(unittest.TestCase):
    def test_base_preserves_every_source_value(self) -> None:
        base = make_heterogeneous_tiny_instance()
        case = make_scaling_experiment_case(2, 2, 2)
        self.assertEqual(replace(case.instance, id=base.id), base)
        self.assertEqual(case.case_id, "scaling_2x2x2")
        self.assertEqual(case.family, "multidimensional_scaling")

    def test_planned_dimensions_and_exact_coefficient_coverage(self) -> None:
        for dimensions in ((2, 2, 2), (4, 4, 5), (6, 6, 10), (10, 10, 10)):
            with self.subTest(dimensions=dimensions):
                instance = make_scaling_experiment_case(*dimensions).instance
                self.assertEqual(instance.dimensions, dimensions)
                validate_problem_instance(instance)
                self.assertEqual(len(instance.base_error_rate), dimensions[0] * dimensions[1])
                for field in (
                    "compute_delay_seconds_per_token",
                    "communication_delay_seconds_per_token",
                    "compute_gflop_per_token",
                    "kv_cache_residency_seconds",
                ):
                    self.assertEqual(
                        len(getattr(instance, field)),
                        dimensions[0] * dimensions[1] * dimensions[2],
                    )

    def test_hand_derived_intermediate_model_and_tier_attributes(self) -> None:
        instance = make_scaling_experiment_case(2, 3, 3).instance
        model = instance.models[2]
        tier = instance.gpu_tiers[2]
        self.assertEqual(model.id, "m_interpolated_1_2")
        self.assertEqual(model.weight_gb, 4.0)
        self.assertAlmostEqual(model.kv_cache_gb_per_token, 0.0000015)
        self.assertEqual(tier.id, "gpu_interpolated_1_2")
        self.assertEqual(tier.memory_capacity_gb, 16.0)
        self.assertEqual(tier.compute_throughput_tflops, 25.0)
        self.assertEqual(tier.hourly_rental_usd, 1.25)
        self.assertEqual(tier.memory_bandwidth_gb_per_second, 200.0)
        self.assertEqual(tier.quantization_latency_scale, 0.75)
        self.assertAlmostEqual(tier.quantization_error_multiplier, 1.075)
        self.assertEqual(tier.tensor_parallel_degrees, (1, 2))
        self.assertEqual(tier.pipeline_parallel_depths, (1, 2))
        for query, error, compute, residency in (
            ("q_short", 0.045, 0.15, 1.125),
            ("q_long", 0.035, 0.18, 2.25),
        ):
            pair = (query, model.id)
            triple = (query, model.id, tier.id)
            self.assertAlmostEqual(instance.base_error_rate[pair], error)
            self.assertAlmostEqual(instance.compute_delay_seconds_per_token[triple], compute)
            self.assertAlmostEqual(instance.communication_delay_seconds_per_token[triple], 0.01875)
            self.assertAlmostEqual(instance.compute_gflop_per_token[triple], 3.0)
            self.assertAlmostEqual(instance.kv_cache_residency_seconds[triple], residency)

    def test_hand_derived_bilinear_cells_and_errors(self) -> None:
        instance = make_scaling_experiment_case(2, 4, 3).instance
        # Model coordinate 1/4, tier coordinate 1/2. At budget/fast the
        # short compute delays are .15/.075, hence the interpolated .1125.
        model = "m_interpolated_1_4"
        tier = "gpu_interpolated_1_2"
        for query, error, compute, communication, operations, residency in (
            ("q_short", 0.0525, 0.1125, 0.016875, 2.25, 0.9375),
            ("q_long", 0.0425, 0.135, 0.016875, 2.25, 1.875),
        ):
            pair = (query, model)
            triple = (query, model, tier)
            self.assertAlmostEqual(instance.base_error_rate[pair], error)
            self.assertAlmostEqual(instance.compute_delay_seconds_per_token[triple], compute)
            self.assertAlmostEqual(instance.communication_delay_seconds_per_token[triple], communication)
            self.assertAlmostEqual(instance.compute_gflop_per_token[triple], operations)
            self.assertAlmostEqual(instance.kv_cache_residency_seconds[triple], residency)

    def test_larger_option_menu_preserves_all_previous_alternatives_exactly(self) -> None:
        smaller = make_scaling_experiment_case(4, 4, 5).instance
        larger = make_scaling_experiment_case(4, 10, 10).instance
        self.assertEqual(larger.models[:4], smaller.models)
        self.assertEqual(larger.gpu_tiers[:5], smaller.gpu_tiers)
        self.assertEqual(larger.queries, smaller.queries)
        self.assertEqual(larger.cost_budget_usd, smaller.cost_budget_usd)
        self.assertEqual(larger.storage_capacity_gb, smaller.storage_capacity_gb)
        for field in (
            "base_error_rate", "compute_delay_seconds_per_token",
            "communication_delay_seconds_per_token", "compute_gflop_per_token",
            "kv_cache_residency_seconds",
        ):
            smaller_table = getattr(smaller, field)
            larger_table = getattr(larger, field)
            for key, value in smaller_table.items():
                self.assertEqual(larger_table[key], value)

    def test_query_scaling_and_stress_interventions_are_separate(self) -> None:
        base = make_heterogeneous_tiny_instance()
        nominal = make_scaling_experiment_case(4, 2, 2).instance
        stressed = make_scaling_experiment_case(
            4, 2, 2, load_multiplier=100, delay_slo_multiplier=0.1,
            budget_multiplier=0.25,
        ).instance
        self.assertEqual(nominal.query_ids, ("q_short", "q_long", "q_short_0003", "q_long_0004"))
        self.assertEqual(nominal.cost_budget_usd, 100.0)
        self.assertEqual(nominal.storage_capacity_gb, 400.0)
        self.assertEqual(stressed.cost_budget_usd, 25.0)
        self.assertEqual(stressed.storage_capacity_gb, 400.0)
        for index, query in enumerate(stressed.queries):
            source = base.queries[index % 2]
            self.assertEqual(query.arrival_rate_per_hour, source.arrival_rate_per_hour * 100)
            self.assertEqual(query.delay_slo_seconds, source.delay_slo_seconds * 0.1)
            self.assertEqual(query.max_unmet_fraction, source.max_unmet_fraction)
            self.assertEqual(
                replace(query, id=source.id, arrival_rate_per_hour=source.arrival_rate_per_hour,
                        delay_slo_seconds=source.delay_slo_seconds), source,
            )
        self.assertEqual(stressed.base_error_rate, nominal.base_error_rate)
        self.assertEqual(stressed.compute_delay_seconds_per_token, nominal.compute_delay_seconds_per_token)
        self.assertEqual(stressed.horizon_hours, 2.0)

    def test_provenance_determinism_and_immutable_coefficients(self) -> None:
        case = make_scaling_experiment_case(6, 6, 10, load_multiplier=100)
        self.assertEqual(case, make_scaling_experiment_case(6, 6, 10, load_multiplier=100))
        self.assertEqual(case.provenance["classification"], "ASSUMED")
        self.assertEqual(case.provenance["model_coordinates"], "0,1,1/2,1/4,3/4,1/8")
        self.assertEqual(case.provenance["gpu_tier_coordinates"], "0,1,1/2,1/4,3/4,1/8,3/8,5/8,7/8,1/16")
        self.assertEqual(case.provenance["load_multiplier"], 100)
        self.assertEqual(case.provenance["capacity_multiplier"], 3.0)
        with self.assertRaises(TypeError):
            case.provenance["load_multiplier"] = 1
        with self.assertRaises(TypeError):
            case.instance.base_error_rate[("q_short", "m_compact")] = 0

    def test_invalid_dimensions_and_interventions_are_rejected(self) -> None:
        for value in (0, 1, -1, True, 2.0, "2"):
            for index in range(3):
                dimensions = [2, 2, 2]
                dimensions[index] = value
                with self.subTest(dimensions=dimensions), self.assertRaises(ValueError):
                    make_scaling_experiment_case(*dimensions)
        for name in ("load_multiplier", "delay_slo_multiplier", "budget_multiplier"):
            for value in (0, -1, True, float("nan"), float("inf"), "1"):
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    make_scaling_experiment_case(2, 2, 2, **{name: value})


if __name__ == "__main__":
    unittest.main()
