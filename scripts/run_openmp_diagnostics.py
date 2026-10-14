"""Opt-in, checkpointed OpenMP diagnostics; run from a Linux/WSL shell."""
import argparse
import gzip
import hashlib
import itertools
import json
import os
from pathlib import Path
import shutil
from statistics import median
import subprocess
import sys
from time import perf_counter
import zipfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from extension_statistics import paired_ratio_bootstrap, timing_summary
from profile_openmp import campaign_workloads
from check_cpp_parity import serialize_case
from check_cpp_parity import decode_placement, objective_array
from llm_resource_allocation.validation.placement import validate_placement

def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".pending")
    temp.write_text(json.dumps(value, indent=2, allow_nan=False)+"\n")
    temp.replace(path)

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def configurations(cpu_count, matrix="full"):
    base = [dict(threads=t, places=p, bind=b, schedule=s, chunk=c,
                 sorted=False, arena=None)
            for t,p,b,s,c in itertools.product(range(1,cpu_count+1),
                ("cores","threads"),("close","spread"),
                ("static","dynamic","guided"),(1,2,4))]
    extra = [dict(threads=t, places="cores", bind="close",schedule="dynamic",
                  chunk=1, sorted=sort, arena=arena)
             for t,sort,arena in itertools.product((1,8,cpu_count),(False,True),(None,1))
             if sort or arena]
    if matrix=="oat":
        # Observe every requested level; do not claim unmeasured interactions.
        base=[c for c in base if (c["places"]=="cores" and c["bind"]=="close")
              or (c["schedule"]=="dynamic" and c["chunk"]==1)]
    return base+extra

def key(c):
    return "_".join(str(c[x]) for x in ("threads","places","bind","schedule","chunk","sorted","arena"))

def measure(binary, manifest, config, warmup=False, evidence="-"):
    env={**os.environ,"OMP_DYNAMIC":"FALSE","OMP_PLACES":config["places"],
         "OMP_PROC_BIND":config["bind"]}
    if config["arena"]: env["MALLOC_ARENA_MAX"]=str(config["arena"])
    command=[str(binary),str(config["threads"]),config["schedule"],str(config["chunk"]),
             "warm" if warmup else "0",str(evidence)]
    start=perf_counter()
    process=subprocess.run(command,input=manifest.read_text(),text=True,capture_output=True,
                           env=env,timeout=180)
    wall=perf_counter()-start
    result=dict(command=command,environment={k:env[k] for k in env if k.startswith("OMP_") or k=="MALLOC_ARENA_MAX"},
                returncode=process.returncode,invocation_seconds=wall,stderr=process.stderr)
    if process.returncode: result["stdout"]=process.stdout
    else: result.update(json.loads(process.stdout))
    return result

def prepare(out):
    if (out/"preparation_complete.json").exists():
        verify(out)
        preparation=json.loads((out/"preparation_complete.json").read_text())
        for relative,expected in preparation["files"].items():
            if digest(out/relative)!=expected: raise ValueError(f"immutable pilot/golden changed: {relative}")
        return ROOT/"cpp/build/extension/openmp_diagnostics",out/"inputs/manifest.txt"
    cases=campaign_workloads(32)["mixed"]
    inputs=out/"inputs"; inputs.mkdir(parents=True,exist_ok=True)
    lines=[f"PACS_CAMPAIGN 1 {len(cases)}"]
    for i,case in enumerate(cases):
        path=inputs/f"{i:03d}.txt"; path.write_text(serialize_case(case))
        lines.append(f'{case.method} "{case.name}" "{path.relative_to(ROOT).as_posix()}"')
    manifest=inputs/"manifest.txt"; manifest.write_text("\n".join(lines)+"\n")
    binary=ROOT/"cpp/build/extension/openmp_diagnostics"; binary.parent.mkdir(parents=True,exist_ok=True)
    sources=[ROOT/"cpp/src"/f"{s}.cpp" for s in ("core","gh","agh","io")]+[ROOT/"cpp/experiments/openmp_diagnostics.cpp"]
    cmd=["g++","-std=c++20","-O2","-g","-ffp-contract=off","-Wall","-Wextra","-Wpedantic","-fopenmp","-Icpp/include",*[str(p) for p in sources],"-o",str(binary)]
    result=subprocess.run(cmd,cwd=ROOT,text=True,capture_output=True)
    save(out/"build.json",dict(command=cmd,returncode=result.returncode,stdout=result.stdout,stderr=result.stderr))
    result.check_returncode()
    python_sources=[*sorted((ROOT/"src/llm_resource_allocation/domain").glob("*.py")),
        *sorted((ROOT/"src/llm_resource_allocation/math").glob("*.py")),
        *[ROOT/"src/llm_resource_allocation"/p for p in
          ("validation/placement.py","validation/tolerances.py","optimization/problem_data.py",
           "data/scaling_experiment_instances.py","data/tiny_instances.py","data/synthetic_benchmark_instances.py")],
        *[ROOT/"scripts"/p for p in ("profile_openmp.py","check_cpp_parity.py","check_openmp_campaign.py","extension_statistics.py")]]
    files=[*sources,*python_sources,*sorted((ROOT/"cpp/include").rglob("*.hpp")),
        *[p for p in inputs.glob("*.txt") if p.name!="manifest_sorted.txt"],Path(__file__),binary]
    save(out/"hashes.json",{p.relative_to(ROOT).as_posix():digest(p) for p in files})
    return binary,manifest

