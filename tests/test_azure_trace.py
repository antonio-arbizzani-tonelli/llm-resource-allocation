"""Hand-derived tests for uncalibrated Azure trace preprocessing."""

from dataclasses import FrozenInstanceError
from datetime import date, datetime, timedelta, timezone
from io import StringIO
import unittest

from llm_resource_allocation.data.azure_trace import (
    AzureTraceFormatError,
    AzureTraceRequest,
    aggregate_azure_trace_requests,
    iter_azure_csv_requests,
)


DAY = date(2024, 5, 14)


def _request(timestamp: str, context: int = 10, generated: int = 4) -> AzureTraceRequest:
    return AzureTraceRequest(datetime.fromisoformat(timestamp), context, generated)


class AzureTraceTests(unittest.TestCase):
    def test_half_open_windows_zero_counts_daily_mean_and_tokens(self) -> None:
        rows = (
            _request("2024-05-14 00:00:00", 2, 1),
            _request("2024-05-14 00:04:59.999999", 6, 3),
            _request("2024-05-14 00:05:00", 10, 5),
            _request("2024-05-14 23:59:59", 14, 7),
        )
        result = aggregate_azure_trace_requests(iter(rows), (DAY,))
        day = result.days[0]
        self.assertEqual(len(day.windows), 288)
        self.assertEqual(tuple(window.request_count for window in day.windows),
                         (2, 1) + (0,) * 285 + (1,))
        self.assertEqual(day.request_count, 4)
        self.assertEqual(day.mean_window_request_count, 1 / 72)
        self.assertEqual(day.mean_arrival_rate_per_hour, 1 / 6)
        self.assertEqual(day.windows[0].arrival_rate_per_hour, 24)
        self.assertEqual(day.windows[1].arrival_rate_per_hour, 12)
        self.assertEqual(tuple(window.daily_multiplier for window in day.windows),
                         (144, 72) + (0,) * 285 + (72,))
        self.assertEqual(day.context_tokens_sum, 32)
        self.assertEqual(day.generated_tokens_sum, 16)
        self.assertEqual(day.mean_context_tokens, 8)
        self.assertEqual(day.mean_generated_tokens, 4)
        self.assertEqual(day.windows[0].context_tokens_sum, 8)
        self.assertEqual(day.windows[0].mean_context_tokens, 4)
        self.assertEqual(day.windows[0].mean_generated_tokens, 2)
        self.assertIsNone(day.windows[2].mean_context_tokens)
        self.assertEqual(day.windows[0].end, day.windows[1].start)
        self.assertEqual(day.windows[-1].end, datetime(2024, 5, 15))
        self.assertEqual(rows[1].timestamp.microsecond, 999999)

    def test_unsorted_rows_duplicate_timestamps_and_source_span(self) -> None:
        rows = (
            _request("2024-05-16 12:00:00"),
            _request("2024-05-14 00:05:00"),
            _request("2024-05-13 23:59:59"),
            _request("2024-05-14 00:05:00"),
        )
        result = aggregate_azure_trace_requests(iter(rows), (DAY,))
        self.assertEqual(result.days[0].windows[1].request_count, 2)
        self.assertEqual(result.source_request_count, 4)
        self.assertEqual(result.selected_request_count, 2)
        self.assertEqual(result.out_of_selected_days_request_count, 2)
        self.assertEqual(result.observed_min_timestamp, datetime(2024, 5, 13, 23, 59, 59))
        self.assertEqual(result.observed_max_timestamp, datetime(2024, 5, 16, 12))
        self.assertEqual(result.observed_span, timedelta(days=2, hours=12, seconds=1))
        self.assertEqual(result.timestamp_basis, "naive")

    def test_utc_source_midnight_and_independent_day_normalization(self) -> None:
        tomorrow = date(2024, 5, 15)
        rows = (
            _request("2024-05-14 23:59:59.999999+00:00"),
            _request("2024-05-15 00:00:00+00:00"),
            _request("2024-05-15 00:05:00+00:00"),
        )
        result = aggregate_azure_trace_requests(rows, (tomorrow, DAY))
        self.assertEqual(tuple(day.day for day in result.days), (DAY, tomorrow))
        self.assertEqual(result.days[0].windows[-1].request_count, 1)
        self.assertEqual(result.days[0].windows[-1].daily_multiplier, 288)
        self.assertEqual(result.days[1].windows[0].daily_multiplier, 144)
        self.assertEqual(result.days[1].windows[1].daily_multiplier, 144)
        for day in result.days:
            self.assertEqual(sum(window.daily_multiplier for window in day.windows), 288)
            self.assertEqual(day.windows[0].start.tzinfo, timezone.utc)
        self.assertEqual(result.timestamp_basis, "utc")

    def test_empty_day_and_empty_source_have_undefined_multipliers(self) -> None:
        result = aggregate_azure_trace_requests((), (DAY,))
        self.assertEqual(result.days[0].request_count, 0)
        self.assertEqual(result.days[0].mean_window_request_count, 0)
        self.assertTrue(all(window.daily_multiplier is None
                            for window in result.days[0].windows))
        self.assertIsNone(result.days[0].mean_generated_tokens)
        self.assertIsNone(result.observed_span)
        self.assertIsNone(result.observed_min_timestamp)
        self.assertEqual(result.timestamp_basis, "no_observations")

    def test_real_schema_exact_precision_extra_columns_and_zero_tokens(self) -> None:
        stream = StringIO(
            "TIMESTAMP,ContextTokens,GeneratedTokens,Other\r\r\n"
            "2024-05-10 00:00:00.009930+00:00,0,3,x\r\r\n"
            "2024-05-10 00:05:00+00:00,8,0,y\r\r\n", newline=""
        )
        rows = tuple(iter_azure_csv_requests(stream))
        self.assertEqual(rows[0], _request("2024-05-10 00:00:00.009930+00:00", 0, 3))
        self.assertEqual(rows[0].timestamp.microsecond, 9930)
        self.assertEqual(rows[1].generated_tokens, 0)
        result = aggregate_azure_trace_requests(rows, (date(2024, 5, 10),))
        self.assertEqual(result.days[0].windows[0].request_count, 1)
        self.assertEqual(result.days[0].windows[1].request_count, 1)

    def test_column_override_is_explicit_and_headers_are_strict(self) -> None:
        text = "Timestamp,ContextTokens,GeneratedTokens\n2024-05-14 00:00:00,1,2\n"
        with self.assertRaisesRegex(AzureTraceFormatError, "missing required"):
            tuple(iter_azure_csv_requests(StringIO(text)))
        self.assertEqual(len(tuple(iter_azure_csv_requests(
            StringIO(text), timestamp_column="Timestamp"))), 1)
        for header in ("", "TIMESTAMP,ContextTokens\n",
                       "TIMESTAMP,ContextTokens,GeneratedTokens,ContextTokens\n"):
            with self.subTest(header=header), self.assertRaises(AzureTraceFormatError):
                tuple(iter_azure_csv_requests(StringIO(header)))

    def test_malformed_records_are_rejected_without_repairs(self) -> None:
        header = "TIMESTAMP,ContextTokens,GeneratedTokens\n"
        for row in (
            "invalid,1,2", "2024-05-14,1,2", "2024-05-14 00:00:00,-1,2",
            "2024-05-14 00:00:00,1.0,2", "2024-05-14 00:00:00,,2",
            "2024-05-14 00:00:00, 1,2", "2024-05-14 00:00:00,1",
            "2024-05-14 00:00:00,1,2,3",
            "2024-05-14 00:00:00.0000001,1,2",
            "2024-05-14 00:00:00+02:00,1,2",
        ):
            with self.subTest(row=row), self.assertRaisesRegex(AzureTraceFormatError, "line 2"):
                tuple(iter_azure_csv_requests(StringIO(header + row + "\n")))
        for tokens in (-1, True, 1.5):
            with self.subTest(tokens=tokens), self.assertRaises(AzureTraceFormatError):
                AzureTraceRequest(datetime(2024, 5, 14), tokens, 0)

    def test_mixed_timestamp_basis_date_validation_and_immutability(self) -> None:
        rows = (_request("2024-05-14 00:00:00"),
                _request("2024-05-14 00:05:00+00:00"))
        with self.assertRaisesRegex(AzureTraceFormatError, "mixed naive"):
            aggregate_azure_trace_requests(rows, (DAY,))
        text = ("TIMESTAMP,ContextTokens,GeneratedTokens\n"
                "2024-05-14 00:00:00,1,2\n2024-05-14 00:05:00+00:00,1,2\n")
        with self.assertRaisesRegex(AzureTraceFormatError, "mixed naive"):
            tuple(iter_azure_csv_requests(StringIO(text)))
        for dates in ((), (DAY, DAY), (datetime(2024, 5, 14),), ("2024-05-14",)):
            with self.subTest(dates=dates), self.assertRaises(AzureTraceFormatError):
                aggregate_azure_trace_requests((), dates)
        result = aggregate_azure_trace_requests(rows[:1], [DAY])
        with self.assertRaises(FrozenInstanceError):
            result.source_request_count = 99
        with self.assertRaises(FrozenInstanceError):
            result.days[0].windows[0].request_count = 99
        with self.assertRaises(FrozenInstanceError):
            rows[0].context_tokens = 99


if __name__ == "__main__":
    unittest.main()
