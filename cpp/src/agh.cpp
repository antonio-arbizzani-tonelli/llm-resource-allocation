#include "pacs/agh.hpp"

#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <cstdint>
#include <numeric>
#include <stdexcept>
#include <utility>

namespace pacs {
namespace {

constexpr double construction_absolute_tolerance = 1e-15;

// CPython random.Random(integer): absolute integer limbs, MT19937's array seed,
// getrandbits rejection sampling, then the same backwards Fisher-Yates shuffle.
// std::shuffle/distributions intentionally do not define this reference stream.
std::vector<std::uint32_t> seed_limbs(const std::string& decimal) {
    if (decimal.empty()) throw std::invalid_argument("AGH seed must be a decimal integer");
    std::size_t pos = decimal.front()=='-' || decimal.front()=='+' ? 1 : 0;
    if (pos == decimal.size()) throw std::invalid_argument("AGH seed must contain digits");
    std::vector<std::uint32_t> limbs{0};
    for (;pos<decimal.size();++pos) {
        const char digit=decimal[pos];
        if (digit<'0' || digit>'9') throw std::invalid_argument("AGH seed must be a decimal integer");
        std::uint64_t carry=static_cast<unsigned>(digit-'0');
        for (auto& limb:limbs) {
            const std::uint64_t value=static_cast<std::uint64_t>(limb)*10+carry;
            limb=static_cast<std::uint32_t>(value);
            carry=value>>32;
        }
        if (carry) limbs.push_back(static_cast<std::uint32_t>(carry));
    }
    return limbs;
}

class PythonRandom {
    std::array<std::uint32_t,624> state_{};
    std::size_t index_{624};

    std::uint32_t word() {
        if (index_==state_.size()) {
            constexpr std::uint32_t upper=0x80000000U, lower=0x7fffffffU, matrix=0x9908b0dfU;
            std::size_t k=0;
            for (;k<227;++k) {
                const auto y=(state_[k]&upper)|(state_[k+1]&lower);
                state_[k]=state_[k+397]^(y>>1)^((y&1U)?matrix:0U);
            }
            for (;k<623;++k) {
                const auto y=(state_[k]&upper)|(state_[k+1]&lower);
                state_[k]=state_[k-227]^(y>>1)^((y&1U)?matrix:0U);
            }
            const auto y=(state_[623]&upper)|(state_[0]&lower);
            state_[623]=state_[396]^(y>>1)^((y&1U)?matrix:0U);
            index_=0;
        }
        auto y=state_[index_++];
        y^=y>>11;
        y^=(y<<7)&0x9d2c5680U;
        y^=(y<<15)&0xefc60000U;
        y^=y>>18;
        return y;
    }

    std::uint64_t getrandbits(unsigned bits) {
        if (bits<=32) return word()>>(32-bits);
        const std::uint64_t low=word();
        const std::uint64_t high=word()>>(64-bits);
        return low|(high<<32);
    }

public:
    explicit PythonRandom(const std::string& seed) {
        const auto key=seed_limbs(seed);
        state_[0]=19650218U;
        for (std::size_t i=1;i<state_.size();++i)
            state_[i]=1812433253U*(state_[i-1]^(state_[i-1]>>30))+static_cast<std::uint32_t>(i);
        std::size_t i=1,j=0;
        for (std::size_t remaining=std::max(state_.size(),key.size());remaining;--remaining) {
            state_[i]=(state_[i]^((state_[i-1]^(state_[i-1]>>30))*1664525U))
                      +key[j]+static_cast<std::uint32_t>(j);
            if (++i==state_.size()) { state_[0]=state_[623]; i=1; }
            if (++j==key.size()) j=0;
        }
        for (std::size_t remaining=623;remaining;--remaining) {
            state_[i]=(state_[i]^((state_[i-1]^(state_[i-1]>>30))*1566083941U))
                      -static_cast<std::uint32_t>(i);
            if (++i==state_.size()) { state_[0]=state_[623]; i=1; }
        }
        state_[0]=0x80000000U;
    }

