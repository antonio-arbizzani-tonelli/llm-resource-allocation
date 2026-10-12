"""Preserve exported evidence fields when records derive former stored values."""

from collections.abc import Iterator
from dataclasses import fields


_EXPORTED_DERIVED_FIELDS = {
    "llm_resource_allocation.algorithms.agh.AGHResult": (
        "final_incumbent", "final_placement", "final_objective_breakdown",
    ),
    "llm_resource_allocation.algorithms.agh_start.AGHStartResult": (
        "gh_placement", "relocate_placement", "consolidation_placement",
        "final_placement", "final_validation", "final_objective_breakdown",
    ),
    "llm_resource_allocation.algorithms.agh_multistart.AGHMultiStartScaleEvidence": (
        "problem_scale", "random_start_count",
    ),
    "llm_resource_allocation.algorithms.agh_multistart.AGHMultiStartTrace": (
        "ordering", "candidate_is_feasible_complete", "candidate_objective",
        "incumbent_objective_before", "incumbent_objective_after",
        "strict_improvement", "incumbent_changed", "consecutive_nonimprovements_after",
    ),
    "llm_resource_allocation.algorithms.agh_multistart.AGHMultiStartResult": (
        "scheduled_start_count", "executed_start_count", "unexecuted_start_count",
        "incumbent_status", "consecutive_nonimprovements", "final_incumbent",
    ),
    "llm_resource_allocation.algorithms.agh_relocate.AGHRelocateMoveResult": (
        "accepted", "accepted_placement", "objective_breakdown_before",
        "objective_breakdown_after",
    ),
    "llm_resource_allocation.algorithms.agh_relocate_pass.AGHRelocateAttemptTrace": (
        "source", "destination", "placement_before", "placement_after", "accepted",
    ),
    "llm_resource_allocation.algorithms.agh_relocate_pass.AGHRelocateSourceTrace": (
        "accepted_destination", "placement_after",
    ),
    "llm_resource_allocation.algorithms.agh_relocate_pass.AGHRelocatePassResult": (
        "attempt_traces", "accepted_move_count", "placement_after",
        "objective_breakdown_before", "objective_breakdown_after",
        "total_objective_improvement", "changed",
    ),
    "llm_resource_allocation.algorithms.agh_relocate_pass.AGHRelocateRunResult": (
        "placement_after", "accepted_move_count", "objective_breakdown_before",
        "objective_breakdown_after", "total_objective_improvement",
    ),
    "llm_resource_allocation.algorithms.agh_consolidation.AGHConsolidationUtilizationEvidence": (
        "utilization",
    ),
    "llm_resource_allocation.algorithms.agh_consolidation.AGHConsolidationDestinationAttempt": (
        "feasible", "placement_after",
    ),
    "llm_resource_allocation.algorithms.agh_consolidation.AGHConsolidationRouteTrace": (
        "selected_destination", "placement_after",
    ),
    "llm_resource_allocation.algorithms.agh_consolidation.AGHConsolidationSourceResult": (
        "accepted", "accepted_placement", "objective_breakdown_before",
        "objective_breakdown_after",
    ),
    "llm_resource_allocation.algorithms.agh_consolidation.AGHConsolidationSourceTrace": (
        "placement_after",
    ),
    "llm_resource_allocation.algorithms.agh_consolidation.AGHConsolidationScanResult": (
        "accepted_source_count", "placement_after", "objective_breakdown_before",
        "objective_breakdown_after", "total_objective_improvement", "changed",
    ),
    "llm_resource_allocation.algorithms.gh.GHResult": (
        "literal_final_state", "objective_breakdown", "residual_demand_by_query",
    ),
    "llm_resource_allocation.algorithms.gh_phase1.GHPhase1State": (
        "iteration_count",
    ),
    "llm_resource_allocation.algorithms.gh_phase1.GHPhase1IterationTrace": (
        "iteration_index", "selected_candidate",
    ),
    "llm_resource_allocation.algorithms.gh_phase1.GHPhase1Result": (
        "final_state",
    ),
    "llm_resource_allocation.algorithms.gh_phase2_query.GHPhase2CandidateAttempt": (
        "rank_key", "state_before", "state_after",
    ),
    "llm_resource_allocation.algorithms.gh_phase2_query.GHPhase2QueryProcessResult": (
        "query_id", "final_state",
    ),
    "llm_resource_allocation.algorithms.gh_phase2_run.GHPhase2QueryTrace": (
        "query_id", "state_at_query_entry", "query_evaluation", "state_after_query",
    ),
    "llm_resource_allocation.algorithms.gh_phase2_run.GHPhase2RunResult": (
        "final_state", "processed_query_ids", "residual_demand_by_query",
    ),
    "llm_resource_allocation.experiments.azure_replay.ReplayQueryMetrics": (
        "served_fraction", "violation",
    ),
    "llm_resource_allocation.experiments.azure_replay.ReplayStage1Attempt": (
        "accepted",
    ),
    "llm_resource_allocation.experiments.azure_replay.AzureReplayAggregate": (
        "mean_window_model_cost", "violation_rate",
    ),
    "llm_resource_allocation.experiments.bounded_experiment.BoundedScenarioExperimentPlan": (
        "scenario_count",
    ),
    "llm_resource_allocation.experiments.synthetic_benchmark.SyntheticBenchmarkRun": (
        "is_warmup",
    ),
    "llm_resource_allocation.experiments.version_comparison.ScalarVersionComparison": (
        "absolute_delta",
    ),
    "llm_resource_allocation.experiments.version_comparison.AggregateMetricComparison": (
        "v1_scenario_count", "v2_scenario_count",
    ),
    "llm_resource_allocation.optimization.pdm_run.PdmScientificEvidence": (
        "objective_breakdown",
    ),
    "llm_resource_allocation.optimization.stage2_run.Stage2ScientificEvidence": (
        "objective_breakdown",
    ),
    "llm_resource_allocation.optimization.stage2_adapter.Stage1ToStage2DeploymentEvidence": (
        "source_identity", "source_final_placement",
    ),
    "llm_resource_allocation.verification.tiny_enumeration.TinyCandidateDiagnostic": (
        "is_feasible",
    ),
    "llm_resource_allocation.verification.tiny_enumeration.TinyEnumerationResult": (
        "candidates_examined", "feasible_candidates", "best_state", "tie_count",
        "is_unique_optimum",
    ),
}


def public_record_items(value: object) -> Iterator[tuple[str, object]]:
    """Yield public stored fields and explicitly retained derived export fields."""

    for field in fields(value):
        if not field.name.startswith("_"):
            yield field.name, getattr(value, field.name)
    record_type = type(value)
    qualified_name = f"{record_type.__module__}.{record_type.__qualname__}"
    for name in _EXPORTED_DERIVED_FIELDS.get(qualified_name, ()):
        yield name, getattr(value, name)
