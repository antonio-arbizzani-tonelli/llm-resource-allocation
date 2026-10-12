#include "pacs/campaign.hpp"
#include "pacs/io.hpp"

#include <algorithm>
#include <charconv>
#include <chrono>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <optional>
#include <stdexcept>
#include <string>
#include <utility>

namespace {

using namespace pacs;

constexpr const char* usage =
    "usage: pacs_campaign [--threads N] [--schedule serial|static|dynamic] "
    "[--repeat N] [--summary] < manifest";

std::size_t positive_count(const std::string& value) {
    std::size_t result{};
    const auto parsed = std::from_chars(value.data(), value.data() + value.size(), result);
    if (parsed.ec != std::errc{} || parsed.ptr != value.data() + value.size() || result == 0) {
        throw std::invalid_argument("campaign counts must be positive decimal integers");
    }
    return result;
}

CampaignSchedule parse_schedule(const std::string& value) {
    if (value == "serial") return CampaignSchedule::serial;
    if (value == "static") return CampaignSchedule::static_schedule;
    if (value == "dynamic") return CampaignSchedule::dynamic_schedule;
    throw std::invalid_argument("unknown campaign schedule");
}

std::vector<CampaignCase> read_manifest(std::istream& input) {
    std::string magic;
    int version{};
    long long count{};
    if (!(input >> magic >> version >> count) || magic != "PACS_CAMPAIGN" || version != 1) {
        throw std::invalid_argument("unsupported or malformed campaign manifest");
    }
    if (count <= 0
        || static_cast<unsigned long long>(count)
           > static_cast<unsigned long long>(std::numeric_limits<std::ptrdiff_t>::max())) {
        throw std::invalid_argument("campaign manifest requires a positive, representable case count");
    }
    std::vector<CampaignCase> cases;
    cases.reserve(static_cast<std::size_t>(count));
    for (long long i = 0; i < count; ++i) {
        std::string method, name, path;
        if (!(input >> method >> std::quoted(name) >> std::quoted(path))) {
            throw std::invalid_argument("missing or malformed campaign entry");
        }
        CampaignMethod parsed_method;
        if (method == "gh") parsed_method = CampaignMethod::gh;
        else if (method == "agh") parsed_method = CampaignMethod::agh;
        else throw std::invalid_argument("campaign method must be gh or agh");
        if (name.empty() || path.empty()) {
            throw std::invalid_argument("campaign requires a nonempty name and path");
        }
        std::ifstream file(path);
        if (!file) throw std::invalid_argument("cannot open campaign input: " + path);
        auto numeric_input = io::read_input(file);
        cases.push_back({std::move(numeric_input.problem), numeric_input.options,
                         std::move(numeric_input.seed), std::move(name), parsed_method});
    }
    std::string extra;
    if (input >> extra) throw std::invalid_argument("unexpected trailing campaign data");
    return cases;
}

void case_json(std::ostream& out, const CampaignCase& input,
               const CampaignCaseResult& result, bool summary) {
    const Placement* placement = nullptr;
    const Validation* validation = nullptr;
    std::string status;
    if (const auto* gh = std::get_if<GhResult>(&result)) {
        placement = &gh->placement;
        validation = &gh->validation;
        status = "algorithm_1_completed";
    } else {
        const auto& agh = std::get<AghResult>(result);
        placement = agh.final_placement();
        validation = agh.final_validation ? &*agh.final_validation : nullptr;
        status = agh.completion_status;
    }
    out << "{\"name\":";
    io::quoted(out, input.name);
    out << ",\"method\":";
    io::quoted(out, input.method == CampaignMethod::gh ? "gh" : "agh");
    out << ",\"status\":";
    io::quoted(out, status);
    if (!summary) {
        out << ",\"placement\":";
        io::placement_json(out, placement);
    }
    io::validation_json(out, validation, !summary);
    if (!summary) {
        if (const auto* gh = std::get_if<GhResult>(&result)) {
            io::gh_trace(out, *gh, input.problem);
        } else {
            io::agh_trace(out, std::get<AghResult>(result));
        }
    }
    out << '}';
}

} // namespace

int main(int argc, char** argv) {
    try {
        int threads = 1;
        CampaignSchedule schedule = CampaignSchedule::serial;
        std::string schedule_name = "serial";
        std::size_t repeat = 1;
        bool summary = false;
        for (int a = 1; a < argc; ++a) {
            const std::string option = argv[a];
            if (option == "--help") {
                std::cout << usage << '\n';
                return 0;
            }
            if (option == "--summary") {
                summary = true;
            } else if ((option == "--threads" || option == "--repeat" || option == "--schedule")
                       && a + 1 < argc) {
                const std::string value = argv[++a];
                if (option == "--schedule") {
                    schedule = parse_schedule(value);
                    schedule_name = value;
                } else {
                    const auto count = positive_count(value);
                    if (option == "--repeat") repeat = count;
                    else {
                        if (count > static_cast<std::size_t>(std::numeric_limits<int>::max())) {
                            throw std::invalid_argument("campaign thread count is too large");
                        }
                        threads = static_cast<int>(count);
                    }
                }
            } else {
                throw std::invalid_argument(usage);
            }
        }
        // All files are parsed and prepared before any algorithm timing begins.
        const auto cases = read_manifest(std::cin);
        std::optional<CampaignResult> result;
        std::vector<double> seconds;
        std::vector<int> repeat_threads;
        seconds.reserve(repeat);
        repeat_threads.reserve(repeat);
        for (std::size_t r = 0; r < repeat; ++r) {
            const auto begin = std::chrono::steady_clock::now();
            auto next = run_campaign(cases, schedule, threads);
            seconds.push_back(std::chrono::duration<double>(std::chrono::steady_clock::now() - begin).count());
            repeat_threads.push_back(next.actual_threads);
            // Previous evidence destruction and all serialization are untimed.
            result = std::move(next);
        }
        const auto fastest = std::min_element(seconds.begin(), seconds.end());
        const auto fastest_index = static_cast<std::size_t>(fastest - seconds.begin());
        // Report the team observed for the retained timing minimum, even when
        // OMP_DYNAMIC changes the team between repeats. Science uses the last
        // owned result; every repeat executes the same complete case list.
        std::cout << std::setprecision(17)
                  << "{\"schedule\":";
        io::quoted(std::cout, schedule_name);
        std::cout << ",\"requested_threads\":" << result->requested_threads
                  << ",\"actual_threads\":" << repeat_threads[fastest_index]
                  << ",\"campaign_seconds\":" << *fastest
                  << ",\"repeat_seconds\":";
        io::array(std::cout, seconds);
        std::cout << ",\"repeat_threads\":";
        io::array(std::cout, repeat_threads);
        std::cout << ",\"cases\":[";
        for (std::size_t i = 0; i < cases.size(); ++i) {
            if (i) std::cout << ',';
            case_json(std::cout, cases[i], result->cases[i], summary);
        }
        std::cout << "]}\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 2;
    }
}
