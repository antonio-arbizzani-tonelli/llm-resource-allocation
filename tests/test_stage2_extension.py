"""Hand-derived sufficient LP contradictions and matched cohort planning."""

from contextlib import redirect_stdout
from copy import deepcopy
from dataclasses import replace
import gzip
import io
import json
from pathlib import Path
import tempfile
from time import perf_counter
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts import run_stage2_extension as extension
from scripts.run_stage2_extension import certificates, planned_jobs
from llm_resource_allocation.data import make_stage2_fully_served_case, make_stage2_capacity_limited_case
from llm_resource_allocation.optimization.problem_data import PdmProblemData
from llm_resource_allocation.optimization.stage2_problem_data import Stage2ProblemData


class Stage2ExtensionTests(unittest.TestCase):
    def test_healthy_tiny_case_has_no_sufficient_certificate(self):
        self.assertEqual(certificates(make_stage2_fully_served_case()),[])

    def test_error_certificate_uses_mandatory_service_from_cap_and_balance(self):
        data=make_stage2_fully_served_case()
        query=replace(data.instance.queries[0],max_unmet_fraction=0.2,error_slo=0.04)
        instance=replace(data.instance,queries=(query,))
        scenario=replace(data.realized_scenario,effective_errors={key:0.1 for key in data.routing_keys})
        data=Stage2ProblemData(PdmProblemData(instance),data.fixed_deployment,scenario)
        found=[item for item in certificates(data) if item["family"]=="error_slo"]
        self.assertEqual(len(found),1)
        self.assertAlmostEqual(found[0]["lower_bound"],0.08)
        self.assertEqual(found[0]["upper_bound"],0.04)
        self.assertIn("unmet_cap",found[0]["supporting_constraints"])
        self.assertIn("demand_balance",found[0]["supporting_constraints"])

    def test_capacity_certificate_uses_canonical_lp_coefficients(self):
        data=make_stage2_capacity_limited_case()
        query=replace(data.instance.queries[0],max_unmet_fraction=0.0)
        data=Stage2ProblemData(PdmProblemData(replace(data.instance,queries=(query,))),
                              data.fixed_deployment,data.realized_scenario)
        found=[item for item in certificates(data) if item["family"]=="compute_capacity"]
        self.assertEqual(len(found),1)
        self.assertEqual(found[0]["lower_bound"],40500.0)
        self.assertEqual(found[0]["upper_bound"],32400.0)
        self.assertEqual(found[0]["raw_gap"],8100.0)

    def test_missing_route_certificate_requires_mandatory_demand(self):
        data=make_stage2_fully_served_case()
        query=replace(data.instance.queries[0],max_unmet_fraction=0.0)
        instance=replace(data.instance,queries=(query,))
        # One available route, positive coefficient, zero fixed compute supply.
        fixed=replace(data.fixed_deployment,gpu_counts={key:0.0 for key in data.fixed_deployment.gpu_counts},
            configuration_selectors={key:0.0 for key in data.fixed_deployment.configuration_selectors},
            admission_indicators={key:0.0 for key in data.fixed_deployment.admission_indicators})
        # With no admitted route, the mandatory demand itself proves infeasibility.
        changed=Stage2ProblemData(PdmProblemData(instance),fixed,data.realized_scenario)
        found=certificates(changed)
        self.assertEqual(len(found),1)
        self.assertEqual(found[0]["family"],"routing_mask_and_demand_cap")
        self.assertEqual(found[0]["lower_bound"],1.0)
        self.assertEqual(found[0]["upper_bound"],0.0)

    def test_plan_shares_all_instance_identities_across_methods(self):
        config={"shapes":[[8,4,4]],"loads":[200,2000],"instance_seeds":[11,23,37],
                "methods":["gh","agh","p_dm"]}
        jobs=planned_jobs(config)
        self.assertEqual(len(jobs),18)
        identities={job["input_id"] for job in jobs}
        self.assertEqual(len(identities),6)
        for identity in identities:
            self.assertEqual({job["method"] for job in jobs if job["input_id"]==identity},{"gh","agh","p_dm"})
        self.assertEqual([job["method"] for job in jobs[:3]],["gh","agh","p_dm"])
        self.assertEqual([job["method"] for job in jobs[3:6]],["agh","p_dm","gh"])

    def test_completed_checkpoint_rejects_source_or_scenario_byte_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)
            (directory/"scenarios").mkdir()
            for path,payload in ((directory/"instance.json.gz",b"input"),
                                 (directory/"stage1.json.gz",b"source"),
                                 (directory/"scenarios/000.json.gz",b"scenario")):
                path.write_bytes(payload)
            result={"instance_sha256":extension.sha256(b"input"),
                    "stage1_evidence_sha256":extension.sha256(b"source"),
                    "attempts":[{"evidence":"scenarios/000.json.gz",
                                 "evidence_sha256":extension.sha256(b"scenario")}]}
            extension.verify_completed_evidence(directory,result)
            for path,payload in ((directory/"stage1.json.gz",b"source"),
                                 (directory/"scenarios/000.json.gz",b"scenario")):
                path.write_bytes(payload+b"changed")
                with self.assertRaisesRegex(ValueError,"completed .* checkpoint changed"):
                    extension.verify_completed_evidence(directory,result)
                path.write_bytes(payload)

    def test_replay_preserves_agh_source_without_feasible_incumbent(self):
        config={"classification":"SYNTHETIC_TEST","shapes":[[2,2,2]],"loads":[200.0],
                "instance_seeds":[11],"instance_amplitude":0.1,"methods":["agh"],
                "stage2_objective_relative_tolerance":1e-12,"bootstrap_rounds":100,
                "bootstrap_seed":1,"arrival_factors":[1.0],"stress_factors":[1.0]}
        job=planned_jobs(config)[0]
        with tempfile.TemporaryDirectory() as temporary:
            output=Path(temporary)
            directory=output/"raw/jobs"/job["id"]
            extension.save_json(output/"config.json",config)
            instance=extension.seeded_instance((2,2,2),200.0,11,0.1)
            input_hash=extension.save_scientific_evidence(directory/"instance.json.gz",instance)
            source_hash=extension.save_scientific_evidence(directory/"stage1.json.gz",
                {"accepted":False,"placement":None,"validation":None,"solver":None,
                 "completion":"no_feasible_incumbent"})
            extension.save_json(directory/"result.json",{**job,"complete":True,
                "instance_sha256":input_hash,"stage1_evidence_sha256":source_hash,
                "stage1_accepted":False,"attempts":[],"aggregate":None,"skipped_scenarios":1})
            with redirect_stdout(io.StringIO()):
                summary=extension.analyze(output,revalidate=True)
            self.assertEqual(summary["completed_sources"],1)
            self.assertEqual(summary["accepted_sources"],0)
            self.assertEqual(summary["attempted_lps"],0)
            self.assertEqual(summary["replay_verification"]["sources_without_complete_placement"],1)


