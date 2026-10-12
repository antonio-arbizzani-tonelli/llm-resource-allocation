"""Version-aware bounded composition of scenario generation and evaluation.

The runner accepts every output-sensitive sampling choice from the caller. It
generates an explicit finite sequence through the existing one-scenario
generator, then delegates the intact sequence to the existing multi-scenario
evaluator. It is synthetic/reference infrastructure, not a paper-exact sampler
or a paper-scale experiment driver. V1 callers must select ``PaperVersion.V1``
explicitly; protocol, policy, accepted Stage-1 source, and every Stage-2 run are
then required to preserve that version identity.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from llm_resource_allocation.math.objective import PaperVersion
from llm_resource_allocation.optimization.extraction import (
    SolutionNormalizationTolerances,
)
from llm_resource_allocation.optimization.problem_data import PdmProblemData
from llm_resource_allocation.optimization.solver import SolverConfig
from llm_resource_allocation.optimization.stage2_adapter import Stage1Result
from llm_resource_allocation.validation.stage2 import Stage2ValidationTolerances

from .scenario_evaluation import (
    MultiScenarioEvaluationResult,
    evaluate_stage1_result_over_scenarios,
)
from .scenario_generation import (
    ExecutableScenarioSamplingPolicy,
    GeneratedScenarioRecord,
    ScenarioSamplingPolicyError,
    generate_realized_scenario,
)
from .scenario_protocol import ScenarioProtocolSpec


class BoundedExperimentStatus(str, Enum):
    """Classify the exact terminal boundary reached by one bounded run."""

    SUCCESS = "success"
    GENERATION_FAILED = "generation_failed"
    EVALUATION_FAILED = "evaluation_failed"


@dataclass(frozen=True, slots=True)
class BoundedScenarioExperimentPlan:
    """Retain the explicit finite scenario identities and shared master seed."""

    scenario_ids: tuple[str, ...]
    master_seed: int

    @property
    def scenario_count(self) -> int:
        """Return the number of explicitly planned scenario identities."""

        return len(self.scenario_ids)

    def __post_init__(self) -> None:
        object.__setattr__(self, "scenario_ids", tuple(self.scenario_ids))
        if not self.scenario_ids:
            raise ValueError("scenario_ids must be non-empty")
        if any(not isinstance(item, str) or not item for item in self.scenario_ids):
            raise ValueError("every scenario ID must be a non-empty string")
        if isinstance(self.master_seed, bool) or not isinstance(self.master_seed, int):
            raise TypeError("master_seed must be an integer")


@dataclass(frozen=True, slots=True)
class ScenarioGenerationFailure:
    """Preserve one generator rejection without retry, repair, or replacement."""

    scenario_index: int
    scenario_id: str
    error_type: str
    message: str

@dataclass(frozen=True, slots=True)
class ScenarioGenerationAttempt:
    """Retain one ordered generation outcome, successful or typed-failed."""

    scenario_index: int
    scenario_id: str
    generated_record: GeneratedScenarioRecord | None = None
    failure: ScenarioGenerationFailure | None = None

    def __post_init__(self) -> None:
        """Keep the intrinsic choice between a generated record and a failure."""

        if (self.generated_record is None) == (self.failure is None):
            raise ValueError("attempt requires exactly one record or failure")

    @property
    def successful(self) -> bool:
        return self.generated_record is not None


@dataclass(frozen=True, slots=True)
class BoundedScenarioExperimentRecord:
    """Retain inputs, ordered generation evidence, and optional batch result."""

    source_result: Stage1Result
    nominal_problem_data: PdmProblemData
    protocol: ScenarioProtocolSpec
    sampling_policy: ExecutableScenarioSamplingPolicy
    plan: BoundedScenarioExperimentPlan
    paper_version: PaperVersion
    status: BoundedExperimentStatus
    generation_attempts: tuple[ScenarioGenerationAttempt, ...]
    evaluation_result: MultiScenarioEvaluationResult | None = None

    def __post_init__(self) -> None:
        """Own ordered attempt evidence; the runner owns pipeline consistency."""

        object.__setattr__(self, "generation_attempts", tuple(self.generation_attempts))

    @property
    def successful(self) -> bool:
        return self.status is BoundedExperimentStatus.SUCCESS

    @property
    def generation_failures(self) -> tuple[ScenarioGenerationFailure, ...]:
        return tuple(
            item.failure
            for item in self.generation_attempts
            if item.failure is not None
        )

    @property
    def generated_records(self) -> tuple[GeneratedScenarioRecord, ...]:
        return tuple(
            item.generated_record
            for item in self.generation_attempts
            if item.generated_record is not None
        )


def _validate_inputs(
    nominal_problem_data: PdmProblemData,
    protocol: ScenarioProtocolSpec,
    sampling_policy: ExecutableScenarioSamplingPolicy,
    plan: BoundedScenarioExperimentPlan,
    paper_version: PaperVersion,
) -> None:
    if not isinstance(nominal_problem_data, PdmProblemData):
        raise TypeError("nominal_problem_data must be a PdmProblemData")
    if not isinstance(protocol, ScenarioProtocolSpec):
        raise TypeError("protocol must be a ScenarioProtocolSpec")
    if not isinstance(sampling_policy, ExecutableScenarioSamplingPolicy):
        raise TypeError(
            "sampling_policy must be an ExecutableScenarioSamplingPolicy"
        )
    if not isinstance(plan, BoundedScenarioExperimentPlan):
        raise TypeError("plan must be a BoundedScenarioExperimentPlan")
    if not isinstance(paper_version, PaperVersion):
        raise TypeError("paper_version must be PaperVersion.V1 or V2")
    if protocol.paper_version is not paper_version:
        raise ValueError("protocol and experiment paper versions differ")
    if sampling_policy.paper_version is not paper_version:
        raise ValueError("sampling policy and experiment paper versions differ")


def run_bounded_scenario_experiment(
    stage1_result: Stage1Result,
    nominal_problem_data: PdmProblemData,
    protocol: ScenarioProtocolSpec,
    sampling_policy: ExecutableScenarioSamplingPolicy,
    plan: BoundedScenarioExperimentPlan,
    *,
    paper_version: PaperVersion = PaperVersion.V2,
    solver_config: SolverConfig | None = None,
    normalization_tolerances: SolutionNormalizationTolerances | None = None,
    validation_tolerances: Stage2ValidationTolerances | None = None,
) -> BoundedScenarioExperimentRecord:
    """Generate and evaluate one explicit bounded synthetic/reference batch."""

    _validate_inputs(
        nominal_problem_data,
        protocol,
        sampling_policy,
        plan,
        paper_version,
    )
    attempts: list[ScenarioGenerationAttempt] = []
    for index, scenario_id in enumerate(plan.scenario_ids):
        try:
            generated = generate_realized_scenario(
                nominal_problem_data,
                protocol,
                sampling_policy,
                seed=plan.master_seed,
                scenario_id=scenario_id,
            )
        except ScenarioSamplingPolicyError as error:
            failure = ScenarioGenerationFailure(
                index,
                scenario_id,
                type(error).__name__,
                str(error),
            )
            attempts.append(
                ScenarioGenerationAttempt(
                    index,
                    scenario_id,
                    failure=failure,
                )
            )
        else:
            attempts.append(
                ScenarioGenerationAttempt(
                    index,
                    scenario_id,
                    generated_record=generated,
                )
            )

    generation_attempts = tuple(attempts)
    if any(not item.successful for item in generation_attempts):
        return BoundedScenarioExperimentRecord(
            source_result=stage1_result,
            nominal_problem_data=nominal_problem_data,
            protocol=protocol,
            sampling_policy=sampling_policy,
            plan=plan,
            paper_version=paper_version,
            status=BoundedExperimentStatus.GENERATION_FAILED,
            generation_attempts=generation_attempts,
        )

    scenarios = tuple(
        item.generated_record.realized_scenario  # type: ignore[union-attr]
        for item in generation_attempts
    )
    evaluation = evaluate_stage1_result_over_scenarios(
        stage1_result,
        nominal_problem_data,
        scenarios,
        paper_version=paper_version,
        solver_config=solver_config,
        normalization_tolerances=normalization_tolerances,
        validation_tolerances=validation_tolerances,
    )
    status = (
        BoundedExperimentStatus.SUCCESS
        if evaluation.successful
        else BoundedExperimentStatus.EVALUATION_FAILED
    )
    return BoundedScenarioExperimentRecord(
        source_result=stage1_result,
        nominal_problem_data=nominal_problem_data,
        protocol=protocol,
        sampling_policy=sampling_policy,
        plan=plan,
        paper_version=paper_version,
        status=status,
        generation_attempts=generation_attempts,
        evaluation_result=evaluation,
    )
