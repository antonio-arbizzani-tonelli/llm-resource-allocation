"""Checkpointed matched-input Stage-2 experiment and historical certificates.

Every measurement belongs to a new opt-in campaign. Scientific solvers,
algorithms, independent validators and observed failures retain their authority.
"""

import argparse
from collections import Counter, defaultdict
import csv
from dataclasses import replace
from datetime import datetime, timezone
import gzip
from importlib.metadata import version
import json
from math import fsum
from pathlib import Path, PurePosixPath
import platform
import sys
from time import perf_counter
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/"src"))

from pyomo.environ import value
from pyomo.repn import generate_standard_repn
from scripts.extension_instances import seeded_instance
from scripts.replay_stage2_policy import EvidenceArchive, mapping, saved_placement, save_json, sha256, require, summarize
from scripts.run_stage2_stress import source_details, save_scientific_evidence
from scripts.run_azure_replay import _plain
from llm_resource_allocation.algorithms import GHPhase1Config, run_agh, run_gh
from llm_resource_allocation.data.scaling_experiment_instances import make_scaling_experiment_case
from llm_resource_allocation.domain import UnitConvention
from llm_resource_allocation.experiments.stress_grid import StressGrid, iter_stress_scenarios, service_observations
from llm_resource_allocation.math.objective import PaperVersion
from llm_resource_allocation.optimization.extraction import PdmSolutionExtractionError, PdmSolutionNormalizationError, SolutionNormalizationTolerances
from llm_resource_allocation.optimization.pdm_run import execute_and_record_pdm_run
from llm_resource_allocation.optimization.problem_data import PdmProblemData
from llm_resource_allocation.optimization.pyomo_stage2 import build_stage2_pyomo_model
from llm_resource_allocation.optimization.solver import NoSolverIncumbentError, SolverBackend, SolverConfig
from llm_resource_allocation.optimization.stage2_extraction import (
    RawStage2Solution, Stage2Solution, Stage2SolutionNormalizationError,
    normalize_raw_stage2_solution, stage2_solution_identity)
from llm_resource_allocation.optimization.stage2_problem_data import Stage2FixedDeployment, Stage2ProblemData
from llm_resource_allocation.optimization.stage2_run import run_stage2
from llm_resource_allocation.validation.objective_comparison import ObjectiveComparison
from llm_resource_allocation.validation.placement import validate_placement, ValidationTolerances
from llm_resource_allocation.validation.stage2 import validate_stage2_solution, Stage2ValidationTolerances


def certificates(data):
    """Derive sufficient contradictions from unchanged canonical LP coefficients.

    Capacity certificates use a relaxation lower bound: single-admitted-route
    queries impose mandatory load on their pair; the global bound selects each
    query's cheapest allowed compute coefficient while ignoring pair contention.
    These are not a unique IIS or a classification of an invented incumbent.
    """
    model = build_stage2_pyomo_model(data)
    tolerances = Stage2ValidationTolerances()
    by_query = defaultdict(list)
    compute_coefficients = {}
    for pair in model.model_tier_keys:
        repn = generate_standard_repn(model.required_compute[pair].expr)
        for variable, coefficient in zip(repn.linear_vars, repn.linear_coefs, strict=True):
            compute_coefficients[variable.index()] = float(coefficient)
    for key in data.routing_keys:
        if data.fixed_deployment.admission_indicators.get(key,0.0) == 1:
            by_query[key[0]].append(key)
    observed = []
    mandatory_by_pair = defaultdict(list)
    global_terms = []
    def add(family, location, lower, upper, absolute, relative, support, details=None):
        threshold = absolute + relative*max(abs(lower),abs(upper))
        if lower-upper > threshold:
            observed.append({"family":family,"location":location,"lower_bound":lower,
                "upper_bound":upper,"raw_gap":lower-upper,"comparison_threshold":threshold,
                "supporting_constraints":support,"details":details})
    for query in data.instance.queries:
        allowed = by_query[query.id]
        mandatory = 1-query.max_unmet_fraction
        support = ["demand_balance","unmet_cap","routing_mask"]
        if not allowed:
            add("routing_mask_and_demand_cap",query.id,mandatory,0.0,
                tolerances.demand_balance,0.0,support)
            continue
        minimum_error = min(data.realized_scenario.effective_errors[key] for key in allowed)
        add("error_slo",query.id,mandatory*minimum_error,query.error_slo,
            tolerances.error_slo,tolerances.error_slo_relative,support+["error_slo"],
            {"minimum_admitted_error":minimum_error,"mandatory_service_fraction":mandatory})
        minimum_delay = min(value(model.realized_configuration_delay[key]) for key in allowed)
        add("delay_slo",query.id,mandatory*minimum_delay,query.delay_slo_seconds,
            tolerances.delay_slo,tolerances.delay_slo_relative,support+["delay_slo"])
        global_terms.append(mandatory*min(compute_coefficients.get(key,0.0) for key in allowed))
        if len(allowed) == 1:
            key=allowed[0]
            mandatory_by_pair[key[1:]].append(mandatory*compute_coefficients.get(key,0.0))
    for pair,terms in mandatory_by_pair.items():
        add("compute_capacity",list(pair),fsum(terms),value(model.available_compute[pair]),
            tolerances.compute_capacity,tolerances.compute_capacity_relative,
            ["demand_balance","unmet_cap","routing_mask","compute_capacity"],
            {"bound":"mandatory single-admitted-route queries"})
    add("compute_capacity_global", "all_pairs",fsum(global_terms),
        fsum(value(model.available_compute[pair]) for pair in model.model_tier_keys),
        tolerances.compute_capacity,tolerances.compute_capacity_relative,
        ["demand_balance","unmet_cap","routing_mask","compute_capacity"],
        {"bound":"minimum admitted compute per query; ignores pair contention"})
    return observed


