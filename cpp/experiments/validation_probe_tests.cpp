#include "validation_probe.hpp"

#include <bit>
#include <cmath>
#include <cstdint>
#include <exception>
#include <iostream>
#include <limits>
#include <omp.h>
#include <stdexcept>
#include <string>

namespace {
using namespace pacs;
using namespace pacs::experiment;

void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}
void same(double expected, double observed) {
    require(std::bit_cast<std::uint64_t>(expected) == std::bit_cast<std::uint64_t>(observed),
            "validation numeric value differs bitwise");
}
void same(const std::vector<double>& expected, const std::vector<double>& observed) {
    require(expected.size() == observed.size(),"validation vector size differs");
    for (std::size_t index = 0; index < expected.size(); ++index) {
        same(expected[index],observed[index]);
    }
}
void same(const Validation& expected, const Validation& observed) {
    require(expected.domains_valid == observed.domains_valid && expected.feasible == observed.feasible,
            "validation classification differs");
    same(expected.objective.c1,observed.objective.c1);
    same(expected.objective.c2,observed.objective.c2);
    same(expected.objective.c3,observed.objective.c3);
    same(expected.objective.c4,observed.objective.c4);
    same(expected.objective.c5,observed.objective.c5);
    same(expected.delay,observed.delay);
    same(expected.error,observed.error);
    same(expected.memory,observed.memory);
    same(expected.compute_required,observed.compute_required);
    same(expected.compute_available,observed.compute_available);
    same(expected.storage,observed.storage);
    same(expected.demand,observed.demand);
    require(expected.residuals.size() == observed.residuals.size(),"residual count differs");
    for (std::size_t index = 0; index < expected.residuals.size(); ++index) {
        const auto& before = expected.residuals[index];
        const auto& after = observed.residuals[index];
        require(before.family == after.family && before.index == after.index,
                "residual family/index/order differs");
        same(before.slack,after.slack);
        same(before.threshold,after.threshold);
    }
}

Problem problem(std::size_t queries) {
    Problem p;
    p.queries.assign(queries,{3600,1,1,0.1,10,0.5,0.001,7,1});
    p.models = {{2,0.1},{3,0.2}};
    // Unequal per-tier grids exercise vc/pc offsets and the direct-slot order.
    p.tiers = {{1e6,1,3,{{1,1},{1,2},{2,1},{2,2}}},
               {1e6,2,4,{{1,1},{2,1}}}};
    const auto routes = p.I()*p.J()*p.K();
    p.error.assign(routes,0.1);
    p.compute_delay.assign(routes,0.25);
    p.communication_delay.assign(routes,0.125);
    p.alpha.assign(routes,1);
    p.residency_seconds.assign(routes,2);
    p.horizon = 2;
    p.storage_price = 0.5;
    p.budget = 1e8;
    p.storage_capacity = 1000;
    p.eta = 1;
    p.data_residency = 0.5;
    p.prepare();
    return p;
}
Placement placement(const Problem& p) {
    auto state = Placement::zero(p);
    state.q[0] = state.y[0] = state.w[0] = 1;
    for (std::size_t i = 0; i < p.I(); ++i) {
        state.x[p.route(i,0,0)] = state.z[p.route(i,0,0)] = 1;
        state.v[p.vc(i,0,0,0)] = 1;
    }
    return state;
}
Validation evaluate(const Problem& p, const Placement& state, const Tolerances& tolerances,
                    const ProbeExecution& execution, ProbeCallObservation& observation) {
    return validate_probe(p,state,tolerances,execution,observation);
}

void compare_modes(const Problem& p, const Placement& state, const Tolerances& tolerances) {
    ProbeCallObservation baseline_observation;
    const auto baseline = evaluate(p,state,tolerances,{},baseline_observation);
    for (const auto execution : {ProbeExecution{ValidationMode::slots,1,0},
                                 ProbeExecution{ValidationMode::omp,1,0},
                                 ProbeExecution{ValidationMode::omp,2,0},
                                 ProbeExecution{ValidationMode::omp,4,0},
                                 ProbeExecution{ValidationMode::omp,8,0}}) {
        ProbeCallObservation observation;
        same(baseline,evaluate(p,state,tolerances,execution,observation));
        if (baseline.domains_valid) {
            require(observation.mccormick_rows == 4*p.I()*p.config_count(),"wrong prefix count");
            require(observation.region_entered == (execution.mode == ValidationMode::omp),
                    "parallel region observation differs");
            require(observation.actual_threads >= 1 && observation.actual_threads <= execution.threads,
                    "observed team outside requested range");
        } else require(!observation.region_entered,"invalid domains entered a parallel region");
    }
    ProbeCallObservation fallback;
    same(baseline,evaluate(p,state,tolerances,
         {ValidationMode::omp,4,4*p.I()*p.config_count()+1},fallback));
    if (baseline.domains_valid) {
        require(fallback.grain_fallback && !fallback.region_entered,"grain fallback not used");
    }
}

