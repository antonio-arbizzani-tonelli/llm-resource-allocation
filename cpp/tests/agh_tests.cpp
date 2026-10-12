#include "pacs/agh.hpp"

#include <cmath>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace {
template<class T>
concept HasFinalPlacement = requires(T&& value) {
    std::forward<T>(value).final_placement();
};
template<class T>
concept HasFinalValidation = requires(T&& value) {
    std::forward<T>(value).final_validation();
};
template<class T>
concept HasIncumbent = requires(T&& value) {
    std::forward<T>(value).incumbent();
};

static_assert(HasFinalPlacement<pacs::AghStartResult&> && HasFinalPlacement<const pacs::AghStartResult&>);
static_assert(!HasFinalPlacement<pacs::AghStartResult> && !HasFinalPlacement<const pacs::AghStartResult>);
static_assert(HasFinalValidation<pacs::AghStartResult&> && HasFinalValidation<const pacs::AghStartResult&>);
static_assert(!HasFinalValidation<pacs::AghStartResult> && !HasFinalValidation<const pacs::AghStartResult>);
static_assert(HasIncumbent<pacs::AghMultiStartResult&> && HasIncumbent<const pacs::AghMultiStartResult&>);
static_assert(!HasIncumbent<pacs::AghMultiStartResult> && !HasIncumbent<const pacs::AghMultiStartResult>);
static_assert(HasFinalPlacement<pacs::AghResult&> && HasFinalPlacement<const pacs::AghResult&>);
static_assert(!HasFinalPlacement<pacs::AghResult> && !HasFinalPlacement<const pacs::AghResult>);

void require(bool condition,const char* message) {
    if (!condition) throw std::runtime_error(message);
}
void close(double actual,double expected,const char* message) {
    require(std::abs(actual-expected)<1e-12,message);
}

pacs::Problem fixture(const std::vector<double>& weights,std::size_t query_count=1) {
    pacs::Problem p;
    p.queries.assign(query_count,{1,1,0,0,10,0.1,0,1,1});
    for (const double weight:weights) p.models.push_back({weight,0});
    p.tiers.push_back({100,1,1,{{1,1}}});
    const auto count=query_count*weights.size();
    p.error.assign(count,0.01);
    p.compute_delay.assign(count,0.1);
    p.communication_delay.assign(count,0);
    p.alpha.assign(count,1);
    p.residency_seconds.assign(count,1);
    p.storage_price=0.1;
    p.budget=100;
    p.storage_capacity=100;
    p.horizon=1;
    p.eta=1;
    p.prepare();
    return p;
}

pacs::Placement all_active(const pacs::Problem& p,const std::vector<std::size_t>& assignments) {
    auto state=pacs::Placement::zero(p);
    for (std::size_t pair=0;pair<p.J()*p.K();++pair) state.q[pair]=state.y[pair]=1;
    for (std::size_t j=0;j<p.J();++j) state.w[p.pc(j,0,0)]=1;
    for (std::size_t i=0;i<p.I();++i) {
        state.x[p.route(i,assignments[i],0)]=1;
        state.z[p.route(i,assignments[i],0)]=1;
        state.v[p.vc(i,assignments[i],0,0)]=1;
    }
    return state;
}

