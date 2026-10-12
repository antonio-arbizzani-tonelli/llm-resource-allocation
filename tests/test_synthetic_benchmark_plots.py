"""Check CSV availability semantics and optional presentation output."""

import csv
import io
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts.plot_synthetic_benchmark import PROVENANCE, REQUIRED_FIELDS, read_summary, render_figures


class SyntheticBenchmarkPlotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.path = Path("summary.csv")
        self.csv_text = ""
        self.record = dict.fromkeys(REQUIRED_FIELDS, "")
        self.record.update(
            case_id="case_2", family="query_scaling", method="P_DM",
            query_count="2", model_count="2", tier_count="2", run_count="3",
            accepted_count="3", feasible_count="3", optimal_count="3", gap_count="3",
            time_median_seconds="0.2", time_q1_seconds="0.1", time_q3_seconds="0.3",
            objective_median="12", c1_median="3", c2_median="2", c3_median="1",
            c4_median="4", c5_median="2", gap_median_percent="0",
            mean_unmet_fraction_median="0.02", unmet_over_1pct_rate_median="0.5",
        )

    def write(self, *records: dict[str, str]) -> None:
        handle = io.StringIO(newline="")
        writer = csv.DictWriter(handle, fieldnames=REQUIRED_FIELDS)
        writer.writeheader()
        writer.writerows(records)
        self.csv_text = handle.getvalue()

    def read(self):
        with patch.object(Path, "open", return_value=io.StringIO(self.csv_text)):
            return read_summary(self.path)

    def test_csv_distinguishes_real_zero_from_unavailable(self) -> None:
        failure = dict(self.record, method="GH", accepted_count="0", feasible_count="0", optimal_count="0", gap_count="0")
        for name in REQUIRED_FIELDS:
            if name.endswith("median") or name == "gap_median_percent":
                failure[name] = ""
        self.write(self.record, failure)
        optimum, failed = self.read()
        self.assertEqual(optimum.objective_median, 12.0)
        self.assertEqual(optimum.gap_median_percent, 0.0)
        self.assertIsNone(failed.objective_median)
        self.assertIsNone(failed.gap_median_percent)
        self.assertEqual(failed.time_median_seconds, 0.2)

    def test_csv_preserves_signed_gap(self) -> None:
        self.write(dict(self.record, gap_median_percent="-0.00001"))
        self.assertEqual(self.read()[0].gap_median_percent, -0.00001)

    def test_nonfinite_measurement_is_rejected(self) -> None:
        self.write(dict(self.record, objective_median="nan"))
        with self.assertRaisesRegex(ValueError, "Riga CSV 2.*finite"):
            self.read()

    def test_duplicate_case_method_is_rejected(self) -> None:
        self.write(self.record, self.record)
        with self.assertRaisesRegex(ValueError, "duplicati"):
            self.read()

    def test_invalid_failure_count_is_rejected(self) -> None:
        self.write(dict(self.record, accepted_count="4"))
        with self.assertRaisesRegex(ValueError, "conteggi"):
            self.read()

    def test_figures_keep_missing_quality_visible(self) -> None:
        try:
            from matplotlib.figure import Figure
        except ImportError:
            self.skipTest("optional matplotlib is unavailable")
        failure = dict(self.record, method="GH", accepted_count="0", feasible_count="0", optimal_count="0", gap_count="0", objective_median="", gap_median_percent="")
        self.write(self.record, failure)
        output = Path("figures")
        saved = {}

        def capture(figure, path, **kwargs):
            saved[path.name] = figure

        with patch.object(Path, "mkdir"), patch.object(Figure, "savefig", capture):
            paths = render_figures(self.read(), output)
        self.assertEqual(len(paths), 8)
        self.assertEqual(set(saved), {path.name for path in paths})
        quality = saved["objective_and_gap.svg"]
        self.assertEqual(quality._suptitle.get_text(), PROVENANCE)
        self.assertEqual(len(quality.axes[0].patches), 1)
        self.assertEqual(quality.axes[0].patches[0].get_height(), 12)
        self.assertIn("n.d.", [text.get_text() for text in quality.axes[0].texts])
        self.assertNotIn("USD", quality.axes[0].get_ylabel())
        gap_markers = [line for line in quality.axes[1].lines if line.get_marker() == "o"]
        self.assertEqual(len(gap_markers), 1)
        self.assertEqual(tuple(gap_markers[0].get_ydata()), (0.0,))


if __name__ == "__main__":
    unittest.main()
