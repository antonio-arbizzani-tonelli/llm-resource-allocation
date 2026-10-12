"""Strict streaming Azure trace ingestion and uncalibrated daily aggregation.

This module retains observed requests and token counts without assigning query
types or constructing scientific instances. Five-minute calendar windows and
their daily-mean multipliers follow the paper-v2 Azure protocol. Input may use
native naive timestamps or explicit UTC timestamps; those conventions cannot
be mixed, and other timezone offsets need a separately approved policy.
"""

from collections.abc import Iterable, Iterator
import csv
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import re
from typing import TextIO


WINDOWS_PER_DAY = 288
WINDOW_DURATION = timedelta(minutes=5)
_TIMESTAMP_FORMAT = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}[ T][0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})?\Z"
)


class AzureTraceFormatError(ValueError):
    """Reject a trace record instead of dropping or repairing its values."""


def _nonnegative_integer(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AzureTraceFormatError(f"{name} must be a non-negative integer")


def _timestamp_basis(timestamp: datetime) -> str:
    if not isinstance(timestamp, datetime):
        raise AzureTraceFormatError("timestamp must be a datetime")
    offset = timestamp.utcoffset()
    if offset is None:
        return "naive"
    if offset != timedelta(0):
        raise AzureTraceFormatError(
            "nonzero timestamp timezone offsets require an explicit policy"
        )
    return "utc"


@dataclass(frozen=True, slots=True)
class AzureTraceRequest:
    """One observed request with its unrounded input timestamp and tokens."""

    timestamp: datetime
    context_tokens: int
    generated_tokens: int

    def __post_init__(self) -> None:
        _timestamp_basis(self.timestamp)
        _nonnegative_integer(self.context_tokens, "ContextTokens")
        _nonnegative_integer(self.generated_tokens, "GeneratedTokens")


@dataclass(frozen=True, slots=True)
class AzureTraceWindow:
    """Observed counts in the half-open interval [start, end)."""

    start: datetime
    request_count: int
    context_tokens_sum: int
    generated_tokens_sum: int
    daily_multiplier: float | None

    @property
    def end(self) -> datetime:
        return self.start + WINDOW_DURATION

    @property
    def arrival_rate_per_hour(self) -> float:
        return self.request_count * 12.0

    @property
    def mean_context_tokens(self) -> float | None:
        return (self.context_tokens_sum / self.request_count
                if self.request_count else None)

    @property
    def mean_generated_tokens(self) -> float | None:
        return (self.generated_tokens_sum / self.request_count
                if self.request_count else None)


@dataclass(frozen=True, slots=True)
class AzureTraceDay:
    """All 288 chronological windows, including zero-count intervals."""

    day: date
    windows: tuple[AzureTraceWindow, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "windows", tuple(self.windows))

    @property
    def request_count(self) -> int:
        return sum(window.request_count for window in self.windows)

    @property
    def mean_window_request_count(self) -> float:
        return self.request_count / WINDOWS_PER_DAY

    @property
    def mean_arrival_rate_per_hour(self) -> float:
        return self.request_count / 24.0

    @property
    def context_tokens_sum(self) -> int:
        return sum(window.context_tokens_sum for window in self.windows)

    @property
    def generated_tokens_sum(self) -> int:
        return sum(window.generated_tokens_sum for window in self.windows)

    @property
    def mean_context_tokens(self) -> float | None:
        count = self.request_count
        return self.context_tokens_sum / count if count else None

    @property
    def mean_generated_tokens(self) -> float | None:
        count = self.request_count
        return self.generated_tokens_sum / count if count else None


@dataclass(frozen=True, slots=True)
class AzureTraceAggregation:
    """Selected daily counts with evidence about every parsed source request.

    Observed endpoints do not establish completeness of intervening days. An
    empty selected day has undefined multipliers, not fabricated zero values.
    """

    days: tuple[AzureTraceDay, ...]
    source_request_count: int
    out_of_selected_days_request_count: int
    observed_min_timestamp: datetime | None
    observed_max_timestamp: datetime | None
    timestamp_basis: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "days", tuple(self.days))

    @property
    def observed_span(self) -> timedelta | None:
        if self.observed_min_timestamp is None or self.observed_max_timestamp is None:
            return None
        return self.observed_max_timestamp - self.observed_min_timestamp

    @property
    def selected_request_count(self) -> int:
        return self.source_request_count - self.out_of_selected_days_request_count


def _parse_timestamp(value: str, line: int, column: str) -> datetime:
    if not _TIMESTAMP_FORMAT.fullmatch(value):
        raise AzureTraceFormatError(
            f"CSV line {line}, {column}: expected an ISO date/time with seconds "
            "and at most six fractional digits"
        )
    try:
        timestamp = datetime.fromisoformat(value)
        _timestamp_basis(timestamp)
    except ValueError as error:
        raise AzureTraceFormatError(f"CSV line {line}, {column}: {error}") from error
    return timestamp


