#include "pacs/gh.hpp"

#include <cmath>
#include <limits>
#include <stdexcept>
#include <string>

namespace {
void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}
void near(double actual, double expected, const char* message) {
    if (!std::isfinite(actual) || !std::isfinite(expected)
        || !(std::abs(actual - expected) <= 1e-12))
        throw std::runtime_error(std::string(message) + ": " + std::to_string(actual));
}

void test_numerical_assertion() {
    const double nan=std::numeric_limits<double>::quiet_NaN();
    const double infinity=std::numeric_limits<double>::infinity();
    for (const double invalid:{nan,infinity,-infinity}) {
        bool rejected_actual=false, rejected_expected=false, rejected_equal=false;
        try { near(invalid,0,"nonfinite actual"); }
        catch (const std::runtime_error&) { rejected_actual=true; }
        try { near(0,invalid,"nonfinite expected"); }
        catch (const std::runtime_error&) { rejected_expected=true; }
        try { near(invalid,invalid,"equal nonfinite operands"); }
        catch (const std::runtime_error&) { rejected_equal=true; }
        require(rejected_actual && rejected_expected && rejected_equal,
                "numerical assertion rejects NaN and infinities in either operand");
    }
}
pacs::Problem fixture(std::size_t queries = 1, std::size_t models = 1) {
    pacs::Problem p;
    p.queries.assign(queries, {1.0, 2.0, 1.0, 0.001, 1.0, 0.1, 1e-6, 10.0, 0.5});
    p.models.assign(models, {1.0, 0.001});
    p.tiers = {{8.0, 10.0, 1.0, {{1, 1}, {2, 1}, {4, 1}}}};
    p.error.assign(queries * models, 0.05);
    p.compute_delay.assign(queries * models, 0.1);
    p.communication_delay.assign(queries * models, 0.01);
    p.alpha.assign(queries * models, 1.0);
    p.residency_seconds.assign(queries * models, 1.0);
    p.storage_price = 0.001;
    p.budget = 20.0;
    p.storage_capacity = 100.0;
    p.horizon = 1.0;
    p.eta = 0.9;
    p.coherent = false; // Explicitly historical fixtures isolate Algorithm 1.
    p.prepare();
    return p;
}