void relocate_checks() {
    auto p=fixture({4,3,1});
    const auto before=all_active(p,{0});
    const auto one=pacs::run_agh_relocate(p,before,1);
    require(one.passes.size()==1 && one.passes[0].accepted_move_count==1,"one relocate pass");
    require(one.placement.x==std::vector<double>({0,1,0}),"relocate must take first improvement");
    require(one.passes[0].sources[0].eligible_destinations==std::vector<std::size_t>({1,2}),"semantic destination order");
    require(one.passes[0].sources[0].attempts.size()==1,"stop destination scan immediately");
    require(one.placement.q==before.q && one.placement.w==before.w && one.placement.y==before.y,"relocate preserves rentals/configurations");
    require(before.x==std::vector<double>({1,0,0}),"relocate does not mutate caller");
    close(one.validation.objective.total(),3.3,"relocate hand-derived objective");
    close(one.passes[0].objective_before.total()-one.passes[0].objective_after.total(),0.1,"first improvement decrease");
    const auto complete=pacs::run_agh_relocate(p,before);
    require(complete.termination_reason=="no_change_pass" && complete.passes.size()==3,"relocate third unchanged pass");
    require(complete.placement.x==std::vector<double>({0,0,1}),"new positive routes wait for next pass");
    require(complete.passes[0].source_snapshot==std::vector<std::size_t>({0})
            && complete.passes[1].source_snapshot==std::vector<std::size_t>({1}),"frozen source snapshots");
    close(complete.validation.objective.total(),3.1,"full relocate hand-derived objective");

    p=fixture({1,1});
    const auto equal=pacs::run_agh_relocate(p,all_active(p,{0}));
    require(equal.passes.size()==1 && equal.passes[0].accepted_move_count==0,"equal objective must reject");
    require(equal.passes[0].sources[0].attempts[0].rejection_reasons==std::vector<std::string>({"not_strictly_improving"}),"strict objective rejection reason");

    p=fixture({4,1});
    p.alpha[1]=7200000; // 7200 TFLOP/h > 3600 TFLOP/h destination capacity.
    const auto blocked=pacs::run_agh_relocate(p,all_active(p,{0}));
    require(blocked.placement.x==std::vector<double>({1,0}),"infeasible transfer rolls back");
    require(!blocked.passes[0].sources[0].attempts[0].feasible,"compute constraint rejects cheaper destination");
    require(blocked.validation.feasible,"rejected transfer keeps feasible original");

    bool invalid=false;
    try { pacs::run_agh_relocate(p,all_active(p,{0}),4); } catch (const std::invalid_argument&) { invalid=true; }
    require(invalid,"relocate maximum exceeds paper bound");
    auto malformed=all_active(p,{0});malformed.x.clear();
    invalid=false;
    try { pacs::run_agh_relocate(p,malformed); } catch (const std::invalid_argument&) { invalid=true; }
    require(invalid,"malformed public placement rejected before dense indexing");

    // Independent demand tolerance may accept the original tiny excess, but
    // route domains remain exact and the full-route candidate exceeds x<=1.
    p=fixture({4,1});
    auto roundoff=all_active(p,{1});
    roundoff.x[0]=roundoff.v[0]=1e-11;roundoff.z[0]=1;
    require(pacs::validate(p,roundoff).feasible,"near-balance source uses configured tolerance");
    const auto domain_rejected=pacs::run_agh_relocate(p,roundoff);
    require(!domain_rejected.passes[0].sources[0].attempts[0].objective_after,
            "invalid candidate domains have no invented objective evidence");
    require(domain_rejected.placement.x==roundoff.x,"domain-invalid transfer cannot repair input decisions");
}

