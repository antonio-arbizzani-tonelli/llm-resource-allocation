#include "pacs/campaign.hpp"
#include "pacs/io.hpp"

#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace {

using namespace pacs;

void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}

Problem fixture(std::size_t query_count) {
    Problem p;
    p.queries.assign(query_count, {1, 1, 0, 0, 10, 0.1, 0, 1, 0});
    p.models = {{1, 0}};
    p.tiers = {{100, 1, 1, {{1, 1}}}};
    p.error.assign(query_count, 0.01);
    p.compute_delay.assign(query_count, 0.1);
    p.communication_delay.assign(query_count, 0);
    p.alpha.assign(query_count, 1);
    p.residency_seconds.assign(query_count, 1);
    p.storage_price = 0;
    p.budget = 100;
    p.storage_capacity = 100;
    p.horizon = 1;
    p.eta = 1;
    p.prepare();
    return p;
}

void require_complete(const Problem& p, const Placement& state, const Validation& report) {
    // One rented GPU serves every query: C1=1, C2-C5=0, x=z=v=1, u=0.
    require(state.x == std::vector<double>(p.I(), 1), "campaign hand-derived routing");
    require(state.z == state.x && state.v == state.x, "campaign canonical auxiliary state");
    require(state.u == std::vector<double>(p.I(), 0), "campaign complete demand coverage");
    require(state.q == std::vector<double>{1} && state.w == state.q && state.y == state.q,
            "campaign single-GPU deployment");
    require(report.feasible && report.objective.c1 == 1
            && report.objective.c2 == 0 && report.objective.c3 == 0
            && report.objective.c4 == 0 && report.objective.c5 == 0,
            "campaign hand-derived C1-C5 and independent feasibility");
    require(report.delay == std::vector<double>(p.I(), 0.1)
            && report.error == std::vector<double>(p.I(), 0.01),
            "campaign hand-derived query metrics");
}

void test_campaign_results(CampaignSchedule schedule) {
    const std::vector<CampaignCase> cases{
        {fixture(1), {}, "37", "one GH", CampaignMethod::gh},
        {fixture(3), {}, "-1208925819614629174706176", "three AGH", CampaignMethod::agh},
        {fixture(2), {}, "0", "two GH", CampaignMethod::gh},
        {fixture(1), {}, "37", "one AGH", CampaignMethod::agh}
    };
    const auto result = run_campaign(cases, schedule, 4);
    require(result.cases.size() == cases.size(), "one result per case");
    require(result.requested_threads == 4, "requested team metadata");
    require(result.actual_threads >= 1 && result.actual_threads <= 4,
            "actual team metadata respects runtime limits");
    if (schedule == CampaignSchedule::serial) {
        require(result.actual_threads == 1, "serial baseline has one worker");
    }
    for (std::size_t i = 0; i < cases.size(); ++i) {
        if (cases[i].method == CampaignMethod::gh) {
            const auto& gh = std::get<GhResult>(result.cases[i]);
            require_complete(cases[i].problem, gh.placement, gh.validation);
            require(gh.queries.size() == cases[i].problem.I(), "GH trace belongs to its input slot");
        } else {
            const auto& agh = std::get<AghResult>(result.cases[i]);
            require(agh.completed() && agh.final_placement() && agh.final_validation,
                    "AGH completed campaign result");
            require_complete(cases[i].problem, *agh.final_placement(), *agh.final_validation);
            const auto& multi = agh.multistart;
            require(multi.random_seed == cases[i].seed, "case-local decimal seed preserved");
            require(multi.incumbent_index == 0 && multi.starts.size() == 6
                    && multi.nonimprovement_count == 5
                    && multi.termination_reason == "five_consecutive_nonimproving",
                    "AGH ordered incumbent and early stopping unchanged");
            for (std::size_t index = 0; index < multi.starts.size(); ++index) {
                require(multi.starts[index].counter_after == index,
                        "AGH per-start nonimprovement evidence");
                require(multi.starts[index].start.ordering.queries.size() == cases[i].problem.I(),
                        "AGH trace belongs to its input slot");
            }
        }
    }
    // Inputs remain owned by their caller; workers never consume or mutate them.
    require(cases[1].problem.queries.size() == 3 && cases[1].seed == "-1208925819614629174706176",
            "campaign preserves caller-owned inputs");
}

