"""Supplemental ratio estimands and unchanged-evidence verification contracts."""

import json
import math
from pathlib import Path
import shlex
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import summarize_extension_results as summary


class PairedRatioDistributionTests(unittest.TestCase):
    def test_hand_derived_ratio_distribution_and_quartiles(self):
        # Paired ratios are 2, 10, 20, 40: median=15, Q1=8, Q3=25, IQR=17.
        result = summary.paired_ratio_distribution([2, 20, 80, 320], [1, 2, 4, 8], resamples=200)
        self.assertEqual(result["median_ratio"], 15)
        self.assertEqual(result["q1_ratio"], 8)
        self.assertEqual(result["q3_ratio"], 25)
        self.assertEqual(result["iqr_ratio"], 17)
        self.assertEqual(result["paired_round_count"], 4)
        # The distinct primary ratio of medians would be 50/3, not 15.
        self.assertNotEqual(result["median_ratio"], 50 / 3)

    def test_exact_paired_constant_ratio_has_exact_bootstrap_interval(self):
        result = summary.paired_ratio_distribution([2, 4, 20, 40], [1, 2, 10, 20], resamples=200)
        self.assertEqual(result["median_ratio"], 2)
        self.assertEqual(result["iqr_ratio"], 0)
        self.assertEqual((result["ci95_median_low"], result["ci95_median_high"]), (2, 2))

    def test_local_seed_is_reproducible_and_invalid_pairs_are_rejected(self):
        self.assertEqual(summary.paired_ratio_distribution([2, 4, 8], [1, 1, 2], seed=11, resamples=200),
                         summary.paired_ratio_distribution([2, 4, 8], [1, 1, 2], seed=11, resamples=200))
        for numerator, denominator in (([1], [1]), ([1, 2], [1]), ([0, 1], [1, 2]), ([1, math.inf], [1, 2])):
            with self.subTest(numerator=numerator), self.assertRaises(ValueError):
                summary.paired_ratio_distribution(numerator, denominator, resamples=200)