void consolidation_checks() {
    auto p=fixture({1,1,1,1},2);
    p.queries[0].arrival=p.queries[1].arrival=1000;
    auto state=all_active(p,{2,3});
    state.x[p.route(0,2,0)]=state.v[p.vc(0,2,0,0)]=0.5;
    state.x[p.route(1,3,0)]=state.v[p.vc(1,3,0,0)]=0.5;
    state.u={0.5,0.5};
    const auto result=pacs::run_agh_consolidation_scan(p,state);
    require(result.source_snapshot.size()==4,"include empty active sources");
    for (std::size_t i=0;i<4;++i) require(result.source_snapshot[i].pair==i,"stable semantic utilization ties");
    close(result.source_snapshot[0].utilization,0,"empty source load");
    close(result.source_snapshot[2].required,0.5,"required compute hand value");
    close(result.source_snapshot[2].available,3600,"available compute hand value");
    close(result.source_snapshot[2].utilization,0.5/3600,"utilization hand ratio");
    require(result.accepted_source_count==3,"multiple deactivations in one frozen scan");
    require(result.placement.q==std::vector<double>({0,0,0,1}),"all traffic consolidated to final active pair");
    close(result.placement.x[p.route(0,3,0)],0.5,"whole source fraction transfer");
    require(result.placement.u==state.u,"consolidation preserves unmet fraction");
    // C1=1, C2=2*0.1, and C5=0.5+0.5; C3=C4=0.
    close(result.validation.objective.resource_cost(),1.2,"consolidation hand-derived resource cost");
    close(result.validation.objective.total(),2.2,"consolidation hand-derived final cost");
    require(result.validation.feasible,"independent consolidation acceptance");

    p=fixture({1,5});
    p.alpha={0,0}; // Both loads are zero, so the source precedes the empty target.
    state=all_active(p,{0});
    const auto worsening=pacs::run_agh_consolidation_scan(p,state);
    require(worsening.sources[0].status=="accepted","final rental removal can justify provisional worsening");
    require(*worsening.sources[0].routes[0].attempts[0].objective_after
            >worsening.sources[0].routes[0].attempts[0].objective_before,"first fit uses feasibility only");
    close(worsening.validation.objective.total(),1.5,"atomic rental removal final cost");

    // Reject the first destination for each route, then accept the second.
    // Rejections preserve the provisional objective; each accepted transfer
    // supplies the objective used as the next route's starting evidence.
    p=fixture({1,1,5},2);
    p.alpha.assign(6,0);
    p.error[p.route(0,1,0)]=p.error[p.route(1,1,0)]=0.2;
    state=all_active(p,{0,0});
    const auto sequential=pacs::run_agh_consolidation_scan(p,state);
    const auto& routes=sequential.sources[0].routes;
    require(sequential.sources[0].status=="accepted" && routes.size()==2,
            "multiple provisional transfers precede one atomic source acceptance");
    for (const auto& route:routes) {
        require(route.attempts.size()==2 && !route.attempts[0].accepted && route.attempts[1].accepted,
                "first-fit retains rejected destination before feasible transfer");
        close(route.attempts[0].objective_before,route.attempts[1].objective_before,
              "rejected candidate cannot update provisional objective");
    }
    close(routes[0].attempts[0].objective_before,3.2,"initial provisional hand objective");
    close(*routes[0].attempts[1].objective_after,3.6,"first accepted provisional hand objective");
    close(routes[1].attempts[0].objective_before,3.6,"next route uses accepted validation objective");
    close(*routes[1].attempts[1].objective_after,4.0,"second accepted provisional hand objective");
    close(sequential.sources[0].prospective_objective->total(),3.0,"rental removal remains final improvement authority");
    require(sequential.validation.feasible && state.x==std::vector<double>({1,0,0,1,0,0}),
            "cached objective preserves independent validation and caller state");

    p=fixture({1,1},2);
    p.alpha.assign(4,0);
    p.error[p.route(1,1,0)]=0.2;
    state=all_active(p,{0,0});
    const auto rollback=pacs::run_agh_consolidation_scan(p,state);
    require(rollback.sources[0].status=="rejected","one unabsorbable route rejects source transaction");
    require(rollback.sources[0].routes.size()==2 && rollback.sources[0].routes[0].selected_destination.has_value()
            && !rollback.sources[0].routes[1].selected_destination.has_value(),"failure after provisional success");
    require(rollback.placement.x==state.x,"partial redistribution rolls back atomically");
    require(rollback.accepted_source_count==1 && rollback.placement.q==std::vector<double>({1,0}),"later empty source can still deactivate");
    require(rollback.validation.feasible,"rollback result remains independently feasible");
}

