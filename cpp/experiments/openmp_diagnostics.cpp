// Opt-in measurement wrapper. Scientific GH/AGH sources are linked unchanged.
#include "pacs/campaign.hpp"
#include "pacs/io.hpp"
#include <algorithm>
#include <chrono>
#include <exception>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <numeric>
#include <optional>
#include <sstream>
#include <string>
#include <omp.h>
#include <sched.h>
using namespace pacs;
using Clock = std::chrono::steady_clock;
double elapsed(Clock::time_point a) { return std::chrono::duration<double>(Clock::now()-a).count(); }
std::string evidence(const CampaignCase& c, const CampaignCaseResult& r, bool full=false) {
    std::ostringstream o; o << std::setprecision(17) << "{\"placement\":";
    if (auto g=std::get_if<GhResult>(&r)) {
        io::placement_json(o,&g->placement); io::validation_json(o,&g->validation,full);
        if(full) io::gh_trace(o,*g,c.problem);
    } else {
        const auto& a=std::get<AghResult>(r);
        io::placement_json(o,a.final_placement());
        io::validation_json(o,a.final_validation?&*a.final_validation:nullptr,full);
        if(full) io::agh_trace(o,a);
    }
    o << '}'; return o.str();
}
std::string fingerprint(const std::string& s) {
    // Compact final-projection fingerprint; file SHA-256 is owned by the coordinator.
    unsigned long long h=14695981039346656037ULL;
    for (unsigned char b:s) { h^=b; h*=1099511628211ULL; }
    std::ostringstream out; out << std::hex << h; return out.str();
}
int main(int argc,char** argv) {
  try {
    if(argc!=6) throw std::invalid_argument("usage: probe threads static|dynamic|guided chunk warm|0 evidence_dir < manifest");
    int threads=std::stoi(argv[1]),chunk=std::stoi(argv[3]); std::string schedule=argv[2];
    if(threads<1||chunk<1) throw std::invalid_argument("positive threads/chunk required");
    omp_sched_t kind= schedule=="static"?omp_sched_static:schedule=="dynamic"?omp_sched_dynamic:omp_sched_guided;
    if(schedule!="static"&&schedule!="dynamic"&&schedule!="guided") throw std::invalid_argument("bad schedule");
    omp_set_schedule(kind,chunk);
    std::string magic; int version{},count{};
    if(!(std::cin>>magic>>version>>count)) throw std::invalid_argument("malformed manifest header");
    if(magic!="PACS_CAMPAIGN"||version!=1||count<1) throw std::invalid_argument("bad manifest");
    std::vector<CampaignCase> cases;
    for(int i=0;i<count;++i) {
        std::string method,name,path; std::cin>>method>>std::quoted(name)>>std::quoted(path);
        if(method!="gh"&&method!="agh") throw std::invalid_argument("unknown campaign method");
        std::ifstream file(path); auto p=io::read_input(file);
        cases.push_back({std::move(p.problem),p.options,p.seed,name,method=="gh"?CampaignMethod::gh:CampaignMethod::agh});
    }
    std::vector<int> order(count); std::iota(order.begin(),order.end(),0);
    std::vector<double> pilot(count);
    // Warmup also observes job costs for the explicitly requested sort intervention.
    if(std::string(argv[4])!="0") for(int i=0;i<count;++i) {
        auto begin=Clock::now();
        if(cases[i].method==CampaignMethod::gh) { auto r=run_gh(cases[i].problem,cases[i].options); pilot[i]=elapsed(begin); }
        else { auto r=run_agh(cases[i].problem,cases[i].seed,cases[i].options); pilot[i]=elapsed(begin); }
    }
    // Cost ordering is a frozen coordinator-supplied manifest, outside timing.
    std::vector<std::optional<CampaignCaseResult>> outputs(count);
    std::vector<std::exception_ptr> errors(count);
    std::vector<double> busy(threads),job_seconds(count); std::vector<int> jobs(threads),cpus(threads);
    int actual=0;
    auto start=Clock::now();
    #pragma omp parallel num_threads(threads) shared(actual,outputs,errors,busy,jobs,cpus,job_seconds,cases,order,count)
    {
        int id=omp_get_thread_num();
        double local_busy=0; int local_jobs=0;
        #pragma omp single
        actual=omp_get_num_threads();
        cpus[id]=sched_getcpu();
        #pragma omp for schedule(runtime)
        for(int oi=0;oi<count;++oi) {
            int i=order[oi]; auto begin=Clock::now();
            try {
                if(cases[i].method==CampaignMethod::gh) outputs[i].emplace(std::in_place_type<GhResult>,run_gh(cases[i].problem,cases[i].options));
                else outputs[i].emplace(std::in_place_type<AghResult>,run_agh(cases[i].problem,cases[i].seed,cases[i].options));
            } catch(...) { errors[i]=std::current_exception(); }
            double seconds=elapsed(begin); local_busy+=seconds; job_seconds[i]=seconds; ++local_jobs;
        }
        busy[id]=local_busy; jobs[id]=local_jobs;
    }
    double core=elapsed(start);
    for(auto& error:errors) if(error) std::rethrow_exception(error);
    std::cout<<std::setprecision(17)<<"{\"core_seconds\":"<<core<<",\"actual_threads\":"<<actual<<",\"busy_seconds\":";
    busy.resize(actual); jobs.resize(actual); cpus.resize(actual);
    io::array(std::cout,busy); std::cout<<",\"job_count\":";io::array(std::cout,jobs);
    std::cout<<",\"cpu_start\":";io::array(std::cout,cpus);
    std::cout<<",\"job_seconds\":";io::array(std::cout,job_seconds);
    std::cout<<",\"fingerprints\":[";
    for(int i=0;i<count;++i) {
        if(i) std::cout<<',';
        auto e=evidence(cases[i],*outputs[i]);io::quoted(std::cout,fingerprint(e));
        if(std::string(argv[5])!="-") { std::ofstream f(std::string(argv[5])+"/"+std::to_string(i)+".json");f<<evidence(cases[i],*outputs[i],true)<<'\n'; }
    }
    std::cout<<"]}\n";
  } catch(const std::exception& e) { std::cerr<<e.what()<<'\n';return 2; }
}
