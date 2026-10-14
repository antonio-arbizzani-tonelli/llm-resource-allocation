"""Compare solver objectives with independently recomputed values."""

from dataclasses import dataclass
from math import isfinite
from numbers import Real


# Implementation choice (D-0025), separate from solver feasibility tolerances.
DEFAULT_OBJECTIVE_COMPARISON_ABSOLUTE_TOLERANCE = 1e-8


@dataclass(frozen=True, slots=True)
class ObjectiveComparison:
    """Compare observed objectives with an optional scale-aware threshold."""

    solver_objective: float
    independent_objective: float
    absolute_tolerance: float = DEFAULT_OBJECTIVE_COMPARISON_ABSOLUTE_TOLERANCE
    relative_tolerance: float = 0.0

    def __post_init__(self) -> None:
        """Require finite values and a non-negative tolerance."""

        for name in (
            "solver_objective",
            "independent_objective",
            "absolute_tolerance",
            "relative_tolerance",
        ):
            object.__setattr__(self, name, _finite_real(name, getattr(self, name)))
        if self.absolute_tolerance < 0.0:
            raise ValueError("absolute_tolerance must be non-negative")
        if self.relative_tolerance < 0.0:
            raise ValueError("relative_tolerance must be non-negative")
        if not isfinite(self.applied_tolerance):
            raise ValueError("applied objective tolerance must be finite")

    @property
    def absolute_difference(self) -> float:
        """Return |solver_objective - independent_objective|."""

        return abs(self.solver_objective - self.independent_objective)

    @property
    def agrees(self) -> bool:
        """Check the inclusive threshold; relative zero keeps the old policy."""

        return self.absolute_difference <= self.applied_tolerance

    @property
    def applied_tolerance(self) -> float:
        """Return max(abs_tol, rel_tol * max(|solver|, |independent|))."""

        return max(
            self.absolute_tolerance,
            self.relative_tolerance
            * max(abs(self.solver_objective), abs(self.independent_objective)),
        )


def _finite_real(name: str, value: object) -> float:
    """Convert a finite real number to float; reject booleans."""

    if (
        isinstance(value, bool)
        or not isinstance(value, Real)
        or not isfinite(float(value))
    ):
        raise ValueError(f"{name} must be a finite real number")
    return float(value)
