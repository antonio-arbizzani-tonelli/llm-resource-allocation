"""Extract finite Stage-2 values and normalize only their continuous domains.

Raw ``x,u`` transport, bound clipping, and scientific validation are separate.
Returned evidence contains no live Pyomo objects.
"""

from dataclasses import dataclass
from enum import Enum
from math import isfinite
from numbers import Real
from types import MappingProxyType
from typing import Mapping

from llm_resource_allocation.math.objective import PaperVersion

from .extraction import SolutionNormalizationTolerances
from .problem_data import RouteKey
from .stage2_problem_data import Stage2ProblemData


class Stage2VariableFamily(str, Enum):
    """Identify routing ``x`` and unmet demand ``u``."""

    X = "x"
    U = "u"


Stage2SemanticKey = str | RouteKey


class Stage2SolutionExtractionError(ValueError):
    """Base error for incomplete, non-finite, or structurally stale models."""


class Stage2ModelLatticeMismatchError(Stage2SolutionExtractionError):
    """Report missing, unexpected, or reordered Stage-2 variable keys."""

    def __init__(
        self,
        family: Stage2VariableFamily,
        expected_keys: tuple[Stage2SemanticKey, ...],
        actual_keys: tuple[Stage2SemanticKey, ...],
    ) -> None:
        actual_key_set = set(actual_keys)
        expected_key_set = set(expected_keys)
        self.family = family
        self.missing_keys = tuple(
            key for key in expected_keys if key not in actual_key_set
        )
        self.unexpected_keys = tuple(
            key for key in actual_keys if key not in expected_key_set
        )
        self.order_mismatch = (
            not self.missing_keys
            and not self.unexpected_keys
            and actual_keys != expected_keys
        )
        super().__init__(
            f"Pyomo Stage-2 variable family {family.value!r} does not match "
            f"its exact lattice: missing={self.missing_keys!r}, "
            f"unexpected={self.unexpected_keys!r}, "
            f"order_mismatch={self.order_mismatch}"
        )


class Stage2VariableValueExtractionError(Stage2SolutionExtractionError):
    """Report an uninitialized, non-real, or non-finite Pyomo value."""

    def __init__(
        self,
        family: Stage2VariableFamily,
        semantic_key: Stage2SemanticKey,
        raw_value: object,
        reason: str,
    ) -> None:
        self.family = family
        self.semantic_key = semantic_key
        self.raw_value = raw_value
        self.reason = reason
        super().__init__(
            f"Cannot extract Stage-2 {family.value}[{semantic_key!r}]: "
            f"{reason}; raw value={raw_value!r}"
        )


class Stage2SolutionNormalizationError(ValueError):
    """Report a raw Stage-2 value or lattice that cannot be normalized."""

    def __init__(
        self,
        family: Stage2VariableFamily,
        semantic_key: Stage2SemanticKey | None,
        raw_value: object,
        requirement: str,
        tolerance: float | None,
    ) -> None:
        self.family = family
        self.semantic_key = semantic_key
        self.raw_value = raw_value
        self.requirement = requirement
        self.tolerance = tolerance
        tolerance_text = "not applicable" if tolerance is None else repr(tolerance)
        super().__init__(
            f"Cannot normalize Stage-2 {family.value}[{semantic_key!r}] from "
            f"{raw_value!r}: required {requirement}; tolerance={tolerance_text}"
        )


@dataclass(frozen=True, slots=True)
class RawStage2Solution:
    """Store dense read-only ``x,u`` transport values before domain checks."""

    x: Mapping[RouteKey, float]
    u: Mapping[str, float]

    def __post_init__(self) -> None:
        object.__setattr__(self, "x", MappingProxyType(dict(self.x)))
        object.__setattr__(self, "u", MappingProxyType(dict(self.u)))


@dataclass(frozen=True, slots=True)
class Stage2SolutionIdentity:
    """Identify a solution's instance, scenario, paper version, and entity order."""

    instance_id: str
    scenario_id: str
    paper_version: PaperVersion
    query_ids: tuple[str, ...]
    model_ids: tuple[str, ...]
    tier_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Stage2Solution:
    """Store read-only operational decisions pending independent validation."""

    identity: Stage2SolutionIdentity
    routing_fractions: Mapping[RouteKey, float]
    unmet_fractions: Mapping[str, float]

    def __post_init__(self) -> None:
        if not isinstance(self.identity, Stage2SolutionIdentity):
            raise TypeError("identity must be a Stage2SolutionIdentity")
        object.__setattr__(
            self,
            "routing_fractions",
            MappingProxyType(dict(self.routing_fractions)),
        )
        object.__setattr__(
            self,
            "unmet_fractions",
            MappingProxyType(dict(self.unmet_fractions)),
        )


def stage2_solution_identity(
    problem_data: Stage2ProblemData,
) -> Stage2SolutionIdentity:
    """Build the deterministic identity attached to normalized evidence."""

    if not isinstance(problem_data, Stage2ProblemData):
        raise TypeError("problem_data must be a Stage2ProblemData")
    indices = problem_data.pdm_problem_data.index_sets
    return Stage2SolutionIdentity(
        instance_id=problem_data.instance.id,
        scenario_id=problem_data.realized_scenario.id,
        paper_version=problem_data.paper_version,
        query_ids=indices.query_ids,
        model_ids=indices.model_ids,
        tier_ids=indices.tier_ids,
    )


