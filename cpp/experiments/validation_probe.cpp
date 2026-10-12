#include "validation_probe.hpp"

#include <chrono>
#include <exception>
#include <stdexcept>

namespace {
thread_local pacs::experiment::ProbeSession* active_session = nullptr;
}

namespace pacs::experiment {
ScopedProbeSession::ScopedProbeSession(ProbeSession& session)
    : previous_(active_session) {
    if (session.execution.threads <= 0) {
        throw std::invalid_argument("validation threads must be positive");
    }
    active_session = &session;
}
ScopedProbeSession::~ScopedProbeSession() {
    active_session = previous_;
}
} // namespace pacs::experiment

namespace pacs {
Validation validate(const Problem& p, const Placement& state, const Tolerances& tolerances) {
    experiment::ProbeCallObservation observation;
    if (!active_session) {
        return validate_probe(p,state,tolerances,{},observation);
    }
    // Save the borrowed pointer before entering workers. Workers never access
    // the observer; all observations are committed after their region joins.
    auto& session = *active_session;
    const auto begin = std::chrono::steady_clock::now();
    Validation result;
    try {
        result = validate_probe(p,state,tolerances,session.execution,observation);
    } catch (...) {
        const auto error = std::current_exception();
        const auto elapsed = std::chrono::duration<double>(
            std::chrono::steady_clock::now()-begin).count();
        session.samples.push_back({elapsed,observation,false});
        std::rethrow_exception(error);
    }
    const auto elapsed = std::chrono::duration<double>(
        std::chrono::steady_clock::now()-begin).count();
    session.samples.push_back({elapsed,observation,true});
    return result;
}
} // namespace pacs
