"""Pure WP2 accounting/control checks and tiny portable-package verification."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from scripts import analyze_openmp_extension as analyzer


def configuration(threads=2, **changes):
    return {"threads": threads, "places": "cores", "bind": "close", "schedule": "dynamic",
            "chunk": 1, "sorted": False, "arena": None, **changes}


def sample(config, seconds, round_number=0, prefix="/mnt/c/measurement/workspace"):
    team = config["threads"]
    return {"configuration": config, "configuration_key": analyzer.key(config), "round": round_number,
            "command": [prefix + "/cpp/build/extension/openmp_diagnostics", str(team), config["schedule"],
                        str(config["chunk"]), "0", "-"], "environment": {}, "returncode": 0, "stderr": "",
            "invocation_seconds": seconds + 1, "core_seconds": seconds, "actual_threads": team,
            "busy_seconds": [seconds * .8] if team == 1 else [seconds * .7, seconds * .5],
            "job_count": [2] if team == 1 else [1, 1], "cpu_start": [0] if team == 1 else [0, 1],
            "fingerprints": ["abc", "def"], "projection_fingerprints_match": True,
            "recorded_utc": "2026-10-14T12:00:00+00:00"}


class OpenmpAccountingTests(unittest.TestCase):
    def test_hand_derived_wall_accounting_does_not_mislabel_serial_code(self):
        account = analyzer.wall_accounting({"actual_threads": 2, "core_seconds": 6,
                                            "busy_seconds": [4, 2]}, baseline_seconds=8)
        self.assertAlmostEqual(account["wall_idle_fraction"], .5)
        self.assertAlmostEqual(account["imbalance_fraction"], 1 / 6)
        self.assertAlmostEqual(account["other_wall_idle_fraction"], 1 / 3)
        self.assertAlmostEqual(account["work_duration_change_fraction"], -1 / 6)
        self.assertAlmostEqual(account["efficiency_loss_fraction"], 1 / 3)
        self.assertEqual(account["ideal_seconds"], 4)
        self.assertEqual(account["imbalance_seconds"], 1)
        self.assertEqual(account["remainder_seconds"], 1)
        negative = analyzer.wall_accounting({"actual_threads": 2, "core_seconds": 6,
                                             "busy_seconds": [4, 2]}, baseline_seconds=14)
        self.assertEqual(negative["remainder_seconds"], -2)

    def test_per_thread_idle_is_computed_per_round_before_median(self):
        config = configuration()
        first = sample(config, 6)
        second = sample(config, 8, 1)
        first["busy_seconds"], second["busy_seconds"] = [4, 2], [6, 4]
        result = analyzer.analyze_observations([config], {analyzer.key(config): {0: first, 1: second}}, 2, 100)
        self.assertEqual(result["thread_rows"][0]["median_busy_seconds"], 5)
        self.assertAlmostEqual(result["thread_rows"][0]["median_wall_idle_percent"], 100 * (1 / 3 + 1 / 4) / 2)

    def test_each_factor_uses_same_team_control_holding_other_fields_fixed(self):
        base = configuration()
        configs = [base, *[configuration(**{factor: value}) for factor, value in
                   (("schedule", "guided"), ("chunk", 2), ("places", "threads"),
                    ("bind", "spread"), ("sorted", True), ("arena", 1))]]
        observations = {analyzer.key(config): {index: sample(config, 4 if config == base else 2, index)
                                             for index in range(2)} for config in configs}
        result = analyzer.analyze_observations(configs, observations, 2, 100)
        self.assertEqual({row["factor"] for row in result["same_team_controls"]}, set(analyzer.CONTROLS))
        for row in result["same_team_controls"]:
            self.assertEqual(row["control_key"], analyzer.key(base))
            self.assertEqual(row["paired_speedup"]["paired_round_count"], 2)
            self.assertEqual(row["paired_speedup"]["ratio_of_medians"], 2)

    def test_changed_actual_team_is_rejected(self):
        config = configuration()
        value = sample(config, 2)
        value["actual_threads"] = 1
        with self.assertRaisesRegex(ValueError, "observed team"):
            analyzer.analyze_observations([config], {analyzer.key(config): {0: value}}, 1, 100)

    def test_only_exact_workspace_prefix_changes_and_numeric_bits_are_retained(self):
        original = {"command": "/mnt/c/measurement/workspace/cpp/test", "scientific_label": "dynamic",
                    "another_path": "/mnt/c/other/workspace/test", "values": [1.25, -0.0, True, 12]}
        portable = analyzer.portable_values(original, "/mnt/c/measurement/workspace")
        self.assertEqual(portable["command"], "./cpp/test")
        self.assertEqual(portable["another_path"], original["another_path"])
        analyzer.preserve_nonpath_values(original, portable, "/mnt/c/measurement/workspace")
        portable["values"][1] = 0.0
        with self.assertRaisesRegex(ValueError, "numeric bits"):
            analyzer.preserve_nonpath_values(original, portable, "/mnt/c/measurement/workspace")


class OpenmpPortablePackageTests(unittest.TestCase):
    def prepare_fixture(self, root, prefix):
        output = root / "benchmarks/openmp_diagnostics_2026-10-14"
        output.mkdir(parents=True)
        configs = [configuration(1), configuration(2)]
        analyzer.save(output / "configuration.json", {"rounds": 2, "matrix": "test", "configurations": configs})
        analyzer.save(output / "pilot.json", {"fingerprints": ["abc", "def"], "command": [prefix + "/cpp/test"]})
        analyzer.save(output / "cost_ordering.json", {"original_indices": [0, 1]})
        analyzer.save(output / "golden_validation.json", [{"case": "a", "independently_feasible": True, "objective_bitwise_equal": True},
                                                          {"case": "b", "independently_feasible": True, "objective_bitwise_equal": True}])
        analyzer.save(output / "environment.json", {"availability": {"perf": "unavailable", "frequency": "unavailable"}})
        analyzer.save(output / "execution.json", {"status": "complete", "rounds": 2})
        analyzer.save(output / "hashes.json", {})
        analyzer.save(output / "build.json", {"command": [prefix + "/source.cpp"], "returncode": 0})
        for index in range(2):
            analyzer.save(output / f"golden/{index}.json", {"placement": {"x": [1.0]}, "objective": [1., 2., 3., 4., 5.], "feasible": True})
        for config in configs:
            for round_number in range(2):
                path = output / "raw" / f"{round_number:02d}_{analyzer.key(config)}.json"
                analyzer.save(path, sample(config, 4 if config["threads"] == 1 else 2, round_number, prefix))
                path.with_suffix(".sha256").write_text(analyzer.digest(path) + "\n")
        frozen = ["configuration.json", "pilot.json", "cost_ordering.json", "golden_validation.json", "hashes.json", "build.json", "golden/0.json", "golden/1.json"]
        analyzer.save(output / "preparation_complete.json", {"validated_goldens": 2, "input_files": 2,
            "files": {name: analyzer.digest(output / name) for name in frozen}})
        analyzer.package(output)
        analyzer.inventory(output)
        return output

    def test_publication_preserves_originals_and_fresh_replay_needs_no_binary(self):
        prefix = "/mnt/c/measurement/workspace"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = self.prepare_fixture(root, prefix)
            original_raw = {path.name: json.loads(path.read_text()) for path in (output / "raw").glob("*.json")}
            golden_hashes = {path.name: analyzer.digest(path) for path in (output / "golden").glob("*.json")}
            backup = root / "results/original"
            with patch.object(analyzer, "ROOT", root):
                summary = analyzer.publish_portable(output, backup, prefix=prefix, resamples=100)
                self.assertEqual(summary["valid_observations"], 4)
                self.assertFalse((output / "raw").exists())
                self.assertFalse((output / "golden").exists())
                self.assertTrue((backup / "manifest.json").exists())
                with zipfile.ZipFile(output / "evidence.zip") as archive:
                    for name, original in original_raw.items():
                        portable = json.loads(archive.read("raw/" + name))
                        self.assertTrue(portable["command"][0].startswith("./"))
                        analyzer.preserve_nonpath_values(original, portable, prefix)
                    for name, expected in golden_hashes.items():
                        self.assertEqual(__import__("hashlib").sha256(archive.read("golden/" + name)).hexdigest(), expected)
                before = (output / "artifact_hashes.json").read_bytes()
                replayed = analyzer.analyze(output, resamples=100)
                analyzer.write_report(output, replayed)
                analyzer.inventory(output)
                self.assertEqual(before, (output / "artifact_hashes.json").read_bytes())
                self.assertEqual(replayed["settings"], summary["settings"])

    def test_archive_member_mutation_is_rejected_before_unpack(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = self.prepare_fixture(Path(temporary), "/mnt/c/measurement/workspace")
            manifest = analyzer.read(output / "evidence_manifest.json")
            manifest["files"][0]["sha256"] = "0" * 64
            analyzer.save(output / "evidence_manifest.json", manifest)
            with self.assertRaisesRegex(ValueError, "archive entry changed"):
                analyzer.unpack(output)


if __name__ == "__main__":
    unittest.main()
