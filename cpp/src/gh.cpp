#include "pacs/gh.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <numeric>
#include <stdexcept>
#include <utility>

namespace pacs {
namespace {

void require_prepared(const Problem& p) {
    if (p.I() == 0 || p.J() == 0 || p.K() == 0 || p.tier_offsets.size() != p.K() + 1)
        throw std::invalid_argument("GH requires a prepared problem");
}

void check_indices(const Problem& p, std::size_t i, std::size_t j, std::size_t k) {
    require_prepared(p);
    if (i >= p.I() || j >= p.J() || k >= p.K())
        throw std::invalid_argument("unknown query/model/tier index");
}

void check_options(const GhOptions& options) {
    if (!std::isfinite(options.budget_fraction) || options.budget_fraction < 0.0 ||
        options.budget_fraction > 1.0)
        throw std::invalid_argument("GH budget_fraction must be in [0,1]");
}

std::optional<double> coverage_limit(double residual, double consumption) {
    if (consumption > 0.0) return residual / consumption;
    if (residual >= 0.0) return std::nullopt;
    return 0.0;
}

M1Result m1_worker(const Problem& p, std::size_t i, std::size_t j, std::size_t k) {
    M1Result result;
    const auto& tier = p.tiers[k];
    for (std::size_t c = 0; c < tier.configs.size(); ++c) {
        const double weight = p.models[j].weight / tier.configs[c].gpu_count();
        const double delay = configuration_delay(p, i, j, k, c);
        result.diagnostics.push_back({c, weight, delay, weight <= tier.capacity,
                                      delay <= p.queries[i].delay_slo});
        if (result.diagnostics.back().feasible() &&
            (!result.selected || tier.configs[c].gpu_count() <
                                     tier.configs[*result.selected].gpu_count()))
            result.selected = c;
    }
    return result;
}

M3Result m3_worker(const Problem& p, std::size_t i, std::size_t j, std::size_t k,
                   int current_configuration, double remaining_budget) {
    M3Result result;
    if (current_configuration < 0) {
        result.no_upgrade_reason = "inactive_pair";
        return result;
    }
    const auto& tier = p.tiers[k];
    const auto current = static_cast<std::size_t>(current_configuration);
    if (current >= tier.configs.size())
        throw std::invalid_argument("current configuration is invalid for its tier");
    result.current_delay = configuration_delay(p, i, j, k, current);
    if (*result.current_delay <= p.queries[i].delay_slo) {
        result.no_upgrade_reason = "current_delay_within_slo";
        return result;
    }
    const int current_gpus = tier.configs[current].gpu_count();
    for (std::size_t c = 0; c < tier.configs.size(); ++c) {
        const int gpus = tier.configs[c].gpu_count();
        const int incremental = std::max(gpus - current_gpus, 0);
        const double cost = p.horizon * tier.rental * incremental;
        const double delay = configuration_delay(p, i, j, k, c);
        result.diagnostics.push_back({c, gpus, incremental, delay, cost,
                                      gpus > current_gpus,
                                      delay <= p.queries[i].delay_slo,
                                      cost <= remaining_budget});
        if (result.diagnostics.back().feasible() &&
            (!result.selected || gpus < tier.configs[*result.selected].gpu_count()))
            result.selected = c;
    }
    if (!result.selected) {
        bool higher = false, delay_feasible = false;
        for (const auto& diagnostic : result.diagnostics) {
            higher |= diagnostic.higher_gpu_count;
            delay_feasible |= diagnostic.higher_gpu_count && diagnostic.delay_passes;
        }
        result.no_upgrade_reason = !higher ? "no_higher_gpu_configuration" :
            !delay_feasible ? "no_delay_feasible_configuration" :
                              "insufficient_remaining_budget";
    }
    return result;
}

M2Result m2_worker(const Problem& p, std::size_t i, std::size_t j, std::size_t k,
                   std::size_t c, double delay, M2Inputs inputs) {
    const auto& query = p.queries[i];
    const auto& tier = p.tiers[k];
    M2Result result;
    result.inputs = inputs;
    result.fixed_delay = delay;
    result.effective_error = p.error[p.route(i, j, k)];
    result.error_slo = query.error_slo;
    result.delay_slo = query.delay_slo;
    const int incremental = std::max(tier.configs[c].gpu_count() - inputs.current_gpu_count, 0);
    result.incremental_gpu_cost = p.horizon * tier.rental * incremental;
    double data_storage = query.storage * query.total_tokens() * query.arrival;
    if (p.coherent) data_storage *= p.data_residency;
    result.storage_cost = p.horizon * p.storage_price * (p.models[j].weight + data_storage);
    result.delay_cost = query.delay_penalty * delay;
    if (p.coherent)
        result.delay_cost = result.delay_cost * 1000.0 * query.arrival * p.horizon;
    return result;
}

GhPhase1Candidate phase1_candidate(const Problem& p, const GhPhase1State& state,
                                   std::size_t j, std::size_t k) {
    GhPhase1Candidate candidate;
    candidate.model = j;
    candidate.tier = k;
    int required_gpus = 0;
    for (const auto i : state.uncovered_queries) {
        auto m1 = m1_worker(p, i, j, k);
        if (m1.selected && p.error[p.route(i, j, k)] <= p.queries[i].error_slo) {
            candidate.covered_queries.push_back(i);
            required_gpus = std::max(required_gpus, p.tiers[k].configs[*m1.selected].gpu_count());
        }
        candidate.m1_results.push_back(std::move(m1));
    }
    if (candidate.covered_queries.empty()) return candidate;
    candidate.activation_cost = p.horizon * p.tiers[k].rental * required_gpus;
    // Eq. (14) fixes the GPU product. Do not silently use a larger feasible shape.
    for (std::size_t c = 0; c < p.tiers[k].configs.size(); ++c) {
        if (p.tiers[k].configs[c].gpu_count() != required_gpus) continue;
        bool common = true;
        for (std::size_t position = 0; position < state.uncovered_queries.size(); ++position) {
            const auto i = state.uncovered_queries[position];
            if (std::find(candidate.covered_queries.begin(), candidate.covered_queries.end(), i) !=
                candidate.covered_queries.end() && !candidate.m1_results[position].diagnostics[c].feasible()) {
                common = false;
                break;
            }
        }
        if (common) {
            candidate.common_configuration = c;
            break;
        }
    }
    return candidate;
}

std::vector<GhPhase1Candidate> phase1_candidates(const Problem& p, const GhPhase1State& state) {
    std::vector<GhPhase1Candidate> candidates;
    for (std::size_t j = 0; j < p.J(); ++j)
        for (std::size_t k = 0; k < p.K(); ++k)
            candidates.push_back(phase1_candidate(p, state, j, k));
    return candidates;
}

const GhDeployment* deployment_for(const GhPhase2State& state, std::size_t j, std::size_t k) {
    const auto it = std::find_if(state.deployments.begin(), state.deployments.end(),
        [=](const auto& deployment) { return deployment.model == j && deployment.tier == k; });
    return it == state.deployments.end() ? nullptr : &*it;
}

Placement canonicalize(const Problem& p, const GhPhase2State& state) {
    auto placement = Placement::zero(p);
    placement.x = state.x;
    placement.u = state.unmet;
    for (const auto& deployment : state.deployments) {
        const auto j = deployment.model, k = deployment.tier, c = deployment.configuration;
        placement.q[p.pair(j, k)] = 1.0;
        placement.y[p.pair(j, k)] = p.tiers[k].configs[c].gpu_count();
        placement.w[p.pc(j, k, c)] = 1.0;
    }
    for (std::size_t i = 0; i < p.I(); ++i)
        for (std::size_t j = 0; j < p.J(); ++j)
            for (std::size_t k = 0; k < p.K(); ++k) {
                const auto route = p.route(i, j, k);
                placement.z[route] = placement.x[route] > 0.0;
                for (std::size_t c = 0; c < p.tiers[k].configs.size(); ++c)
                    placement.v[p.vc(i, j, k, c)] = placement.x[route] * placement.w[p.pc(j, k, c)];
            }
    return placement;
}

GhBudget sparse_budget(const Problem& p, const GhPhase2State& state) {
    std::vector<double> gpu, weights, data;
    for (const auto& deployment : state.deployments)
        gpu.push_back(p.tiers[deployment.tier].rental *
                      p.tiers[deployment.tier].configs[deployment.configuration].gpu_count());
    for (const auto route : state.route_insertion_order) {
        const auto i = route / (p.J() * p.K());
        const auto j = (route / p.K()) % p.J();
        const auto& query = p.queries[i];
        weights.push_back(p.models[j].weight);
        data.push_back(query.storage * query.total_tokens() * query.arrival * state.x[route]);
    }
    GhBudget result;
    result.c1 = p.horizon * python_sum(gpu);
    result.c2 = p.horizon * p.storage_price * python_sum(weights);
    result.c3 = p.horizon * p.storage_price * python_sum(data);
    if (p.coherent) result.c3 *= p.data_residency;
    return result;
}

void check_carried_budget(const Problem& p, const GhPhase2State& state) {
    if (state.budget_used + state.remaining_budget != p.budget)
        throw std::runtime_error("accumulated and remaining budget must sum to delta");
}

GhCandidate phase2_candidate(const Problem& p, const GhPhase2State& state,
                             std::size_t i, std::size_t j, std::size_t k) {
    GhCandidate candidate;
    candidate.query = i;
    candidate.model = j;
    candidate.tier = k;
    const auto* deployment = deployment_for(state, j, k);
    int current_gpus = 0;
    double delay = 0.0;
    if (!deployment) {
        candidate.source = "m1_inactive_pair";
        candidate.m1 = m1_worker(p, i, j, k);
        candidate.selected_configuration = candidate.m1->selected;
        if (!candidate.selected_configuration) {
            candidate.rejection = "m1_no_feasible_configuration";
            return candidate;
        }
        delay = candidate.m1->diagnostics[*candidate.selected_configuration].delay;
    } else {
        candidate.current_configuration = static_cast<int>(deployment->configuration);
        current_gpus = p.tiers[k].configs[deployment->configuration].gpu_count();
        delay = configuration_delay(p, i, j, k, deployment->configuration);
        if (delay <= p.queries[i].delay_slo) {
            candidate.source = "current_active_configuration";
            candidate.selected_configuration = deployment->configuration;
        } else {
            candidate.source = "m3_active_pair_upgrade";
            candidate.m3 = m3_worker(p, i, j, k, candidate.current_configuration, state.remaining_budget);
            candidate.selected_configuration = candidate.m3->selected;
            if (!candidate.selected_configuration) {
                candidate.rejection = "m3_no_feasible_upgrade";
                return candidate;
            }
            delay = candidate.m3->diagnostics[*candidate.selected_configuration].delay;
        }
    }
    candidate.m2 = m2_worker(p, i, j, k, *candidate.selected_configuration, delay,
        {state.remaining[i], state.cumulative_error[i], state.cumulative_delay[i], current_gpus});
    if (!candidate.m2->rankable()) candidate.rejection = "m2_zero_effective_coverage";
    return candidate;
}

GhAttempt commit_candidate(const Problem& p, const GhPhase2State& state,
                           const GhCandidate& candidate, std::size_t ranked_position) {
    GhAttempt attempt;
    attempt.ranked_position = ranked_position;
    attempt.before = state;
    attempt.after = state;
    attempt.allocation = std::min(state.unmet[candidate.query], candidate.m2->coverage());
    if (attempt.allocation <= 0.0) {
        attempt.rejection_reasons.push_back("zero_allocation");
        return attempt;
    }
    attempt.prior_budget = sparse_budget(p, state);
    auto proposal = state;
    const auto i = candidate.query, j = candidate.model, k = candidate.tier;
    const auto c = *candidate.selected_configuration;
    auto it = std::find_if(proposal.deployments.begin(), proposal.deployments.end(),
        [=](const auto& deployment) { return deployment.model == j && deployment.tier == k; });
    if (it == proposal.deployments.end())
        proposal.deployments.push_back({j, k, c, {}, 0.0});
    else
        it->configuration = c;
    const auto route = p.route(i, j, k);
    if (proposal.x[route] == 0.0) proposal.route_insertion_order.push_back(route);
    proposal.x[route] = proposal.x[route] + attempt.allocation;
    proposal.unmet[i] -= attempt.allocation;
    const auto decisions = canonicalize(p, proposal);
    attempt.resource_validation = resource_diagnostics(p, decisions);
    attempt.prospective_budget = sparse_budget(p, proposal);
    const auto add_failure = [&](const std::string& family, const std::string& reason) {
        if (std::any_of(attempt.resource_validation.residuals.begin(),
                        attempt.resource_validation.residuals.end(),
                        [&](const auto& residual) { return residual.family == family && residual.slack < 0.0; }))
            attempt.rejection_reasons.push_back(reason);
    };
    add_failure("gpu_memory", "gpu_memory");
    add_failure("compute_capacity", "compute_capacity");
    add_failure("storage_capacity", "storage");
    if (p.budget - attempt.prospective_budget.total() < 0.0)
        attempt.rejection_reasons.push_back("global_budget");
    if (!attempt.rejection_reasons.empty()) return attempt;
    proposal.remaining[i] -= attempt.allocation;
    proposal.cumulative_error[i] += p.error[route] * attempt.allocation;
    proposal.cumulative_delay[i] += candidate.m2->fixed_delay * attempt.allocation;
    proposal.budget_used = attempt.prospective_budget.total();
    proposal.remaining_budget = p.budget - proposal.budget_used;
    check_carried_budget(p, proposal);
    attempt.after = std::move(proposal);
    return attempt;
}

} // namespace

std::optional<double> M2Result::error_limit() const {
    return coverage_limit(error_slo - inputs.cumulative_error, effective_error);
}
std::optional<double> M2Result::delay_limit() const {
    return coverage_limit(delay_slo - inputs.cumulative_delay, fixed_delay);
}
double M2Result::coverage() const {
    double minimum = inputs.remaining_demand;
    if (const auto limit = error_limit()) minimum = std::min(minimum, *limit);
    if (const auto limit = delay_limit()) minimum = std::min(minimum, *limit);
    return std::max(0.0, minimum);
}
double M2Result::kappa() const {
    if (!rankable()) throw std::logic_error("zero coverage has no M2 rank");
    return marginal_cost() / coverage();
}
double GhPhase1Candidate::coverage_per_cost() const {
    if (!rankable()) throw std::logic_error("unrankable Phase-1 candidate");
    return *activation_cost == 0.0 ? std::numeric_limits<double>::infinity() :
           static_cast<double>(covered_queries.size()) / *activation_cost;
}

M1Result select_m1(const Problem& p, std::size_t i, std::size_t j, std::size_t k) {
    check_indices(p, i, j, k);
    return m1_worker(p, i, j, k);
}
M3Result select_m3(const Problem& p, std::size_t i, std::size_t j, std::size_t k,
                   int current_configuration, double remaining_budget) {
    check_indices(p, i, j, k);
    if (!std::isfinite(remaining_budget)) throw std::invalid_argument("remaining budget must be finite");
    if (current_configuration < -1) throw std::invalid_argument("invalid current configuration");
    return m3_worker(p, i, j, k, current_configuration, remaining_budget);
}
M2Result evaluate_m2(const Problem& p, std::size_t i, std::size_t j, std::size_t k,
                      std::size_t configuration, double fixed_delay, M2Inputs inputs) {
    check_indices(p, i, j, k);
    if (configuration >= p.tiers[k].configs.size() || !std::isfinite(fixed_delay) || fixed_delay < 0.0 ||
        !std::isfinite(inputs.remaining_demand) || inputs.remaining_demand < 0.0 || inputs.remaining_demand > 1.0 ||
        !std::isfinite(inputs.cumulative_error) || inputs.cumulative_error < 0.0 ||
        !std::isfinite(inputs.cumulative_delay) || inputs.cumulative_delay < 0.0 || inputs.current_gpu_count < 0)
        throw std::invalid_argument("invalid M2 configuration or dynamic inputs");
    return m2_worker(p, i, j, k, configuration, fixed_delay, inputs);
}

GhPhase1 run_gh_phase1(const Problem& p, const GhOptions& options) {
    require_prepared(p);
    check_options(options);
    GhPhase1 result;
    result.initial.uncovered_queries.resize(p.I());
    std::iota(result.initial.uncovered_queries.begin(), result.initial.uncovered_queries.end(), 0);
    result.initial.cap = options.budget_fraction * p.budget;
    auto state = result.initial;
    while (!state.uncovered_queries.empty() && state.rental < state.cap) {
        auto candidates = phase1_candidates(p, state);
        std::vector<std::size_t> ranked;
        for (std::size_t position = 0; position < candidates.size(); ++position)
            if (candidates[position].rankable()) ranked.push_back(position);
        std::stable_sort(ranked.begin(), ranked.end(), [&](auto a, auto b) {
            return candidates[a].coverage_per_cost() > candidates[b].coverage_per_cost();
        });
        if (ranked.empty()) {
            result.final = state;
            result.termination = "no_rankable_candidate";
            result.terminal_candidates = std::move(candidates);
            return result;
        }
        const auto& selected = candidates[ranked.front()];
        auto next = state;
        std::erase_if(next.uncovered_queries, [&](auto i) {
            return std::find(selected.covered_queries.begin(), selected.covered_queries.end(), i) !=
                   selected.covered_queries.end();
        });
        next.deployments.push_back({selected.model, selected.tier,
            *selected.common_configuration, selected.covered_queries, *selected.activation_cost});
        next.rental = state.rental + *selected.activation_cost;
        result.iterations.push_back({state, next, std::move(candidates), std::move(ranked)});
        state = std::move(next);
    }
    result.final = std::move(state);
    result.termination = result.final.uncovered_queries.empty() ?
                         "all_queries_covered" : "rental_cap_reached";
    return result;
}

GhResult detail::run_gh_with_phase1(const Problem& p, const GhOptions& options,
                                    const std::vector<std::size_t>& query_order,
                                    const GhPhase1& phase1) {
    GhResult result;
    result.phase1 = phase1;
    auto& initial = result.initial;
    initial.deployments = result.phase1.final.deployments;
    initial.query_order = query_order;
    if (query_order.empty()) {
        initial.query_order.resize(p.I());
        std::iota(initial.query_order.begin(), initial.query_order.end(), 0);
        std::stable_sort(initial.query_order.begin(), initial.query_order.end(), [&](auto a, auto b) {
            return p.queries[a].arrival > p.queries[b].arrival;
        });
    } else {
        auto sorted = query_order;
        std::sort(sorted.begin(), sorted.end());
        if (sorted.size() != p.I()) throw std::invalid_argument("query order must contain every query exactly once");
        for (std::size_t i = 0; i < sorted.size(); ++i)
            if (sorted[i] != i) throw std::invalid_argument("query order must be an exact semantic permutation");
    }
    initial.x.assign(p.I() * p.J() * p.K(), 0.0);
    initial.unmet.assign(p.I(), 1.0);
    initial.remaining.assign(p.I(), 1.0);
    initial.cumulative_error.assign(p.I(), 0.0);
    initial.cumulative_delay.assign(p.I(), 0.0);
    initial.budget_used = result.phase1.final.rental;
    initial.remaining_budget = p.budget - initial.budget_used;
    check_carried_budget(p, initial);
    auto state = initial;
    for (const auto i : initial.query_order) {
        GhQueryTrace trace;
        trace.query = i;
        trace.before = state;
        for (std::size_t j = 0; j < p.J(); ++j)
            for (std::size_t k = 0; k < p.K(); ++k)
                trace.candidates.push_back(phase2_candidate(p, state, i, j, k));
        for (std::size_t position = 0; position < trace.candidates.size(); ++position)
            if (trace.candidates[position].rankable()) trace.ranked_candidates.push_back(position);
        std::stable_sort(trace.ranked_candidates.begin(), trace.ranked_candidates.end(), [&](auto a, auto b) {
            const auto& left = *trace.candidates[a].m2;
            const auto& right = *trace.candidates[b].m2;
            return left.pi() != right.pi() ? left.pi() < right.pi() : left.kappa() < right.kappa();
        });
        // All selected configurations, coverage and ranks stay frozen at query
        // entry. Only resource decisions and the allocation min use current state.
        for (std::size_t rank = 0; rank < trace.ranked_candidates.size() && state.unmet[i] > 0.0; ++rank) {
            auto attempt = commit_candidate(p, state, trace.candidates[trace.ranked_candidates[rank]], rank);
            if (attempt.committed()) state = attempt.after;
            trace.attempts.push_back(std::move(attempt));
        }
        trace.after = state;
        trace.termination = state.unmet[i] == 0.0 ? "query_fully_served" :
                            "candidates_exhausted_with_residual_demand";
        result.queries.push_back(std::move(trace));
    }
    result.final = state;
    result.placement = canonicalize(p, state);
    result.validation = validate(p, result.placement, options.tolerances);
    return result;
}

GhResult run_gh(const Problem& p, const GhOptions& options,
                const std::vector<std::size_t>& query_order) {
    require_prepared(p);
    check_options(options);
    const auto phase1 = run_gh_phase1(p, options);
    return detail::run_gh_with_phase1(p, options, query_order, phase1);
}

} // namespace pacs