class Stage2ExtensionOperationalReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from llm_resource_allocation.math.parallelism import ParallelismDecisionState
        from llm_resource_allocation.math.placement import PlacementDecisionState
        from llm_resource_allocation.math.routing import RoutingDecisionState
        from llm_resource_allocation.optimization.solver import SolverBackend,SolverConfig
        cls.data=make_stage2_fully_served_case()
        record=extension.run_stage2(cls.data,SolverConfig(backend=SolverBackend.HIGHS),
                                    objective_relative_tolerance=1e-12)
        route=cls.data.routing_keys[0]
        configuration=cls.data.pdm_problem_data.variable_lattices.configuration_keys[0]
        routing=RoutingDecisionState({route:1.0},cls.data.fixed_deployment.admission_indicators,
            cls.data.derived_deployment_indicators,{route[0]:0.0})
        cls.nominal=PlacementDecisionState(ParallelismDecisionState(routing,
            cls.data.fixed_deployment.configuration_selectors,cls.data.fixed_deployment.gpu_counts),
            {(route[0],*configuration):1.0})
        cls.saved=extension._plain({"realization":cls.data.realized_scenario,"operational_run":record,
                                   "sufficient_infeasibility_certificates":[]})
        costs=record.scientific_evidence.objective_breakdown
        comparison=record.scientific_evidence.objective_comparison
        cls.attempt={"solver_status":record.solver_evidence.result.status.value,
            "stage2_status":record.status.value,"new_usable":True,"old_usable":True,
            "independently_feasible":True,"solver_objective":comparison.solver_objective,
            "independent_objective":comparison.independent_objective,"absolute_tolerance":1e-8,
            "adapted_cost_usd":costs.operational_objective,"certificate_families":[],
            "quality":{**extension.service_observations(cls.data.instance,cls.data.realized_scenario,
                record.solution,cls.nominal),"c3_usd":costs.realized_data_storage_cost,
                "c4_usd":costs.delay_penalty,"c5_usd":costs.unmet_demand_penalty}}

    def test_good_record_replays_raw_transport_and_default_opt_in_policies(self):
        self.assertTrue(extension.replay_operational_attempt(self.data,self.nominal,self.saved,self.attempt))

    def test_attempt_metadata_mutations_are_rejected(self):
        for field,replacement in (("solver_status","infeasible"),("solver_objective",12.0),
                                  ("independent_objective",12.0),("old_usable",False),
                                  ("new_usable",False)):
            with self.subTest(field=field):
                mutated={**self.attempt,field:replacement}
                with self.assertRaises(ValueError):
                    extension.replay_operational_attempt(self.data,self.nominal,self.saved,mutated)

    def test_raw_decision_mutation_cannot_be_hidden_by_normalized_solution(self):
        saved=deepcopy(self.saved)
        saved["operational_run"]["raw_solution"]["x"][0]["value"]=0.9
        with self.assertRaisesRegex(ValueError,"raw transport normalization changed"):
            extension.replay_operational_attempt(self.data,self.nominal,saved,self.attempt)

    def test_infeasible_solver_record_keeps_missing_solution_and_zero_usable_cost(self):
        saved=deepcopy(self.saved)
        run=saved["operational_run"]
        run["solver_evidence"]["result"].update(status="infeasible",has_incumbent=False,objective_value=None)
        run.update(status="solver_no_usable_solution",raw_solution=None,solution=None,
                   failure={"status":"solver_no_usable_solution","error_type":"NoSolverIncumbentError","message":"no incumbent"})
        run["scientific_evidence"].update(validation_report=None,objective_comparison=None)
        attempt={**self.attempt,"solver_status":"infeasible","stage2_status":"solver_no_usable_solution",
                 "new_usable":False,"old_usable":False,"independently_feasible":False,
                 "solver_objective":None,"independent_objective":None,"adapted_cost_usd":None,"quality":None}
        self.assertFalse(extension.replay_operational_attempt(self.data,self.nominal,saved,attempt))