def historical_diagnosis(output):
    archive = EvidenceArchive(ROOT/"benchmarks/stage2_stress_2026-10-13")
    rows=[]
    try:
        config=archive.read("snapshot/configs/nightly_campaign.json")
        grid=StressGrid(tuple(config["arrival_factors"]),tuple(config["stress_factors"]))
        for job in archive.read("jobs.json"):
            base=job["output"].replace("\\","/")
            result=archive.read(base+"/result.json")
            if not result["stage1_accepted"]:
                continue
            shape,load=result["shape"],result["load_multiplier"]
            instance=replace(make_scaling_experiment_case(*shape,load_multiplier=load).instance,
                unit_convention=UnitConvention.COHERENT,data_residency_hours=config["data_residency_hours"],
                id=f"extended_{shape[0]}x{shape[1]}x{shape[2]}_load{load:g}")
            require(_plain(instance)==archive.read(base+"/instance.json.gz"),"historical input changed")
            nominal=saved_placement(archive.read(base+"/stage1.json.gz")["placement"])
            fixed=Stage2FixedDeployment(nominal.admission_indicators,nominal.configuration_selectors,nominal.gpu_counts)
            problem=PdmProblemData(instance)
            for row,(_,_,scenario) in zip(result["attempts"],iter_stress_scenarios(instance,grid),strict=True):
                if row["solver_status"] != "infeasible":
                    continue
                observations=certificates(Stage2ProblemData(problem,fixed,scenario))
                families=sorted({item["family"] for item in observations})
                rows.append({"job":job["id"],"shape":shape,"load":load,"index":row["index"],
                    "arrival_factor":row["arrival_factor"],"stress_factor":row["stress_factor"],
                    "sufficient_certificate_families":families,"certificates":observations,
                    "unexplained":not observations,"original_evidence":base+"/"+row["evidence"],
                    "original_evidence_sha256":row["evidence_sha256"]})
        require(len(rows)==1000,"historical infeasible denominator changed")
        def counts(items):
            return {"solver_infeasible":len(items),"with_sufficient_certificate":sum(bool(r["certificates"]) for r in items),
                "unexplained":sum(r["unexplained"] for r in items),
                "overlapping_family_counts":dict(Counter(family for r in items for family in r["sufficient_certificate_families"])),
                "supporting_demand_cap_and_balance":sum(bool(r["certificates"]) for r in items)}
        summary={"archive_sha256":archive.manifest["archive_sha256"],"scope":"sufficient algebraic certificates; no solver rerun or unique IIS",
            "all":counts(rows),"by_load":{str(load):counts([r for r in rows if r["load"]==load]) for load in sorted({r["load"] for r in rows})},
            "by_arrival_factor":{str(factor):counts([r for r in rows if r["arrival_factor"]==factor]) for factor in sorted({r["arrival_factor"] for r in rows})}}
        save_json(output/"historical_infeasibility.json",{"summary":summary,"rows":rows})
        print(json.dumps(summary["all"]))
    finally:
        archive.close()


def planned_jobs(config):
    jobs=[]
    for shape in config["shapes"]:
        for load in config["loads"]:
            for index,seed in enumerate(config["instance_seeds"]):
                methods=config["methods"]
                order=methods[index%len(methods):]+methods[:index%len(methods)]
                for method in order:
                    identity=f"{'x'.join(map(str,shape))}_L{load:g}_i{seed}"
                    jobs.append({"id":identity+"_"+method,"input_id":identity,"shape":shape,
                                 "load":load,"instance_seed":seed,"method":method})
    return jobs


def current_sources():
    paths=list((ROOT/"src").rglob("*.py"))
    paths += [ROOT/"scripts"/name for name in ("run_stage2_extension.py","extension_instances.py",
        "replay_stage2_policy.py","run_stage2_stress.py","run_azure_replay.py")]
    return {path.relative_to(ROOT).as_posix():sha256(path.read_bytes()) for path in sorted(paths)}


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_gzip(path):
    return json.loads(gzip.decompress(path.read_bytes()))


def raw_inventory(raw):
    return {path.relative_to(raw).as_posix():sha256(path.read_bytes())
        for path in sorted(raw.rglob("*")) if path.is_file()}


def verify_completed_evidence(directory,result):
    """Check retained input/source/scenario bytes before reusing a completed job."""
    require(sha256((directory/"instance.json.gz").read_bytes())==result["instance_sha256"],
            "completed input checkpoint changed")
    if "stage1_evidence_sha256" in result:
        require(sha256((directory/"stage1.json.gz").read_bytes())==result["stage1_evidence_sha256"],
                "completed source checkpoint changed")
    for attempt in result["attempts"]:
        require(sha256((directory/attempt["evidence"]).read_bytes())==attempt["evidence_sha256"],
                "completed scenario checkpoint changed")
    for interrupted in result.get("interrupted_attempts",[]):
        require(sha256((directory/interrupted["retained_path"]).read_bytes())==interrupted["sha256"],
                "interrupted evidence checkpoint changed")
        require(sha256((directory/interrupted["metadata_path"]).read_bytes())==interrupted["metadata_sha256"],
                "interrupted provenance checkpoint changed")


