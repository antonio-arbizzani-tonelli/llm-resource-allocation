// Opt-in measurement adapter. Scientific GH/AGH routines are linked unchanged.
#include "pacs/io.hpp"

#include <chrono>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <optional>
#include <stdexcept>
#include <string>

int main(int argc, char** argv) {
    try {
        if (argc < 3) throw std::invalid_argument("usage: pacs_matched_runtime gh|agh INPUT [--warmup] [--evidence]");
        const std::string method = argv[1];
        bool warmup = false, evidence = false;
        for (int index = 3; index < argc; ++index) {
            const std::string flag = argv[index];
            if (flag == "--warmup") warmup = true;
            else if (flag == "--evidence") evidence = true;
            else throw std::invalid_argument("unknown measurement option");
        }
        if (method != "gh" && method != "agh") throw std::invalid_argument("method must be gh or agh");
        std::ifstream stream(argv[2]);
        if (!stream) throw std::invalid_argument("cannot open prepared input");
        const auto input = pacs::io::read_input(stream);
        if (warmup) {
            // Warm evidence is destroyed before the measured fresh-result call.
            if (method == "gh") { const auto discarded = pacs::run_gh(input.problem, input.options); }
            else { const auto discarded = pacs::run_agh(input.problem, input.seed, input.options); }
        }
        std::optional<pacs::GhResult> gh;
        std::optional<pacs::AghResult> agh;
        const auto begin = std::chrono::steady_clock::now();
        if (method == "gh") gh.emplace(pacs::run_gh(input.problem, input.options));
        else agh.emplace(pacs::run_agh(input.problem, input.seed, input.options));
        const double seconds = std::chrono::duration<double>(std::chrono::steady_clock::now() - begin).count();
        const pacs::Placement* state = gh ? &gh->placement : agh->final_placement();
        const pacs::Validation* validation = gh ? &gh->validation
            : (agh->final_validation ? &*agh->final_validation : nullptr);
        std::cout << std::setprecision(17) << "{\"core_seconds\":" << seconds << ",\"status\":";
        pacs::io::quoted(std::cout, gh ? "algorithm_1_completed" : agh->completion_status);
        std::cout << ",\"placement\":";
        pacs::io::placement_json(std::cout, state);
        std::cout << ",\"feasible\":" << (validation && validation->feasible ? "true" : "false") << ",\"objective\":";
        if (validation) {
            const auto& cost = validation->objective;
            std::cout << '[' << cost.c1 << ',' << cost.c2 << ',' << cost.c3 << ',' << cost.c4 << ',' << cost.c5 << ']';
        } else std::cout << "null";
        if (evidence) {
            if (gh) pacs::io::gh_trace(std::cout, *gh, input.problem);
            else pacs::io::agh_trace(std::cout, *agh);
        }
        std::cout << "}\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 2;
    }
}
