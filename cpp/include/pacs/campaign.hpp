#pragma once

#include "pacs/agh.hpp"

#include <span>
#include <string>
#include <variant>
#include <vector>

namespace pacs {

enum class CampaignMethod { gh, agh };
enum class CampaignSchedule { serial, static_schedule, dynamic_schedule };

// Each independent case owns its prepared problem, options and local RNG seed.
// Neither its algorithm nor another case may modify these inputs during a run.
struct CampaignCase {
    Problem problem;
    GhOptions options;
    std::string seed, name;
    CampaignMethod method{CampaignMethod::gh};
};

using CampaignCaseResult = std::variant<GhResult, AghResult>;

struct CampaignResult {
    int requested_threads{}, actual_threads{};
    // Results retain the input order, irrespective of worker completion order.
    std::vector<CampaignCaseResult> cases;
};

// Borrow inputs only for this call. GH/AGH scientific validation remains owned
// by those algorithms. Exceptions are rethrown in input order after all workers
// finish; no exception escapes an OpenMP region and no partial result is returned.
CampaignResult run_campaign(std::span<const CampaignCase>, CampaignSchedule,
                            int thread_count = 1);

} // namespace pacs
