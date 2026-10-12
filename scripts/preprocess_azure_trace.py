"""Validate the raw Azure code trace and retain UTC five-minute day profiles."""

import argparse
import csv
from datetime import date
import json
from pathlib import Path
import sys
from time import perf_counter

from download_azure_trace import file_sha256


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, default=ROOT / "data/external/azure_2024/AzureLLMInferenceTrace_code_1week.csv")
    parser.add_argument("--dates", nargs="+", default=["2024-05-14", "2024-05-15"])
    parser.add_argument("--output", type=Path, default=ROOT / "results/azure_trace")
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT / "src"))
    from llm_resource_allocation.data.azure_trace import (
        aggregate_azure_trace_requests, iter_azure_csv_requests,
    )
    dates = tuple(date.fromisoformat(value) for value in args.dates)
    source_manifest = json.loads((args.raw.parent / "source_manifest.json").read_text(encoding="utf-8"))
    digest = file_sha256(args.raw)
    if digest != source_manifest["sha256"] or args.raw.stat().st_size != source_manifest["size_bytes"]:
        raise ValueError("Raw source no longer matches the retained download manifest")
    start = perf_counter()
    def progress_rows(stream):
        for count, request in enumerate(iter_azure_csv_requests(stream), 1):
            if count % 2_000_000 == 0:
                print(f"Validated {count:,} requests", flush=True)
            yield request
    with args.raw.open("r", encoding="utf-8", newline="") as stream:
        aggregation = aggregate_azure_trace_requests(progress_rows(stream), dates)
    output = {
        "classification": "REAL_TRACE_COUNTS_WITHOUT_SCIENTIFIC_CALIBRATION",
        "source_manifest": source_manifest,
        "source_request_count": aggregation.source_request_count,
        "out_of_selected_days_request_count": aggregation.out_of_selected_days_request_count,
        "observed_min_timestamp": aggregation.observed_min_timestamp.isoformat() if aggregation.observed_min_timestamp else None,
        "observed_max_timestamp": aggregation.observed_max_timestamp.isoformat() if aggregation.observed_max_timestamp else None,
        "timestamp_basis": aggregation.timestamp_basis,
        "window_seconds": 300,
        "windows_per_day": 288,
        "multiplier_formula": "window_request_count * 288 / daily_request_count",
        "coverage_caveat": "Observed source endpoints do not prove completeness of every intervening window",
        "invalid_records": "reject; no repair, clipping or deduplication",
        "days": [],
    }
    for day in aggregation.days:
        output["days"].append({
            "date": day.day.isoformat(),
            "request_count": day.request_count,
            "mean_window_request_count": day.mean_window_request_count,
            "mean_arrival_rate_per_hour": day.mean_arrival_rate_per_hour,
            "context_tokens_sum": day.context_tokens_sum,
            "generated_tokens_sum": day.generated_tokens_sum,
            "mean_context_tokens": day.mean_context_tokens,
            "mean_generated_tokens": day.mean_generated_tokens,
            "windows": [{"index": index, "start": window.start.isoformat(),
                         "request_count": window.request_count,
                         "arrival_rate_per_hour": window.arrival_rate_per_hour,
                         "daily_multiplier": window.daily_multiplier,
                         "context_tokens_sum": window.context_tokens_sum,
                         "generated_tokens_sum": window.generated_tokens_sum}
                        for index, window in enumerate(day.windows)],
        })
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "profiles.json").write_text(json.dumps(output, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    with (args.output / "windows.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["date", "index", "start", "request_count", "arrival_rate_per_hour", "daily_multiplier", "context_tokens_sum", "generated_tokens_sum"])
        writer.writeheader()
        for day in output["days"]:
            writer.writerows({"date": day["date"], **window} for window in day["windows"])
    print(f"Validated {aggregation.source_request_count:,} requests in {perf_counter()-start:.3f} s; timestamp basis={aggregation.timestamp_basis}", flush=True)
    for day in aggregation.days:
        print(f"{day.day}: {day.request_count:,} requests, {len(day.windows)} windows", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
