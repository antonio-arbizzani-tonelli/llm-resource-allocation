"""Post-processing archives preserve measured bytes with bounded ZIP parts."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import warnings
import zipfile

from scripts import run_stage2_extension as extension


class Stage2ArchiveTests(unittest.TestCase):
    def write_raw(self,output):
        files={"jobs/a/result.json":b"12345678", "jobs/b/result.json":b"abcdefgh",
               "status.json":b"done"}
        for name,payload in files.items():
            path=output/"raw"/name
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(payload)
        return files

    def make_parts(self,output):
        files=self.write_raw(output)
        manifest=extension.package(output,raw_payload_budget=8,maximum_part_bytes=1024)
        return files,manifest

    def test_multipart_bound_membership_hashes_and_exact_payload_roundtrip(self):
        with tempfile.TemporaryDirectory() as temporary:
            output=Path(temporary)
            files,manifest=self.make_parts(output)
            self.assertEqual(manifest["file_count"],3)
            self.assertEqual(manifest["uncompressed_bytes"],20)
            self.assertEqual(len(manifest["archives"]),3)
            self.assertTrue(all(part["bytes"]<=1024 for part in manifest["archives"]))
            self.assertEqual({entry["path"] for entry in manifest["files"]},set(files))
            for entry in manifest["files"]:
                self.assertEqual(entry["sha256"],hashlib.sha256(files[entry["path"]]).hexdigest())
            read,names,archive=extension.delivered_reader(output)
            try:
                self.assertEqual(set(names),set(files))
                self.assertEqual({name:read(name) for name in names},files)
            finally:
                archive.close()
            self.assertEqual({name:(output/"raw"/name).read_bytes() for name in files},files)

    def test_frozen_measured_source_is_identified_separately_from_packaging_helper(self):
        with tempfile.TemporaryDirectory() as temporary:
            output=Path(temporary)
            self.write_raw(output)
            source=b"# frozen measured producer\n"
            config=b"{}\n"
            (output/"config.json").write_bytes(config)
            extension.save_json(output/"raw/campaign_manifest.json",{"source_sha256":{
                "scripts/run_stage2_extension.py":extension.sha256(source)}})
            with zipfile.ZipFile(output/"scientific-source-snapshot.zip","w") as archive:
                archive.writestr("scripts/run_stage2_extension.py",source)
                archive.writestr("config.json",config)
            manifest=extension.package(output,raw_payload_budget=1024,maximum_part_bytes=4096)
            self.assertEqual(manifest["measured_source_snapshot"]["sha256"],
                             extension.sha256((output/"scientific-source-snapshot.zip").read_bytes()))
            self.assertEqual(manifest["post_processing"]["helper_sha256"],
                             extension.sha256(Path(extension.__file__).read_bytes()))
            self.assertEqual((output/"config.json").read_bytes(),config)
            source_path=output/"scientific-source-snapshot.zip"
            source_path.write_bytes(source_path.read_bytes()+b"mutation")
            with self.assertRaisesRegex(ValueError,"frozen measured source archive changed"):
                extension.delivered_reader(output)

    def test_unexpected_zip_member_is_rejected_after_refreshing_part_hash(self):
        with tempfile.TemporaryDirectory() as temporary:
            output=Path(temporary)
            _,manifest=self.make_parts(output)
            part=manifest["archives"][0]
            path=output/part["path"]
            with zipfile.ZipFile(path,"a") as archive:
                archive.writestr("unexpected.json",b"{}")
            part.update(sha256=extension.sha256(path.read_bytes()),bytes=path.stat().st_size)
            extension.save_json(output/"evidence_manifest.json",manifest)
            with self.assertRaisesRegex(ValueError,"ZIP membership changed"):
                extension.delivered_reader(output)

    def test_legacy_single_zip_still_replays_exact_membership(self):
        with tempfile.TemporaryDirectory() as temporary:
            output=Path(temporary)
            files={"one.json":b"{}","nested/two.json":b"[]"}
            with zipfile.ZipFile(output/"evidence.zip","w") as archive:
                for name,payload in files.items():
                    archive.writestr(name,payload)
            extension.save_json(output/"evidence_manifest.json",{"file_count":2,
                "archive_sha256":extension.sha256((output/"evidence.zip").read_bytes()),"files":[
                    {"path":name,"bytes":len(payload),"sha256":extension.sha256(payload)}
                    for name,payload in files.items()]})
            read,names,archive=extension.delivered_reader(output)
            try:
                self.assertEqual({name:read(name) for name in names},files)
            finally:
                archive.close()

    def test_raw_reader_remains_explicitly_available_after_packaging(self):
        with tempfile.TemporaryDirectory() as temporary:
            output=Path(temporary)
            files,manifest=self.make_parts(output)
            part=output/manifest["archives"][0]["path"]
            part.write_bytes(part.read_bytes()+b"mutation")
            with self.assertRaisesRegex(ValueError,"archive changed"):
                extension.delivered_reader(output)
            read,names,archive=extension.delivered_reader(output,prefer_raw=True)
            self.assertIsNone(archive)
            self.assertEqual({name:read(name) for name in names},files)

    def test_duplicate_manifest_entry_and_cross_part_membership_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            output=Path(temporary)
            _,manifest=self.make_parts(output)
            duplicated=json.loads(json.dumps(manifest))
            duplicated["files"].append(duplicated["files"][0])
            extension.save_json(output/"evidence_manifest.json",duplicated)
            with self.assertRaisesRegex(ValueError,"duplicate manifest entry"):
                extension.delivered_reader(output)
            duplicated=json.loads(json.dumps(manifest))
            duplicated["archives"][1]["members"].append(duplicated["archives"][0]["members"][0])
            duplicated["archives"][1]["file_count"]+=1
            extension.save_json(output/"evidence_manifest.json",duplicated)
            with self.assertRaisesRegex(ValueError,"duplicate membership across"):
                extension.delivered_reader(output)

    def test_per_entry_hash_and_declared_membership_mutations_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            output=Path(temporary)
            _,manifest=self.make_parts(output)
            mutated=json.loads(json.dumps(manifest))
            mutated["files"][0]["sha256"]="0"*64
            extension.save_json(output/"evidence_manifest.json",mutated)
            with self.assertRaisesRegex(ValueError,"archive entry changed"):
                extension.delivered_reader(output)
            mutated=json.loads(json.dumps(manifest))
            mutated["archives"][0]["members"]=["extra.json"]
            extension.save_json(output/"evidence_manifest.json",mutated)
            with self.assertRaisesRegex(ValueError,"declared archive membership changed"):
                extension.delivered_reader(output)

    def test_duplicate_actual_zip_entry_is_rejected_even_with_valid_part_hash(self):
        with tempfile.TemporaryDirectory() as temporary:
            output=Path(temporary)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore",UserWarning)
                with zipfile.ZipFile(output/"evidence.zip","w") as archive:
                    archive.writestr("same.json",b"first")
                    archive.writestr("same.json",b"second")
            extension.save_json(output/"evidence_manifest.json",{"file_count":1,
                "archive_sha256":extension.sha256((output/"evidence.zip").read_bytes()),"files":[
                    {"path":"same.json","bytes":6,"sha256":extension.sha256(b"second")}]})
            with self.assertRaisesRegex(ValueError,"duplicate ZIP entry"):
                extension.delivered_reader(output)

    def test_oversized_raw_file_is_retained_and_never_silently_split(self):
        with tempfile.TemporaryDirectory() as temporary:
            output=Path(temporary)
            raw=output/"raw/large.bin"
            raw.parent.mkdir()
            raw.write_bytes(b"123456789")
            with self.assertRaisesRegex(ValueError,"raw file exceeds ZIP payload budget"):
                extension.package(output,raw_payload_budget=8,maximum_part_bytes=1024)
            self.assertEqual(raw.read_bytes(),b"123456789")


if __name__=="__main__":
    unittest.main()
