"""WP6 protocol, rejection, raw replay and checkpoint integrity checks."""

from dataclasses import replace
import gzip
import json
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts import extension_solver_quality as campaign


class SolverQualityProtocolTests(unittest.TestCase):
    def test_declared_counts_and_runtime_gate(self):
        jobs = campaign.campaign_jobs(["highs", "gurobi"])
        self.assertEqual(len(jobs), 36)
        self.assertEqual(sum(not job["warmup"] for job in jobs), 32)
        self.assertEqual(sum(job["method"] == "p_dm" and not job["warmup"] for job in jobs), 24)
        self.assertEqual(len({job["id"] for job in jobs}), len(jobs))
        estimate = campaign.runtime_estimate(["highs", "gurobi"])
        self.assertEqual(estimate["native_limit_sum_seconds"], 5920)
        self.assertEqual(estimate["estimated_seconds"], 9200)
        self.assertLess(estimate["estimated_seconds"], 10800)
        self.assertGreater(campaign.runtime_estimate(["highs", "gurobi"], [20, 120, 1600])["estimated_seconds"], 10800)

    def test_rotation_and_fresh_limit_cells(self):
        jobs = campaign.campaign_jobs(["highs", "gurobi"])
        measured = [job for job in jobs if not job["warmup"] and job["method"] == "p_dm"]
        orders = [[job["case"] + job["backend"] for job in measured if job["limit"] == limit]
                  for limit in campaign.LIMITS]
        self.assertEqual(set(orders[0]), set(orders[1]))
        self.assertNotEqual(orders[0], orders[1])
        self.assertNotEqual(orders[1], orders[2])

    def test_rejected_solver_has_no_rank_or_paired_quality(self):
        case = {"id": "a"}
        manifest = {"cases": [case], "limits": [20], "backends": ["highs", "gurobi"],
                    "jobs": [{"warmup": False}] * 3}
        rows = [{"id": name, "warmup": False, "accepted": accepted,
                 "usable_objective_usd": value, "method": method, "backend": backend}
                for name, accepted, value, method, backend in (
                    ("a_agh", True, 12.0, "agh", None),
                    ("a_highs_20", True, 10.0, "p_dm", "highs"),
                    ("a_gurobi_20", False, None, "p_dm", "gurobi"))]
        summary = campaign.summarize_rows(rows, manifest)
        self.assertIsNone(summary["case_orders"][0]["order_by_objective"])
        self.assertFalse(summary["case_orders"][0]["complete_accepted_cohort"])
        highs, gurobi = summary["agh_incumbent_comparisons"]
        self.assertEqual(highs["median_agh_over_incumbent"], 1.2)
        self.assertIsNone(highs["descriptive_bootstrap95_median"])
        self.assertEqual(gurobi["accepted_paired_cases"], 0)
        self.assertIsNone(gurobi["median_agh_over_incumbent"])

    def test_bootstrap_is_deterministic_and_excludes_single_case(self):
        self.assertIsNone(campaign.bootstrap_median([1.2]))
        self.assertEqual(campaign.bootstrap_median([1.0, 2.0, 3.0], draws=100),
                         campaign.bootstrap_median([1.0, 2.0, 3.0], draws=100))

    def test_attempted_denominator_includes_failed_milp_workers(self):
        jobs = [{"id": name, "warmup": False} for name in ("gh", "agh", "highs", "gurobi")]
        checkpoint = {"attempts": [{"job_id": name, "status": status} for name, status in
                      (("gh", "complete"), ("agh", "complete"), ("highs", "timeout"), ("gurobi", "failed"))]}
        counts = campaign.attempted_counts(checkpoint, {"jobs": jobs})
        self.assertEqual(counts["attempted_unique_measured_jobs"], 4)
        self.assertEqual(counts["attempted_measured_worker_calls"], 4)
        self.assertEqual(counts["completed_unique_measured_jobs"], 2)
        self.assertEqual(counts["measured_jobs_without_completed_result"], 2)
        self.assertEqual(counts["measured_worker_status_counts"], {"complete": 2, "timeout": 1, "failed": 1})

    def test_retries_count_worker_calls_without_duplicating_unique_jobs_or_warmups(self):
        manifest = {"jobs": [{"id": "warmup", "warmup": True}, {"id": "milp", "warmup": False}]}
        checkpoint = {"attempts": [{"job_id": "warmup", "status": "complete"},
                                   {"job_id": "milp", "status": "timeout"},
                                   {"job_id": "milp", "status": "complete"}]}
        counts = campaign.attempted_counts(checkpoint, manifest)
        self.assertEqual(counts["attempted_unique_measured_jobs"], 1)
        self.assertEqual(counts["attempted_measured_worker_calls"], 2)
        self.assertEqual(counts["completed_unique_measured_jobs"], 1)
        self.assertEqual(counts["measured_jobs_without_completed_result"], 0)


class SolverQualityReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # The shared repository owns the temporary campaign, never historical data.
        result_root = campaign.ROOT / "results"
        result_root.mkdir(exist_ok=True)
        cls.temporary = tempfile.TemporaryDirectory(prefix="wp6_test_", dir=result_root)
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.output = Path(cls.temporary.name)
        cls.manifest = campaign.prepare(cls.output, ["highs"])

    def test_preparation_does_not_run_campaign(self):
        self.assertTrue((self.output / "PLAN.md").exists())
        self.assertEqual(campaign.load_json(self.output / "checkpoint.json")["attempts"], [])
        self.assertFalse((self.output / "raw").exists())
        self.assertEqual(self.manifest["backends"], ["highs"])

    def test_tiny_raw_solver_evidence_replays_without_calling_solver(self):
        job = next(job for job in self.manifest["jobs"] if job["id"] == "warmup_highs")
        directory = self.output / "verification_smoke"
        row = campaign.run_worker(self.output, job, directory)
        self.assertTrue(row["accepted"])
        with gzip.open(directory / "evidence.json.gz", "rt", encoding="utf-8") as stream:
            evidence = json.load(stream)
        self.assertIsNotNone(evidence["raw"])
        self.assertIsNotNone(evidence["raw"]["v"])
        self.assertEqual(row["normalized_gap"], 0.0)
        self.assertIsNone(row["native_gap"])
        self.assertEqual(row["native_gap_observation"], "not exposed by approved APPSI adapter")
        attempt = {"directory": "verification_smoke", "sha256": {
            name: campaign.sha256(directory / name) for name in ("result.json", "evidence.json.gz")}}
        with patch("llm_resource_allocation.optimization.solver.solve_pyomo_model",
                   side_effect=AssertionError("replay must never solve")):
            replayed = campaign.replay_row(self.output, self.manifest, attempt)
        self.assertEqual(replayed, row)

    def test_input_decoding_retains_coherent_instance_and_semantic_indices(self):
        instance = campaign.load_input(self.output, self.manifest, "6x6x10_L100000")
        self.assertEqual(instance.dimensions, (6, 6, 10))
        self.assertTrue(instance.uses_coherent_units)
        self.assertEqual(instance, campaign.decode_instance(campaign.plain(instance)))
        self.assertEqual(instance.queries[0].arrival_rate_per_hour, 1200000.0)

    def test_hash_mutation_blocks_resume(self):
        source = self.output / "snapshot/scripts/extension_solver_quality.py"
        original = source.read_bytes()
        try:
            source.write_bytes(original + b"\n# mutation\n")
            with self.assertRaisesRegex(ValueError, "source hash mismatch"):
                campaign.verify_prepared(self.output)
        finally:
            source.write_bytes(original)
        campaign.verify_prepared(self.output)

    def test_missing_incumbent_preserves_solver_status_and_bound(self):
        from llm_resource_allocation.optimization.solver import SolverBackend, SolverResult, SolverStatus
        job = next(job for job in self.manifest["jobs"] if job["id"] == "warmup_highs")
        directory = self.output / "no_incumbent"
        solver = SolverResult(SolverBackend.HIGHS, SolverStatus.NO_SOLUTION, "maxTimeLimit",
                              False, None, 0.0, None, 0.1, {})
        with patch("llm_resource_allocation.optimization.solver.solve_pyomo_model", return_value=solver):
            row = campaign.run_worker(self.output, job, directory)
        self.assertFalse(row["accepted"])
        self.assertEqual(row["solver_status"], "no_solution")
        self.assertEqual(row["best_bound_usd"], 0.0)
        self.assertIsNone(row["usable_objective_usd"])
        self.assertEqual(row["rejection_reasons"], ["no_complete_placement"])

    def test_z_checkpoint_worker_uses_snapshot_and_leaves_measured_jobs_pending(self):
        checkpoint = campaign.run_campaign(self.output, "Tiny verification smoke; no performance observations", max_jobs=1)
        self.assertFalse(checkpoint["complete"])
        self.assertEqual(len(checkpoint["attempts"]), 1)
        attempt = checkpoint["attempts"][0]
        self.assertEqual(attempt["job_id"], "warmup_highs")
        self.assertEqual(attempt["status"], "complete")
        row = campaign.replay_row(self.output, self.manifest, attempt)
        self.assertTrue(row["warmup"])
        self.assertTrue(row["accepted"])
        self.assertEqual(checkpoint["invocations"][0]["completed_jobs"], 1)