void test_values() {
    for (const auto queries : {1u,4u,32u,64u}) {
        const auto p = problem(queries);
        auto state = placement(p);
        ProbeCallObservation observation;
        const auto hand = evaluate(p,state,{}, {},observation);
        require(hand.feasible,"hand-derived complete placement must be feasible");
        require(hand.objective.c1 == 6 && hand.objective.c2 == 2*queries &&
                hand.objective.c3 == 360*queries && hand.objective.c4 == 4500*queries &&
                hand.objective.c5 == 0,"hand-derived costs differ");
        require(hand.delay.front() == 0.625 && hand.storage.front() == 362,
                "hand-derived service/resource values differ");
        require(hand.residuals.size() == 4*p.I()*p.config_count()+4*p.I()+1+
                4*p.J()*p.K()+3*p.I()*p.J()*p.K(),"hand-derived residual count differs");
        compare_modes(p,state,{});
        compare_modes(p,state,Tolerances::exact());
        // Negative zeros are admissible in domains and must survive every
        // residual slack/threshold operation exactly like the append baseline.
        for (auto* values : {&state.x,&state.z,&state.q,&state.u,&state.w,&state.y,&state.v}) {
            for (double& value : *values) if (value == 0) value = -0.0;
        }
        const Tolerances signed_zero{-0.0,-0.0,-0.0,-0.0,-0.0,-0.0,-0.0,-0.0,
                                      -0.0,-0.0,-0.0,-0.0,-0.0,-0.0,-0.0};
        compare_modes(p,state,signed_zero);
        const auto zeros = evaluate(p,state,signed_zero,{},observation);
        require(!std::signbit(zeros.residuals.front().threshold),
                "threshold must retain the original addition of positive zero");
        state.v[0] = 0;
        require(!evaluate(p,state,{}, {},observation).feasible,"supplied auxiliary must not be repaired");
        compare_modes(p,state,{});
        state.y[0] = 0.5;
        compare_modes(p,state,{});
    }
}

void test_nested_fallback() {
    const auto p = problem(4);
    const auto state = placement(p);
    const Tolerances tolerances;
    ProbeCallObservation baseline_observation, observation;
    const auto baseline = evaluate(p,state,tolerances,{},baseline_observation);
    Validation nested;
    std::exception_ptr error;
    int outer_team = 1;
    #pragma omp parallel num_threads(2) default(none) \
        shared(p,state,tolerances,nested,observation,error,outer_team)
    {
        #pragma omp single
        {
            outer_team = omp_get_num_threads();
            try {
                nested = evaluate(p,state,tolerances,{ValidationMode::omp,4,0},observation);
            } catch (...) { error = std::current_exception(); }
        }
    }
    if (error) std::rethrow_exception(error);
    same(baseline,nested);
    if (outer_team > 1) {
        require(observation.nested_fallback && !observation.region_entered,
                "active outer team must select the append fallback");
    }
}

void test_observer() {
    const auto p = problem(4);
    const auto state = placement(p);
    ProbeSession outer, inner{{ValidationMode::omp,2,0},{}};
    {
        ScopedProbeSession scope(outer);
        validate(p,state);
        {
            ScopedProbeSession nested_scope(inner);
            validate(p,state);
        }
        validate(p,state);
    }
    require(outer.samples.size() == 2 && inner.samples.size() == 1,
            "observer scope failed to restore the previous borrowed session");
    require(!outer.samples.front().observation.region_entered &&
            inner.samples.front().observation.region_entered,"observer execution settings leaked");
    ProbeSession failure;
    {
        ScopedProbeSession scope(failure);
        auto invalid = Tolerances::exact();
        invalid.mccormick = -1;
        bool rejected = false;
        try { validate(p,state,invalid); }
        catch (const std::invalid_argument&) { rejected = true; }
        require(rejected,"invalid tolerance must still fail");
    }
    require(failure.samples.size() == 1 && !failure.samples.front().succeeded,
            "observer failed to retain/rethrow boundary failure");
}

void test_overflow() {
    auto p = problem(4);
    const auto state = placement(p);
    p.models[0].kv = std::numeric_limits<double>::max();
    p.prepare();
    std::string baseline_message;
    for (const auto mode : {ValidationMode::append,ValidationMode::slots,ValidationMode::omp}) {
        ProbeCallObservation observation;
        try {
            evaluate(p,state,{}, {mode,4,0},observation);
            throw std::runtime_error("nonfinite scientific arithmetic was accepted");
        } catch (const std::overflow_error& error) {
            if (baseline_message.empty()) baseline_message = error.what();
            require(baseline_message == error.what(),"overflow exception changed between modes");
            require(!observation.region_entered,"quantity overflow must occur before the team");
        }
    }
}
} // namespace

int main() {
    try {
        test_values();
        test_nested_fallback();
        test_observer();
        test_overflow();
        std::cout << "validation probe bitwise, hand-derived, fallback and observer tests passed\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
