#pragma once

#include "pacs/core.hpp"
#include <cstddef>
#include <vector>

namespace pacs::experiment {

enum class ValidationMode { append, slots, omp };

// Experimental implementation settings only; no scientific parameter changes.
struct ProbeExecution {
    ValidationMode mode{ValidationMode::append};
    int threads{1};
    std::size_t min_rows{};
};

struct ProbeCallObservation {
    std::size_t mccormick_rows{};
    int actual_threads{1};
    bool region_entered{}, nested_fallback{}, grain_fallback{};
};

struct ProbeSample {
    double seconds{};
    ProbeCallObservation observation;
    bool succeeded{};
};

struct ProbeSession {
    ProbeExecution execution;
    std::vector<ProbeSample> samples;
};

// Borrows a CLI-owned session on this thread for the scope's lifetime. The
// explicit implementation below receives execution/observation arguments;
// this observer merely connects unmodified GH/AGH calls to the experiment.
class ScopedProbeSession {
public:
    explicit ScopedProbeSession(ProbeSession&);
    ~ScopedProbeSession();
    ScopedProbeSession(const ScopedProbeSession&) = delete;
    ScopedProbeSession& operator=(const ScopedProbeSession&) = delete;
private:
    ProbeSession* previous_{};
};

} // namespace pacs::experiment

namespace pacs {
// Defined by a checked, generated core source. Production core.cpp is intact.
Validation validate_probe(const Problem&, const Placement&, const Tolerances&,
                          const experiment::ProbeExecution&,
                          experiment::ProbeCallObservation&);
} // namespace pacs