    std::size_t below(std::size_t bound) {
        const auto bits=static_cast<unsigned>(std::bit_width(bound));
        std::uint64_t result;
        do { result=getrandbits(bits); } while (result>=bound);
        return static_cast<std::size_t>(result);
    }

    std::vector<std::size_t> shuffle(std::size_t count) {
        std::vector<std::size_t> result(count);
        std::iota(result.begin(),result.end(),0);
        for (std::size_t remaining=count;remaining>1;--remaining)
            std::swap(result[remaining-1],result[below(remaining)]);
        return result;
    }
};

bool coherent_active(const Problem& p,const Placement& state,std::size_t pair) {
    return active_config(p,state,pair/p.K(),pair%p.K())>=0;
}

std::vector<std::size_t> active_destinations(const Problem& p,const Placement& state,
                                          std::size_t source_pair) {
    std::vector<std::size_t> destinations;
    for (std::size_t pair=0;pair<p.J()*p.K();++pair)
        if (pair!=source_pair && coherent_active(p,state,pair)) destinations.push_back(pair);
    return destinations;
}

Placement transfer_route(const Problem& p,const Placement& before,std::size_t source,
                         std::size_t destination,double fraction) {
    Placement after=before;
    const auto query=source/(p.J()*p.K()), source_pair=source%(p.J()*p.K());
    const auto destination_route=query*p.J()*p.K()+destination;
    after.x[source]=0;
    after.x[destination_route]+=fraction;
    after.z[source]=after.x[source]>0 ? 1 : 0;
    after.z[destination_route]=after.x[destination_route]>0 ? 1 : 0;
    for (const auto pair:{source_pair,destination}) {
        const auto j=pair/p.K(),k=pair%p.K();
        const auto route=query*p.J()*p.K()+pair;
        for (std::size_t c=0;c<p.tiers[k].configs.size();++c)
            after.v[p.vc(query,j,k,c)]=after.x[route]*after.w[p.pc(j,k,c)];
    }
    return after;
}

double routed_total(const Problem& p,const Placement& state,std::size_t query) {
    return python_fsum(std::span<const double>(state.x).subspan(query*p.J()*p.K(),p.J()*p.K()));
}

bool demand_preserved(const Problem& p,const Placement& before,const Placement& after,
                      std::size_t query) {
    return before.u[query]==after.u[query]
           && std::abs(routed_total(p,after,query)-routed_total(p,before,query))
              <=construction_absolute_tolerance;
}

struct MoveEvaluation {
    AghTransferAttempt trace;
    std::optional<Placement> candidate;
    std::optional<Validation> report;
};

MoveEvaluation evaluate_relocate(const Problem& p,const Placement& before,
                                const Validation& validation_before,std::size_t source,
                                std::size_t destination,const Tolerances& tolerance) {
    MoveEvaluation result;
    auto& trace=result.trace;
    trace.source_route=source;
    trace.destination_pair=destination;
    trace.objective_before=validation_before.objective.total();
    const auto reject=[&](const char* reason) {
        trace.rejection_reasons.emplace_back(reason);
    };
    if (!validation_before.domains_valid) { reject("invalid_placement_domains"); return result; }
    if (source>=p.I()*p.J()*p.K()) { reject("invalid_source"); return result; }
    trace.moved_fraction=before.x[source];
    if (trace.moved_fraction<=0) { reject("no_source_routing"); return result; }
    const auto source_pair=source%(p.J()*p.K()),query=source/(p.J()*p.K());
    if (!coherent_active(p,before,source_pair) || before.z[source]!=1) {
        reject("incoherent_source_deployment"); return result;
    }
    if (destination>=p.J()*p.K()) { reject("invalid_destination"); return result; }
    if (destination==source_pair) { reject("same_source_and_destination"); return result; }
    if (before.q[destination]!=1 || before.y[destination]<=0) {
        reject("destination_not_active"); return result;
    }
    if (!coherent_active(p,before,destination)) {
        reject("incoherent_destination_deployment"); return result;
    }
    result.candidate=transfer_route(p,before,source,destination,trace.moved_fraction);
    trace.routed_difference=std::abs(routed_total(p,*result.candidate,query)-routed_total(p,before,query));
    result.report=validate(p,*result.candidate,tolerance);
    trace.feasible=result.report->feasible;
    if (result.report->domains_valid) trace.objective_after=result.report->objective.total();
    if (!demand_preserved(p,before,*result.candidate,query)) reject("construction_inconsistency");
    if (!trace.feasible) reject("infeasible");
    if (trace.objective_after && !(*trace.objective_after<trace.objective_before)) reject("not_strictly_improving");
    trace.accepted=trace.rejection_reasons.empty();
    return result;
}

AghRelocateResult relocate_worker(const Problem& p,Placement current,Validation validation,
                                  std::size_t max_passes,const Tolerances& tolerance) {
    AghRelocateResult result;
    for (std::size_t pass_index=0;pass_index<max_passes;++pass_index) {
        AghRelocatePass pass;
        pass.objective_before=validation.objective;
        for (std::size_t route=0;route<p.I()*p.J()*p.K();++route)
            if (current.x[route]>0) pass.source_snapshot.push_back(route);
        for (const auto source:pass.source_snapshot) {
            AghRelocateSourceTrace source_trace;
            source_trace.source_route=source;
            if (current.x[source]<=0) source_trace.status="source_no_longer_active";
            else {
                source_trace.eligible_destinations=active_destinations(p,current,source%(p.J()*p.K()));
                for (const auto destination:source_trace.eligible_destinations) {
                    auto move=evaluate_relocate(p,current,validation,source,destination,tolerance);
                    const bool accepted=move.trace.accepted;
                    source_trace.attempts.push_back(std::move(move.trace));
                    if (accepted) {
                        current=std::move(*move.candidate);
                        validation=std::move(*move.report);
                        source_trace.status="move_accepted";
                        ++pass.accepted_move_count;
                        break;
                    }
                }
            }
            pass.sources.push_back(std::move(source_trace));
        }
        pass.objective_after=validation.objective;
        const bool changed=pass.accepted_move_count!=0;
        result.passes.push_back(std::move(pass));
        if (!changed) { result.termination_reason="no_change_pass"; break; }
    }
    result.placement=std::move(current);
    result.validation=std::move(validation);
    return result;
}

Placement deactivate_pair(const Problem& p,const Placement& before,std::size_t pair) {
    Placement after=before;
    const auto j=pair/p.K(),k=pair%p.K();
    after.q[pair]=0;
    after.y[pair]=0;
    for (std::size_t c=0;c<p.tiers[k].configs.size();++c) after.w[p.pc(j,k,c)]=0;
    for (std::size_t i=0;i<p.I();++i) {
        after.x[p.route(i,j,k)]=0;
        after.z[p.route(i,j,k)]=0;
        for (std::size_t c=0;c<p.tiers[k].configs.size();++c) after.v[p.vc(i,j,k,c)]=0;
    }
    return after;
}

struct ConsolidationEvaluation {
    AghConsolidationSourceTrace trace;
    std::optional<Placement> candidate;
    std::optional<Validation> validation;
};

ConsolidationEvaluation consolidate_source(const Problem& p,const Placement& before,
                                          const Validation& validation_before,std::size_t source,
                                          const Tolerances& tolerance) {
    ConsolidationEvaluation result;
    auto& trace=result.trace;
    trace.source_pair=source;
    trace.objective_before=validation_before.objective;
    const auto reject=[&](const char* reason) { trace.rejection_reasons.emplace_back(reason); };
    if (!validation_before.domains_valid) { reject("invalid_placement_domains"); return result; }
    if (before.q[source]!=1 || before.y[source]<=0) { reject("source_not_active"); return result; }
    if (!coherent_active(p,before,source)) { reject("incoherent_source_deployment"); return result; }
    for (std::size_t i=0;i<p.I();++i) {
        const auto route=i*p.J()*p.K()+source;
        if (before.x[route]>0) trace.source_routes.push_back(route);
    }
    trace.eligible_destinations=active_destinations(p,before,source);
    Placement provisional=before;
    Objective provisional_objective=validation_before.objective;
    for (const auto route:trace.source_routes) {
        AghConsolidationRouteTrace route_trace;
        route_trace.source_route=route;
        for (const auto destination:trace.eligible_destinations) {
            AghTransferAttempt attempt;
            attempt.source_route=route;
            attempt.destination_pair=destination;
            attempt.moved_fraction=provisional.x[route];
            attempt.objective_before=provisional_objective.total();
            auto candidate=transfer_route(p,provisional,route,destination,attempt.moved_fraction);
            auto report=validate(p,candidate,tolerance);
            attempt.feasible=report.feasible;
            attempt.accepted=report.feasible; // First fit compares feasibility only.
            if (report.domains_valid) attempt.objective_after=report.objective.total();
            attempt.routed_difference=std::abs(routed_total(p,candidate,route/(p.J()*p.K()))
                                               -routed_total(p,provisional,route/(p.J()*p.K())));
            route_trace.attempts.push_back(std::move(attempt));
            if (report.feasible) {
                provisional=std::move(candidate);
                provisional_objective=report.objective;
                route_trace.selected_destination=destination;
                break;
            }
        }
        const bool redistributed=route_trace.selected_destination.has_value();
        trace.routes.push_back(std::move(route_trace));
        if (!redistributed) { reject("redistribution_failed"); return result; }
    }
    result.candidate=deactivate_pair(p,provisional,source);
    bool consistent=true;
    for (std::size_t i=0;i<p.I();++i)
        consistent=consistent && demand_preserved(p,before,*result.candidate,i);
    result.validation=validate(p,*result.candidate,tolerance);
    if (result.validation->domains_valid) trace.prospective_objective=result.validation->objective;
    trace.prospective_feasible=result.validation->feasible;
    if (!consistent) reject("construction_inconsistency");
    if (!result.validation->feasible) reject("infeasible");
    if (trace.prospective_objective && !(result.validation->objective.total()<validation_before.objective.total()))
        reject("not_strictly_improving");
    if (trace.rejection_reasons.empty()) trace.status="accepted";
    return result;
}

AghConsolidationResult consolidation_worker(const Problem& p,Placement current,
                                             Validation validation,const Tolerances& tolerance) {
    AghConsolidationResult result;
    for (std::size_t pair=0;pair<p.J()*p.K();++pair) {
        if (!coherent_active(p,current,pair)) continue;
        const double required=validation.compute_required[pair],available=validation.compute_available[pair];
        result.source_snapshot.push_back({pair,required,available,required==0 ? 0 : required/available});
    }
    std::stable_sort(result.source_snapshot.begin(),result.source_snapshot.end(),
                     [](const AghLoad& a,const AghLoad& b) { return a.utilization<b.utilization; });
    for (const auto& load:result.source_snapshot) {
        if (current.q[load.pair]!=1 || current.y[load.pair]<=0) {
            AghConsolidationSourceTrace skipped;
            skipped.source_pair=load.pair;
            skipped.objective_before=validation.objective;
            skipped.status="source_no_longer_active";
            result.sources.push_back(std::move(skipped));
            continue;
        }
        auto transaction=consolidate_source(p,current,validation,load.pair,tolerance);
        if (transaction.trace.status=="accepted") {
            current=std::move(*transaction.candidate);
            validation=std::move(*transaction.validation);
            ++result.accepted_source_count;
        }
        result.sources.push_back(std::move(transaction.trace));
    }
    result.placement=std::move(current);
    result.validation=std::move(validation);
    return result;
}

bool same_objective(const Objective& a,const Objective& b) {
    return a.c1==b.c1 && a.c2==b.c2 && a.c3==b.c3 && a.c4==b.c4 && a.c5==b.c5;
}

} // namespace

std::vector<AghOrdering> build_deterministic_agh_orderings(const Problem& p) {
    const std::array<std::string,4> names{"arrival_rate","unmet_penalty","storage_per_token","error_slo"};
    std::vector<AghOrdering> result;
    for (std::size_t criterion=0;criterion<4;++criterion) {
        const auto value=[&](std::size_t i) {
            const auto& q=p.queries[i];
            if (criterion==0) return q.arrival;
            if (criterion==1) return q.unmet_penalty;
            if (criterion==2) return q.storage;
            return q.error_slo;
        };
        for (const bool descending:{false,true}) {
            AghOrdering ordering;
            ordering.queries.resize(p.I());
            std::iota(ordering.queries.begin(),ordering.queries.end(),0);
            std::stable_sort(ordering.queries.begin(),ordering.queries.end(),
                             [&](std::size_t a,std::size_t b) {
                                 return descending ? value(a)>value(b) : value(a)<value(b);
                             });
            ordering.criterion=names[criterion];
            ordering.direction=descending ? "descending" : "ascending";
            result.push_back(std::move(ordering));
        }
    }
    return result;
}

AghOrdering build_seeded_random_agh_ordering(std::size_t query_count,const std::string& seed,
                                           std::size_t random_start_index) {
    if (!query_count) throw std::invalid_argument("query count must be positive");
    PythonRandom rng(seed);
    AghOrdering result;
    result.source="seeded_random";
    result.seed=seed;
    result.random_start_index=random_start_index;
    for (std::size_t draw=0;;++draw) {
        result.queries=rng.shuffle(query_count);
        if (draw==random_start_index) return result;
    }
}

std::size_t adaptive_agh_random_start_count(std::size_t I,std::size_t J,std::size_t K) {
    if (!I || !J || !K) throw std::invalid_argument("AGH dimensions must be positive");
    // Only the strict thresholds matter: saturate safely above the largest one.
    if (I>5000 || J>5000/I) return 3;
    const auto IJ=I*J;
    if (K>5000/IJ) return 3;
    const auto scale=IJ*K;
    return scale>2000 ? 5 : scale>500 ? 10 : 20;
}

AghRelocateResult run_agh_relocate(const Problem& p,const Placement& before,
                                 std::size_t max_passes,const Tolerances& tolerance) {
    if (max_passes<1 || max_passes>3) throw std::invalid_argument("relocate max_passes must be in [1,3]");
    auto report=validate(p,before,tolerance);
    if (!report.domains_valid) throw std::invalid_argument("relocate requires valid placement domains");
    return relocate_worker(p,before,std::move(report),max_passes,tolerance);
}

AghConsolidationResult run_agh_consolidation_scan(const Problem& p,const Placement& before,
                                                const Tolerances& tolerance) {
    auto report=validate(p,before,tolerance);
    if (!report.domains_valid) throw std::invalid_argument("consolidation requires valid placement domains");
    return consolidation_worker(p,before,std::move(report),tolerance);
}

namespace {
AghStartResult start_worker(const Problem& p,const AghOrdering& ordering,
                           const GhOptions& options,const GhPhase1& phase1) {
    // GH's empty order selects its default; a supplied AGH order must be explicit.
    if (ordering.queries.empty()) throw std::invalid_argument("AGH ordering must be an explicit query permutation");
    AghStartResult result;
    result.ordering=ordering;
    result.gh=detail::run_gh_with_phase1(p,options,ordering.queries,phase1);
    if (!result.gh.algorithm_completed) result.failure_reasons.emplace_back("gh_algorithm_not_completed");
    if (!result.gh.validation.feasible) result.failure_reasons.emplace_back("gh_independently_infeasible");
    if (!result.gh.validation.domains_valid) result.failure_reasons.emplace_back("gh_objective_unavailable");
    if (!result.failure_reasons.empty()) return result;
    result.relocate=relocate_worker(p,result.gh.placement,result.gh.validation,3,options.tolerances);
    if (!result.relocate->validation.feasible) {
        result.completion_status="stopped_after_relocate";
        result.failure_reasons.emplace_back("relocate_independently_infeasible");
        return result;
    }
    result.consolidation=consolidation_worker(p,result.relocate->placement,
                                            result.relocate->validation,options.tolerances);
    if (!result.consolidation->validation.feasible) {
        result.completion_status="final_evaluation_failed";
        result.failure_reasons.emplace_back("final_independently_infeasible");
    } else result.completion_status="completed";
    return result;
}
} // namespace

AghStartResult run_agh_start(const Problem& p,const AghOrdering& ordering,
                            const GhOptions& options) {
    const auto phase1=run_gh_phase1(p,options);
    return start_worker(p,ordering,options,phase1);
}

AghMultiStartResult run_agh_multistart(const Problem& p,const std::string& random_seed,
                                      const GhOptions& options) {
    seed_limbs(random_seed); // Validate the external seed even if early stopping avoids random starts.
    AghMultiStartResult result;
    result.random_seed=random_seed;
    result.random_start_count=adaptive_agh_random_start_count(p.I(),p.J(),p.K());
    const auto deterministic=build_deterministic_agh_orderings(p);
    result.scheduled_start_count=deterministic.size()+result.random_start_count;
    const auto phase1=run_gh_phase1(p,options);
    for (std::size_t index=0;index<result.scheduled_start_count;++index) {
        AghStartTrace trace;
        trace.incumbent_before=result.incumbent_index;
        trace.counter_before=result.nonimprovement_count;
        if (index<deterministic.size()) {
            trace.start=start_worker(p,deterministic[index],options,phase1);
        } else {
            const auto ordering=build_seeded_random_agh_ordering(p.I(),random_seed,index-deterministic.size());
            trace.start=start_worker(p,ordering,options,phase1);
        }
        const bool feasible=trace.start.completed() && trace.start.final_validation()->feasible;
        if (feasible && !result.incumbent_index) {
            result.incumbent_index=index;
            result.nonimprovement_count=0;
            trace.comparison_outcome="initial_incumbent_established";
        } else if (feasible && result.incumbent_index
                   && trace.start.final_validation()->objective.total()
                      <result.incumbent()->final_validation()->objective.total()) {
            result.incumbent_index=index;
            result.nonimprovement_count=0;
            trace.comparison_outcome="strict_improvement";
        } else {
            ++result.nonimprovement_count;
            trace.comparison_outcome="non_improving";
        }
        trace.incumbent_after=result.incumbent_index;
        trace.counter_after=result.nonimprovement_count;
        result.starts.push_back(std::move(trace));
        if (result.nonimprovement_count==5) {
            result.termination_reason="five_consecutive_nonimproving";
            break;
        }
    }
    return result;
}

AghResult run_agh(const Problem& p,const std::string& random_seed,const GhOptions& options) {
    AghResult result;
    result.multistart=run_agh_multistart(p,random_seed,options);
    const auto* incumbent=result.multistart.incumbent();
    if (!incumbent) {
        result.failure_reasons.emplace_back("no_feasible_incumbent");
        return result;
    }
    result.final_validation=validate(p,*incumbent->final_placement(),options.tolerances);
    if (!result.final_validation->feasible) result.failure_reasons.emplace_back("final_validation_infeasible");
    if (!same_objective(result.final_validation->objective,incumbent->final_validation()->objective))
        result.failure_reasons.emplace_back("final_objective_mismatch");
    result.completion_status=result.failure_reasons.empty() ? "completed" : "final_consistency_failed";
    return result;
}

} // namespace pacs
