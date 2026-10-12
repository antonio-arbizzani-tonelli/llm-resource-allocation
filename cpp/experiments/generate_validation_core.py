"""Generate the bounded validator experiment without changing production core.

Only the validate signature and its McCormick construction block are replaced.
The generated translation unit owns the other original core definitions, so it
must be linked instead of core.o. The build passes the accepted source SHA-256.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


SIGNATURE = "Validation validate(const Problem& p, const Placement& s, const Tolerances& t) {"
PROBE_SIGNATURE = """Validation validate_probe(const Problem& p, const Placement& s, const Tolerances& t,
                          const experiment::ProbeExecution& execution,
                          experiment::ProbeCallObservation& observation) {
    if (execution.threads <= 0) throw std::invalid_argument("validation threads must be positive");
    observation = {};"""

APPEND_BLOCK = """    for (std::size_t i = 0; i < p.I(); ++i) {
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
    }"""

SLOT_BLOCK = """    observation.mccormick_rows = 4*p.I()*p.config_count();
    observation.nested_fallback = execution.mode == experiment::ValidationMode::omp && omp_in_parallel();
    observation.grain_fallback = execution.mode == experiment::ValidationMode::omp &&
        observation.mccormick_rows < execution.min_rows;
    const bool use_slots = execution.mode != experiment::ValidationMode::append &&
        !observation.nested_fallback && !observation.grain_fallback;
    if (!use_slots) {
@APPEND@
    } else {
        out.residuals.resize(observation.mccormick_rows);
        // Each query owns one contiguous prefix block and one status/error
        // slot. Byte flags avoid vector<bool>'s shared packed-bit writes.
        std::vector<unsigned char> query_feasible(p.I(),1);
        std::vector<std::exception_ptr> errors(p.I());
        const auto fill_query = [&](std::size_t i) {
            bool feasible = true;
            try {
                const auto slot_row = [&](std::size_t index, double slack) {
                    const double absolute = t.mccormick, relative = 0, lhs = 0, rhs = 0;
                    const double threshold = absolute+relative*std::max(std::abs(lhs),std::abs(rhs));
                    if (!std::isfinite(slack) || !std::isfinite(threshold)) {
                        throw std::overflow_error("non-finite residual");
                    }
                    out.residuals[index] = {"mccormick",index,slack,threshold};
                    if (slack < -threshold) feasible = false;
                };
                for (std::size_t j = 0; j < p.J(); ++j) {
                    for (std::size_t k = 0; k < p.K(); ++k) {
                        for (std::size_t c = 0; c < p.tiers[k].configs.size(); ++c) {
                            const auto a = p.vc(i,j,k,c);
                            const double x = s.x[p.route(i,j,k)], w = s.w[p.pc(j,k,c)], v = s.v[a];
                            slot_row(4*a,x-v);
                            slot_row(4*a+1,w-v);
                            slot_row(4*a+2,v-x-w+1);
                            slot_row(4*a+3,v);
                        }
                    }
                }
                query_feasible[i] = feasible ? 1 : 0;
            } catch (...) {
                errors[i] = std::current_exception();
            }
        };
        const auto query_count = p.I();
        if (execution.mode == experiment::ValidationMode::omp) {
            observation.region_entered = true;
            #pragma omp parallel for num_threads(execution.threads) schedule(static) default(none) \\
                shared(fill_query,observation) firstprivate(query_count)
            for (std::size_t i = 0; i < query_count; ++i) {
                if (i == 0) observation.actual_threads = omp_get_num_threads();
                fill_query(i);
            }
        } else {
            for (std::size_t i = 0; i < query_count; ++i) fill_query(i);
        }
        // Preserve the first exception and feasibility classification in
        // semantic query order, after every worker has joined.
        for (std::size_t i = 0; i < query_count; ++i) {
            if (errors[i]) std::rethrow_exception(errors[i]);
            if (!query_feasible[i]) out.feasible = false;
        }
    }""".replace("@APPEND@", "\n".join("    " + line for line in APPEND_BLOCK.splitlines()))


def generate(source: Path, output: Path, expected_sha256: str) -> dict[str, str | int]:
    if source.resolve() == output.resolve():
        raise ValueError("the generated source must not replace production core")
    raw = source.read_bytes()
    source_sha256 = hashlib.sha256(raw).hexdigest()
    if source_sha256 != expected_sha256.lower():
        raise ValueError("production core hash differs from the accepted experiment baseline")
    text = raw.decode("utf-8").replace("\r\n", "\n")
    if text.count(SIGNATURE) != 1 or text.count(APPEND_BLOCK) != 1:
        raise ValueError("expected exactly one validate signature and McCormick block")
    generated = '#include "validation_probe.hpp"\n#include <exception>\n#include <omp.h>\n' + text
    generated = generated.replace(SIGNATURE, PROBE_SIGNATURE, 1).replace(APPEND_BLOCK, SLOT_BLOCK, 1)
    encoded = generated.encode("utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(encoded)
    metadata = {
        "source": str(source),
        "source_sha256": source_sha256,
        "generated_sha256": hashlib.sha256(encoded).hexdigest(),
        "signature_replacements": 1,
        "mccormick_block_replacements": 1,
    }
    output.with_suffix(output.suffix + ".json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-source-sha256", required=True)
    args = parser.parse_args()
    if len(args.expected_source_sha256) != 64 or any(
        char not in "0123456789abcdefABCDEF" for char in args.expected_source_sha256
    ):
        parser.error("expected source SHA-256 must have 64 hexadecimal digits")
    print(json.dumps(generate(args.source, args.output, args.expected_source_sha256)))


if __name__ == "__main__":
    main()