def preserve_uncheckpointed_evidence(directory,path,result,result_path,config,phase):
    """Retain uncommitted bytes/provenance before retrying unchanged inputs.

    The interrupted output is never promoted to a measured attempt. Its timer
    metadata was not committed, so the original scientific phase is rerun.
    """
    payload=path.read_bytes()
    retained=directory/"interrupted"
    retained.mkdir(exist_ok=True)
    number=1
    while (retained/f"{phase}_{number:03d}.json.gz").exists() or (retained/f"{phase}_{number:03d}.metadata.json").exists():
        number+=1
    target=retained/f"{phase}_{number:03d}.json.gz"
    pending=target.with_suffix(target.suffix+".pending")
    pending.write_bytes(payload)
    pending.replace(target)
    require(sha256(target.read_bytes())==sha256(payload),"retained interrupted copy changed")
    metadata=retained/f"{phase}_{number:03d}.metadata.json"
    record={"classification":"INTERRUPTED_UNCHECKPOINTED_OUTPUT","phase":phase,
        "observed_utc":datetime.now(timezone.utc).isoformat(),"job_id":result["id"],
        "original_path":path.relative_to(directory).as_posix(),
        "retained_path":target.relative_to(directory).as_posix(),"sha256":sha256(payload),
        "metadata_path":metadata.relative_to(directory).as_posix(),
        "instance_sha256":result["instance_sha256"],
        "configuration_sha256":sha256(json.dumps(config,sort_keys=True,separators=(",",":")).encode()),
        "continuation":"retry unchanged scientific phase; no values repaired or imputed",
        "timing":"uncommitted; excluded from measurement summaries"}
    save_json(metadata,record)
    result.setdefault("interrupted_attempts",[]).append({**record,"metadata_sha256":sha256(metadata.read_bytes())})
    save_json(result_path,result)
    # A retained, hashed copy and atomic result checkpoint now own these bytes.
    path.unlink()


def run_job(output,job,config,deadline):
    directory=output/"raw/jobs"/job["id"]
    directory.mkdir(parents=True,exist_ok=True)
    instance=seeded_instance(tuple(job["shape"]),job["load"],job["instance_seed"],config["instance_amplitude"])
    problem=PdmProblemData(instance)
    input_path=directory/"instance.json.gz"
    if not input_path.exists():
        save_scientific_evidence(input_path,instance)
    require(read_gzip(input_path)==_plain(instance),"prepared input changed")
    result_path=directory/"result.json"
    result=read_json(result_path) if result_path.exists() else {**job,"complete":False,
        "instance_sha256":sha256(input_path.read_bytes()),"stage1_accepted":None,"attempts":[],"aggregate":None}
    if result["complete"]:
        verify_completed_evidence(directory,result)
        return result
    method=job["method"]
    source_path=directory/"stage1.json.gz"
    if source_path.exists() and "stage1_evidence_sha256" not in result:
        preserve_uncheckpointed_evidence(directory,source_path,result,result_path,config,"stage1")
    if not source_path.exists():
        start=perf_counter()
        try:
            if method=="p_dm":
                source=execute_and_record_pdm_run(problem,SolverConfig(backend=SolverBackend(config["backend"]),
                    time_limit_seconds=config["stage1_solver_limit_seconds"],relative_mip_gap=0.0,absolute_mip_gap=0.0))
            elif method=="gh":
                source=run_gh(instance,GHPhase1Config(config["gh_budget_fraction"]))
            else:
                source=run_agh(instance,GHPhase1Config(config["gh_budget_fraction"]),random_seed=config["agh_algorithm_seed"])
        except (NoSolverIncumbentError,PdmSolutionExtractionError,PdmSolutionNormalizationError) as error:
            result.update(stage1_accepted=False,complete=True,stage1_seconds=perf_counter()-start,
                stage1_failure={"type":type(error).__name__,"message":str(error)},skipped_scenarios=50)
            save_json(result_path,result)
            return result
        accepted,nominal,report,solver=source_details(source,method)
        result.update(stage1_seconds=perf_counter()-start,stage1_accepted=accepted)
        result["stage1_evidence_sha256"]=save_scientific_evidence(source_path,
            {"accepted":accepted,"placement":nominal,"validation":report,"solver":solver,
             "completion":source.completion_status if method!="p_dm" else None})
        save_json(result_path,result)
    saved=read_gzip(source_path)
    require(sha256(source_path.read_bytes())==result["stage1_evidence_sha256"],"source checkpoint changed")
    if not saved["accepted"]:
        result.update(complete=True,stage1_accepted=False,skipped_scenarios=50)
        save_json(result_path,result)
        return result
    nominal=saved_placement(saved["placement"])
    report=validate_placement(instance,nominal,PaperVersion.V2,tolerances=ValidationTolerances(**saved["validation"]["tolerances"]))
    require(_plain(report)==saved["validation"] and report.is_feasible,"source replay changed")
    fixed=Stage2FixedDeployment(nominal.admission_indicators,nominal.configuration_selectors,nominal.gpu_counts)
    grid=StressGrid(tuple(config["arrival_factors"]),tuple(config["stress_factors"]))
    solver_config=SolverConfig(backend=SolverBackend(config["backend"]),time_limit_seconds=config["stage2_solver_limit_seconds"])
    for index,(arrival,stress,scenario) in enumerate(iter_stress_scenarios(instance,grid)):
        if index < len(result["attempts"]):
            attempt=result["attempts"][index]
            require(sha256((directory/attempt["evidence"]).read_bytes())==attempt["evidence_sha256"],"scenario checkpoint changed")
            continue
        if perf_counter()+config["stage2_solver_limit_seconds"] >= deadline:
            save_json(result_path,result)
            return result
        evidence_path=directory/"scenarios"/f"{index:03d}.json.gz"
        if evidence_path.exists():
            preserve_uncheckpointed_evidence(directory,evidence_path,result,result_path,config,f"scenario_{index:03d}")
        data=Stage2ProblemData(problem,fixed,scenario)
        start=perf_counter()
        record=run_stage2(data,solver_config=solver_config,
            objective_relative_tolerance=config["stage2_objective_relative_tolerance"])
        integrated=perf_counter()-start
        frozen=Stage2Solution(stage2_solution_identity(data),nominal.routing_fractions,nominal.unmet_fractions)
        frozen_report=validate_stage2_solution(data,frozen)
        diagnostic=certificates(data) if record.solver_evidence.result.status.value=="infeasible" else []
        digest=save_scientific_evidence(evidence_path,{"realization":scenario,"operational_run":record,
            "frozen_routing_validation":frozen_report,"sufficient_infeasibility_certificates":diagnostic})
        comparison=record.scientific_evidence.objective_comparison
        costs=record.scientific_evidence.objective_breakdown
        result["attempts"].append({"index":index,"arrival_factor":arrival,"stress_factor":stress,
            "stage2_status":record.status.value,"solver_status":record.solver_evidence.result.status.value,
            "new_usable":record.successful,"old_usable":record.independently_feasible and comparison is not None and ObjectiveComparison(
                comparison.solver_objective,comparison.independent_objective,comparison.absolute_tolerance).agrees,
            "independently_feasible":record.independently_feasible,"frozen_feasible":frozen_report.is_feasible,
            "solver_objective":comparison.solver_objective if comparison else None,
            "independent_objective":comparison.independent_objective if comparison else None,"absolute_tolerance":1e-8,
            "frozen_cost_usd":frozen_report.objective_breakdown.operational_objective if frozen_report.is_feasible else None,
            "adapted_cost_usd":costs.operational_objective if costs else None,
            "quality":{**service_observations(instance,scenario,record.solution,nominal),
                "c3_usd":costs.realized_data_storage_cost,"c4_usd":costs.delay_penalty,"c5_usd":costs.unmet_demand_penalty} if record.successful else None,
            "integrated_seconds":integrated,"certificate_families":sorted({c["family"] for c in diagnostic}),
            "evidence":evidence_path.relative_to(directory).as_posix(),"evidence_sha256":digest})
        save_json(result_path,result)
    result.update(complete=True,accepted_scenarios=sum(a["new_usable"] for a in result["attempts"]))
    if result["accepted_scenarios"]==grid.scenario_count:
        result["aggregate"]={"mean_operational_cost_usd":fsum(a["adapted_cost_usd"] for a in result["attempts"])/grid.scenario_count}
    save_json(result_path,result)
    return result


