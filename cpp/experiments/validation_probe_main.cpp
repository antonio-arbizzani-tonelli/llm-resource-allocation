#include "validation_probe.hpp"
#include "pacs/io.hpp"

#include <algorithm>
#include <charconv>
#include <chrono>
#include <iomanip>
#include <iostream>
#include <limits>
#include <numeric>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <variant>

namespace {
using namespace pacs;
using namespace pacs::experiment;
using Clock = std::chrono::steady_clock;

constexpr const char* usage =
    "usage: pacs_validation_probe gh|agh [--repeat N] [--summary] "
    "[--validation-mode append|slots|omp] [--validation-threads N] "
    "[--validation-min-rows N] < input";

double elapsed(Clock::time_point begin) {
    return std::chrono::duration<double>(Clock::now()-begin).count();
}
std::size_t count(const std::string& value, bool zero_allowed = false) {
    std::size_t result{};
    const auto parsed = std::from_chars(value.data(),value.data()+value.size(),result);
    if (parsed.ec != std::errc{} || parsed.ptr != value.data()+value.size() ||
        (!zero_allowed && result == 0)) {
        throw std::invalid_argument("expected a representable decimal count");
    }
    return result;
}
ValidationMode validation_mode(const std::string& name) {
    if (name == "append") return ValidationMode::append;
    if (name == "slots") return ValidationMode::slots;
    if (name == "omp") return ValidationMode::omp;
    throw std::invalid_argument("unknown validation mode");
}

void statistics_json(std::ostream& out, const ProbeSession& session,
                     const std::vector<std::size_t>& repeat_offsets) {
    std::vector<double> durations;
    std::vector<int> observed_teams;
    std::size_t failures = 0, regions = 0, parallel = 0, nested = 0, grain = 0;
    durations.reserve(session.samples.size());
    for (const auto& sample : session.samples) {
        durations.push_back(sample.seconds);
        observed_teams.push_back(sample.observation.actual_threads);
        failures += !sample.succeeded;
        regions += sample.observation.region_entered;
        parallel += sample.observation.actual_threads > 1;
        nested += sample.observation.nested_fallback;
        grain += sample.observation.grain_fallback;
    }
    std::sort(durations.begin(),durations.end());
    std::sort(observed_teams.begin(),observed_teams.end());
    observed_teams.erase(std::unique(observed_teams.begin(),observed_teams.end()),observed_teams.end());
    const auto size = durations.size();
    const double median = size == 0 ? 0 : size%2 ? durations[size/2] :
        (durations[size/2-1]+durations[size/2])/2;
    const double total = std::accumulate(durations.begin(),durations.end(),0.0);
    out << ",\"validation_statistics\":{\"calls\":" << size
        << ",\"failed_calls\":" << failures << ",\"seconds_total\":" << total
        << ",\"minimum_seconds\":" << (size ? durations.front() : 0)
        << ",\"median_seconds\":" << median
        << ",\"maximum_seconds\":" << (size ? durations.back() : 0)
        << ",\"parallel_region_calls\":" << regions
        << ",\"calls_with_parallel_team\":" << parallel
        << ",\"nested_fallback_calls\":" << nested
        << ",\"grain_fallback_calls\":" << grain
        << ",\"observed_teams\":";
    io::array(out,observed_teams);
    out << ",\"repeat_call_offsets\":";
    io::array(out,repeat_offsets);
    out << ",\"samples\": [";
    bool first = true;
    for (const auto& sample : session.samples) {
        if (!first) out << ',';
        first = false;
        out << "{\"seconds\":" << sample.seconds
            << ",\"mccormick_rows\":" << sample.observation.mccormick_rows
            << ",\"actual_threads\":" << sample.observation.actual_threads
            << ",\"region_entered\":" << (sample.observation.region_entered ? "true" : "false")
            << ",\"nested_fallback\":" << (sample.observation.nested_fallback ? "true" : "false")
            << ",\"grain_fallback\":" << (sample.observation.grain_fallback ? "true" : "false")
            << ",\"succeeded\":" << (sample.succeeded ? "true" : "false") << '}';
    }
    out << "]}";
}
} // namespace

