#include "pacs/core.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>
#include <set>

namespace pacs {
namespace {
void nonnegative(double x) {
    if (!std::isfinite(x) || x < 0) {
        throw std::invalid_argument("nonnegative finite input required");
    }
}
void positive(double x) {
    nonnegative(x);
    if (x == 0) {
        throw std::invalid_argument("positive input required");
    }
}
bool fraction(double x, double maximum = 1) {
    return std::isfinite(x) && x >= 0 && x <= maximum;
}
bool binary(double x) {
    return x == 0 || x == 1;
}
bool shape(const Problem& p, const Placement& s) {
    if (p.I() == 0 || p.J() == 0 || p.K() == 0 || p.tier_offsets.size() != p.K()+1) {
        throw std::invalid_argument("a prepared problem is required");
    }
    return s.x.size() == p.I()*p.J()*p.K() && s.z.size() == s.x.size() &&
        s.q.size() == p.J()*p.K() && s.y.size() == s.q.size() && s.u.size() == p.I() &&
        s.w.size() == p.config_count() && s.v.size() == p.I()*p.config_count();
}
bool domains(const Problem& p, const Placement& s) {
    if (!shape(p,s)) return false;
    for (double x : s.x) {
        if (!fraction(x)) return false;
    }
    for (double x : s.v) {
        if (!fraction(x)) return false;
    }
    for (double z : s.z) {
        if (!binary(z)) return false;
    }
    for (double q : s.q) {
        if (!binary(q)) return false;
    }
    for (double w : s.w) {
        if (!binary(w)) return false;
    }
    for (double y : s.y) {
        if (!std::isfinite(y) || y < 0 || y != std::floor(y)) return false;
    }
    for (std::size_t i = 0; i < p.I(); ++i) {
        if (!fraction(s.u[i],p.queries[i].max_unmet)) return false;
    }
    return true;
}
std::vector<double> processing_delays(const Problem& p, const Placement& s) {
    std::vector<double> values(p.I()), terms;
    for (std::size_t i = 0; i < p.I(); ++i) {
        terms.clear();
        for (std::size_t j = 0; j < p.J(); ++j) {
            for (std::size_t k = 0; k < p.K(); ++k) {
                for (std::size_t c = 0; c < p.tiers[k].configs.size(); ++c) {
                    terms.push_back(s.v[p.vc(i,j,k,c)]*configuration_delay(p,i,j,k,c));
                }
            }
        }
        values[i] = python_fsum(terms);
    }
    return values;
}
Objective objective_from_delays(const Problem& p, const Placement& s,
                                const std::vector<double>& delays) {
    Objective result;
    std::vector<double> terms;
    for (std::size_t j = 0; j < p.J(); ++j) {
        for (std::size_t k = 0; k < p.K(); ++k) {
            terms.push_back(p.tiers[k].rental*s.y[p.pair(j,k)]);
        }
    }
    result.c1 = p.horizon*python_sum(terms);
    terms.clear();
    for (std::size_t i = 0; i < p.I(); ++i) {
        for (std::size_t j = 0; j < p.J(); ++j) {
            for (std::size_t k = 0; k < p.K(); ++k) {
                terms.push_back(p.models[j].weight*s.z[p.route(i,j,k)]);
            }
        }
    }
    result.c2 = p.horizon*p.storage_price*python_sum(terms);
    terms.clear();
    for (std::size_t i = 0; i < p.I(); ++i) {
        for (std::size_t j = 0; j < p.J(); ++j) {
            for (std::size_t k = 0; k < p.K(); ++k) {
                const auto& query = p.queries[i];
                terms.push_back(query.storage*query.total_tokens()*query.arrival*s.x[p.route(i,j,k)]);
            }
        }
    }
    result.c3 = p.horizon*p.storage_price*python_sum(terms);
    if (p.coherent) result.c3 *= p.data_residency;
    terms.clear();
    for (std::size_t i = 0; i < p.I(); ++i) {
        const auto& query = p.queries[i];
        double value = query.delay_penalty*delays[i];
        if (p.coherent) value = value*1000*query.arrival*p.horizon;
        terms.push_back(value);
    }
    result.c4 = python_sum(terms);
    terms.clear();
    for (std::size_t i = 0; i < p.I(); ++i) {
        terms.push_back(p.queries[i].unmet_penalty*s.u[i]);
    }
    result.c5 = python_sum(terms);
    if (p.version == 2) result.c5 *= p.horizon;
    return result;
}
Validation quantities(const Problem& p, const Placement& s) {
    Validation result;
    result.delay = processing_delays(p,s);
    result.objective = objective_from_delays(p,s,result.delay);
    const auto pairs = p.J()*p.K();
    result.memory.resize(pairs);
    result.compute_required.resize(pairs);
    result.compute_available.resize(pairs);
    result.storage.resize(p.I());
    result.error.resize(p.I());
    result.demand.resize(p.I());
    std::vector<double> weights, kv, compute, terms, stored, data;
    for (std::size_t j = 0; j < p.J(); ++j) {
        for (std::size_t k = 0; k < p.K(); ++k) {
            weights.clear();
            kv.clear();
            compute.clear();
            const auto& tier = p.tiers[k];
            const auto& model = p.models[j];
            for (std::size_t c = 0; c < tier.configs.size(); ++c) {
                weights.push_back(model.weight/tier.configs[c].gpu_count()*s.w[p.pc(j,k,c)]);
            }
            for (std::size_t i = 0; i < p.I(); ++i) {
                const auto& query = p.queries[i];
                const auto r = p.route(i,j,k);
                compute.push_back(p.alpha[r]*query.total_tokens()*query.arrival*s.x[r]/1000);
                for (std::size_t c = 0; c < tier.configs.size(); ++c) {
                    kv.push_back(model.kv/tier.configs[c].gpu_count()*query.total_tokens()*p.residency_seconds[r]*
                        (p.coherent?query.arrival/p.seconds_per_hour:1.0)*s.v[p.vc(i,j,k,c)]);
                }
            }
            const auto a = p.pair(j,k);
            result.memory[a] = python_fsum(weights)+python_fsum(kv);
            result.compute_required[a] = python_fsum(compute);
            result.compute_available[a] = p.eta*p.seconds_per_hour*tier.throughput*s.y[a];
        }
    }
    for (std::size_t i = 0; i < p.I(); ++i) {
        terms.clear();
        stored.clear();
        data.clear();
        const auto& query = p.queries[i];
        for (std::size_t j = 0; j < p.J(); ++j) {
            for (std::size_t k = 0; k < p.K(); ++k) {
                const auto r = p.route(i,j,k);
                terms.push_back(p.error[r]*s.x[r]);
                stored.push_back(p.models[j].weight*s.z[r]);
                data.push_back(query.storage*query.total_tokens()*query.arrival*s.x[r]);
            }
        }
        result.error[i] = python_fsum(terms);
        result.storage[i] = python_fsum(stored)+python_fsum(data)*(p.coherent?p.data_residency:1.0);
        terms.assign(s.x.begin()+i*pairs,s.x.begin()+(i+1)*pairs);
        terms.push_back(s.u[i]);
        result.demand[i] = python_fsum(terms);
    }
    return result;
}
} // namespace

void Problem::prepare() {
    if (I() == 0 || J() == 0 || K() == 0) {
        throw std::invalid_argument("empty problem dimension");
    }
    if (I() > std::numeric_limits<std::size_t>::max()/J()/K()) {
        throw std::invalid_argument("dimension overflow");
    }
    if (version != 1 && version != 2) {
        throw std::invalid_argument("paper version must be 1 or 2");
    }
    if (coherent && (version != 2 || seconds_per_hour != 3600)) {
        throw std::invalid_argument("coherent units require v2 and 3600 seconds/hour");
    }
    nonnegative(storage_price);
    nonnegative(budget);
    positive(storage_capacity);
    positive(horizon);
    positive(eta);
    if (eta > 1) throw std::invalid_argument("utilization exceeds one");
    positive(seconds_per_hour);
    nonnegative(data_residency);
    for (const auto& q : queries) {
        for (double x : {q.arrival,q.input_tokens,q.output_tokens,q.storage,q.delay_penalty,q.unmet_penalty}) {
            nonnegative(x);
        }
        positive(q.delay_slo);
        if (!fraction(q.error_slo) || !fraction(q.max_unmet)) {
            throw std::invalid_argument("invalid query fraction");
        }
    }
    for (const auto& m : models) {
        positive(m.weight);
        nonnegative(m.kv);
    }
    tier_offsets = {0};
    for (const auto& t : tiers) {
        positive(t.capacity);
        positive(t.throughput);
        nonnegative(t.rental);
        if (t.configs.empty()) throw std::invalid_argument("no parallelism configurations");
        std::set<std::pair<int,int>> seen;
        std::vector<int> tensor_degrees, pipeline_depths;
        for (const auto& c : t.configs) {
            if (c.n <= 0 || c.m <= 0 || c.n > std::numeric_limits<int>::max()/c.m ||
                !seen.emplace(c.n,c.m).second) {
                throw std::invalid_argument("invalid or duplicated configuration");
            }
            if (std::find(tensor_degrees.begin(),tensor_degrees.end(),c.n) == tensor_degrees.end()) {
                tensor_degrees.push_back(c.n);
            }
            if (std::find(pipeline_depths.begin(),pipeline_depths.end(),c.m) == pipeline_depths.end()) {
                pipeline_depths.push_back(c.m);
            }
        }
        // Python's tier authority is the ordered N_k x M_k product. The local
        // transport expands it; it may not supply a different coupled subset
        // or reorder equal-product shapes and thereby change tie selection.
        if (tensor_degrees.size() > std::numeric_limits<std::size_t>::max()/pipeline_depths.size() ||
            t.configs.size() != tensor_degrees.size()*pipeline_depths.size()) {
            throw std::invalid_argument("configurations must contain the complete tier Cartesian product");
        }
        std::size_t configuration = 0;
        for (const int n : tensor_degrees) {
            for (const int m : pipeline_depths) {
                const auto& c = t.configs[configuration++];
                if (c.n != n || c.m != m) {
                    throw std::invalid_argument("configurations must follow nested tier Cartesian order");
                }
            }
        }
        tier_offsets.push_back(tier_offsets.back()+t.configs.size());
    }
    const auto count = I()*J()*K();
    for (const auto* a : {&error,&compute_delay,&communication_delay,&alpha,&residency_seconds}) {
        if (a->size() != count) throw std::invalid_argument("coefficient shape mismatch");
        for (double x : *a) {
            nonnegative(x);
        }
    }
}
Placement Placement::zero(const Problem& p) {
    return {std::vector<double>(p.I()*p.J()*p.K()),std::vector<double>(p.I()*p.J()*p.K()),
        std::vector<double>(p.J()*p.K()),std::vector<double>(p.I()),std::vector<double>(p.config_count()),
        std::vector<double>(p.J()*p.K()),std::vector<double>(p.I()*p.config_count())};
}
Tolerances Tolerances::exact() {
    return {0,0,0,0,0,0,0,0,0,0,0,0,0,0,0};
}
double python_sum(std::span<const double> values) {
    // Neumaier compensation: matches CPython 3.12+ float sum, preserving sequence order.
    double high = 0, low = 0;
    for (double value : values) {
        const double next = high+value;
        low += std::abs(high) >= std::abs(value) ? (high-next)+value : (value-next)+high;
        high = next;
    }
    return low != 0 && std::isfinite(low) ? high+low : high;
}
double python_fsum(std::span<const double> values) {
    // Non-overlapping partial sums, followed by a half-even rounded collapse.
    std::vector<double> partials;
    partials.reserve(32);
    for (double value : values) {
        if (!std::isfinite(value)) throw std::overflow_error("non-finite fsum input");
        std::size_t next = 0;
        for (double part : partials) {
            if (std::abs(value) < std::abs(part)) std::swap(value,part);
            const double high = value+part, low = part-(high-value);
            if (low != 0) partials[next++] = low;
            value = high;
        }
        partials.resize(next);
        if (!std::isfinite(value)) throw std::overflow_error("fsum overflow");
        if (value != 0) partials.push_back(value);
    }
    if (partials.empty()) return 0;
    double high = partials.back(), low = 0;
    partials.pop_back();
    while (!partials.empty()) {
        const double part = partials.back(), previous = high;
        partials.pop_back();
        high = previous+part;
        low = part-(high-previous);
        if (low != 0) break;
    }
    if (!partials.empty() && ((low < 0 && partials.back() < 0) || (low > 0 && partials.back() > 0))) {
        const double twice = low*2, next = high+twice;
        if (next-high == twice) high = next;
    }
    return high;
}
double configuration_delay(const Problem& p, std::size_t i, std::size_t j,
                           std::size_t k, std::size_t c) {
    const auto& query = p.queries[i];
    const auto& config = p.tiers[k].configs[c];
    const auto r = p.route(i,j,k);
    const double ttft = p.compute_delay[r]*query.input_tokens/config.n;
    const double generation = (p.compute_delay[r]/config.n+config.m*p.communication_delay[r])*query.output_tokens;
    return ttft+generation;
}
Objective objective(const Problem& p, const Placement& s) {
    if (!shape(p,s)) throw std::invalid_argument("placement shape mismatch");
    return objective_from_delays(p,s,processing_delays(p,s));
}
Validation validate(const Problem& p, const Placement& s, const Tolerances& t) {
    for (double x : {t.mccormick,t.demand,t.routing,t.budget,t.budget_relative,t.memory,t.memory_relative,
        t.compute,t.compute_relative,t.storage,t.storage_relative,t.delay,t.delay_relative,t.error,t.error_relative}) {
        nonnegative(x);
    }
    Validation out;
    if (!domains(p,s)) {
        out.domains_valid = false;
        out.feasible = false;
        return out;
    }
    out = quantities(p,s);
    // Every Eq. (7)/(8) row remains recorded. Reserve the known lattice size
    // instead of repeatedly moving an expanding diagnostic report (PACS lecture 06).
    const auto pairs = p.J()*p.K();
    out.residuals.reserve(4*p.I()*p.config_count()+4*p.I()+1+4*pairs+3*p.I()*pairs);
    auto row = [&](const std::string& family, std::size_t index, double slack,
                   double absolute, double relative = 0, double lhs = 0, double rhs = 0) {
        const double threshold = absolute+relative*std::max(std::abs(lhs),std::abs(rhs));
        if (!std::isfinite(slack) || !std::isfinite(threshold)) {
            throw std::overflow_error("non-finite residual");
        }
        out.residuals.push_back({family,index,slack,threshold});
        if (slack < -threshold) out.feasible = false;
    };
    for (std::size_t i = 0; i < p.I(); ++i) {
        for (std::size_t j = 0; j < p.J(); ++j) {
            for (std::size_t k = 0; k < p.K(); ++k) {
                for (std::size_t c = 0; c < p.tiers[k].configs.size(); ++c) {
                    const auto a = p.vc(i,j,k,c);
                    const double x = s.x[p.route(i,j,k)], w = s.w[p.pc(j,k,c)], v = s.v[a];
                    row("mccormick",4*a,x-v,t.mccormick);
                    row("mccormick",4*a+1,w-v,t.mccormick);
                    row("mccormick",4*a+2,v-x-w+1,t.mccormick);
                    row("mccormick",4*a+3,v,t.mccormick);
                }
            }
        }
    }
    for (std::size_t i = 0; i < p.I(); ++i) {
        row("demand_balance",i,-std::abs(out.demand[i]-1),t.demand);
    }
    row("budget",0,p.budget-out.objective.resource_cost(),t.budget,t.budget_relative,out.objective.resource_cost(),p.budget);
    for (std::size_t j = 0; j < p.J(); ++j) {
        for (std::size_t k = 0; k < p.K(); ++k) {
            const auto a = p.pair(j,k);
            double selected = 0, implied = 0;
            for (std::size_t c = 0; c < p.tiers[k].configs.size(); ++c) {
                selected += s.w[p.pc(j,k,c)];
                implied += p.tiers[k].configs[c].gpu_count()*s.w[p.pc(j,k,c)];
            }
            row("configuration_selection",a,-std::abs(selected-s.q[a]),0);
            row("gpu_count_linking",a,-std::abs(s.y[a]-implied),0);
            const double memory_cap = p.tiers[k].capacity*s.q[a];
            row("gpu_memory",a,memory_cap-out.memory[a],t.memory,t.memory_relative,out.memory[a],memory_cap);
            row("compute_capacity",a,out.compute_available[a]-out.compute_required[a],t.compute,t.compute_relative,out.compute_required[a],out.compute_available[a]);
        }
    }
    for (std::size_t i = 0; i < p.I(); ++i) {
        const auto& query = p.queries[i];
        row("storage_capacity",i,p.storage_capacity-out.storage[i],t.storage,t.storage_relative,out.storage[i],p.storage_capacity);
        row("delay_slo",i,query.delay_slo-out.delay[i],t.delay,t.delay_relative,out.delay[i],query.delay_slo);
        row("error_slo",i,query.error_slo-out.error[i],t.error,t.error_relative,out.error[i],query.error_slo);
        for (std::size_t j = 0; j < p.J(); ++j) {
            for (std::size_t k = 0; k < p.K(); ++k) {
                const auto r = p.route(i,j,k);
                row("routing_consistency",3*r,s.x[r],t.routing);
                row("routing_consistency",3*r+1,s.z[r]-s.x[r],t.routing);
                row("routing_consistency",3*r+2,s.q[p.pair(j,k)]-s.z[r],t.routing);
            }
        }
    }
    return out;
}
bool resources_feasible(const Problem& p, const Placement& s, bool check_budget) {
    const auto report = resource_diagnostics(p,s);
    return report.feasible && (!check_budget || report.objective.resource_cost() <= p.budget);
}
Validation resource_diagnostics(const Problem& p, const Placement& s) {
    if (!shape(p,s)) throw std::invalid_argument("placement shape mismatch");
    auto report = quantities(p,s);
    report.residuals.reserve(2*p.J()*p.K()+p.I());
    auto row = [&](const std::string& family, std::size_t index, double slack) {
        if (!std::isfinite(slack)) throw std::overflow_error("non-finite resource residual");
        report.residuals.push_back({family,index,slack,0});
        if (slack < 0) report.feasible = false;
    };
    for (std::size_t j = 0; j < p.J(); ++j) {
        for (std::size_t k = 0; k < p.K(); ++k) {
            const auto a = p.pair(j,k);
            row("gpu_memory",a,p.tiers[k].capacity*s.q[a]-report.memory[a]);
            row("compute_capacity",a,report.compute_available[a]-report.compute_required[a]);
        }
    }
    for (std::size_t i = 0; i < p.I(); ++i) {
        row("storage_capacity",i,p.storage_capacity-report.storage[i]);
    }
    return report;
}
int active_config(const Problem& p, const Placement& s, std::size_t j, std::size_t k) {
    if (!shape(p,s) || j >= p.J() || k >= p.K()) {
        throw std::invalid_argument("invalid active-pair lookup");
    }
    const auto a = p.pair(j,k);
    int selected = -1;
    for (std::size_t c = 0; c < p.tiers[k].configs.size(); ++c) {
        const double w = s.w[p.pc(j,k,c)];
        if (!binary(w)) return -2;
        if (w == 1) {
            if (selected >= 0) return -2;
            selected = static_cast<int>(c);
        }
    }
    if (s.q[a] == 0) return selected < 0 && s.y[a] == 0 ? -1 : -2;
    if (s.q[a] != 1 || selected < 0 || s.y[a] != p.tiers[k].configs[selected].gpu_count()) return -2;
    return selected;
}
} // namespace pacs