void test_mechanisms() {
    auto p = fixture();
    const auto m1 = pacs::select_m1(p, 0, 0, 0);
    require(m1.selected == 0, "M1 minimum feasible product");
    near(m1.diagnostics[0].delay, 0.31, "M1 TTFT plus generation");
    near(m1.diagnostics[1].delay, 0.16, "M1 TP2 delay");
    p.models[0].weight = 8.0;
    p.tiers[0].capacity = 5.0;
    require(pacs::select_m1(p, 0, 0, 0).selected == 1, "M1 memory requires TP2");
    p.queries[0].delay_slo = 0.01;
    require(!pacs::select_m1(p, 0, 0, 0).selected, "M1 rejects jointly infeasible configurations");

    p = fixture();
    p.tiers[0].configs = {{1, 2}, {1, 1}, {2, 2}, {2, 1}};
    p.models[0].weight = 8.0;
    p.tiers[0].capacity = 5.0;
    p.prepare();
    require(pacs::select_m1(p, 0, 0, 0).selected == 0, "M1 equal product keeps tier order");
    p.tiers[0].configs = {{1, 1}, {4, 1}};
    p.models[0].weight = 8.0;
    p.tiers[0].capacity = 3.0;
    p.prepare();
    require(pacs::select_m1(p, 0, 0, 0).selected == 1, "M1 only supported configurations");

    p = fixture();
    p.queries[0].delay_slo = 0.2;
    p.horizon = 2.0;
    p.tiers[0].rental = 3.0;
    const auto m3 = pacs::select_m3(p, 0, 0, 0, 0, 6.0);
    require(m3.selected == 1, "M3 inclusive incremental budget boundary");
    near(m3.diagnostics[1].incremental_cost, 6.0, "M3 incremental rental");
    require(pacs::select_m3(p, 0, 0, 0, 0, 5.99).no_upgrade_reason ==
            "insufficient_remaining_budget", "M3 refuses unaffordable upgrade");
    require(pacs::select_m3(p, 0, 0, 0, 1, 6.0).no_upgrade_reason ==
            "current_delay_within_slo", "M3 applies only above delay SLO");
    require(pacs::select_m3(p, 0, 0, 0, -1, 6.0).no_upgrade_reason ==
            "inactive_pair", "M3 never activates an inactive pair");

    p = fixture();
    auto m2 = pacs::evaluate_m2(p, 0, 0, 0, 0, 0.31, {1.0, 0.0, 0.0, 0});
    near(m2.incremental_gpu_cost, 1.0, "M2 full incremental GPU cost");
    near(m2.storage_cost, 0.001003, "M2 weight plus hourly data storage");
    near(m2.delay_cost, 0.00000031, "M2 literal delay cost");
    near(m2.coverage(), 1.0, "M2 full remaining coverage");
    m2 = pacs::evaluate_m2(p, 0, 0, 0, 0, 0.31, {1.0, 0.075, 0.0, 1});
    near(m2.coverage(), 0.5, "M2 residual error cap");
    require(m2.pi() == 1, "M2 marks partial coverage");
    near(m2.incremental_gpu_cost, 0.0, "M2 active GPU cost is zero");
    p.error[0] = 0.0;
    m2 = pacs::evaluate_m2(p, 0, 0, 0, 0, 0.0, {0.25, 0.0, 0.0, 1});
    require(!m2.error_limit() && !m2.delay_limit(), "M2 zero consumption is nonbinding");
    near(m2.coverage(), 0.25, "M2 zero denominators keep demand cap");
    m2 = pacs::evaluate_m2(p, 0, 0, 0, 0, 0.0, {0.25, 0.2, 0.0, 1});
    near(m2.coverage(), 0.0, "M2 zero consumption cannot repair exceeded budget");

    p = fixture();
    p.coherent = true;
    p.queries[0] = {6.0, 60.0, 40.0, 0.002, 1.0, 0.1, 0.02, 10.0, 0.5};
    p.models[0].weight = 4.0;
    p.horizon = 3.0;
    p.storage_price = 0.25;
    p.data_residency = 2.0;
    const auto coherent = pacs::evaluate_m2(p, 0, 0, 0, 0, 0.1, {1.0, 0.0, 0.0, 0});
    near(coherent.incremental_gpu_cost, 3.0, "coherent M2 period rental");
    near(coherent.storage_cost, 4.8, "coherent M2 resident data stock");
    near(coherent.delay_cost, 36.0, "coherent M2 period arrivals and milliseconds");
    near(coherent.marginal_cost(), 43.8, "coherent M2 hand total");
}

void test_phase1() {
    auto p = fixture(2, 2);
    p.models[1].weight = 3.0;
    p.tiers[0].capacity = 1.0;
    p.tiers[0].configs = {{1, 1}, {3, 1}};
    p.error = {0.05, 0.2, 0.2, 0.05};
    p.budget = 2.0;
    p.prepare();
    const auto overshoot = pacs::run_gh_phase1(p, {0.8, {}});
    require(overshoot.iterations.size() == 2, "Phase1 reevaluates uncovered query set");
    near(overshoot.final.rental, 4.0, "Phase1 pre-iteration cap permits overshoot");
    require(overshoot.termination == "all_queries_covered", "coverage precedence over cap");
    require(overshoot.iterations[0].after.uncovered_queries == std::vector<std::size_t>{1},
            "Phase1 ordered set subtraction");
    require(overshoot.iterations[1].candidates[0].covered_queries.empty(),
            "Phase1 coverage is recomputed");
    const auto equality = pacs::run_gh_phase1(p, {0.5, {}});
    require(equality.iterations.size() == 1 && equality.termination == "rental_cap_reached",
            "Phase1 cap equality stops at guard");
    const auto zero = pacs::run_gh_phase1(p, {0.0, {}});
    require(zero.iterations.empty(), "zero Phase1 cap skips loop");

    p = fixture(1, 2);
    const auto tie = pacs::run_gh_phase1(p);
    require(tie.final.deployments.front().model == 0, "Phase1 stable candidate tie");
    p.queries[0].error_slo = 0.01;
    const auto impossible = pacs::run_gh_phase1(p);
    require(impossible.termination == "no_rankable_candidate" &&
            impossible.terminal_candidates.size() == 2, "Phase1 explicit nonrankable stop");
}