def verify(out, require_binary=True):
    for relative,expected in json.loads((out/"hashes.json").read_text()).items():
        if relative.startswith("cpp/build/") and not require_binary: continue
        if digest(ROOT/relative)!=expected: raise ValueError(f"frozen measurement input/source changed: {relative}")
    if (out/"artifact_hashes.json").exists():
        for relative,expected in json.loads((out/"artifact_hashes.json").read_text()).items():
            if digest(out/relative)!=expected: raise ValueError(f"retained evidence changed: {relative}")

def unpack(out):
    if (out/"evidence.zip").exists() and not (out/"raw").exists():
        manifest=json.loads((out/"evidence_manifest.json").read_text())
        if digest(out/"evidence.zip")!=manifest["archive_sha256"]: raise ValueError("archive hash changed")
        with zipfile.ZipFile(out/"evidence.zip") as z:
            for item in manifest["files"]:
                path=(out/item["path"]).resolve()
                if not path.is_relative_to(out.resolve()): raise ValueError("archive path escapes campaign")
                data=z.read(item["path"])
                if hashlib.sha256(data).hexdigest()!=item["sha256"]: raise ValueError("archive entry changed")
                path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(data)

def analyze(out, plots=True):
    unpack(out)
    verify(out,require_binary=False)
    plan=json.loads((out/"configuration.json").read_text()); configs=plan["configurations"]
    observations={key(c):{} for c in configs}
    failures=[]
    for path in sorted((out/"raw").glob("*.json")):
        if path.with_suffix(".sha256").read_text().strip()!=digest(path): raise ValueError("raw checkpoint hash changed")
        r=json.loads(path.read_text())
        if r.get("returncode") or not r.get("projection_fingerprints_match"):
            failures.append(str(path.relative_to(out))); continue
        observations[r["configuration_key"]][r["round"]]=r
    rows=[]
    for c in configs:
        k=key(c); samples=observations[k]
        if not samples: continue
        teams={r["actual_threads"] for r in samples.values()}
        if teams!={c["threads"]}: raise ValueError(f"observed team differs or changes: {k}, {teams}")
        baseline=key({**c,"threads":1})
        if baseline not in observations: baseline=key({**c,"threads":1,"sorted":False,"arena":None})
        paired=sorted(samples.keys() & observations[baseline].keys())
        speed=paired_ratio_bootstrap([observations[baseline][i]["core_seconds"] for i in paired],
               [samples[i]["core_seconds"] for i in paired],resamples=2000) if len(paired)>1 else None
        idle=[1-sum(r["busy_seconds"])/(r["actual_threads"]*r["core_seconds"]) for r in samples.values()]
        imbalance=[(max(r["busy_seconds"])-sum(r["busy_seconds"])/r["actual_threads"])/r["core_seconds"] for r in samples.values()]
        fraction=(c["threads"]/speed["ratio_of_medians"]-1)/(c["threads"]-1) if speed and c["threads"]>1 else None
        rows.append(dict(configuration=c,key=k,timing=timing_summary([r["core_seconds"] for r in samples.values()]),
            speedup=speed,idle_fraction_median=median(idle),imbalance_fraction_median=median(imbalance),
            amdahl_equivalent_serial_fraction=fraction,
            non_imbalance_idle_fraction=max(0,median(idle)-median(imbalance))))
        if c["sorted"] or c["arena"]:
            control=observations[key({**c,"sorted":False,"arena":None})]
            pairs=sorted(samples.keys() & control.keys())
            rows[-1]["intervention_speedup_vs_same_team_control"]=paired_ratio_bootstrap(
                [control[i]["core_seconds"] for i in pairs],
                [samples[i]["core_seconds"] for i in pairs],resamples=2000) if len(pairs)>1 else None
    save(out/"analysis/summary.json",dict(rows=rows,failed_samples=failures,
        approximation="Amdahl fraction includes all overhead, not measured serial code; busy is wall time inside each job; idle includes startup/barriers; remainder is not causal attribution"))
    if rows and plots:
        import matplotlib; matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig,ax=plt.subplots(figsize=(8,5))
        for s in ("static","dynamic","guided"):
            selected=sorted((r for r in rows if r["configuration"]=={**r["configuration"],"places":"cores","bind":"close","schedule":s,"chunk":1,"sorted":False,"arena":None} and r["speedup"]),key=lambda r:r["configuration"]["threads"])
            xs=[r["configuration"]["threads"] for r in selected]; ys=[r["speedup"]["ratio_of_medians"] for r in selected]
            ax.errorbar(xs,ys,yerr=[[y-r["speedup"]["ci95_low"] for r,y in zip(selected,ys)],[r["speedup"]["ci95_high"]-y for r,y in zip(selected,ys)]],marker="o",label=s)
        ax.set(xlabel="Observed WSL team",ylabel="Core ratio of medians vs same-setting team 1",title="32 synthetic mixed cases; paired-round bootstrap 95% CI")
        ax.legend(); fig.tight_layout(); (out/"plots").mkdir(exist_ok=True)
        for suffix in ("svg","png"): fig.savefig(out/f"plots/speedup.{suffix}")
    return rows

