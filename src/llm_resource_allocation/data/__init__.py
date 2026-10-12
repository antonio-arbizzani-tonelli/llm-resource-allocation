"""Synthetic input fixtures for placement and Stage-2 verification."""

from .tiny_instances import (
    make_coherent_tiny_instance,
    make_heterogeneous_solve_tiny_instance,
    make_heterogeneous_tiny_instance,
    make_minimal_tiny_instance,
    make_parallelism_tradeoff_tiny_instance,
)
from .stage2_tiny_cases import (
    make_stage2_capacity_limited_case,
    make_stage2_delay_stress_pair,
    make_stage2_fully_served_case,
    make_stage2_two_route_case,
)


__all__ = [
    "make_coherent_tiny_instance",
    "make_heterogeneous_solve_tiny_instance",
    "make_heterogeneous_tiny_instance",
    "make_minimal_tiny_instance",
    "make_parallelism_tradeoff_tiny_instance",
    "make_stage2_capacity_limited_case",
    "make_stage2_delay_stress_pair",
    "make_stage2_fully_served_case",
    "make_stage2_two_route_case",
]