def _parse_tokens(value: str, line: int, column: str) -> int:
    if not value or not value.isascii() or not value.isdecimal():
        raise AzureTraceFormatError(
            f"CSV line {line}, {column}: expected a non-negative decimal integer"
        )
    return int(value)


def iter_azure_csv_requests(
    stream: TextIO, *, timestamp_column: str = "TIMESTAMP"
) -> Iterator[AzureTraceRequest]:
    """Parse required exact column names; never guess timestamp aliases.

    The caller owns source-file handling (open CSV files with ``newline=''``).
    Additional named columns are allowed. Blank physical CSV lines are not
    request records; malformed nonblank records raise with their line number.
    """

    if not isinstance(timestamp_column, str) or not timestamp_column:
        raise AzureTraceFormatError("timestamp_column must be a non-empty string")
    columns = (timestamp_column, "ContextTokens", "GeneratedTokens")
    if len(set(columns)) != 3:
        raise AzureTraceFormatError("timestamp_column must differ from token columns")
    reader = csv.DictReader(stream, strict=True)
    try:
        header = reader.fieldnames
        if header is None:
            raise AzureTraceFormatError("CSV has no header")
        if len(header) != len(set(header)) or any(not name for name in header):
            raise AzureTraceFormatError("CSV header has duplicate or empty column names")
        missing = tuple(column for column in columns if column not in header)
        if missing:
            raise AzureTraceFormatError(f"CSV header missing required columns: {missing}")
        basis = None
        for row in reader:
            line = reader.line_num
            if None in row or any(value is None for value in row.values()):
                raise AzureTraceFormatError(f"CSV line {line}: field count differs from header")
            timestamp = _parse_timestamp(row[timestamp_column], line, timestamp_column)
            current_basis = _timestamp_basis(timestamp)
            if basis is not None and current_basis != basis:
                raise AzureTraceFormatError(
                    f"CSV line {line}: mixed naive and UTC-aware timestamps"
                )
            basis = current_basis
            yield AzureTraceRequest(
                timestamp,
                _parse_tokens(row["ContextTokens"], line, "ContextTokens"),
                _parse_tokens(row["GeneratedTokens"], line, "GeneratedTokens"),
            )
    except csv.Error as error:
        raise AzureTraceFormatError(f"CSV line {reader.line_num}: {error}") from error


def aggregate_azure_trace_requests(
    requests: Iterable[AzureTraceRequest], dates: Iterable[date]
) -> AzureTraceAggregation:
    """Stream all requests into explicit dates without retaining request rows.

    Selected dates are returned chronologically. Source-wide span and counts
    include requests outside the selection; those rows are still validated.
    Date membership follows the source's naive or UTC calendar convention.
    """

    selected = tuple(dates)
    if not selected or any(type(day) is not date for day in selected):
        raise AzureTraceFormatError("dates must contain at least one calendar date")
    if len(set(selected)) != len(selected):
        raise AzureTraceFormatError("dates must be distinct")
    ordered = tuple(sorted(selected))
    counters = {day: [[0, 0, 0] for _ in range(WINDOWS_PER_DAY)] for day in ordered}
    source_count = outside_count = 0
    observed_min = observed_max = None
    basis = None
    for request in requests:
        if not isinstance(request, AzureTraceRequest):
            raise AzureTraceFormatError("requests must contain AzureTraceRequest records")
        current_basis = _timestamp_basis(request.timestamp)
        if basis is not None and current_basis != basis:
            raise AzureTraceFormatError("mixed naive and UTC-aware source timestamps")
        basis = current_basis
        source_count += 1
        timestamp = request.timestamp
        if observed_min is None or timestamp < observed_min:
            observed_min = timestamp
        if observed_max is None or timestamp > observed_max:
            observed_max = timestamp
        daily = counters.get(timestamp.date())
        if daily is None:
            outside_count += 1
            continue
        window = daily[(timestamp.hour * 60 + timestamp.minute) // 5]
        window[0] += 1
        window[1] += request.context_tokens
        window[2] += request.generated_tokens
    tzinfo = timezone.utc if basis == "utc" else None
    days = []
    for day in ordered:
        daily = counters[day]
        total = sum(values[0] for values in daily)
        midnight = datetime.combine(day, time.min, tzinfo=tzinfo)
        windows = tuple(
            AzureTraceWindow(
                midnight + index * WINDOW_DURATION,
                count, context_sum, generated_sum,
                count * WINDOWS_PER_DAY / total if total else None,
            )
            for index, (count, context_sum, generated_sum) in enumerate(daily)
        )
        days.append(AzureTraceDay(day, windows))
    return AzureTraceAggregation(
        tuple(days), source_count, outside_count, observed_min, observed_max,
        basis if basis is not None else "no_observations",
    )