void ordering_and_schedule_checks() {
    const std::vector<std::vector<std::size_t>> draws{
        {3,1,2,6,0,4,5},{5,1,2,6,0,4,3},{1,2,0,4,6,5,3}};
    for (std::size_t draw=0;draw<draws.size();++draw) {
        require(pacs::build_seeded_random_agh_ordering(7,"37",draw).queries==draws[draw],"Python seed shuffle parity");
        require(pacs::build_seeded_random_agh_ordering(7,"-37",draw).queries==draws[draw],"Python negative seed absolute semantics");
    }
    require(pacs::build_seeded_random_agh_ordering(7,"18446744073709551617",0).queries
            ==std::vector<std::size_t>({1,6,4,2,3,5,0}),"seed greater than uint64 uses all limbs");
    require(pacs::build_seeded_random_agh_ordering(7,"-123456789012345678901234567890",2).queries
            ==std::vector<std::size_t>({4,2,3,6,1,0,5}),"arbitrary signed integer seed parity");
    require(pacs::build_seeded_random_agh_ordering(1,"0",5).queries==std::vector<std::size_t>({0}),"duplicate singleton draws retained");
    require(pacs::adaptive_agh_random_start_count(1,1,500)==20
            && pacs::adaptive_agh_random_start_count(1,1,501)==10
            && pacs::adaptive_agh_random_start_count(1,1,2000)==10
            && pacs::adaptive_agh_random_start_count(1,1,2001)==5
            && pacs::adaptive_agh_random_start_count(1,1,5000)==5
            && pacs::adaptive_agh_random_start_count(1,1,5001)==3,"strict adaptive thresholds");
    auto p=fixture({1},3);
    p.queries[0].arrival=2;p.queries[1].arrival=1;p.queries[2].arrival=2;
    const auto orders=pacs::build_deterministic_agh_orderings(p);
    require(orders.size()==8 && orders[0].queries==std::vector<std::size_t>({1,0,2})
            && orders[1].queries==std::vector<std::size_t>({0,2,1}),"stable ties in both sorting directions");
    require(orders[2].queries==orders[3].queries,"duplicate labelled deterministic starts remain");

    p=fixture({1});
    const auto agh=pacs::run_agh(p,"37");
    require(agh.completed() && agh.final_validation->feasible,"complete AGH closure");
    require(agh.multistart.starts.size()==6 && agh.multistart.incumbent_index==0,"first feasible plus five equal starts");
    require(agh.multistart.nonimprovement_count==5
            && agh.multistart.termination_reason=="five_consecutive_nonimproving","global early stop at exactly five");
    require(agh.multistart.unexecuted_start_count()==22,"unexecuted schedule evidence");
    for (std::size_t i=1;i<6;++i)
        require(agh.multistart.starts[i].comparison_outcome=="non_improving"
                && agh.multistart.starts[i].counter_after==i,"equal start cannot replace incumbent");
    close(agh.final_validation->objective.total(),1.1,"complete AGH hand-derived objective");
    bool invalid_seed=false;
    try { pacs::run_agh(p,"37junk"); } catch (const std::invalid_argument&) { invalid_seed=true; }
    require(invalid_seed,"malformed external seed rejected even before random starts");

    p.queries[0].max_unmet=0;p.budget=0;
    const auto failed=pacs::run_agh(p,"37");
    require(!failed.completed() && failed.completion_status=="no_feasible_incumbent","failed GH does not trigger repair");
    require(failed.multistart.starts.size()==5 && !failed.final_placement(),"five failed starts without incumbent");
    require(!failed.multistart.starts[0].start.relocate.has_value(),"local search does not consume infeasible GH");
    require(failed.multistart.starts[0].start.failure_reasons
            ==std::vector<std::string>({"gh_independently_infeasible","gh_objective_unavailable"}),
            "domain-invalid GH retains missing-objective evidence");
}
} // namespace

void test_agh() {
    relocate_checks();
    consolidation_checks();
    ordering_and_schedule_checks();
}