class SolverQualityIntegrityTests(unittest.TestCase):
    def temporary_root(self):
        result_root = campaign.ROOT / "results"
        result_root.mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix="wp6_integrity_", dir=result_root)
        self.addCleanup(temporary.cleanup)
        return Path(temporary.name)

    def test_failed_attempt_log_hash_is_verified(self):
        output = self.temporary_root()
        directory = output / "raw/failure/attempt_01"
        directory.mkdir(parents=True)
        log = directory / "worker.log"
        log.write_bytes(b"original failed worker bytes")
        attempt = {"directory": "raw/failure/attempt_01", "status": "failed",
                   "sha256": {"worker.log": hashlib.sha256(b"original failed worker bytes").hexdigest()}}
        campaign.verify_attempt(output, attempt)
        log.write_bytes(b"changed failure bytes")
        with self.assertRaisesRegex(ValueError, "retained attempt hash mismatch"):
            campaign.verify_attempt(output, attempt)

    def test_running_and_orphan_attempts_are_sealed_without_promotion_or_overwrite(self):
        output = self.temporary_root()
        for number in (1, 2):
            directory = output / "raw/job" / f"attempt_{number:02d}"
            directory.mkdir(parents=True)
            (directory / "result.json").write_bytes(b"uncommitted original bytes")
        checkpoint = {"attempts": [{"job_id": "job", "directory": "raw/job/attempt_01",
                                   "status": "running", "sha256": {}}]}
        campaign.seal_interrupted_attempts(output, checkpoint, {"jobs": [{"id": "job"}]})
        self.assertEqual(len(checkpoint["attempts"]), 2)
        for attempt in checkpoint["attempts"]:
            self.assertEqual(attempt["status"], "interrupted")
            self.assertFalse(attempt["interruption_provenance"]["scientifically_accepted"])
            self.assertEqual(attempt["sha256"]["result.json"], hashlib.sha256(b"uncommitted original bytes").hexdigest())
            self.assertEqual((output / attempt["directory"] / "result.json").read_bytes(), b"uncommitted original bytes")
        self.assertIn("orphan_provenance", checkpoint["attempts"][1])

    def test_runtime_native_artifact_provenance_uses_relative_members_and_sha(self):
        output = self.temporary_root()
        binary = output / "native.so"
        binary.write_bytes(b"hand known native binary fixture")
        installed = SimpleNamespace(files=[Path("module/native.so"), Path("module/code.py")],
                                    locate_file=lambda member: binary)
        with patch.object(campaign, "distribution", return_value=installed), \
             patch.object(campaign, "version", return_value="fixture-version"), \
             patch.object(campaign.shutil, "which", return_value=None):
            record = campaign.environment_record("fixture; no performance measurement")
        native = record["native_package_artifacts"]["highspy"]
        self.assertEqual(native, [{"distribution_member": "module/native.so", "bytes": 32,
                                   "sha256": hashlib.sha256(b"hand known native binary fixture").hexdigest()}])
        self.assertEqual(record["runtime_executable"]["filename"], Path(sys.executable).name)

    def test_exact_path_redaction_preserves_numeric_bits_booleans_and_other_strings(self):
        value = {"command": "/exact/root/worker", "number": -0.0, "flag": True,
                 "scientific_label": "default absolute objective policy", "similar_path": "/different/root/worker"}
        portable = campaign.redact_metadata(value, "/exact/root")
        self.assertEqual(portable["command"], "./worker")
        self.assertEqual(portable["number"].hex(), "-0x0.0p+0")
        self.assertIs(portable["flag"], True)
        self.assertEqual(portable["scientific_label"], value["scientific_label"])
        self.assertEqual(portable["similar_path"], value["similar_path"])

    def test_package_membership_hash_and_entry_hash_are_rejected_if_changed(self):
        output = self.temporary_root()
        (output / "raw").mkdir()
        (output / "raw/worker.log").write_bytes(b"failure retained verbatim")
        campaign.package_campaign(output)
        archive = output / "evidence.zip"
        original_archive = archive.read_bytes()
        original_manifest = campaign.load_json(output / "evidence_manifest.json")
        archive.write_bytes(original_archive + b"mutated trailer")
        with self.assertRaisesRegex(ValueError, "archive changed"):
            campaign.unpack_campaign(output)
        archive.write_bytes(original_archive)
        changed_manifest = json.loads(json.dumps(original_manifest))
        changed_manifest["files"][0]["sha256"] = "0" * 64
        campaign.save_json(output / "evidence_manifest.json", changed_manifest)
        with self.assertRaisesRegex(ValueError, "archive entry changed"):
            campaign.unpack_campaign(output)
        changed_manifest = json.loads(json.dumps(original_manifest))
        changed_manifest["files"].append({"path": "raw/missing.log", "bytes": 0, "sha256": "0" * 64})
        campaign.save_json(output / "evidence_manifest.json", changed_manifest)
        with self.assertRaisesRegex(ValueError, "archive membership changed"):
            campaign.unpack_campaign(output)

    def test_independent_row_field_mutation_is_rejected_even_with_refreshed_file_sha(self):
        output = self.temporary_root()
        manifest = campaign.prepare(output, ["highs"])
        job = next(job for job in manifest["jobs"] if job["id"] == "warmup_highs")
        directory = output / "raw/warmup_highs/attempt_01"
        row = campaign.run_worker(output, job, directory)
        self.assertTrue(row["accepted"])
        for field, wrong in (("independent_objective_diagnostic_usd", -123.0), ("objective_agrees", False),
                             ("objective_absolute_difference_usd", 1.0), ("rejection_reasons", ["fabricated"]),
                             ("normalized_gap", 0.5), ("native_gap", 0.0)):
            with self.subTest(field=field):
                changed = {**row, field: wrong}
                campaign.save_json(directory / "result.json", changed)
                attempt = {"directory": "raw/warmup_highs/attempt_01", "sha256": {
                    name: campaign.sha256(directory / name) for name in ("result.json", "evidence.json.gz")}}
                with self.assertRaises(ValueError):
                    campaign.replay_row(output, manifest, attempt)

    def test_raw_normalization_rejection_replays_without_placement_or_solver(self):
        from llm_resource_allocation.optimization.extraction import RawPdmSolution
        from llm_resource_allocation.optimization.solver import SolverBackend, SolverResult, SolverStatus
        output = self.temporary_root()
        manifest = campaign.prepare(output, ["highs"])
        job = next(job for job in manifest["jobs"] if job["id"] == "warmup_highs")
        original_directory = output / "original_tiny"
        campaign.run_worker(output, job, original_directory)
        with gzip.open(original_directory / "evidence.json.gz", "rt", encoding="utf-8") as stream:
            original = json.load(stream)
        solver_values = dict(original["solver"])
        solver_values["backend"] = SolverBackend(solver_values["backend"])
        solver_values["status"] = SolverStatus(solver_values["status"])
        solver = SolverResult(**solver_values)
        values = {name: campaign.unpack_mapping(value) for name, value in original["raw"].items()}
        values["z"][next(iter(values["z"]))] = 0.25  # z is binary; x is a continuous routing fraction
        raw = RawPdmSolution(**values)
        directory = output / "rejected_tiny"
        with patch("llm_resource_allocation.optimization.solver.solve_pyomo_model", return_value=solver), \
             patch("llm_resource_allocation.optimization.extraction.extract_raw_pdm_solution_from_pyomo", return_value=raw):
            row = campaign.run_worker(output, job, directory)
        self.assertFalse(row["completed"])
        self.assertFalse(row["accepted"])
        self.assertIsNone(row["usable_objective_usd"])
        self.assertEqual(row["rejection_reasons"], ["no_complete_placement"])
        attempt = {"directory": "rejected_tiny", "sha256": {
            name: campaign.sha256(directory / name) for name in ("result.json", "evidence.json.gz")}}
        with patch("llm_resource_allocation.optimization.solver.solve_pyomo_model", side_effect=AssertionError("replay must not solve")):
            self.assertEqual(campaign.replay_row(output, manifest, attempt), row)

    def test_archive_only_publication_replays_frozen_source_without_current_src_or_solver(self):
        base = self.temporary_root()
        output = base / "campaign"
        manifest = campaign.prepare(output, ["highs"], "fixture skip; no three-way ordering")
        job = next(job for job in manifest["jobs"] if job["id"] == "warmup_highs")
        directory = output / "raw/warmup_highs/attempt_01"
        campaign.run_worker(output, job, directory)
        checkpoint = campaign.load_json(output / "checkpoint.json")
        checkpoint["attempts"].append({"job_id": job["id"], "directory": "raw/warmup_highs/attempt_01",
            "status": "complete", "sha256": {path.name: campaign.sha256(path) for path in directory.iterdir()}})
        failure_directory = output / "raw/10x10x10_L1_highs_20/attempt_01"
        failure_directory.mkdir(parents=True)
        (failure_directory / "worker.log").write_bytes(b"failed model worker; raw state unavailable")
        checkpoint["attempts"].append({"job_id": "10x10x10_L1_highs_20", "directory": failure_directory.relative_to(output).as_posix(),
            "status": "failed", "sha256": {"worker.log": campaign.sha256(failure_directory / "worker.log")}})
        campaign.save_json(output / "checkpoint.json", checkpoint)
        result = campaign.publish_campaign(output, base / "original", prefix="/exact/unused/measured/root")
        self.assertTrue(result["source_and_input_bytes_unchanged"])
        self.assertEqual((base / "original/campaign" / failure_directory.relative_to(output) / "worker.log").read_bytes(),
                         b"failed model worker; raw state unavailable")
        for name in campaign.ARCHIVED_DIRECTORIES:
            self.assertFalse((output / name).exists())
        before = campaign.sha256(output / "analysis.json")
        replay = base / "fresh"
        replay_output = replay / "benchmarks/solver_quality_2026-10-14"
        shutil.copytree(output, replay_output)
        launcher = replay / "scripts/extension_solver_quality.py"
        launcher.parent.mkdir(parents=True)
        shutil.copyfile(Path(campaign.__file__), launcher)
        self.assertFalse((replay / "src").exists())
        process = subprocess.run([sys.executable, "-B", str(launcher), "summarize", "--output", str(replay_output)],
                                 capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(campaign.sha256(replay_output / "analysis.json"), before)
        summary = campaign.load_json(replay_output / "analysis.json")
        self.assertEqual(summary["attempted_unique_measured_jobs"], 1)
        self.assertEqual(summary["accepted_measurement_rows"], 0)
        self.assertEqual(summary["measured_jobs_without_completed_result"], 1)
        self.assertEqual(len(summary["worker_failures"]), 1)


if __name__ == "__main__":
    unittest.main()