def run_campaign(output,resume):
    config=read_json(output/"config.json")
    jobs=planned_jobs(config)
    raw=output/"raw"
    raw.mkdir(exist_ok=True)
    manifest_path=raw/"campaign_manifest.json"
    digest=sha256(json.dumps(config,sort_keys=True,separators=(",",":")).encode())
    sources=current_sources()
    if manifest_path.exists():
        require(resume,"existing campaign requires --resume")
        manifest=read_json(manifest_path)
        require(manifest["configuration_sha256"]==digest and manifest["source_sha256"]==sources,"configuration or source snapshot changed")
    else:
        manifest={"configuration_sha256":digest,"source_sha256":sources,"jobs":jobs,
            "runtime":{"python":platform.python_version(),"platform":platform.platform(),
                "pyomo":version("pyomo"),"highspy":version("highspy")},"invocations":[]}
        with zipfile.ZipFile(output/"scientific-source-snapshot.zip","w",zipfile.ZIP_DEFLATED) as archive:
            for name in sources:
                archive.write(ROOT/name,name)
            archive.write(output/"config.json","config.json")
    start=perf_counter()
    deadline=start+config["maximum_wall_seconds"]
    invocation={"resume":resume,"planned_jobs":len(jobs),"completed":0,"wall_budget_seconds":config["maximum_wall_seconds"]}
    manifest["invocations"].append(invocation)
    save_json(manifest_path,manifest)
    for job in jobs:
        if perf_counter()+config["stage1_solver_limit_seconds"]>=deadline:
            break
        result=run_job(output,job,config,deadline)
        if not result["complete"]:
            break
        invocation["completed"]+=1
        invocation["elapsed_seconds"]=perf_counter()-start
        save_json(manifest_path,manifest)
        print(f"{invocation['completed']}/{len(jobs)} {job['id']}: source={result['stage1_accepted']}, usable={sum(a['new_usable'] for a in result['attempts'])}/{len(result['attempts'])}",flush=True)
    invocation["elapsed_seconds"]=perf_counter()-start
    invocation["status"]="complete" if invocation["completed"]==len(jobs) else "partial_wall_budget"
    save_json(manifest_path,manifest)
    return invocation


