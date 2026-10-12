"""Audited, immutable scenario-protocol specifications for Milestone 9.1.

The factories in this module encode only paper evidence and explicitly open
fields.  They do not own an RNG, draw realized coefficients, construct Stage-2
data, or invoke a Stage-1 or Stage-2 algorithm.
"""

from dataclasses import dataclass
from enum import Enum

from llm_resource_allocation.math.objective import PaperVersion


class ProvenanceClass(str, Enum):
    """Project provenance classes applicable to protocol facts."""

    PAPER_SPECIFIED = "paper-specified"
    DERIVED = "derived"
    SCIENTIFIC_INTERPRETATION = "scientific-interpretation"
    ASSUMED = "assumed"


class SpecificationAvailability(str, Enum):
    """Whether the paper makes a protocol item executable without a choice."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable-not-recoverable-from-paper"


class ProtocolKind(str, Enum):
    """Keep scientifically distinct experiment protocols separate."""

    PRIMARY_UNCERTAINTY = "primary-uncertainty"
    DELAY_ERROR_STRESS = "delay-error-stress"
    SYNTHETIC_ROLLING = "synthetic-rolling"
    AZURE_ROLLING = "azure-rolling"


class ScenarioQuantity(str, Enum):
    """Realized quantities consumed by the Stage-2 scientific boundary."""

    ARRIVAL_RATE = "arrival-rate"
    DELAY_COEFFICIENT = "delay-coefficient"
    EFFECTIVE_ERROR = "effective-error"


class PerturbationDirection(str, Enum):
    """Published direction of a relative perturbation."""

    SYMMETRIC = "symmetric"
    ADVERSE_ONLY = "adverse-only"


@dataclass(frozen=True, slots=True)
class PaperEvidence:
    """Human-auditable location of one protocol statement."""

    paper_version: PaperVersion
    section: str
    pdf_page: int
    statement: str


@dataclass(frozen=True, slots=True)
class FieldProvenance:
    """Attach the project provenance taxonomy to a named encoded field."""

    field_name: str
    classification: ProvenanceClass
    rationale: str


@dataclass(frozen=True, slots=True)
class PerturbationSpecification:
    """Describe one audited quantity without supplying a sampling rule.

    ``executable_relative_bounds`` is populated only when the paper supplies
    unambiguous signed relative bounds.  The v2 delay/error wording
    ``up to 10-25%`` is retained in ``reported_magnitude`` but deliberately does
    not become executable bounds.
    """

    quantity: ScenarioQuantity
    symbol: str
    semantic_meaning: str
    nominal_source: str
    unit: str
    canonical_stage2_fields: tuple[str, ...]
    direction: PerturbationDirection
    reported_magnitude: str
    is_relative: bool
    executable_relative_bounds: tuple[float, float] | None
    distribution_family: str | None
    sampling_scope: str | None
    independence_or_correlation: str | None
    clipping_or_domain_rule: str | None
    stage2_role: str
    availability: SpecificationAvailability
    field_provenance: tuple[FieldProvenance, ...]
    evidence: tuple[PaperEvidence, ...]
    open_questions: tuple[str, ...]

    def __post_init__(self) -> None:
        """Normalize all caller sequences to immutable tuples."""

        for field_name in (
            "canonical_stage2_fields",
            "field_provenance",
            "evidence",
            "open_questions",
        ):
            object.__setattr__(self, field_name, tuple(getattr(self, field_name)))


@dataclass(frozen=True, slots=True)
class ScenarioProtocolSpec:
    """Version-aware protocol metadata with no sampling or execution behavior."""

    protocol_id: str
    paper_version: PaperVersion
    kind: ProtocolKind
    scenario_count: int | None
    perturbations: tuple[PerturbationSpecification, ...]
    deterministic_multipliers: tuple[float, ...]
    strict_unmet_fraction_cap: float | None
    random_seed_policy: str | None
    repetition_policy: str | None
    same_realizations_across_methods: bool | None
    field_provenance: tuple[FieldProvenance, ...]
    evidence: tuple[PaperEvidence, ...]
    open_questions: tuple[str, ...]

    def __post_init__(self) -> None:
        """Copy sequence inputs so a specification cannot change after creation."""

        for field_name in (
            "perturbations",
            "deterministic_multipliers",
            "field_provenance",
            "evidence",
            "open_questions",
        ):
            object.__setattr__(self, field_name, tuple(getattr(self, field_name)))


def _v2_primary_evidence() -> PaperEvidence:
    return PaperEvidence(
        PaperVersion.V2,
        "Section 5.2, Performance Evaluation",
        10,
        (
            "S=500; delay/error coefficients are adversely inflated by up to "
            "10-25%; each arrival rate is perturbed by +/-20%."
        ),
    )


def v2_primary_scenario_protocol() -> ScenarioProtocolSpec:
    """Return the audited primary v2 Stage-2 uncertainty protocol."""

    evidence = (_v2_primary_evidence(),)
    common_unknowns = (
        "distribution family and parameters are not stated",
        "draw scope and dependence structure are not stated",
        "clipping or other post-draw domain handling is not stated",
    )
    perturbations = (
        PerturbationSpecification(
            ScenarioQuantity.ARRIVAL_RATE,
            "lambda_tilde[i,l]",
            "realized type-i query arrival rate in scenario l",
            "nominal lambda[i] from the experiment instance/forecast",
            "queries/hour",
            ("arrival_rates_per_hour",),
            PerturbationDirection.SYMMETRIC,
            "+/-20%",
            True,
            (-0.20, 0.20),
            None,
            None,
            None,
            None,
            "coefficient in realized Stage-2 compute-capacity constraints",
            SpecificationAvailability.PARTIAL,
            (
                FieldProvenance(
                    "direction/reported_magnitude",
                    ProvenanceClass.PAPER_SPECIFIED,
                    "Paper v2 Section 5.2 states each arrival rate is perturbed by +/-20%.",
                ),
                FieldProvenance(
                    "is_relative/executable_relative_bounds",
                    ProvenanceClass.DERIVED,
                    "Percentage perturbation yields signed relative bounds around nominal lambda.",
                ),
            ),
            evidence,
            common_unknowns,
        ),
        PerturbationSpecification(
            ScenarioQuantity.DELAY_COEFFICIENT,
            "d_tilde[l]",
            "realized delay coefficient used to form fixed-configuration delay",
            "nominal delay coefficients from the experiment instance/forecast",
            "seconds/token at the current Stage-2 component boundary",
            (
                "compute_delay_seconds_per_token",
                "communication_delay_seconds_per_token",
            ),
            PerturbationDirection.ADVERSE_ONLY,
            "inflated above nominal by up to 10-25%",
            True,
            None,
            None,
            None,
            None,
            None,
            "coefficient in realized Stage-2 delay constraints and C4",
            SpecificationAvailability.PARTIAL,
            (
                FieldProvenance(
                    "direction/reported_magnitude",
                    ProvenanceClass.PAPER_SPECIFIED,
                    "Paper v2 Section 5.2 states one-sided adverse inflation.",
                ),
                FieldProvenance(
                    "is_relative",
                    ProvenanceClass.DERIVED,
                    "The paper expresses inflation as percentages of nominal values.",
                ),
            ),
            evidence,
            common_unknowns
            + (
                "the phrase 'up to 10-25%' does not assign an exact maximum",
                "the paper does not say whether d_comp and d_comm share a factor or are drawn separately",
            ),
        ),
        PerturbationSpecification(
            ScenarioQuantity.EFFECTIVE_ERROR,
            "e_tilde[i,j,k,l]",
            "realized effective error for route (i,j,k) in scenario l",
            "nominal effective error e_bar[i,j,k] from the experiment instance/forecast",
            "dimensionless",
            ("effective_errors",),
            PerturbationDirection.ADVERSE_ONLY,
            "inflated above nominal by up to 10-25%",
            True,
            None,
            None,
            None,
            None,
            None,
            "coefficient in realized Stage-2 error-SLO constraints",
            SpecificationAvailability.PARTIAL,
            (
                FieldProvenance(
                    "direction/reported_magnitude",
                    ProvenanceClass.PAPER_SPECIFIED,
                    "Paper v2 Section 5.2 states one-sided adverse inflation.",
                ),
                FieldProvenance(
                    "is_relative",
                    ProvenanceClass.DERIVED,
                    "The paper expresses inflation as percentages of nominal values.",
                ),
            ),
            evidence,
            common_unknowns
            + ("the phrase 'up to 10-25%' does not assign an exact maximum",),
        ),
    )
    return ScenarioProtocolSpec(
        "paper-v2-primary-stage2-uncertainty",
        PaperVersion.V2,
        ProtocolKind.PRIMARY_UNCERTAINTY,
        500,
        perturbations,
        (),
        None,
        None,
        None,
        None,
        (
            FieldProvenance(
                "scenario_count",
                ProvenanceClass.PAPER_SPECIFIED,
                "Paper v2 Section 5.2 and Table 2 state S=500.",
            ),
        ),
        evidence,
        (
            "random seed and repetition policy are not stated",
            "whether identical realized scenarios are shared across methods is not stated",
            "whether one scenario set is reused across experiment settings S1-S5 is not stated",
        ),
    )


def v1_primary_scenario_protocol() -> ScenarioProtocolSpec:
    """Return the older v1 protocol without merging it into v2."""

    evidence = (
        PaperEvidence(
            PaperVersion.V1,
            "Section 4.2, Performance Evaluation",
            10,
            "S=500; delays/errors +/-25%; arrivals +/-20%.",
        ),
    )

    def symmetric_quantity(
        quantity: ScenarioQuantity,
        symbol: str,
        meaning: str,
        nominal_source: str,
        unit: str,
        stage2_fields: tuple[str, ...],
        magnitude: float,
        role: str,
    ) -> PerturbationSpecification:
        return PerturbationSpecification(
            quantity,
            symbol,
            meaning,
            nominal_source,
            unit,
            stage2_fields,
            PerturbationDirection.SYMMETRIC,
            f"+/-{int(magnitude * 100)}%",
            True,
            (-magnitude, magnitude),
            None,
            None,
            None,
            None,
            role,
            SpecificationAvailability.PARTIAL,
            (
                FieldProvenance(
                    "direction/reported_magnitude",
                    ProvenanceClass.PAPER_SPECIFIED,
                    "Paper v1 Section 4.2 prints the symmetric percentage.",
                ),
                FieldProvenance(
                    "is_relative/executable_relative_bounds",
                    ProvenanceClass.DERIVED,
                    "Percentage perturbation yields signed relative bounds.",
                ),
            ),
            evidence,
            (
                "distribution family and parameters are not stated",
                "draw scope and dependence structure are not stated",
                "clipping or other post-draw domain handling is not stated",
            ),
        )

    perturbations = (
        symmetric_quantity(
            ScenarioQuantity.ARRIVAL_RATE,
            "lambda_tilde[i,l]",
            "realized type-i query arrival rate in scenario l",
            "nominal lambda[i]",
            "queries/hour",
            ("arrival_rates_per_hour",),
            0.20,
            "realized Stage-2 compute-capacity constraints",
        ),
        symmetric_quantity(
            ScenarioQuantity.DELAY_COEFFICIENT,
            "d_tilde[l]",
            "realized delay coefficient",
            "nominal delay coefficients",
            "seconds/token at the current Stage-2 component boundary",
            (
                "compute_delay_seconds_per_token",
                "communication_delay_seconds_per_token",
            ),
            0.25,
            "realized Stage-2 delay constraints and C4",
        ),
        symmetric_quantity(
            ScenarioQuantity.EFFECTIVE_ERROR,
            "e_tilde[i,j,k,l]",
            "realized effective error",
            "nominal effective error e_bar[i,j,k]",
            "dimensionless",
            ("effective_errors",),
            0.25,
            "realized Stage-2 error-SLO constraints",
        ),
    )
    return ScenarioProtocolSpec(
        "paper-v1-primary-stage2-uncertainty",
        PaperVersion.V1,
        ProtocolKind.PRIMARY_UNCERTAINTY,
        500,
        perturbations,
        (),
        None,
        None,
        None,
        None,
        (
            FieldProvenance(
                "scenario_count",
                ProvenanceClass.PAPER_SPECIFIED,
                "Paper v1 Section 4.2 states S=500.",
            ),
        ),
        evidence,
        (
            "random seed and repetition policy are not stated",
            "whether identical realized scenarios are shared across methods is not stated",
        ),
    )


def v2_delay_error_stress_protocol() -> ScenarioProtocolSpec:
    """Return the separate deterministic v2 Fig. 5 stress specification."""

    evidence = (
        PaperEvidence(
            PaperVersion.V2,
            "Figure 5 caption and Section 5.2",
            11,
            "Delay/error multipliers alpha=1.0, 1.2, 1.5 with strict u[i]<=0.02.",
        ),
    )
    perturbations = tuple(
        PerturbationSpecification(
            quantity,
            symbol,
            meaning,
            nominal_source,
            unit,
            stage2_fields,
            PerturbationDirection.ADVERSE_ONLY,
            "deterministic multiplier alpha",
            True,
            None,
            None,
            "global stress level; coefficient-level sharing is not further specified",
            "same alpha is shown on delay and effective error",
            None,
            role,
            SpecificationAvailability.PARTIAL,
            (
                FieldProvenance(
                    "direction/reported_magnitude",
                    ProvenanceClass.PAPER_SPECIFIED,
                    "Paper v2 Figure 5 labels delay-error inflation levels.",
                ),
            ),
            evidence,
            (
                "mapping alpha onto the two Stage-2 delay component maps is not stated",
            ),
        )
        for quantity, symbol, meaning, nominal_source, unit, stage2_fields, role in (
            (
                ScenarioQuantity.DELAY_COEFFICIENT,
                "d_bar",
                "stress-scaled nominal delay coefficient",
                "nominal delay coefficients",
                "seconds/token at the current Stage-2 component boundary",
                (
                    "compute_delay_seconds_per_token",
                    "communication_delay_seconds_per_token",
                ),
                "realized Stage-2 delay constraints and C4",
            ),
            (
                ScenarioQuantity.EFFECTIVE_ERROR,
                "e_bar",
                "stress-scaled nominal effective error",
                "nominal effective error e_bar[i,j,k]",
                "dimensionless",
                ("effective_errors",),
                "realized Stage-2 error-SLO constraints",
            ),
        )
    )
    return ScenarioProtocolSpec(
        "paper-v2-figure5-delay-error-stress",
        PaperVersion.V2,
        ProtocolKind.DELAY_ERROR_STRESS,
        None,
        perturbations,
        (1.0, 1.2, 1.5),
        0.02,
        None,
        None,
        None,
        (
            FieldProvenance(
                "deterministic_multipliers/strict_unmet_fraction_cap",
                ProvenanceClass.PAPER_SPECIFIED,
                "Paper v2 Figure 5 gives the three levels and strict cap.",
            ),
        ),
        evidence,
        (
            "Figure 3 shows a broader alpha sweep on delay/error, but its exact sampled grid is not enumerated in prose",
            "this stress protocol is not the S=500 primary uncertainty sampler",
        ),
    )
