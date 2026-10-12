#include "pacs/io.hpp"

#include <algorithm>
#include <chrono>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>

namespace {
using namespace pacs;
using namespace pacs::io;
} // namespace

int main(int argc, char** argv) {
    try {
        if (argc < 2) {
            throw std::invalid_argument("usage: pacs_serial gh|agh|relocate|consolidate|validate|rng [--repeat N] [--summary] [--draw N] < input");
        }
        const std::string mode = argv[1];
        std::size_t repeat = 1, draw = 0;
        bool summary = false;
        for (int a = 2; a < argc; ++a) {
            const std::string arg = argv[a];
            if (arg == "--summary") {
                summary = true;
            } else if ((arg == "--repeat" || arg == "--draw") && a+1 < argc) {
                const std::string value = argv[++a];
                if (value.empty() || value[0] == '-') throw std::invalid_argument("negative loop count");
                std::size_t consumed = 0;
                const auto n = std::stoull(value,&consumed);
                if (consumed != value.size()) throw std::invalid_argument("invalid loop count");
                if (arg == "--repeat") repeat = n;
                else draw = n;
            } else {
                throw std::invalid_argument("unknown option");
            }
        }
        if (repeat == 0) throw std::invalid_argument("repeat must be positive");
        const auto input = read_input(std::cin);
        const auto& p = input.problem;
        std::cout << std::setprecision(17);
        if (mode == "rng") {
            std::cout << "{\"order\":";
            array(std::cout,build_seeded_random_agh_ordering(p.I(),input.seed,draw).queries);
            std::cout << "}\n";
            return 0;
        }
        std::optional<GhResult> gh;
        std::optional<AghResult> agh;
        std::optional<AghRelocateResult> relocate;
        std::optional<AghConsolidationResult> consolidate;
        std::optional<Validation> validation;
        std::vector<double> seconds;
        seconds.reserve(repeat);
        for (std::size_t r = 0; r < repeat; ++r) {
            const auto begin = std::chrono::steady_clock::now();
            if (mode == "gh") {
                gh = run_gh(p,input.options);
            } else if (mode == "agh") {
                agh = run_agh(p,input.seed,input.options);
            } else {
                if (!input.state) throw std::invalid_argument("this mode requires a supplied placement");
                if (mode == "relocate") relocate = run_agh_relocate(p,*input.state);
                else if (mode == "consolidate") consolidate = run_agh_consolidation_scan(p,*input.state);
                else if (mode == "validate") validation = validate(p,*input.state);
                else throw std::invalid_argument("unknown mode");
            }
            seconds.push_back(std::chrono::duration<double>(std::chrono::steady_clock::now()-begin).count());
        }
        // Borrow only after the repeat loop has finished replacing result owners.
        const Placement* state = nullptr;
        const Validation* report = nullptr;
        std::string status;
        if (gh) {
            state = &gh->placement;
            report = &gh->validation;
            status = "algorithm_1_completed";
        }
        if (agh) {
            state = agh->final_placement();
            report = agh->final_validation?&*agh->final_validation:nullptr;
            status = agh->completion_status;
        }
        if (relocate) {
            state = &relocate->placement;
            report = &relocate->validation;
            status = relocate->termination_reason;
        }
        if (consolidate) {
            state = &consolidate->placement;
            report = &consolidate->validation;
            status = "completed";
        }
        if (validation) {
            state = &*input.state;
            report = &*validation;
            status = report->feasible?"valid":"invalid";
        }
        std::cout << "{\"status\":";
        quoted(std::cout,status);
        std::cout << ",\"algorithm_seconds\":" << *std::min_element(seconds.begin(),seconds.end())
            << ",\"repeat_seconds\":";
        array(std::cout,seconds);
        std::cout << ",\"placement\":";
        placement_json(std::cout,summary?nullptr:state);
        validation_json(std::cout,report);
        if (gh && !summary) gh_trace(std::cout,*gh,p);
        if (agh) agh_trace(std::cout,*agh);
        if (relocate) {
            std::size_t accepted = 0;
            for (const auto& pass : relocate->passes) {
                accepted += pass.accepted_move_count;
            }
            std::cout << ",\"accepted_count\":" << accepted << ",\"passes_executed\":" << relocate->passes.size();
        }
        if (consolidate) std::cout << ",\"accepted_count\":" << consolidate->accepted_source_count;
        std::cout << "}\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 2;
    }
}
