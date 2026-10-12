#include "pacs/core.hpp"
#include <cmath>
#include <iostream>
#include <stdexcept>
#include <utility>
#include <vector>

void test_gh();void test_agh();
namespace {
void require(bool condition,const char* message) {if(!condition) throw std::runtime_error(message);}
void test_core() {
    using namespace pacs;
    require(python_fsum(std::vector<double>{1e16,1,-1e16})==1,"fsum cancellation");
    require(python_sum(std::vector<double>{1e16,1,-1e16})==1,"sum compensation");
    require(python_fsum(std::vector<double>{0.6,0.3,0.1})==1,"fsum demand rounding");
    Problem p;p.queries={{3600,1,1,0.1,10,0.5,0.001,7,1}};p.models={{2,0.1}};
    p.tiers={{4,1,3,{{1,1}}}};p.error={0.1};p.compute_delay={0.25};p.communication_delay={0.125};p.alpha={1};p.residency_seconds={2};
    p.horizon=2;p.storage_price=0.5;p.budget=1000;p.storage_capacity=1000;p.eta=1;p.data_residency=0.5;p.prepare();
    auto s=Placement::zero(p);s.x[0]=s.z[0]=s.q[0]=s.w[0]=s.y[0]=s.v[0]=1;
    const auto report=validate(p,s);
    require(report.feasible,"hand-derived complete placement");
    require(report.delay[0]==0.625,"TTFT plus generation operation order");
    require(report.memory[0]==2.4,"coherent KV mean stock");
    require(report.storage[0]==362,"coherent resident storage");
    require(report.compute_required[0]==7.2,"compute units");
    require(report.objective.c1==6&&report.objective.c2==2&&report.objective.c3==360&&report.objective.c4==4500&&report.objective.c5==0,"hand-derived C1-C5");
    s.v[0]=0;require(!validate(p,s).feasible,"supplied auxiliary must not be repaired");
    s.v[0]=1;s.y[0]=0.5;require(!validate(p,s).domains_valid,"exact GPU integer domain");
    auto configurations=p;
    configurations.tiers[0].configs={{2,2},{2,1},{1,2},{1,1}};
    configurations.prepare();
    require(configurations.tiers[0].configs.front().n==2 && configurations.tiers[0].configs.front().m==2,
            "Cartesian axes retain supplied semantic order rather than numeric sorting");
    const auto reject_configurations=[&](std::vector<Config> choices) {
        auto candidate=p;candidate.tiers[0].configs=std::move(choices);
        try {candidate.prepare();} catch(const std::invalid_argument&) {return true;}
        return false;
    };
    require(reject_configurations({{1,2},{2,1}}),"reject incomplete Cartesian configuration subset");
    require(reject_configurations({{1,1},{2,1},{1,2},{2,2}}),"reject interleaved Cartesian configuration order");
    require(reject_configurations({{1,2},{1,1},{2,1},{2,2}}),"reject inconsistent pipeline order across tensor blocks");
    bool rejected=false;p.seconds_per_hour=60;try {p.prepare();}catch(const std::invalid_argument&) {rejected=true;}
    require(rejected,"coherent time conversion boundary");
}
}
int main() {
    try {test_core();test_gh();test_agh();std::cout<<"core, GH and AGH tests passed\n";return 0;}
    catch(const std::exception& error) {std::cerr<<error.what()<<'\n';return 1;}
}
