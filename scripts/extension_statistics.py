"""Small reproducible statistical summaries for the opt-in extension campaigns."""

from math import isfinite
from random import Random
from statistics import median


def quantile(values, probability):
    """Linear interpolation between ordered observations (R type 7)."""
    ordered = sorted(values)
    if not ordered or not 0 <= probability <= 1:
        raise ValueError("quantile requires observations and a probability in [0, 1]")
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (position - lower) * (ordered[upper] - ordered[lower])


def timing_summary(values):
    """Retain sample count, median and IQR without replacing raw observations."""
    values = tuple(values)
    if not values or any(isinstance(value, bool) or not isinstance(value, (int, float))
                         or not isfinite(value) or value <= 0 for value in values):
        raise ValueError("timing observations must be finite and positive")
    first, third = quantile(values, 0.25), quantile(values, 0.75)
    return {"count": len(values), "median_seconds": median(values),
            "q1_seconds": first, "q3_seconds": third,
            "iqr_seconds": third - first, "minimum_seconds": min(values)}


def paired_ratio_bootstrap(numerator, denominator, *, seed=20261014, resamples=10000):
    """Percentile CI for ratio of medians, resampling paired measurement rounds."""
    numerator, denominator = tuple(numerator), tuple(denominator)
    timing_summary(numerator)
    timing_summary(denominator)
    if len(numerator) != len(denominator) or len(numerator) < 2:
        raise ValueError("paired bootstrap requires at least two complete pairs")
    if isinstance(resamples, bool) or not isinstance(resamples, int) or resamples < 100:
        raise ValueError("bootstrap requires at least 100 resamples")
    rng = Random(seed)
    ratios = []
    for _ in range(resamples):
        indices = [rng.randrange(len(numerator)) for _ in numerator]
        ratios.append(median(numerator[index] for index in indices)
                      / median(denominator[index] for index in indices))
    return {"ratio_of_medians": median(numerator) / median(denominator),
            "ci95_low": quantile(ratios, 0.025), "ci95_high": quantile(ratios, 0.975),
            "paired_round_count": len(numerator), "resamples": resamples, "seed": seed,
            "method": "paired-round percentile bootstrap; ratio of sample medians"}