class _ArchiveParts:
    """Own validated ZIP handles and dispatch an exact logical raw tree."""

    def __init__(self,archives,entry_archives):
        self.archives=archives
        self.entry_archives=entry_archives

    def read(self,name):
        return self.archives[self.entry_archives[name]].read(name)

    def namelist(self):
        return list(self.entry_archives)

    def close(self):
        for archive in self.archives.values():
            archive.close()


def valid_entry_name(name):
    require(isinstance(name,str),"invalid archive entry path")
    path=PurePosixPath(name)
    require(not path.is_absolute() and ".." not in path.parts
            and "\\" not in name and path.as_posix()==name,"invalid archive entry path")


def delivered_reader(output,*,prefer_raw=False):
    raw=output/"raw"
    manifest_path=output/"evidence_manifest.json"
    if raw.is_dir() and (prefer_raw or not manifest_path.is_file()):
        return lambda name: raw.joinpath(name).read_bytes(), [p.relative_to(raw).as_posix() for p in raw.rglob("*") if p.is_file()],None
    manifest=read_json(manifest_path)
    snapshot=manifest.get("measured_source_snapshot")
    if snapshot is not None:
        valid_entry_name(snapshot["path"])
        require(PurePosixPath(snapshot["path"]).name==snapshot["path"] and "\\" not in snapshot["path"],
                "invalid frozen source archive path")
        require(sha256((output/snapshot["path"]).read_bytes())==snapshot["sha256"],
                "frozen measured source archive changed")
    files=manifest["files"]
    file_map={entry["path"]:entry for entry in files}
    require(len(file_map)==len(files),"duplicate manifest entry")
    require(len(files)==manifest["file_count"],"archive file count changed")
    for name in file_map:
        valid_entry_name(name)
    multipart="archives" in manifest
    parts=manifest["archives"] if multipart else [{"path":"evidence.zip",
        "sha256":manifest["archive_sha256"],"members":list(file_map),"file_count":len(files)}]
    require(len({part["path"] for part in parts})==len(parts),"duplicate archive part")
    archives={}
    entry_archives={}
    success=False
    try:
        for part in parts:
            name=part["path"]
            valid_entry_name(name)
            require(PurePosixPath(name).name==name and "\\" not in name,"invalid archive part path")
            members=part["members"]
            require(len(set(members))==len(members),"duplicate declared archive membership")
            require(len(members)==part["file_count"],"archive part file count changed")
            require(not set(members)&entry_archives.keys(),"duplicate membership across archive parts")
            expected={entry["path"] for entry in files if not multipart or entry["archive"]==name}
            require(set(members)==expected,"declared archive membership changed")
            path=output/name
            require(sha256(path.read_bytes())==part["sha256"],"new campaign archive changed")
            if multipart:
                require(path.stat().st_size==part["bytes"] and path.stat().st_size<=manifest["maximum_part_bytes"],
                        "archive part byte size changed")
            archive=zipfile.ZipFile(path)
            archives[name]=archive
            actual=archive.namelist()
            require(len(set(actual))==len(actual),"duplicate ZIP entry")
            require(set(actual)==expected,"ZIP membership changed")
            for member in members:
                payload=archive.read(member)
                entry=file_map[member]
                require(len(payload)==entry["bytes"] and sha256(payload)==entry["sha256"],
                        "new campaign archive entry changed")
                entry_archives[member]=name
        require(set(entry_archives)==set(file_map),"logical archive membership changed")
        combined=_ArchiveParts(archives,entry_archives)
        success=True
        return combined.read,combined.namelist(),combined
    finally:
        if not success:
            for archive in archives.values():
                archive.close()