void test_complete_gh() {
    const pacs::GhOptions no_preallocation{0.0, {}};
    auto p = fixture(1, 2);
    auto result = pacs::run_gh(p, no_preallocation);
    require(result.scientifically_usable(), "tiny GH independently feasible");
    require(result.queries[0].ranked_candidates == std::vector<std::size_t>({0, 1}),
            "M2 candidate exact tie is stable");
    require(result.queries[0].attempts.size() == 1 && result.placement.x[0] == 1.0 &&
            result.placement.x[1] == 0.0, "full first candidate stops traversal");
    near(result.validation.objective.total(), 1.00100331, "GH independently recomputed hand objective");

    p.queries[0].error_slo = 0.025;
    result = pacs::run_gh(p, no_preallocation);
    require(result.algorithm_completed && !result.validation.feasible,
            "literal frozen GH completion is separate from feasibility");
    require(result.queries[0].attempts.size() == 2, "frozen GH retains second partial candidate");
    near(result.placement.x[0], 0.5, "frozen GH first half");
    near(result.placement.x[1], 0.5, "frozen GH original second half");
    near(result.final.cumulative_error[0], 0.05, "frozen GH error overshoot remains visible");
    near(result.queries[0].candidates[1].m2->coverage(), 0.5, "original second M2 is frozen");

    p = fixture();
    p.queries[0].error_slo = 0.025;
    result = pacs::run_gh(p, no_preallocation);
    require(result.scientifically_usable(), "one partial candidate meets explicit unmet cap");
    near(result.placement.u[0], 0.5, "GH copies remaining unmet directly");
    near(result.placement.v[0], 0.5, "GH exact auxiliary mapping");

    p = fixture(1, 2);
    p.models[0].kv = 100.0;
    result = pacs::run_gh(p, no_preallocation);
    require(result.queries[0].attempts.size() == 2, "rejected resource candidate continues");
    require(result.queries[0].attempts[0].rejection_reasons == std::vector<std::string>{"gpu_memory"},
            "memory rejection is retained");
    require(result.placement.x[0] == 0.0 && result.placement.x[1] == 1.0,
            "rejection preserves exact prior state");

    p = fixture(1, 2);
    p.alpha[0] = 1e9;
    result = pacs::run_gh(p, no_preallocation);
    require(result.queries[0].attempts[0].rejection_reasons == std::vector<std::string>{"compute_capacity"},
            "compute rejection is retained");
    require(result.placement.x[1] == 1.0, "compute rejection continues to safe candidate");

    p = fixture();
    p.storage_capacity = 0.5;
    result = pacs::run_gh(p, no_preallocation);
    require(result.queries[0].attempts[0].rejection_reasons == std::vector<std::string>{"storage"},
            "query storage rejection is retained");
    p = fixture();
    p.budget = 0.5;
    result = pacs::run_gh(p, no_preallocation);
    require(result.queries[0].attempts[0].rejection_reasons == std::vector<std::string>{"global_budget"},
            "global resource budget rejection is retained");
    near(result.final.unmet[0], 1.0, "failed construction keeps unserved demand");

    p = fixture(1, 2);
    p.models[1].weight = 20.0;
    p.error = {0.2, 0.01};
    result = pacs::run_gh(p, no_preallocation);
    require(result.queries[0].ranked_candidates.front() == 1,
            "M2 full coverage precedes cheaper partial coverage");
    require(result.queries[0].candidates[1].m2->kappa() > result.queries[0].candidates[0].m2->kappa(),
            "full coverage priority dominates unit cost");
    require(result.placement.y[1] == 4.0 && result.placement.x[1] == 1.0,
            "GH commits expensive full-coverage configuration");

    p = fixture(2, 1);
    p.queries[0].arrival = 2.0;
    p.queries[1].delay_slo = 0.2;
    result = pacs::run_gh(p, no_preallocation);
    require(result.queries[1].candidates[0].source == "m3_active_pair_upgrade",
            "later GH query uses active M3 branch");
    require(result.placement.y[0] == 2.0, "M3 replaces one active configuration");
    near(result.final.cumulative_delay[0], 0.31, "earlier GH delay evidence persists after M3");
    near(result.validation.delay[0], 0.16, "final validator uses final supplied auxiliary state");
    const auto overridden = pacs::run_gh(p, no_preallocation, {1, 0});
    require(overridden.queries[0].query == 1 && overridden.queries[1].query == 0,
            "explicit AGH ordering reaches GH Phase2");
    const auto cached = pacs::run_gh_phase1(p, no_preallocation);
    const auto from_cache = pacs::detail::run_gh_with_phase1(p, no_preallocation, {}, cached);
    require(from_cache.placement.x == result.placement.x && from_cache.placement.w == result.placement.w,
            "cached Phase1 preserves GH output");
}
} // namespace

void test_gh() {
    test_numerical_assertion();
    test_mechanisms();
    test_phase1();
    test_complete_gh();
}
