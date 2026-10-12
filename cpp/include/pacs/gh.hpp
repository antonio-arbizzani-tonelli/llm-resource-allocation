#pragma once

#include "pacs/core.hpp"

#include <optional>
#include <string>
#include <vector>

namespace pacs {

struct GhOptions {
    double budget_fraction{0.8};
    Tolerances tolerances{};
};

struct M1Diagnostic {
    std::size_t configuration{};
    double weight_shard{}, delay{};
    bool weight_passes{}, delay_passes{};
    bool feasible() const { return weight_passes && delay_passes; }
};
struct M1Result {
    std::optional<std::size_t> selected;
    std::vector<M1Diagnostic> diagnostics;
};
M1Result select_m1(const Problem&, std::size_t i, std::size_t j, std::size_t k);

struct M3Diagnostic {
    std::size_t configuration{};
    int gpu_count{}, incremental_gpu_count{};
    double delay{}, incremental_cost{};
    bool higher_gpu_count{}, delay_passes{}, budget_passes{};
    bool feasible() const { return higher_gpu_count && delay_passes && budget_passes; }
};
struct M3Result {
    std::optional<std::size_t> selected;
    std::optional<double> current_delay;
    std::vector<M3Diagnostic> diagnostics;
    std::string no_upgrade_reason;
};
M3Result select_m3(const Problem&, std::size_t i, std::size_t j, std::size_t k,
                   int current_configuration, double remaining_budget);

struct M2Inputs {
    double remaining_demand{}, cumulative_error{}, cumulative_delay{};
    int current_gpu_count{};
};
struct M2Result {
    M2Inputs inputs;
    double fixed_delay{}, effective_error{}, error_slo{}, delay_slo{};
    double incremental_gpu_cost{}, storage_cost{}, delay_cost{};
    std::optional<double> error_limit() const;
    std::optional<double> delay_limit() const;
    double coverage() const;
    double marginal_cost() const { return incremental_gpu_cost + storage_cost + delay_cost; }
    int pi() const { return coverage() < inputs.remaining_demand; }
    bool rankable() const { return coverage() > 0.0; }
    double kappa() const;
};
M2Result evaluate_m2(const Problem&, std::size_t i, std::size_t j, std::size_t k,
                      std::size_t configuration, double fixed_delay, M2Inputs);

struct GhDeployment {
    std::size_t model{}, tier{}, configuration{};
    std::vector<std::size_t> covered_queries;
    double activation_cost{};
};
struct GhPhase1State {
    std::vector<std::size_t> uncovered_queries;
    std::vector<GhDeployment> deployments;
    double rental{}, cap{};
};
struct GhPhase1Candidate {
    std::size_t model{}, tier{};
    std::vector<std::size_t> covered_queries;
    std::vector<M1Result> m1_results;
    std::optional<std::size_t> common_configuration;
    std::optional<double> activation_cost;
    bool rankable() const { return common_configuration.has_value() && activation_cost.has_value(); }
    double coverage_per_cost() const;
};
struct GhPhase1Iteration {
    GhPhase1State before, after;
    std::vector<GhPhase1Candidate> candidates;
    std::vector<std::size_t> ranked_candidates;
};
struct GhPhase1 {
    GhPhase1State initial, final;
    std::vector<GhPhase1Iteration> iterations;
    std::vector<GhPhase1Candidate> terminal_candidates;
    std::string termination;
};
GhPhase1 run_gh_phase1(const Problem&, const GhOptions& = {});

// A state owns explicit semantic and sparse insertion orders. The latter is
// needed by the literal running C1-C3 computation; final placement is canonical.
struct GhPhase2State {
    std::vector<GhDeployment> deployments;
    std::vector<std::size_t> query_order, route_insertion_order;
    std::vector<double> x, unmet, remaining, cumulative_error, cumulative_delay;
    double budget_used{}, remaining_budget{};
};
struct GhCandidate {
    std::size_t query{}, model{}, tier{};
    int current_configuration{-1};
    std::optional<std::size_t> selected_configuration;
    std::string source, rejection;
    std::optional<M1Result> m1;
    std::optional<M3Result> m3;
    std::optional<M2Result> m2;
    bool rankable() const { return m2.has_value() && m2->rankable(); }
};
struct GhBudget {
    double c1{}, c2{}, c3{};
    double total() const { return c1 + c2 + c3; }
};
struct GhAttempt {
    std::size_t ranked_position{};
    double allocation{};
    GhPhase2State before, after;
    GhBudget prior_budget, prospective_budget;
    Validation resource_validation;
    std::vector<std::string> rejection_reasons;
    bool committed() const { return rejection_reasons.empty(); }
};
struct GhQueryTrace {
    std::size_t query{};
    GhPhase2State before, after;
    std::vector<GhCandidate> candidates;
    std::vector<std::size_t> ranked_candidates;
    std::vector<GhAttempt> attempts;
    std::string termination;
};
struct GhResult {
    GhPhase1 phase1;
    GhPhase2State initial, final;
    std::vector<GhQueryTrace> queries;
    Placement placement;
    Validation validation;
    bool algorithm_completed{true};
    bool scientifically_usable() const { return algorithm_completed && validation.feasible; }
};

GhResult run_gh(const Problem&, const GhOptions& = {},
                const std::vector<std::size_t>& query_order = {});

namespace detail {
// Internal composition on the same validated problem and producer-owned Phase 1.
GhResult run_gh_with_phase1(const Problem&, const GhOptions&,
                           const std::vector<std::size_t>& query_order,
                           const GhPhase1&);
}

} // namespace pacs
