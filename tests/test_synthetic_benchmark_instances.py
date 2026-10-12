"""Hand-check controlled synthetic input scaling, identity, and provenance."""

from dataclasses import FrozenInstanceError, replace
import unittest

from llm_resource_allocation.data.synthetic_benchmark_instances import (
    SyntheticBenchmarkCase,
    make_synthetic_benchmark_cases,
)
from llm_resource_allocation.data.tiny_instances import (
    make_heterogeneous_tiny_instance,
    make_minimal_tiny_instance,
    make_parallelism_tradeoff_tiny_instance,
)
from llm_resource_allocation.domain.validation import validate_problem_instance


class SyntheticBenchmarkInstanceTests(unittest.TestCase):
    """Verify assumptions without running or depending on an allocation method."""

    def test_default_dimensions_order_and_original_fixtures(self) -> None:
        cases = make_synthetic_benchmark_cases()
        self.assertEqual(
            tuple(case.case_id for case in cases),
            (
                "minimal", "parallelism_tradeoff", "heterogeneous",
                "query_scaling_2", "query_scaling_4", "query_scaling_8",
                "query_scaling_16",
            ),
        )
        self.assertEqual(
            tuple(case.instance.dimensions for case in cases),
            ((1, 1, 1), (1, 1, 1), (2, 2, 2), (2, 2, 2),
             (4, 2, 2), (8, 2, 2), (16, 2, 2)),
        )
        self.assertEqual(cases[0].instance, make_minimal_tiny_instance())
        self.assertEqual(cases[1].instance, make_parallelism_tradeoff_tiny_instance())
        self.assertEqual(cases[2].instance, make_heterogeneous_tiny_instance())
        for case in cases:
            validate_problem_instance(case.instance)

    def test_scaling_clones_preserve_all_query_values_and_lattices(self) -> None:
        base = make_heterogeneous_tiny_instance()
        instance = make_synthetic_benchmark_cases((3,))[3].instance
        self.assertEqual(instance.query_ids, ("q_short_0001", "q_long_0002", "q_short_0003"))
        self.assertEqual(instance.model_ids, ("m_compact", "m_accurate"))
        self.assertEqual(instance.gpu_tier_ids, ("gpu_budget_int8", "gpu_fast_fp16"))
        for index, query in enumerate(instance.queries):
            source = base.queries[index % 2]
            self.assertEqual(replace(query, id=source.id), source)
        self.assertEqual(instance.models, base.models)
        self.assertEqual(instance.gpu_tiers, base.gpu_tiers)
        self.assertEqual(len(instance.base_error_rate), 6)
        self.assertEqual(len(instance.compute_delay_seconds_per_token), 12)
        self.assertEqual(instance.cost_budget_usd, 75.0)
        self.assertEqual(instance.storage_capacity_gb, 300.0)
        self.assertEqual(instance.horizon_hours, 2.0)
        self.assertEqual(instance.compute_utilization, 0.9)
        self.assertEqual(instance.storage_price_usd_per_gb_hour, 0.001)
        self.assertEqual(instance.seconds_per_hour, 3600.0)

    def test_all_cloned_coefficients_match_hand_written_tables(self) -> None:
        instance = make_synthetic_benchmark_cases((4,))[3].instance
        # Each row follows (compact/budget, compact/fast,
        # accurate/budget, accurate/fast) for one source query type.
        errors = ((0.06, 0.03), (0.05, 0.02))
        tables = {
            "compute_delay_seconds_per_token": (
                (0.10, 0.05, 0.30, 0.15), (0.12, 0.06, 0.36, 0.18)
            ),
            "communication_delay_seconds_per_token": (
                (0.020, 0.010, 0.030, 0.015), (0.020, 0.010, 0.030, 0.015)
            ),
            "compute_gflop_per_token": (
                (1.0, 2.0, 3.0, 6.0), (1.0, 2.0, 3.0, 6.0)
            ),
            "kv_cache_residency_seconds": (
                (1.0, 0.5, 2.0, 1.0), (2.0, 1.0, 4.0, 2.0)
            ),
        }
        for index, query_id in enumerate(instance.query_ids):
            for model_index, model_id in enumerate(instance.model_ids):
                self.assertEqual(
                    instance.base_error_rate[(query_id, model_id)],
                    errors[index % 2][model_index],
                )
                for tier_index, tier_id in enumerate(instance.gpu_tier_ids):
                    for name, rows in tables.items():
                        self.assertEqual(
                            getattr(instance, name)[(query_id, model_id, tier_id)],
                            rows[index % 2][2 * model_index + tier_index],
                        )

    def test_caller_order_single_query_and_empty_scaling_are_supported(self) -> None:
        cases = make_synthetic_benchmark_cases((8, 1, 4))
        self.assertEqual(
            tuple(case.case_id for case in cases[3:]),
            ("query_scaling_8", "query_scaling_1", "query_scaling_4"),
        )
        self.assertEqual(cases[4].instance.dimensions, (1, 2, 2))
        self.assertEqual(cases[4].instance.cost_budget_usd, 25.0)
        self.assertEqual(cases[4].instance.storage_capacity_gb, 100.0)
        self.assertEqual(len(make_synthetic_benchmark_cases(())), 3)

    def test_repeated_generation_and_provenance_are_immutable(self) -> None:
        first = make_synthetic_benchmark_cases((4,))
        self.assertEqual(first, make_synthetic_benchmark_cases((4,)))
        case = first[3]
        self.assertEqual(case.family, "query_scaling")
        self.assertEqual(case.provenance["classification"], "ASSUMED")
        self.assertIn("Synthetic", case.provenance["description"])
        self.assertEqual(case.provenance["source_query_count"], 2)
        self.assertEqual(case.provenance["capacity_multiplier"], 2.0)
        self.assertEqual(case.provenance["cost_budget_usd"], 100.0)
        self.assertEqual(case.provenance["storage_capacity_gb"], 400.0)
        with self.assertRaises(FrozenInstanceError):
            case.case_id = "changed"
        with self.assertRaises(TypeError):
            case.provenance["query_count"] = 99
        with self.assertRaises(TypeError):
            case.instance.base_error_rate[("q_short_0001", "m_compact")] = 0.0
        provenance = {"description": "Synthetic caller-owned values"}
        isolated = SyntheticBenchmarkCase("custom", "verification", case.instance, provenance)
        provenance["description"] = "changed"
        self.assertEqual(isolated.provenance["description"], "Synthetic caller-owned values")

    def test_invalid_counts_are_rejected(self) -> None:
        for counts in ((0,), (-1,), (True,), (False,), (2.0,), ("2",), (2, 2)):
            with self.subTest(counts=counts), self.assertRaises(ValueError):
                make_synthetic_benchmark_cases(counts)


if __name__ == "__main__":
    unittest.main()