def replay_operational_attempt(data,nominal,saved,attempt):
    """Replay retained transport and acceptance, including typed failed LPs."""
    require(_plain(data.realized_scenario)==saved["realization"],"scenario realization changed")
    run=saved["operational_run"]
    solver=run["solver_evidence"]["result"]
    scientific=run["scientific_evidence"]
    require(attempt["solver_status"]==solver["status"],"solver status changed")
    require(attempt["stage2_status"]==run["status"],"operational classification changed")
    solution=report=comparison=None
    expected_status=None
    if run["raw_solution"] is not None:
        require(solver["has_incumbent"] and solver["objective_value"] is not None,
                "raw transport has no solver incumbent")
        raw=RawStage2Solution(mapping(run["raw_solution"]["x"]),mapping(run["raw_solution"]["u"]))
        try:
            solution=normalize_raw_stage2_solution(raw,data,
                SolutionNormalizationTolerances(**scientific["normalization_tolerances"]))
        except Stage2SolutionNormalizationError as error:
            expected_status="normalization_failed"
            require(run["failure"] is not None and run["failure"]["error_type"]==type(error).__name__,
                    "normalization failure changed")
        require(_plain(solution)==run["solution"],"raw transport normalization changed")
    else:
        require(run["solution"] is None,"normalized solution has no raw transport")
        if not solver["has_incumbent"] or solver["objective_value"] is None:
            expected_status="solver_no_usable_solution"
        else:
            expected_status="extraction_failed"
    if solution is not None:
        require(solver["has_incumbent"] and solver["objective_value"] is not None,
                "transported solution has no solver incumbent")
        report=validate_stage2_solution(data,solution,
            Stage2ValidationTolerances(**scientific["validation_tolerances"]))
        if not report.is_feasible:
            expected_status="validation_failed"
        else:
            recorded=scientific["objective_comparison"]
            require(recorded is not None,"feasible solution has no objective comparison")
            comparison=ObjectiveComparison(solver["objective_value"],report.objective_breakdown.operational_objective,
                recorded["absolute_tolerance"],recorded["relative_tolerance"])
            expected_status="success" if comparison.agrees else "objective_inconsistent"
    require(_plain(report)==scientific["validation_report"],"new operational report changed")
    require(_plain(comparison)==scientific["objective_comparison"],"native/independent objective evidence changed")
    require(expected_status==run["status"],"failed LP boundary changed")
    feasible=report is not None and report.is_feasible
    new_usable=feasible and comparison is not None and comparison.agrees
    old_usable=feasible and comparison is not None and ObjectiveComparison(
        comparison.solver_objective,comparison.independent_objective,comparison.absolute_tolerance).agrees
    require(attempt["independently_feasible"]==feasible,"operational feasibility changed")
    require(attempt["new_usable"]==new_usable and attempt["old_usable"]==old_usable,
            "old/new objective acceptance changed")
    require(attempt["solver_objective"]==(comparison.solver_objective if comparison else None),
            "attempt solver objective changed")
    require(attempt["independent_objective"]==(comparison.independent_objective if comparison else None),
            "attempt independent objective changed")
    costs=report.objective_breakdown if report else None
    require(attempt["adapted_cost_usd"]==(costs.operational_objective if costs else None),
            "operational independent cost changed")
    if comparison is not None:
        require(attempt["absolute_tolerance"]==comparison.absolute_tolerance,"attempt objective policy changed")
    expected_quality={**service_observations(data.instance,data.realized_scenario,solution,nominal),
        "c3_usd":costs.realized_data_storage_cost,"c4_usd":costs.delay_penalty,
        "c5_usd":costs.unmet_demand_penalty} if new_usable else None
    require(attempt["quality"]==expected_quality,"service/cost observations changed")
    recorded_certificates=saved["sufficient_infeasibility_certificates"]
    expected_certificates=certificates(data) if solver["status"]=="infeasible" else []
    require(recorded_certificates==expected_certificates,"infeasibility certificates changed")
    require(attempt["certificate_families"]==sorted({item["family"] for item in recorded_certificates}),
            "certificate family observations changed")
    return report is not None