class Stage2ExtensionInterruptionTests(unittest.TestCase):
    def config(self,method):
        return {"classification":"SYNTHETIC_INTERRUPTION_TEST","shapes":[[2,2,2]],
                "loads":[200.0],"instance_seeds":[11],"methods":[method],
                "instance_amplitude":0.1,"agh_algorithm_seed":37,"gh_budget_fraction":0.8,
                "backend":"highs","stage1_solver_limit_seconds":20,
                "stage2_solver_limit_seconds":20,"stage2_objective_relative_tolerance":1e-12,
                "arrival_factors":[1.0],"stress_factors":[1.0]}

    def test_source_written_before_checkpoint_is_retained_before_retry(self):
        config=self.config("agh")
        job=planned_jobs(config)[0]
        source=SimpleNamespace(completion_status="no_feasible_incumbent")
        with tempfile.TemporaryDirectory() as temporary:
            output=Path(temporary)
            directory=output/"raw/jobs"/job["id"]
            result_path=directory/"result.json"
            original_save=extension.save_json
            def interrupt_checkpoint(path,record):
                if path==result_path and "stage1_evidence_sha256" in record:
                    raise KeyboardInterrupt("producer interrupted after source write")
                original_save(path,record)
            with patch.object(extension,"run_agh",return_value=source) as algorithm, \
                    patch.object(extension,"source_details",return_value=(False,None,None,None)):
                with patch.object(extension,"save_json",side_effect=interrupt_checkpoint):
                    with self.assertRaises(KeyboardInterrupt):
                        extension.run_job(output,job,config,perf_counter()+60)
                orphan=(directory/"stage1.json.gz").read_bytes()
                result=extension.run_job(output,job,config,perf_counter()+60)
                self.assertEqual(algorithm.call_count,2)
            self.assertTrue(result["complete"])
            self.assertFalse(result["stage1_accepted"])
            prior=result["interrupted_attempts"][0]
            self.assertEqual(prior["phase"],"stage1")
            self.assertEqual(prior["sha256"],extension.sha256(orphan))
            self.assertEqual((directory/prior["retained_path"]).read_bytes(),orphan)
            self.assertEqual(prior["instance_sha256"],result["instance_sha256"])
            extension.verify_completed_evidence(directory,result)

    def test_scenario_written_before_checkpoint_is_retained_and_rerun_unchanged(self):
        from llm_resource_allocation.math.parallelism import ParallelismDecisionState
        from llm_resource_allocation.math.placement import PlacementDecisionState
        from llm_resource_allocation.math.routing import RoutingDecisionState
        data=make_stage2_fully_served_case()
        route=data.routing_keys[0]
        configuration=data.pdm_problem_data.variable_lattices.configuration_keys[0]
        nominal=PlacementDecisionState(ParallelismDecisionState(
            RoutingDecisionState({route:1.0},data.fixed_deployment.admission_indicators,
                data.derived_deployment_indicators,{route[0]:0.0}),
            data.fixed_deployment.configuration_selectors,data.fixed_deployment.gpu_counts),
            {(route[0],*configuration):1.0})
        source_report=extension.validate_placement(data.instance,nominal,extension.PaperVersion.V2)
        self.assertTrue(source_report.is_feasible)
        config=self.config("gh")
        job=planned_jobs(config)[0]
        source=SimpleNamespace(completion_status="algorithm_1_completed")
        with tempfile.TemporaryDirectory() as temporary:
            output=Path(temporary)
            directory=output/"raw/jobs"/job["id"]
            result_path=directory/"result.json"
            original_save=extension.save_json
            def interrupt_checkpoint(path,record):
                if path==result_path and len(record["attempts"])==1:
                    raise KeyboardInterrupt("producer interrupted after scenario write")
                original_save(path,record)
            with patch.object(extension,"seeded_instance",return_value=data.instance), \
                    patch.object(extension,"run_gh",return_value=source) as algorithm, \
                    patch.object(extension,"source_details",return_value=(True,nominal,source_report,None)), \
                    patch.object(extension,"run_stage2",wraps=extension.run_stage2) as solver:
                with patch.object(extension,"save_json",side_effect=interrupt_checkpoint):
                    with self.assertRaises(KeyboardInterrupt):
                        extension.run_job(output,job,config,perf_counter()+60)
                orphan=(directory/"scenarios/000.json.gz").read_bytes()
                result=extension.run_job(output,job,config,perf_counter()+60)
                self.assertEqual(algorithm.call_count,1)
                self.assertEqual(solver.call_count,2)
                self.assertEqual(extension._plain(solver.call_args_list[0].args[0].realized_scenario),
                                 extension._plain(solver.call_args_list[1].args[0].realized_scenario))
            self.assertTrue(result["complete"])
            self.assertEqual(len(result["attempts"]),1)
            prior=result["interrupted_attempts"][0]
            self.assertEqual(prior["phase"],"scenario_000")
            self.assertEqual(prior["sha256"],extension.sha256(orphan))
            self.assertEqual((directory/prior["retained_path"]).read_bytes(),orphan)
            extension.verify_completed_evidence(directory,result)


if __name__=="__main__":
    unittest.main()
