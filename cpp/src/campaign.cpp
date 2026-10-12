#include "pacs/campaign.hpp"

#include <exception>
#include <limits>
#include <optional>
#include <stdexcept>
#include <utility>

#include <omp.h>

namespace pacs {
namespace {

void run_one(const CampaignCase& input,
             std::optional<CampaignCaseResult>& output,
             std::exception_ptr& error) noexcept {
    try {
        if (input.method == CampaignMethod::gh) {
            output.emplace(std::in_place_type<GhResult>,
                           run_gh(input.problem, input.options));
        } else {
            output.emplace(std::in_place_type<AghResult>,
                           run_agh(input.problem, input.seed, input.options));
        }
    } catch (...) {
        // Save the original exception; the coordinator rethrows after the join.
        error = std::current_exception();
    }
}

} // namespace

CampaignResult run_campaign(std::span<const CampaignCase> cases,
                            CampaignSchedule schedule, int thread_count) {
    if (thread_count <= 0) {
        throw std::invalid_argument("campaign thread count must be positive");
    }
    if (schedule != CampaignSchedule::serial
        && schedule != CampaignSchedule::static_schedule
        && schedule != CampaignSchedule::dynamic_schedule) {
        throw std::invalid_argument("unknown campaign schedule");
    }
    if (cases.empty()
        || cases.size() > static_cast<std::size_t>(std::numeric_limits<std::ptrdiff_t>::max())) {
        throw std::invalid_argument("campaign requires a positive, representable case count");
    }
    for (const auto& input : cases) {
        if (input.method != CampaignMethod::gh && input.method != CampaignMethod::agh) {
            throw std::invalid_argument("unknown campaign method");
        }
    }

    // Workers write distinct pre-existing slots. No vector grows in the region.
    std::vector<std::optional<CampaignCaseResult>> outputs(cases.size());
    std::vector<std::exception_ptr> errors(cases.size());
    const auto count = static_cast<std::ptrdiff_t>(cases.size());
    int actual_threads = 1;
    if (schedule == CampaignSchedule::serial) {
        for (std::ptrdiff_t i = 0; i < count; ++i) {
            run_one(cases[i], outputs[i], errors[i]);
        }
    } else {
        // Thread count is scoped to this region; process-global OpenMP settings
        // are neither changed nor assumed. Report the runtime's actual team size.
        #pragma omp parallel default(none) num_threads(thread_count) \
            shared(cases, outputs, errors, actual_threads, schedule, count)
        {
            #pragma omp single
            actual_threads = omp_get_num_threads();

            if (schedule == CampaignSchedule::static_schedule) {
                #pragma omp for schedule(static)
                for (std::ptrdiff_t i = 0; i < count; ++i) {
                    run_one(cases[i], outputs[i], errors[i]);
                }
            } else {
                #pragma omp for schedule(dynamic, 1)
                for (std::ptrdiff_t i = 0; i < count; ++i) {
                    run_one(cases[i], outputs[i], errors[i]);
                }
            }
        }
    }

    for (const auto& error : errors) {
        if (error) std::rethrow_exception(error);
    }
    CampaignResult result{thread_count, actual_threads, {}};
    result.cases.reserve(cases.size());
    for (auto& output : outputs) {
        result.cases.push_back(std::move(*output));
    }
    return result;
}

} // namespace pacs