def analyze(output,revalidate=False):
    read,names,archive=delivered_reader(output)
    try:
        config=read_json(output/"config.json")
        jobs=planned_jobs(config)
        results=[]
        rows=[]
        validation_counts=Counter()
        for job in jobs:
            base="jobs/"+job["id"]
            if base+"/result.json" not in names:
                continue
            result=json.loads(read(base+"/result.json"))
            results.append(result)
            if revalidate:
                for interrupted in result.get("interrupted_attempts",[]):
                    require(sha256(read(base+"/"+interrupted["retained_path"]))==interrupted["sha256"],
                            "interrupted evidence replay changed")
                    require(sha256(read(base+"/"+interrupted["metadata_path"]))==interrupted["metadata_sha256"],
                            "interrupted provenance replay changed")
            if revalidate and base+"/stage1.json.gz" in names:
                instance=seeded_instance(tuple(job["shape"]),job["load"],job["instance_seed"],config["instance_amplitude"])
                input_bytes=read(base+"/instance.json.gz")
                require(sha256(input_bytes)==result["instance_sha256"],"new input checkpoint changed")
                require(_plain(instance)==json.loads(gzip.decompress(input_bytes)),"new input replay changed")
                source_bytes=read(base+"/stage1.json.gz")
                require(sha256(source_bytes)==result["stage1_evidence_sha256"],"new source checkpoint changed")
                source=json.loads(gzip.decompress(source_bytes))
                require(source["accepted"]==result["stage1_accepted"],"source acceptance checkpoint changed")
                if source["placement"] is None or source["validation"] is None:
                    require(not source["accepted"] and not result["attempts"],
                            "source without placement/report has usable results")
                    validation_counts["sources_without_complete_placement"]+=1
                    continue
                nominal=saved_placement(source["placement"])
                source_report=validate_placement(instance,nominal,PaperVersion.V2,tolerances=ValidationTolerances(**source["validation"]["tolerances"]))
                require(_plain(source_report)==source["validation"],"new source replay changed")
                require(not result["stage1_accepted"] or source_report.is_feasible,"accepted source replay infeasible")
                validation_counts["sources"]+=1
                if not result["stage1_accepted"]:
                    require(not result["attempts"],"rejected source has operational attempts")
                    continue
                fixed=Stage2FixedDeployment(nominal.admission_indicators,nominal.configuration_selectors,nominal.gpu_counts)
                problem=PdmProblemData(instance)
                scenarios=tuple(iter_stress_scenarios(instance,StressGrid(tuple(config["arrival_factors"]),tuple(config["stress_factors"]))))
                for attempt in result["attempts"]:
                    payload=read(base+"/"+attempt["evidence"])
                    require(sha256(payload)==attempt["evidence_sha256"],"scenario evidence pointer changed")
                    saved=json.loads(gzip.decompress(payload))
                    data=Stage2ProblemData(problem,fixed,scenarios[attempt["index"]][2])
                    frozen=Stage2Solution(stage2_solution_identity(data),nominal.routing_fractions,nominal.unmet_fractions)
                    frozen_report=validate_stage2_solution(data,frozen)
                    require(_plain(frozen_report)==saved["frozen_routing_validation"],"new frozen report changed")
                    require(attempt["frozen_feasible"]==frozen_report.is_feasible,"frozen feasibility changed")
                    require(attempt["frozen_cost_usd"]==(frozen_report.objective_breakdown.operational_objective if frozen_report.is_feasible else None),"frozen usable cost changed")
                    validation_counts["frozen"]+=1
                    if replay_operational_attempt(data,nominal,saved,attempt):
                        validation_counts["operational"]+=1
            for attempt in result["attempts"]:
                rows.append({**attempt,"job":job["id"],"input_id":job["input_id"],"shape":job["shape"],
                    "load":job["load"],"instance_seed":job["instance_seed"],"method":job["method"]})
        inputs=defaultdict(dict)
        for result in results:
            inputs[result["input_id"]][result["method"]]=result
        matched=sorted(identity for identity,methods in inputs.items() if set(methods)==set(config["methods"])
                       and all(result["stage1_accepted"] for result in methods.values()))
        for identity,methods in inputs.items():
            require(len({r["instance_sha256"] for r in methods.values()})==1,"methods received different prepared input bytes")
        # Shared-input clusters preserve covariance across methods in pooled results.
        pooled=[{**row,"job":row["input_id"]} for row in rows]
        summary={"classification":config["classification"],"planned_sources":len(jobs),"completed_sources":sum(r["complete"] for r in results),
            "accepted_sources":sum(bool(r["stage1_accepted"]) for r in results),"attempted_lps":len(rows),
            "status_counts":dict(Counter(r["stage2_status"] for r in rows)),"accepted_input_intersection":matched,
            "matched_input_count":len(matched),"source_input_count":len(inputs),"replay_verification":dict(validation_counts),
            "ranking_policy":"no unmatched method rankings; conditional feasibility/cost denominators remain explicit",
            "by_load":{str(load):summarize([r for r in pooled if r["load"]==load],config["stage2_objective_relative_tolerance"],
                config["bootstrap_rounds"],config["bootstrap_seed"]) for load in config["loads"]},
            "by_method_on_matched_inputs":{method:{str(load):summarize([r for r in rows if r["method"]==method and r["load"]==load and r["input_id"] in matched],
                config["stage2_objective_relative_tolerance"],config["bootstrap_rounds"],config["bootstrap_seed"])
                for load in config["loads"]} for method in config["methods"]},
            "infeasibility_certificate_counts":dict(Counter(family for row in rows for family in row["certificate_families"]))}
        save_json(output/("replay_analysis.json" if revalidate else "analysis.json"),summary)
        save_json(output/"source_results.json",[{name:result[name] for name in result if name!="attempts"} for result in results])
        with (output/"attempts.csv").open("w",newline="",encoding="utf-8") as stream:
            columns=("job","method","load","instance_seed","index","arrival_factor","stress_factor","stage2_status","solver_status","new_usable","frozen_feasible","frozen_cost_usd","adapted_cost_usd","integrated_seconds")
            writer=csv.DictWriter(stream,fieldnames=columns)
            writer.writeheader()
            writer.writerows({name:row[name] for name in columns} for row in rows)
        if not revalidate:
            make_plots(output,summary)
            report=["# Matched synthetic Stage-2 extension", "",f"Completed sources: {summary['completed_sources']}/{len(jobs)}; accepted: {summary['accepted_sources']}/{len(results)}. Attempted LPs: {len(rows)}.","",
                "| Nominal load | Usable / attempted | Recovery / frozen failures | Paired scenarios | C4+C5 paired reduction | 95% shared-input cluster bootstrap |",
                "|---|---:|---:|---:|---:|---|"]
            for load,item in summary["by_load"].items():
                reduction=item["paired_reduction_fraction"]
                report.append(f"| {load} | {item['usable']}/{item['attempted']} | {item['recovered']}/{item['frozen_failures']} | {item['paired_scenarios']} | {reduction:.6%} | {item['source_cluster_bootstrap']['ci95']} |" if reduction is not None else f"| {load} | {item['usable']}/{item['attempted']} | {item['recovered']}/{item['frozen_failures']} | 0 | unavailable | unavailable |")
            report += ["",f"Accepted-source intersection: {len(matched)}/{len(inputs)} prepared input identities. All methods share exact input hashes; acceptance can still differ.","",
                "No infeasible baseline receives cost savings. Pooled by_load summaries can include unmatched accepted inputs; only by_method_on_matched_inputs uses the accepted-source intersection. Bootstrap resamples contributing shared-input clusters of usable pairs, preserving available shared-method dependence. Report each paired-source-grid count as the contributing input-cluster count. A one-cluster interval is degenerate and supports no precision claim. These are conditional synthetic intervals, not real-world probabilities or rankings.","",
                "The historical diagnosis records sufficient contradiction certificates and their supporting demand caps/balance; overlaps are permitted and unresolved cases stay explicit. No unique IIS is claimed.","",
                "Raw failures and decisions are retained in the ZIP archive(s) listed in evidence_manifest.json, with exact membership and per-entry/per-part hashes. The measured producer and scientific sources remain frozen in scientific-source-snapshot.zip; multipart archive transport and this report wording are separate post-processing, with the helper fingerprint recorded in the evidence manifest. Scientific observations, decisions and numerical arithmetic are unchanged. Replay: `python scripts/run_stage2_extension.py --output benchmarks/stage2_robustness_2026-10-14 --replay`."]
            (output/"README.md").write_text("\n".join(report)+"\n",encoding="utf-8")
        print(json.dumps({name:summary[name] for name in ("completed_sources","accepted_sources","attempted_lps","matched_input_count")}))
        return summary
    finally:
        if archive:
            archive.close()