int main(int argc, char** argv) {
    try {
        if (argc < 2) throw std::invalid_argument(usage);
        const std::string method = argv[1];
        if (method != "gh" && method != "agh") throw std::invalid_argument(usage);
        std::size_t repeat = 1;
        bool summary = false;
        std::string mode_name = "append";
        ProbeSession session;
        for (int a = 2; a < argc; ++a) {
            const std::string option = argv[a];
            if (option == "--summary") {
                summary = true;
            } else if ((option == "--repeat" || option == "--validation-mode" ||
                        option == "--validation-threads" || option == "--validation-min-rows") &&
                       a+1 < argc) {
                const std::string value = argv[++a];
                if (option == "--validation-mode") {
                    session.execution.mode = validation_mode(value);
                    mode_name = value;
                } else {
                    const auto parsed = count(value,option == "--validation-min-rows");
                    if (option == "--repeat") repeat = parsed;
                    else if (option == "--validation-min-rows") session.execution.min_rows = parsed;
                    else {
                        if (parsed > static_cast<std::size_t>(std::numeric_limits<int>::max())) {
                            throw std::invalid_argument("validation thread count is too large");
                        }
                        session.execution.threads = static_cast<int>(parsed);
                    }
                }
            } else throw std::invalid_argument(usage);
        }
        const auto observed_begin = Clock::now();
        auto begin = Clock::now();
        std::optional<io::Input> input;
        input.emplace(io::read_input(std::cin));
        const double parse_seconds = elapsed(begin);
        std::optional<std::variant<GhResult,AghResult>> result;
        std::vector<double> seconds, destruction_seconds;
        std::vector<std::size_t> repeat_offsets{0};
        seconds.reserve(repeat);
        destruction_seconds.reserve(repeat);
        repeat_offsets.reserve(repeat+1);
        {
            ScopedProbeSession scope(session);
            for (std::size_t r = 0; r < repeat; ++r) {
                if (result) {
                    begin = Clock::now();
                    result.reset();
                    destruction_seconds.push_back(elapsed(begin));
                }
                begin = Clock::now();
                if (method == "gh") result.emplace(run_gh(input->problem,input->options));
                else result.emplace(run_agh(input->problem,input->seed,input->options));
                seconds.push_back(elapsed(begin));
                repeat_offsets.push_back(session.samples.size());
            }
        }
        // Scientific output delegates to the same adapter used by pacs_serial.
        // Format while all borrowed objects are alive, then observe destruction.
        begin = Clock::now();
        std::ostringstream json;
        json << std::setprecision(17);
        const Placement* state = nullptr;
        const Validation* report = nullptr;
        std::string status;
        if (const auto* gh = std::get_if<GhResult>(&*result)) {
            state = &gh->placement;
            report = &gh->validation;
            status = "algorithm_1_completed";
        } else {
            const auto& agh = std::get<AghResult>(*result);
            state = agh.final_placement();
            report = agh.final_validation ? &*agh.final_validation : nullptr;
            status = agh.completion_status;
        }
        json << "{\"status\":";
        io::quoted(json,status);
        json << ",\"algorithm_seconds\":" << *std::min_element(seconds.begin(),seconds.end())
             << ",\"repeat_seconds\":";
        io::array(json,seconds);
        json << ",\"placement\":";
        io::placement_json(json,summary ? nullptr : state);
        io::validation_json(json,report);
        if (const auto* gh = std::get_if<GhResult>(&*result)) {
            if (!summary) io::gh_trace(json,*gh,input->problem);
        } else io::agh_trace(json,std::get<AghResult>(*result));
        const std::string scientific_json = json.str();
        const double format_seconds = elapsed(begin);
        begin = Clock::now();
        result.reset();
        destruction_seconds.push_back(elapsed(begin));
        begin = Clock::now();
        input.reset();
        const double input_destruction_seconds = elapsed(begin);
        const double observed_seconds = elapsed(observed_begin);
        std::cout << std::setprecision(17) << scientific_json
            << ",\"phase_seconds\":{\"input_parse\":" << parse_seconds
            << ",\"algorithm\":";
        io::array(std::cout,seconds);
        std::cout << ",\"scientific_json_format\":" << format_seconds
            << ",\"result_destruction\":";
        io::array(std::cout,destruction_seconds);
        std::cout << ",\"input_destruction\":" << input_destruction_seconds
            << ",\"observed_body_before_write\":" << observed_seconds << '}';
        statistics_json(std::cout,session,repeat_offsets);
        std::cout << ",\"validation_execution\":{\"mode\":";
        io::quoted(std::cout,mode_name);
        std::cout << ",\"requested_threads\":" << session.execution.threads
            << ",\"minimum_mccormick_rows\":" << session.execution.min_rows << "}}\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 2;
    }
}
