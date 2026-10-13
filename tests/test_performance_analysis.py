"""Hand-derived timing/quality ratios and recorded-evidence integrity."""

import json
from dataclasses import replace
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import analyze_performance_campaign as analysis
import run_nightly_campaign as campaign
import run_performance_campaign as timing
import export_performance_campaign as export_tool
import profile_native_validated_instances as native_profile
from llm_resource_allocation.data import make_coherent_tiny_instance


def sample_profile():
    return {"complete": True, "fingerprints_verified_unchanged": True,
            "cases": [{"method": method, "dimensions": [16, 4, 4], "feasible": True,
                       "input_sha256": "same", "python_parity": {"bitwise_difference_count": 0, "compared_numeric_values": 10},
                       "samples": [{"cpp_repeat_seconds": [value], "process_wall_seconds": value + 1} for value in values],
                       "python_reference_check_seconds": 12.0, "objective": [rental, 1, 0, 0, 0]}
                      for method, values, rental in (("gh", [1, 3, 2], 9), ("agh", [2, 4, 3], 8))]}


class PerformanceAnalysisTests(unittest.TestCase):
    def record(self, directory, profile, kind="serial"):
        root = directory / "jobs/test"
        root.mkdir(parents=True, exist_ok=True)
        campaign.save_json(root / "profile.json", profile)
        job = {"id": "test", "kind": kind}
        campaign.save_json(directory / "plan.json", {"jobs": [job, {"id": "unrun", "kind": "serial"}]})
        campaign.save_json(directory / "jobs.json", [{**job, "status": "completed", "output": "jobs/test",
                                                    "evidence_sha256": campaign.evidence_inventory(root)}])

    def test_hand_derived_statistics_and_quality_have_the_same_input(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            root = Path(temporary)
            self.record(root, sample_profile())
            report = analysis.analyze(root)
            self.assertEqual(report["completed_jobs"], 1)
            self.assertEqual(report["planned_jobs"], 2)
            self.assertEqual(report["coverage"][1]["status"], "not_run")
            self.assertEqual(report["serial"][0]["cpp_core"]["median_seconds"], 2)
            self.assertEqual(report["serial"][0]["python_reference_to_cpp_median_ratio"], 6)
            quality = report["paired_quality"][0]
            self.assertAlmostEqual(quality["rental_reduction_fraction"], 1 / 9)
            self.assertAlmostEqual(quality["total_reduction_fraction"], 1 / 10)
            analysis.save_report(root / "analysis", report)
            self.assertTrue((root / "analysis/serial_timings.csv").is_file())

    def test_tampering_and_scientific_mismatch_are_rejected(self):
        for mutation, message in (("changed_file", "evidence changed"), ("parity", "differ bitwise"),
                                  ("different_input", "identical instance"), ("incomplete", "completely verified")):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory(dir=ROOT) as temporary:
                root = Path(temporary)
                profile = sample_profile()
                if mutation == "parity":
                    profile["cases"][0]["python_parity"]["bitwise_difference_count"] = 1
                elif mutation == "different_input":
                    profile["cases"][1]["input_sha256"] = "different"
                elif mutation == "incomplete":
                    profile["complete"] = False
                self.record(root, profile)
                if mutation == "changed_file":
                    (root / "jobs/test/profile.json").write_text("edited", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, message):
                    analysis.analyze(root)

    def test_failed_placement_is_not_a_cost_advantage(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            root = Path(temporary)
            profile = sample_profile()
            profile["cases"][1]["feasible"] = False
            self.record(root, profile)
            self.assertEqual(analysis.analyze(root)["paired_quality"], [])

    def test_openmp_median_baseline_and_actual_team_efficiency(self):
        def setting(schedule, threads, durations, walls):
            return {"schedule": schedule, "requested_threads": threads, "actual_threads": threads,
                    "speedup": 4 if threads == 2 else 1,
                    "samples": [{"repeat_threads": [threads], "campaign_seconds": duration, "process_wall_seconds": wall}
                                for duration, wall in zip(durations, walls, strict=True)]}
        profile = {"metadata": {"fingerprints_verified_unchanged": True},
                   "workloads": [{"workload": "uniform", "job_count": 32,
                                  "scaling": [setting("serial", 1, [8, 10, 12], [12, 16, 20]),
                                              setting("dynamic", 2, [2, 4, 6], [6, 8, 10])]}]}
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            root = Path(temporary)
            self.record(root, profile, "openmp")
            report = analysis.analyze(root)
            candidate = report["openmp"][1]
            self.assertEqual(candidate["median_core_speedup"], 2.5)
            self.assertEqual(candidate["median_core_efficiency"], 1.25)
            self.assertEqual(candidate["minimum_core_speedup"], 4)
            self.assertEqual(candidate["median_process_speedup"], 2)

    def test_timing_subset_preserves_original_manifest_and_stress_plan(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            root = Path(temporary)
            prepared = root / "prepared"
            snapshot = prepared / "snapshot"
            (snapshot / "cpp/build/release").mkdir(parents=True)
            (snapshot / "cpp/Makefile").write_text("build", encoding="utf-8")
            for name in ("pacs_serial", "pacs_campaign"):
                (snapshot / "cpp/build/release" / name).write_bytes(b"binary")
            config = campaign.load_configuration(ROOT / "configs/nightly_campaign.json")
            campaign.save_json(snapshot / "configs/nightly_campaign.json", config)
            manifest = {"source_sha256": campaign.source_inventory(snapshot), "configuration_sha256": campaign.configuration_digest(config),
                        "binary_sha256": {name: campaign.digest(snapshot / "cpp/build/release" / name) for name in ("pacs_serial", "pacs_campaign")}}
            campaign.save_json(prepared / "snapshot_manifest.json", manifest)
            before = (prepared / "snapshot_manifest.json").read_bytes()
            actual_config, jobs = timing.prepare_timing_subset(prepared, root / "timings")
            self.assertEqual(actual_config, config)
            self.assertEqual(len(jobs), 12)
            self.assertTrue(all(job["kind"] in ("serial", "openmp") for job in jobs))
            self.assertEqual((prepared / "snapshot_manifest.json").read_bytes(), before)
            self.assertEqual((root / "timings/snapshot_manifest.json").read_bytes(), before)

    def test_portable_export_keeps_observations_and_digest_links_consistent(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            root = Path(temporary)
            source = root / "recorded"
            profile = sample_profile()
            profile["metadata"] = {"binary": str(ROOT / "results/run/snapshot/cpp/pacs_serial")}
            self.record(source, profile)
            (source / "snapshot/src").mkdir(parents=True)
            original_source = b"# measured source\r\nVALUE = 1\r\n"
            (source / "snapshot/src/llm_resource_allocation").mkdir()
            (source / "snapshot/src/llm_resource_allocation/__init__.py").write_bytes(original_source)
            report_before = analysis.analyze(source)
            report_after = export_tool.export(source, root / "portable", ROOT)
            self.assertEqual(report_before, report_after)
            profile_text = (root / "portable/jobs/test/profile.json").read_text()
            self.assertIn("<workspace>", profile_text)
            self.assertNotIn(str(ROOT).replace("\\", "\\\\"), profile_text)
            import zipfile
            with zipfile.ZipFile(root / "portable/scientific-source-snapshot.zip") as archive:
                self.assertEqual(archive.read("src/llm_resource_allocation/__init__.py"), original_source)

    def test_home_paths_outside_project_are_removed_without_changing_numbers(self):
        example_path = "\\".join(("C:", "Users", "example", "AppData", "Local", "Python"))
        value = {"duration": 1.25, "error": example_path}
        cleaned = export_tool.portable(value, ROOT)
        self.assertEqual(cleaned["duration"], 1.25)
        self.assertEqual(cleaned["error"], "<user-home>/AppData/Local/Python")

    def test_finished_method_in_timed_out_worker_retains_only_checked_samples(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            root = Path(temporary)
            job_root = root / "jobs/test"
            job_root.mkdir(parents=True)
            profile = sample_profile()
            profile["complete"] = False
            profile["cases"] = profile["cases"][:1]
            case = profile["cases"][0]
            for key in ("input", "python_golden", "full_cpp_evidence"):
                path = job_root / (key + ".txt")
                path.write_bytes(b"checked evidence")
                case[key], case[key + "_sha256"] = path.name, campaign.digest(path)
            for index, sample in enumerate(case["samples"]):
                path = job_root / f"sample_{index}.json"
                path.write_bytes(b"checked sample")
                sample.update(evidence=path.name, evidence_sha256=campaign.digest(path))
            self.record(root, profile)
            history = json.loads((root / "jobs.json").read_text())
            history[0]["status"] = "timeout"
            campaign.save_json(root / "jobs.json", history)
            campaign.save_json(root / "status.json", {"status": "incomplete"})
            report = analysis.analyze(root)
            self.assertEqual(report["completed_jobs"], 0)
            self.assertEqual(len(report["serial"]), 1)
            self.assertEqual(report["serial"][0]["job_status"], "timeout")
            self.assertEqual(report["serial"][0]["cpp_core"]["count"], 3)
            self.assertEqual(report["paired_quality"], [])
            (job_root / "python_golden.txt").write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "finished method evidence changed"):
                analysis.analyze(root)

    def test_native_final_decision_uses_the_shared_validator_without_repair(self):
        base = make_coherent_tiny_instance()
        route = (base.query_ids[0], base.model_ids[0], base.gpu_tier_ids[0])
        instance = replace(base, queries=(replace(base.queries[0], arrival_rate_per_hour=8,
                           input_tokens=2, output_tokens=2, storage_gb_per_token=0.125,
                           delay_penalty_usd_per_millisecond_query=0.125),),
                           models=(replace(base.models[0], weight_gb=2),),
                           gpu_tiers=(replace(base.gpu_tiers[0], hourly_rental_usd=0.5),),
                           compute_delay_seconds_per_token={route: 0.125},
                           communication_delay_seconds_per_token={route: 0.125},
                           storage_price_usd_per_gb_hour=0.125, horizon_hours=2)
        # D=.125*4+.125*2=.75; C4=.125*.75*1000*8*2=1500.
        # C1=2*.5; C2=2*.125*2; C3=2*.125*4*.125*8.
        actual = {"status": "completed", "feasible": True,
                  "placement": {"x": [1], "z": [1], "q": [1], "u": [0],
                                "w": [1, 0], "y": [1], "v": [1, 0]},
                  "objective": [1.0, 0.5, 1.0, 1500.0, 0.0]}
        report = native_profile.validate_native_decision(instance, actual)
        self.assertTrue(report.is_feasible)
        # Corrupt an independently supplied auxiliary; the validator must not
        # reconstruct it from x*w to make the native state usable.
        actual["placement"]["v"][0] = 0.0
        with self.assertRaisesRegex(ValueError, "independent validation"):
            native_profile.validate_native_decision(instance, actual)

    def test_supplemental_measurement_has_no_fabricated_python_time_or_ratio(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            root = Path(temporary)
            self.record(root, sample_profile())
            native = root / "native_validation/native_256"
            native.mkdir(parents=True)
            record = {"complete": True, "fingerprints_verified_unchanged": True,
                      "independently_feasible": True, "objective_agrees_bitwise": True,
                      "shape": [256, 4, 4], "method": "agh", "case": "native_256",
                      "python_independent_validation_seconds": 0.125,
                      "objective_components_usd": [8, 1, 0, 0, 0], "samples": []}
            for key in ("input", "native_full_evidence", "python_validation_evidence"):
                path = native / (key + ".txt")
                path.write_bytes(b"accepted evidence")
                record[key], record[key + "_sha256"] = path.name, campaign.digest(path)
            for index, seconds in enumerate((2, 4, 3)):
                path = native / f"sample_{index}.json"
                path.write_bytes(b"checked sample")
                record["samples"].append({"evidence": path.name, "evidence_sha256": campaign.digest(path),
                                           "cpp_repeat_seconds": [seconds], "process_wall_seconds": seconds + 1})
            campaign.save_json(native / "profile.json", record)
            report = analysis.analyze(root)
            row = report["serial"][-1]
            self.assertEqual(row["verification_mode"], "independent_final_decision")
            self.assertIsNone(row["python_reference_seconds"])
            self.assertIsNone(row["python_reference_to_cpp_median_ratio"])
            self.assertEqual(row["cpp_core"]["median_seconds"], 3)
            analysis.save_report(root / "derived", report)


if __name__ == "__main__":
    unittest.main()