void test_failed_scientific_result(CampaignSchedule schedule) {
    auto p = fixture(1);
    p.error[0] = 0.2; // No feasible M1; max_unmet=0 rejects the complete placement.
    const std::vector<CampaignCase> cases{
        {std::move(p), {}, "37", "infeasible AGH", CampaignMethod::agh},
        {fixture(1), {}, "37", "feasible GH", CampaignMethod::gh}
    };
    const auto result = run_campaign(cases, schedule, 4);
    const auto& agh = std::get<AghResult>(result.cases[0]);
    require(!agh.completed() && !agh.final_placement() && !agh.final_validation,
            "scientifically failed result is preserved without repair");
    require(agh.completion_status == "no_feasible_incumbent"
            && agh.multistart.starts.size() == 5,
            "failed AGH early stopping evidence");
    const auto& gh = std::get<GhResult>(result.cases[1]);
    require_complete(cases[1].problem, gh.placement, gh.validation);
}

void test_exception_order(CampaignSchedule schedule) {
    std::vector<CampaignCase> cases{
        {fixture(1), {}, "37", "valid first", CampaignMethod::gh},
        {fixture(1), {}, "invalid seed", "first failing case", CampaignMethod::agh},
        {fixture(1), {}, "37", "second failing case", CampaignMethod::gh}
    };
    cases[2].options.budget_fraction = -1;
    bool original_exception = false;
    try {
        (void)run_campaign(cases, schedule, 4);
    } catch (const std::invalid_argument& error) {
        original_exception = std::string(error.what()) == "AGH seed must be a decimal integer";
    }
    require(original_exception, "first failing input rethrows its original exception after join");
}

void test_campaign_boundaries() {
    const std::vector<CampaignCase> cases{{fixture(1), {}, "37", "GH", CampaignMethod::gh}};
    const auto rejects = [&](std::span<const CampaignCase> input, CampaignSchedule schedule, int threads) {
        try {
            (void)run_campaign(input, schedule, threads);
        } catch (const std::invalid_argument&) {
            return true;
        }
        return false;
    };
    require(rejects(cases, CampaignSchedule::serial, 0), "reject zero thread count");
    require(rejects(cases, CampaignSchedule::dynamic_schedule, -1), "reject negative thread count");
    require(rejects({}, CampaignSchedule::serial, 1), "reject empty campaign");
    require(rejects(cases, static_cast<CampaignSchedule>(-1), 1), "reject unknown schedule");
    auto invalid = cases;
    invalid[0].method = static_cast<CampaignMethod>(-1);
    require(rejects(invalid, CampaignSchedule::static_schedule, 4), "reject unknown case method");
}

void test_json_quoting() {
    std::ostringstream output;
    const std::string text = std::string("quote\" slash\\ newline\n nul") + '\0';
    io::quoted(output, text);
    require(output.str() == "\"quote\\\" slash\\\\ newline\\u000a nul\\u0000\"",
            "shared JSON adapter escapes quote, backslash, newline and NUL");
}

} // namespace

int main() {
    try {
        for (const auto schedule : {CampaignSchedule::serial,
                                   CampaignSchedule::static_schedule,
                                   CampaignSchedule::dynamic_schedule}) {
            test_campaign_results(schedule);
            test_failed_scientific_result(schedule);
            test_exception_order(schedule);
        }
        test_campaign_boundaries();
        test_json_quoting();
        std::cout << "campaign serial/static/dynamic tests passed\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