class SummaryEvidenceTests(unittest.TestCase):
    @staticmethod
    def write(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def fixture(self, directory, source_root):
        (source_root / "source.py").write_text("unchanged\n", encoding="utf-8")
        self.write(directory / "inputs/case.json", {})
        (directory / "inputs/case.txt").write_text("numeric\n", encoding="utf-8")
        prepared = {"source_sha256": {"source.py": summary.digest(source_root / "source.py")},
                    "cases": [{"name": "case", "shape": [4, 2, 2], "method": "gh", "load": 1,
                               "json": "inputs/case.json", "json_sha256": summary.digest(directory / "inputs/case.json"),
                               "numeric": "inputs/case.txt", "numeric_sha256": summary.digest(directory / "inputs/case.txt")}]}
        self.write(directory / "prepared.json", prepared)
        self.write(directory / "raw/sample/stdout.json", {"core_seconds": 2})
        (directory / "raw/sample/stderr.txt").write_text("", encoding="utf-8")
        self.write(directory / "raw/sample/invocation.json", {"process_wall_seconds": 3})
        status = {"state": "completed", "rounds": 10, "samples": {"case/core/round00/python": {
            "directory": "raw/sample", "stdout_sha256": summary.digest(directory / "raw/sample/stdout.json"),
            "stderr_sha256": summary.digest(directory / "raw/sample/stderr.txt"), "core_seconds": 2,
            "process_wall_seconds": 3, "verified_bitwise": True}}}
        self.write(directory / "status.json", status)
        files = {path.relative_to(directory).as_posix(): summary.digest(path) for path in directory.rglob("*") if path.is_file()}
        self.write(directory / "evidence_manifest.json", {"file_count": len(files), "files": files})

    def test_manifest_sources_and_accepted_raw_digests_are_checked(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory, sources = Path(temporary) / "campaign", Path(temporary) / "sources"
            (directory / "inputs").mkdir(parents=True)
            sources.mkdir()
            self.fixture(directory, sources)
            _, _, verification = summary.verify_wp1(directory, sources)
            self.assertEqual(verification["verified_prepared_sources"], 1)
            self.assertEqual(verification["verified_accepted_raw_samples"], 1)
            (directory / "raw/sample/stdout.json").write_text("changed", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "delivered evidence changed"):
                summary.verify_wp1(directory, sources)

    def test_prepared_source_change_is_not_hidden_by_same_evidence_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory, sources = Path(temporary) / "campaign", Path(temporary) / "sources"
            (directory / "inputs").mkdir(parents=True)
            sources.mkdir()
            self.fixture(directory, sources)
            (sources / "source.py").write_text("changed\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "prepared source changed"):
                summary.verify_wp1(directory, sources)

    def test_optional_missing_analysis_does_not_invent_completion_status(self):
        self.assertEqual(summary.optional_analysis(None), {"included": False, "availability": "analysis not supplied"})
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "analysis.json"
            self.write(path, {"state": "interrupted", "completed_jobs": 3})
            collected = summary.optional_analysis(path)
            self.assertEqual(collected["observed_status_fields"], {"state": "interrupted"})
            self.assertEqual(collected["analysis"]["completed_jobs"], 3)

    def test_default_frozen_zip_survives_later_intentional_source_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory, sources = Path(temporary) / "campaign", Path(temporary) / "sources"
            (directory / "inputs").mkdir(parents=True)
            sources.mkdir()
            self.fixture(directory, sources)
            snapshot = directory / "source_snapshot.zip"
            with zipfile.ZipFile(snapshot, "w") as archive:
                archive.write(sources / "source.py", "source.py")
            (sources / "source.py").write_text("later opt-in change\n", encoding="utf-8")
            _, _, verification = summary.verify_wp1(directory)
            provenance = verification["source_provenance"]
            self.assertEqual(provenance["kind"], "frozen_source_zip")
            self.assertEqual(provenance["sha256"], summary.digest(snapshot))
            self.assertTrue(provenance["additional_snapshot_outside_original_manifest"])

    def test_frozen_zip_changed_entry_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory, sources = Path(temporary) / "campaign", Path(temporary) / "sources"
            (directory / "inputs").mkdir(parents=True)
            sources.mkdir()
            self.fixture(directory, sources)
            with zipfile.ZipFile(directory / "source_snapshot.zip", "w") as archive:
                archive.writestr("source.py", "changed")
            with self.assertRaisesRegex(ValueError, "frozen source ZIP entry changed"):
                summary.verify_wp1(directory)


class SummaryReplayCommandTests(unittest.TestCase):
    def test_default_emitted_cli_selects_the_default_verified_frozen_snapshot(self):
        command = shlex.split(summary.replay_command(summary.DEFAULT_WP1, summary.DEFAULT_OUTPUT, {}))
        wp1_argument = command[command.index("--wp1") + 1]
        selected_root = (summary.ROOT / wp1_argument).resolve()
        self.assertEqual(selected_root, summary.DEFAULT_WP1)
        self.assertEqual(summary.source_snapshot_for(selected_root), summary.DEFAULT_WP1 / "source_snapshot.zip")
        self.assertNotIn("--source-root", command)
        self.assertNotIn("--source-snapshot", command)
        self.assertEqual(command[command.index("--output") + 1], "docs/extension_numbers.json")

    def test_explicit_archive_and_optional_analysis_arguments_are_preserved(self):
        archive = summary.ROOT / "benchmarks/custom/source.zip"
        policy = summary.ROOT / "benchmarks/stage2_policy_2026-10-14/analysis.json"
        command = shlex.split(summary.replay_command(summary.DEFAULT_WP1, summary.DEFAULT_OUTPUT,
                                                    {"wp3": policy}, source_snapshot=archive))
        self.assertEqual(command[command.index("--source-snapshot") + 1], "benchmarks/custom/source.zip")
        self.assertEqual(command[command.index("--wp3") + 1], "benchmarks/stage2_policy_2026-10-14/analysis.json")
        self.assertNotIn("--source-root", command)


if __name__ == "__main__":
    unittest.main()
