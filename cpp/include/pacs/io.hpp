#pragma once

#include "pacs/agh.hpp"
#include <istream>
#include <ostream>
#include <string>
#include <vector>

namespace pacs::io {
// Owns parsed/prepared input. Scientific algorithms consume it read-only.
struct Input {
    Problem problem;
    GhOptions options;
    std::string seed;
    std::optional<Placement> state;
};
Input read_input(std::istream&);
void quoted(std::ostream&, const std::string&);
template<class T>
void array(std::ostream& out, const std::vector<T>& values) {
    out << '[';
    bool first = true;
    for (const auto& value : values) {
        if (!first) out << ',';
        first = false;
        out << value;
    }
    out << ']';
}
// Nullable pointers borrow from live result owners for this call only.
void placement_json(std::ostream&, const Placement*);
// The flag controls serialization only; validation always runs in full.
void validation_json(std::ostream&, const Validation*, bool residuals = true);
void gh_trace(std::ostream&, const GhResult&, const Problem&);
void agh_trace(std::ostream&, const AghResult&);
} // namespace pacs::io
