#pragma once

#include <cstddef>
#include <span>
#include <string>
#include <vector>

namespace pacs {
// Physical units below describe coherent Stage 1 (docs/UNITS.md). Literal
// fixtures retain the historical paper convention selected by Problem::coherent.
struct Config {
    int n{1}, m{1}; // Tensor and pipeline parallelism degrees.
    int gpu_count() const { return n*m; }
};
struct Query {
    double arrival{}; // Requests/hour.
    double input_tokens{}, output_tokens{}; // Tokens/request.
    double storage{}; // Decimal GB/token.
    double delay_slo{}; // Seconds/request.
    double error_slo{}; // Error fraction.
    double delay_penalty{}; // USD/(millisecond * request).
    double unmet_penalty{}; // USD/hour for an unmet fraction of one.
    double max_unmet{}; // Maximum unmet fraction.
    double total_tokens() const { return input_tokens + output_tokens; }
};
struct Model {
    double weight{}; // Decimal GB.
    double kv{}; // Decimal GB/token.
};
struct Tier {
    double capacity{}; // Decimal GB/GPU.
    double throughput{}; // TFLOP/(second * GPU).
    double rental{}; // USD/(GPU * hour).
    std::vector<Config> configs;
};
struct Problem {
    std::vector<Query> queries;
    std::vector<Model> models;
    std::vector<Tier> tiers;
    // Arrays follow query/model/tier semantic order. Error is already tier-adjusted.
    std::vector<double> error; // Error fractions.
    std::vector<double> compute_delay, communication_delay; // Seconds/token.
    std::vector<double> alpha; // GFLOP/token.
    std::vector<double> residency_seconds; // KV residency in seconds/request.
    double storage_price{}; // USD/(GB * hour).
    double budget{}; // Period-wide USD.
    double storage_capacity{}; // Decimal GB, applied per query.
    double horizon{}; // Hours.
    double eta{}; // Utilization fraction.
    double seconds_per_hour{3600}, data_residency{1}; // Seconds/hour and hours.
    bool coherent{true};
    int version{2};
    std::vector<std::size_t> tier_offsets;

    // Validate external data and derive configuration offsets before use. Keep
    // the problem unchanged while algorithms or index-dependent states use it.
    void prepare();
    std::size_t I() const { return queries.size(); }
    std::size_t J() const { return models.size(); }
    std::size_t K() const { return tiers.size(); }

    // Unchecked indexing helpers require a prepared problem and valid semantic
    // indices: i<I(), j<J(), k<K(), c<tiers[k].configs.size().
    std::size_t pair(std::size_t j, std::size_t k) const { return j*K()+k; }
    std::size_t route(std::size_t i, std::size_t j, std::size_t k) const {
        return i*J()*K()+pair(j,k);
    }
    std::size_t config_count() const { return J()*tier_offsets.back(); }
    std::size_t pc(std::size_t j, std::size_t k, std::size_t c) const {
        return j*tier_offsets.back()+tier_offsets[k]+c;
    }
    std::size_t vc(std::size_t i, std::size_t j, std::size_t k, std::size_t c) const {
        return i*config_count()+pc(j,k,c);
    }
};
struct Placement {
    std::vector<double> x,z,q,u,w,y,v;
    // Owns dense arrays indexed by the prepared problem; no borrowed storage.
    static Placement zero(const Problem&);
};
struct Objective {
    // C1-C5 and both totals are period-wide USD in coherent mode.
    double c1{},c2{},c3{},c4{},c5{};
    double total() const { return c1+c2+c3+c4+c5; }
    double resource_cost() const { return c1+c2+c3; }
};
struct Tolerances {
    double mccormick{1e-10}, demand{1e-10}, routing{1e-10};
    double budget{1e-8}, budget_relative{1e-12};
    double memory{1e-9}, memory_relative{1e-12};
    double compute{1e-8}, compute_relative{1e-12};
    double storage{1e-9}, storage_relative{1e-12};
    double delay{1e-10}, delay_relative{1e-12};
    double error{1e-12}, error_relative{1e-12};
    static Tolerances exact();
};
struct Residual {
    std::string family;
    std::size_t index{};
    double slack{}, threshold{};
};
struct Validation {
    bool domains_valid{true}, feasible{true};
    Objective objective;
    std::vector<double> delay,error,memory,compute_required,compute_available,storage,demand;
    std::vector<Residual> residuals;
};
// Spans borrow read-only contiguous values only for the duration of the call;
// neither summation function stores the view or invalidates its backing data.
double python_fsum(std::span<const double>);
double python_sum(std::span<const double>);
// Scientific primitives require a prepared problem. Direct configuration
// lookup additionally requires valid indices as documented above.
double configuration_delay(const Problem&, std::size_t i,std::size_t j,std::size_t k,std::size_t c);
Objective objective(const Problem&,const Placement&);
Validation validate(const Problem&,const Placement&,const Tolerances& = {});
// GH checks resources exactly, without imposing complete-placement demand/SLO checks.
bool resources_feasible(const Problem&,const Placement&,bool check_budget = true);
Validation resource_diagnostics(const Problem&,const Placement&);
// Returns -1 for an inactive pair, -2 for incoherent q/w/y, otherwise local config index.
int active_config(const Problem&,const Placement&,std::size_t j,std::size_t k);
} // namespace pacs
