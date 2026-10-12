"""Publication boundary checks: containment, stable bytes and standalone export."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from prepare_release import export_release, prepare_files, relative_file


class ReleasePreparationTests(unittest.TestCase):
    def test_paths_reject_traversal_absolute_and_metadata(self):
        for path in ("../secret", "a/../b", "/absolute", "C:/absolute", ".git/config", "a\\b", "a//b", "a."):
            with self.subTest(path=path), self.assertRaises(ValueError):
                relative_file(path)

    def make_root(self, root):
        (root / "configs").mkdir()
        (root / "draft.md").write_bytes(b"readable\r\n")
        config = root / "configs/publication.json"
        config.write_text(json.dumps({"format_version": 1, "scope": "fixture", "files": [
            {"path": "README.md", "source": "draft.md"},
            {"path": "configs/publication.json"}]}), encoding="utf-8")
        return config

    def test_editorial_mapping_is_standalone_after_export(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            root = Path(temporary)
            config = self.make_root(root)
            destination = root / "build/release"
            manifest = export_release(root, config, destination)
            self.assertEqual((destination / "README.md").read_bytes(), b"readable\n")
            self.assertEqual((root / "draft.md").read_bytes(), b"readable\r\n")
            _, reproduced = prepare_files(destination, destination / "configs/publication.json")
            self.assertEqual(reproduced, manifest)

    def test_existing_destination_is_preserved(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            root = Path(temporary)
            config = self.make_root(root)
            destination = root / "build"
            destination.mkdir()
            marker = destination / "retained.txt"
            marker.write_text("keep", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "already exists"):
                export_release(root, config, destination)
            self.assertEqual(marker.read_text(), "keep")

    def test_case_insensitive_duplicates_and_protected_destination_fail(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            root = Path(temporary)
            config = self.make_root(root)
            with self.assertRaisesRegex(ValueError, "separate"):
                export_release(root, config, root / "docs/export")
            content = json.loads(config.read_text())
            content["files"].append({"path": "readme.md", "source": "draft.md"})
            config.write_text(json.dumps(content))
            with self.assertRaisesRegex(ValueError, "duplicate"):
                prepare_files(root, config)

    def test_generated_manifest_is_reserved_without_case_sensitivity(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            root = Path(temporary)
            config = self.make_root(root)
            content = json.loads(config.read_text())
            content["files"].append({"path": "Release-Manifest.json", "source": "draft.md"})
            config.write_text(json.dumps(content))
            with self.assertRaisesRegex(ValueError, "reserved"):
                prepare_files(root, config)

    def test_historical_observation_bytes_survive_transport(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            root = Path(temporary)
            config = self.make_root(root)
            (root / "benchmarks").mkdir()
            observation = b'{"measured": 1.0}\r\n'
            (root / "benchmarks/record.json").write_bytes(observation)
            content = json.loads(config.read_text())
            content["files"].append({"path": "benchmarks/record.json"})
            config.write_text(json.dumps(content))
            exported, _ = prepare_files(root, config)
            self.assertEqual(exported["benchmarks/record.json"], observation)


if __name__ == "__main__":
    unittest.main()