def _family_lattices(
    problem_data: Stage2ProblemData,
) -> tuple[
    tuple[Stage2VariableFamily, tuple[Stage2SemanticKey, ...]], ...
]:
    return (
        (Stage2VariableFamily.X, problem_data.routing_keys),
        (Stage2VariableFamily.U, problem_data.unmet_keys),
    )


def _extract_family(
    model: object,
    family: Stage2VariableFamily,
    expected_keys: tuple[Stage2SemanticKey, ...],
) -> dict[Stage2SemanticKey, float]:
    component = getattr(model, family.value, None)
    if component is None or not hasattr(component, "keys"):
        raise Stage2ModelLatticeMismatchError(family, expected_keys, ())
    actual_keys = tuple(component.keys())
    if actual_keys != expected_keys:
        raise Stage2ModelLatticeMismatchError(family, expected_keys, actual_keys)

    extracted: dict[Stage2SemanticKey, float] = {}
    for semantic_key in expected_keys:
        raw_value = component[semantic_key].value
        if raw_value is None:
            raise Stage2VariableValueExtractionError(
                family, semantic_key, raw_value, "value is uninitialized"
            )
        if isinstance(raw_value, bool) or not isinstance(raw_value, Real):
            raise Stage2VariableValueExtractionError(
                family, semantic_key, raw_value, "value is not a real number"
            )
        value = float(raw_value)
        if not isfinite(value):
            raise Stage2VariableValueExtractionError(
                family, semantic_key, raw_value, "value is not finite"
            )
        extracted[semantic_key] = value
    return extracted


def extract_raw_stage2_solution_from_pyomo(
    model: object,
    problem_data: Stage2ProblemData,
) -> RawStage2Solution:
    """Extract dense finite ``x,u`` values in the exact problem-data order."""

    if not isinstance(problem_data, Stage2ProblemData):
        raise TypeError("problem_data must be a Stage2ProblemData")
    extracted = {
        family.value: _extract_family(model, family, keys)
        for family, keys in _family_lattices(problem_data)
    }
    return RawStage2Solution(**extracted)


def _require_exact_raw_lattices(
    raw_solution: RawStage2Solution,
    problem_data: Stage2ProblemData,
) -> None:
    for family, expected_keys in _family_lattices(problem_data):
        actual_keys = tuple(getattr(raw_solution, family.value))
        if set(actual_keys) != set(expected_keys) or len(actual_keys) != len(
            expected_keys
        ):
            raise Stage2SolutionNormalizationError(
                family,
                None,
                actual_keys,
                f"exact key set {expected_keys!r}",
                None,
            )


def _normalize_continuous(
    family: Stage2VariableFamily,
    key: Stage2SemanticKey,
    raw_value: object,
    upper_bound: float,
    tolerance: float,
) -> float:
    if isinstance(raw_value, bool) or not isinstance(raw_value, Real):
        raise Stage2SolutionNormalizationError(
            family, key, raw_value, "a finite real number", None
        )
    value = float(raw_value)
    if not isfinite(value):
        raise Stage2SolutionNormalizationError(
            family, key, raw_value, "a finite real number", None
        )
    if 0.0 <= value <= upper_bound:
        return value
    if value < 0.0 and -value <= tolerance:
        return 0.0
    if value > upper_bound and value - upper_bound <= tolerance:
        return upper_bound
    raise Stage2SolutionNormalizationError(
        family,
        key,
        raw_value,
        f"domain [0, {upper_bound!r}] with only bound-scale clipping",
        tolerance,
    )


def normalize_raw_stage2_solution(
    raw_solution: RawStage2Solution,
    problem_data: Stage2ProblemData,
    tolerances: SolutionNormalizationTolerances | None = None,
) -> Stage2Solution:
    """Normalize ``x`` to [0,1] and ``u`` to [0,max_unmet_fraction].

    Clip only bound violations within ``bound_clipping`` tolerance.
    Attach solution identity without repairing demand balance or constraints.
    """

    if not isinstance(raw_solution, RawStage2Solution):
        raise TypeError("raw_solution must be a RawStage2Solution")
    if not isinstance(problem_data, Stage2ProblemData):
        raise TypeError("problem_data must be a Stage2ProblemData")
    selected_tolerances = tolerances or SolutionNormalizationTolerances()
    if not isinstance(selected_tolerances, SolutionNormalizationTolerances):
        raise TypeError("tolerances must be a SolutionNormalizationTolerances")

    _require_exact_raw_lattices(raw_solution, problem_data)
    max_unmet_by_query = {
        query.id: query.max_unmet_fraction for query in problem_data.instance.queries
    }
    return Stage2Solution(
        identity=stage2_solution_identity(problem_data),
        routing_fractions={
            key: _normalize_continuous(
                Stage2VariableFamily.X,
                key,
                raw_solution.x[key],
                1.0,
                selected_tolerances.bound_clipping,
            )
            for key in problem_data.routing_keys
        },
        unmet_fractions={
            query_id: _normalize_continuous(
                Stage2VariableFamily.U,
                query_id,
                raw_solution.u[query_id],
                max_unmet_by_query[query_id],
                selected_tolerances.bound_clipping,
            )
            for query_id in problem_data.unmet_keys
        },
    )