def make_plots(output,summary):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    (output/"plots").mkdir(exist_ok=True)
    fig,axes=plt.subplots(1,2,figsize=(11,4),layout="constrained")
    loads=list(summary["by_load"])
    items=list(summary["by_load"].values())
    for index,item in enumerate(items):
        if item["recovery_fraction"] is not None:
            axes[0].bar(index,100*item["recovery_fraction"],color="#245b9c")
            axes[0].text(index,100*item["recovery_fraction"],f"{item['recovered']}/{item['frozen_failures']}",ha="center",va="bottom",fontsize=8)
        if item["paired_reduction_fraction"] is not None:
            point=100*item["paired_reduction_fraction"]
            lower,upper=item["source_cluster_bootstrap"]["ci95"]
            axes[1].errorbar(index,point,yerr=[[max(0,point-100*lower)],[max(0,100*upper-point)]],fmt="o",capsize=4,color="#245b9c")
    for axis in axes:
        axis.set_xticks(range(len(loads)),[f"{float(load):g}" for load in loads])
        axis.set_xlabel("Nominal synthetic load multiplier")
    axes[0].set_ylabel("Recovered frozen failures (%)")
    axes[1].set_ylabel("Paired C4+C5 reduction (%)")
    axes[1].set_title("95% shared-input cluster bootstrap")
    for extension in ("png","svg"):
        fig.savefig(output/"plots"/f"per_load.{extension}",dpi=180)
    plt.close(fig)


def package(output,*,raw_payload_budget=70_000_000,maximum_part_bytes=80_000_000):
    """Repack the exact measured raw tree into conservatively bounded ZIP parts."""
    require(0<raw_payload_budget<maximum_part_bytes,"invalid ZIP part budgets")
    raw=output/"raw"
    entries=[]
    groups=[]
    group=[]
    payload_bytes=0
    for path in sorted(raw.rglob("*")):
        if not path.is_file():
            continue
        size=path.stat().st_size
        require(size<=raw_payload_budget,"raw file exceeds ZIP payload budget")
        if group and payload_bytes+size>raw_payload_budget:
            groups.append(group)
            group=[]
            payload_bytes=0
        group.append(path)
        payload_bytes+=size
    if group:
        groups.append(group)
    require(groups,"raw evidence tree is empty")
    parts=[]
    for index,paths in enumerate(groups,1):
        name=f"evidence-part-{index:03d}.zip"
        destination=output/name
        pending=destination.with_suffix(destination.suffix+".pending")
        members=[]
        with zipfile.ZipFile(pending,"w",zipfile.ZIP_DEFLATED) as archive:
            for path in paths:
                member=path.relative_to(raw).as_posix()
                valid_entry_name(member)
                payload=path.read_bytes()
                entries.append({"path":member,"bytes":len(payload),"sha256":sha256(payload),"archive":name})
                archive.writestr(member,payload)
                members.append(member)
        require(pending.stat().st_size<=maximum_part_bytes,"ZIP part exceeds byte limit")
        pending.replace(destination)
        parts.append({"path":name,"bytes":destination.stat().st_size,"sha256":sha256(destination.read_bytes()),
                      "file_count":len(members),"members":members})
    source_path=output/"scientific-source-snapshot.zip"
    snapshot=None
    if (raw/"campaign_manifest.json").is_file():
        require(source_path.is_file(),"frozen measured source archive is missing")
    if source_path.is_file():
        snapshot={"path":source_path.name,"sha256":sha256(source_path.read_bytes())}
        measured=read_json(raw/"campaign_manifest.json")
        with zipfile.ZipFile(source_path) as archive:
            names=archive.namelist()
            require(len(set(names))==len(names),"duplicate frozen source entry")
            require(set(names)==set(measured["source_sha256"])|{"config.json"},"frozen measured source membership changed")
            require(all(sha256(archive.read(name))==expected for name,expected in measured["source_sha256"].items()),
                    "frozen measured source bytes changed")
            require(archive.read("config.json")== (output/"config.json").read_bytes(),"frozen measured configuration changed")
    manifest={"format_version":2,"archive_format":"multipart_zip","raw_payload_budget_bytes":raw_payload_budget,
        "maximum_part_bytes":maximum_part_bytes,"archives":parts,"file_count":len(entries),
        "uncompressed_bytes":sum(entry["bytes"] for entry in entries),"files":entries,
        "measured_source_snapshot":snapshot,"post_processing":{
            "helper_sha256":sha256(Path(__file__).read_bytes()),"scope":"archive transport/report text only; measured source and numerical observations unchanged"}}
    save_json(output/"evidence_manifest.json",manifest)
    _,_,verified=delivered_reader(output)
    verified.close()
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--diagnose-original",action="store_true")
    parser.add_argument("--run",action="store_true")
    parser.add_argument("--resume",action="store_true")
    parser.add_argument("--analyze",action="store_true")
    parser.add_argument("--replay",action="store_true")
    parser.add_argument("--package",action="store_true",help="post-process measured raw bytes into bounded ZIP parts")
    args=parser.parse_args()
    output=args.output.resolve()
    require((output/"PLAN.md").is_file(),"write PLAN.md before campaign execution")
    if args.diagnose_original:
        historical_diagnosis(output)
    if args.run:
        run_campaign(output,args.resume)
        package(output)
    elif args.package:
        package(output)
    if args.analyze or args.replay:
        analyze(output,revalidate=args.replay)


if __name__=="__main__":
    main()
