#include "pacs/io.hpp"

#include <limits>
#include <stdexcept>

namespace pacs::io {
namespace {
template<class T>
void read(std::istream& input, T& value) {
    if (!(input >> value)) throw std::invalid_argument("missing or malformed transport value");
}
void read_array(std::istream& input, std::vector<double>& values) {
    for (auto& value : values) {
        read(input,value);
    }
}
} // namespace

Input read_input(std::istream& input) {
    Input result;
    std::string magic;
    int revision;
    read(input,magic);
    read(input,revision);
    if (magic != "PACS_GH_AGH" || revision != 1) {
        throw std::invalid_argument("unsupported transport version");
    }
    long long I, J, K;
    int coherent;
    auto& p = result.problem;
    read(input,I);
    read(input,J);
    read(input,K);
    read(input,coherent);
    read(input,p.version);
    if (I <= 0 || J <= 0 || K <= 0 || (coherent != 0 && coherent != 1)) {
        throw std::invalid_argument("invalid dimensions or units");
    }
    p.coherent = coherent == 1;
    p.queries.resize(I);
    p.models.resize(J);
    p.tiers.resize(K);
    read(input,p.storage_price);
    read(input,p.budget);
    read(input,p.storage_capacity);
    read(input,p.horizon);
    read(input,p.eta);
    read(input,p.seconds_per_hour);
    read(input,p.data_residency);
    for (auto& q : p.queries) {
        read(input,q.arrival);
        read(input,q.input_tokens);
        read(input,q.output_tokens);
        read(input,q.storage);
        read(input,q.delay_slo);
        read(input,q.error_slo);
        read(input,q.delay_penalty);
        read(input,q.unmet_penalty);
        read(input,q.max_unmet);
    }
    for (auto& m : p.models) {
        read(input,m.weight);
        read(input,m.kv);
    }
    for (auto& t : p.tiers) {
        long long count;
        read(input,t.capacity);
        read(input,t.throughput);
        read(input,t.rental);
        read(input,count);
        if (count <= 0) throw std::invalid_argument("invalid configuration count");
        t.configs.resize(count);
        for (auto& c : t.configs) {
            read(input,c.n);
            read(input,c.m);
        }
    }
    if (p.I() > std::numeric_limits<std::size_t>::max()/p.J()/p.K()) {
        throw std::invalid_argument("dimension overflow");
    }
    const auto count = p.I()*p.J()*p.K();
    for (auto* a : {&p.error,&p.compute_delay,&p.communication_delay,&p.alpha,&p.residency_seconds}) {
        a->resize(count);
    }
    for (std::size_t r = 0; r < count; ++r) {
        read(input,p.error[r]);
        read(input,p.compute_delay[r]);
        read(input,p.communication_delay[r]);
        read(input,p.alpha[r]);
        read(input,p.residency_seconds[r]);
    }
    read(input,result.options.budget_fraction);
    read(input,result.seed);
    p.prepare();
    int state_present;
    read(input,state_present);
    if (state_present != 0 && state_present != 1) {
        throw std::invalid_argument("invalid state-presence flag");
    }
    if (state_present) {
        result.state = Placement::zero(p);
        auto& s = *result.state;
        for (auto* a : {&s.x,&s.z,&s.q,&s.u,&s.w,&s.y,&s.v}) {
            read_array(input,*a);
        }
    }
    std::string extra;
    if (input >> extra) throw std::invalid_argument("unexpected trailing transport data");
    return result;
}
void quoted(std::ostream& out, const std::string& value) {
    constexpr char hex[] = "0123456789abcdef";
    out << '"';
    for (const unsigned char c : value) {
        if (c == '"' || c == '\\') {
            out << '\\' << static_cast<char>(c);
        } else if (c < 0x20) {
            out << "\\u00" << hex[c >> 4] << hex[c & 0xf];
        } else {
            out << static_cast<char>(c);
        }
    }
    out << '"';
}
void placement_json(std::ostream& out, const Placement* state) {
    if (!state) {
        out << "null";
        return;
    }
    out << "{\"x\":";
    array(out,state->x);
    out << ",\"z\":";
    array(out,state->z);
    out << ",\"q\":";
    array(out,state->q);
    out << ",\"u\":";
    array(out,state->u);
    out << ",\"w\":";
    array(out,state->w);
    out << ",\"y\":";
    array(out,state->y);
    out << ",\"v\":";
    array(out,state->v);
    out << '}';
}
void validation_json(std::ostream& out, const Validation* report, bool residuals) {
    out << ",\"feasible\":" << (report&&report->feasible?"true":"false") << ",\"objective\":";
    if (!report || !report->domains_valid) {
        out << "null";
    } else {
        out << '[' << report->objective.c1 << ',' << report->objective.c2 << ','
            << report->objective.c3 << ',' << report->objective.c4 << ',' << report->objective.c5 << ']';
    }
    if (report && residuals) {
        out << ",\"residuals\":[";
        bool first = true;
        for (const auto& row : report->residuals) {
            if (!first) out << ',';
            first = false;
            out << "{\"family\":";
            quoted(out,row.family);
            out << ",\"index\":" << row.index << ",\"slack\":" << row.slack
                << ",\"threshold\":" << row.threshold << '}';
        }
        out << ']';
    }
}
void gh_trace(std::ostream& out, const GhResult& result, const Problem& p) {
    out << ",\"gh_trace\":{\"phase1_termination\":";
    quoted(out,result.phase1.termination);
    out << ",\"phase1_selected\":[";
    bool first = true;
    for (const auto& iteration : result.phase1.iterations) {
        if (!first) out << ',';
        first = false;
        const auto& candidate = iteration.candidates[iteration.ranked_candidates.front()];
        out << '[' << p.pair(candidate.model,candidate.tier) << ',' << *candidate.common_configuration << ']';
    }
    out << "],\"queries\":[";
    first = true;
    for (const auto& query : result.queries) {
        if (!first) out << ',';
        first = false;
        out << "{\"query\":" << query.query << ",\"ranked\":[";
        bool first_rank = true;
        for (auto index : query.ranked_candidates) {
            if (!first_rank) out << ',';
            first_rank = false;
            const auto& candidate = query.candidates[index];
            out << p.pair(candidate.model,candidate.tier);
        }
        out << "],\"attempts\":[";
        bool first_attempt = true;
        for (const auto& attempt : query.attempts) {
            if (!first_attempt) out << ',';
            first_attempt = false;
            out << "{\"position\":" << attempt.ranked_position << ",\"allocation\":" << attempt.allocation
                << ",\"committed\":" << (attempt.committed()?"true":"false")
                << ",\"budget\":" << attempt.after.budget_used << ",\"x\":";
            array(out,attempt.after.x);
            out << ",\"remaining\":";
            array(out,attempt.after.remaining);
            out << '}';
        }
        out << "],\"termination\":";
        quoted(out,query.termination);
        out << '}';
    }
    out << "]}";
}

void agh_trace(std::ostream& out, const AghResult& result) {
    const auto& multi = result.multistart;
    out << ",\"executed_count\":" << multi.starts.size() << ",\"incumbent_index\":";
    if (multi.incumbent_index) out << *multi.incumbent_index;
    else out << -1;
    out << ",\"termination\":";
    quoted(out,multi.termination_reason);
    out << ",\"starts\":[";
    bool first = true;
    for (const auto& trace : multi.starts) {
        if (!first) out << ',';
        first = false;
        out << "{\"order\":";
        array(out,trace.start.ordering.queries);
        out << ",\"counter\":" << trace.counter_after << ",\"comparison\":";
        quoted(out,trace.comparison_outcome);
        const auto* start_report = trace.start.final_validation();
        out << ",\"cost\":";
        if (start_report) out << start_report->objective.total();
        else out << "null";
        out << '}';
    }
    out << ']';
}
} // namespace pacs::io