def inventory(out):
    save(out/"artifact_hashes.json",{p.relative_to(out).as_posix():digest(p)
          for p in sorted(out.rglob("*")) if p.is_file() and p.name!="artifact_hashes.json"})

def package(out):
    records=[]
    with zipfile.ZipFile(out/"evidence.zip","w",zipfile.ZIP_DEFLATED) as archive:
        for directory in ("raw","golden"):
            for p in sorted((out/directory).rglob("*")):
                if not p.is_file(): continue
                relative=p.relative_to(out).as_posix(); archive.write(p,relative)
                records.append(dict(path=relative,sha256=digest(p),bytes=p.stat().st_size))
    save(out/"evidence_manifest.json",dict(archive_sha256=digest(out/"evidence.zip"),files=records))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,default=ROOT/"benchmarks/openmp_diagnostics_2026-10-14")
    parser.add_argument("--analyze",action="store_true"); parser.add_argument("--rounds",type=int,default=30)
    parser.add_argument("--pilot-only",action="store_true")
    parser.add_argument("--matrix",choices=("full","oat"),default="oat")
    args=parser.parse_args(); out=args.output.resolve(); os.chdir(ROOT)
    if args.analyze: analyze(out,plots=False); return
    if not (out/"PLAN.md").exists(): raise ValueError("write PLAN.md first")
    binary,manifest=prepare(out); configs=configurations(os.cpu_count(),args.matrix)
    specification=dict(rounds=args.rounds,matrix=args.matrix,configurations=configs)
    if (out/"raw").exists() and json.loads((out/"configuration.json").read_text())!=specification:
        raise ValueError("resume cannot change configuration or round count")
    save(out/"configuration.json",specification)
    golden=out/"golden"; golden.mkdir(exist_ok=True)
    if (out/"pilot.json").exists(): pilot=json.loads((out/"pilot.json").read_text())
    else:
        pilot=measure(binary,manifest,configs[0],True,golden)
        save(out/"pilot.json",pilot)
    if pilot["returncode"]: raise RuntimeError("pilot failed")
    if not (out/"golden_validation.json").exists():
        validations=[]
        for i,case in enumerate(campaign_workloads(32)["mixed"]):
            actual=json.loads((golden/f"{i}.json").read_text())
            placement=decode_placement(case.instance,actual["placement"])
            report=validate_placement(case.instance,placement,case.version)
            independent=objective_array(report.objective_breakdown)
            if [float(x).hex() for x in independent]!=[float(x).hex() for x in actual["objective"]]:
                raise ValueError("golden objective differs bitwise from independent Python validator")
            if report.is_feasible!=actual["feasible"]: raise ValueError("golden independent feasibility differs")
            validations.append(dict(case=case.name,independently_feasible=report.is_feasible,objective_bitwise_equal=True))
        save(out/"golden_validation.json",validations)
    # Timed work scaling plus warmups and measured invocation overhead; sorting adds serial warmup.
    if (out/"measurement_pilot.json").exists(): measurement_pilot=json.loads((out/"measurement_pilot.json").read_text())
    else:
        measurement_pilot=measure(binary,manifest,configs[0])
        save(out/"measurement_pilot.json",measurement_pilot)
    if measurement_pilot["returncode"]: raise RuntimeError("measurement pilot failed")
    overhead=max(0,measurement_pilot["invocation_seconds"]-measurement_pilot["core_seconds"])
    # Known sublinear scaling: budget at 50% efficiency, capped at serial time.
    pilot_core=max(pilot["core_seconds"],measurement_pilot["core_seconds"])
    forecast=lambda c: min(pilot_core,2*pilot_core/c["threads"])
    estimate=sum(args.rounds*(forecast(c)+overhead)+pilot["core_seconds"] for c in configs)
    full_estimate=sum(args.rounds*(forecast(c)+overhead)+pilot["core_seconds"] for c in configurations(os.cpu_count(),"full"))
    permutation=sorted(range(len(pilot["job_seconds"])),key=lambda i:-pilot["job_seconds"][i])
    sorted_manifest=manifest.with_name("manifest_sorted.txt")
    lines=manifest.read_text().splitlines()
    sorted_manifest.write_text("\n".join([lines[0],*[lines[1+i] for i in permutation]])+"\n")
    save(out/"cost_ordering.json",dict(original_indices=permutation,pilot_job_seconds=pilot["job_seconds"]))
    availability={}
    for name,cmd in {"lscpu":["lscpu"],"topology":["lscpu","-e=CPU,CORE,SOCKET,NODE"],"perf":["perf","stat","true"]}.items():
        if not shutil.which(cmd[0]): availability[name]="executable unavailable";continue
        p=subprocess.run(cmd,capture_output=True,text=True);availability[name]=dict(returncode=p.returncode,stdout=p.stdout,stderr=p.stderr)
    for name,path in {"governor":"/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor","frequency":"/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq","temperature":"/sys/class/thermal/thermal_zone0/temp"}.items():
        availability[name]=Path(path).read_text().strip() if Path(path).exists() else "unavailable in WSL"
    save(out/"environment.json",dict(python=sys.version,logical_cpus=os.cpu_count(),availability=availability,
         host_power_plan="Windows Balanced (observed before preparation)",closed_apps="not verified; no apps forcibly closed",estimated_seconds=estimate,
         full_matrix_estimated_seconds=full_estimate,
         estimate_method="pilot one-team at assumed 50% parallel efficiency capped at serial time plus observed invocation overhead; one excluded warmup per configuration"))
    frozen=[out/p for p in ("hashes.json","build.json","configuration.json","pilot.json",
        "measurement_pilot.json","golden_validation.json","cost_ordering.json","inputs/manifest_sorted.txt")]
    frozen += list(golden.glob("*.json"))
    save(out/"preparation_complete.json",dict(validated_goldens=32,input_files=32,matrix=args.matrix,
         files={p.relative_to(out).as_posix():digest(p) for p in frozen}))
    print(f"Estimated {estimate/3600:.2f} h for {len(configs)} settings × {args.rounds} rounds",flush=True)
    if args.pilot_only or estimate>10800:
        save(out/"execution.json",dict(status="pilot_only" if args.pilot_only else "skipped_over_three_hours",estimated_seconds=estimate));return
    reference=pilot["fingerprints"]
    started=perf_counter()
    for round_no in range(args.rounds):
        rotation=round_no%len(configs); rotated=configs[rotation:]+configs[:rotation]
        if round_no%2: rotated=list(reversed(rotated))
        for c in rotated:
            if perf_counter()-started>10800:
                save(out/"execution.json",dict(status="wall_budget_reached",rounds_finished=round_no)); analyze(out); inventory(out); return
            path=out/"raw"/f"{round_no:02d}_{key(c)}.json"
            if path.exists():
                if path.with_suffix(".sha256").read_text().strip()!=digest(path): raise ValueError("raw checkpoint changed on resume")
                continue
            try: r=measure(binary,sorted_manifest if c["sorted"] else manifest,c,round_no==0)
            except subprocess.TimeoutExpired as e:
                partial={}
                for name,data in (("stdout",e.stdout),("stderr",e.stderr)):
                    target=path.with_suffix(f".{name}.partial")
                    target.parent.mkdir(parents=True,exist_ok=True)
                    target.write_bytes(data if isinstance(data,bytes) else (data or "").encode())
                    partial[name]=dict(path=target.relative_to(out).as_posix(),sha256=digest(target))
                r=dict(returncode=-1,error="timeout",partial_output=partial)
            r.update(round=round_no,configuration_key=key(c),configuration=c,
                     projection_fingerprints_match=r.get("fingerprints")==([reference[i] for i in permutation] if c["sorted"] else reference),
                     recorded_utc=datetime.now(timezone.utc).isoformat())
            save(path,r)
            path.with_suffix(".sha256").write_text(digest(path)+"\n")
        print(f"Completed round {round_no+1}/{args.rounds}",flush=True)
    analyze(out); save(out/"execution.json",dict(status="complete",rounds=args.rounds)); package(out); inventory(out)

if __name__=="__main__": main()
