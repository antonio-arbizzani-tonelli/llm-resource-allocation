#pragma once

#include "pacs/gh.hpp"
#include <cstddef>
#include <optional>
#include <string>
#include <vector>

namespace pacs {

struct AghOrdering {
    std::vector<std::size_t> queries;
    std::string source{"deterministic"}, criterion, direction;
    std::optional<std::size_t> random_start_index;
    std::string seed;
};

// The decimal seed interface preserves Python's signed, arbitrary-size integers.
std::vector<AghOrdering> build_deterministic_agh_orderings(const Problem&);
AghOrdering build_seeded_random_agh_ordering(std::size_t query_count,
                                           const std::string& seed,
                                           std::size_t random_start_index);
std::size_t adaptive_agh_random_start_count(std::size_t I, std::size_t J, std::size_t K);

struct AghTransferAttempt {
    std::size_t source_route{}, destination_pair{};
    double moved_fraction{}, objective_before{};
    std::optional<double> objective_after;
    double routed_difference{};
    bool feasible{}, accepted{};
    std::vector<std::string> rejection_reasons;
};

struct AghRelocateSourceTrace {
    std::size_t source_route{};
    std::vector<std::size_t> eligible_destinations;
    std::vector<AghTransferAttempt> attempts;
    std::string status{"no_improving_destination"};
};

struct AghRelocatePass {
    std::vector<std::size_t> source_snapshot;
    std::vector<AghRelocateSourceTrace> sources;
    Objective objective_before, objective_after;
    std::size_t accepted_move_count{};
};

struct AghRelocateResult {
    Placement placement;
    Validation validation;
    std::vector<AghRelocatePass> passes;
    std::string termination_reason{"max_passes_reached"};
};

struct AghLoad {
    std::size_t pair{};
    double required{}, available{}, utilization{};
};

struct AghConsolidationRouteTrace {
    std::size_t source_route{};
    std::vector<AghTransferAttempt> attempts;
    std::optional<std::size_t> selected_destination;
};

struct AghConsolidationSourceTrace {
    std::size_t source_pair{};
    std::vector<std::size_t> source_routes, eligible_destinations;
    std::vector<AghConsolidationRouteTrace> routes;
    Objective objective_before;
    std::optional<Objective> prospective_objective;
    bool prospective_feasible{};
    std::string status{"rejected"};
    std::vector<std::string> rejection_reasons;
};

struct AghConsolidationResult {
    Placement placement;
    Validation validation;
    std::vector<AghLoad> source_snapshot;
    std::vector<AghConsolidationSourceTrace> sources;
    std::size_t accepted_source_count{};
};

AghRelocateResult run_agh_relocate(const Problem&, const Placement&,
                                 std::size_t max_passes=3, const Tolerances& = {});
AghConsolidationResult run_agh_consolidation_scan(const Problem&, const Placement&,
                                                const Tolerances& = {});

struct AghStartResult {
    AghOrdering ordering;
    GhResult gh;
    std::optional<AghRelocateResult> relocate;
    std::optional<AghConsolidationResult> consolidation;
    std::string completion_status{"stopped_after_gh"};
    std::vector<std::string> failure_reasons;
    bool completed() const { return completion_status == "completed"; }
    // Borrowed pointers require a live, unchanged owner; never retain them
    // across moving/replacing this result or its consolidation value.
    const Placement* final_placement() const & {
        return consolidation ? &consolidation->placement : nullptr;
    }
    const Placement* final_placement() const && = delete;
    const Validation* final_validation() const & {
        return consolidation ? &consolidation->validation : nullptr;
    }
    const Validation* final_validation() const && = delete;
};

AghStartResult run_agh_start(const Problem&, const AghOrdering&,
                            const GhOptions& = {});

struct AghStartTrace {
    AghStartResult start;
    std::optional<std::size_t> incumbent_before, incumbent_after;
    std::string comparison_outcome;
    std::size_t counter_before{}, counter_after{};
};

struct AghMultiStartResult {
    std::vector<AghStartTrace> starts;
    std::string random_seed, termination_reason{"schedule_exhausted"};
    std::size_t random_start_count{}, scheduled_start_count{}, nonimprovement_count{};
    std::optional<std::size_t> incumbent_index;
    std::size_t unexecuted_start_count() const { return scheduled_start_count-starts.size(); }
    // Borrows from starts: owner destruction/replacement, moves or vector
    // reallocation invalidate the pointer.
    const AghStartResult* incumbent() const & {
        return incumbent_index ? &starts[*incumbent_index].start : nullptr;
    }
    const AghStartResult* incumbent() const && = delete;
};

AghMultiStartResult run_agh_multistart(const Problem&, const std::string& random_seed,
                                      const GhOptions& = {});

struct AghResult {
    AghMultiStartResult multistart;
    std::optional<Validation> final_validation;
    std::string completion_status{"no_feasible_incumbent"};
    std::vector<std::string> failure_reasons;
    bool completed() const { return completion_status == "completed"; }
    // Borrows through multistart; its owner and starts must remain unchanged.
    const Placement* final_placement() const & {
        const auto* start = multistart.incumbent();
        return start ? start->final_placement() : nullptr;
    }
    const Placement* final_placement() const && = delete;
};

AghResult run_agh(const Problem&, const std::string& random_seed, const GhOptions& = {});

} // namespace pacs
