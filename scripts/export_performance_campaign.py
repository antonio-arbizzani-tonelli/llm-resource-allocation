"""Export measured campaign evidence with explicit portable-path provenance.

Scientific numbers and unchanged evidence files keep their original bytes.
Only local path prefixes in metadata/manifests/logs are replaced. Hash pointers
to transformed files are refreshed and original/portable digests are retained.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile

from analyze_performance_campaign import analyze


def sha(payload):
    return hashlib.sha256(payload).hexdigest()


def portable_string(value, workspace):
    windows = str(workspace)
    posix = workspace.as_posix()
    prefixes = [windows, posix]
    if len(posix) > 2 and posix[1] == ":":
        prefixes.append("/mnt/" + posix[0].lower() + posix[2:])
    for prefix in sorted(set(prefixes), key=len, reverse=True):
        value = value.replace(prefix, "<workspace>")
    value = re.sub(r"[A-Za-z]:[\\/]+Users[\\/]+[^\\/]+", "<user-home>", value)
    value = re.sub(r"/mnt/[a-z]/Users/[^/]+", "<user-home>", value)
    return value.replace("\\", "/") if "<workspace>" in value or "<user-home>" in value else value


def portable(value, workspace):
    if isinstance(value, dict):
        result = {portable_string(key, workspace): portable(item, workspace) for key, item in value.items()}
        if isinstance(result.get("linux_environment"), str):
            result["linux_environment"] = re.sub(r"^Linux \S+ ", "Linux <host> ", result["linux_environment"])
        return result
    if isinstance(value, list):
        return [portable(item, workspace) for item in value]
    return portable_string(value, workspace) if isinstance(value, str) else value


def export(source, destination, workspace):
    # Verify complete job evidence before creating any publication files.
    analyze(source)
    destination.mkdir(parents=True, exist_ok=False)
    records = {}
    paths = [path for path in source.rglob("*") if path.is_file()
             and not path.is_relative_to(source / "snapshot") and path.suffix != ".pending"]
    for path in sorted(paths):
        name = path.relative_to(source).as_posix()
        original = path.read_bytes()
        payload = original
        if path.suffix == ".json":
            value = json.loads(original)
            converted = portable(value, workspace)
            if converted != value:
                payload = (json.dumps(converted, indent=2, allow_nan=False) + "\n").encode()
        elif path.suffix in (".txt", ".log", ".md", ".csv"):
            converted = portable_string(original.decode("utf-8"), workspace)
            if converted != original.decode("utf-8"):
                payload = converted.encode()
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        records[name] = {"path": name, "original_sha256": sha(original), "portable_sha256": sha(payload),
                         "transformation": "local path/host labels replaced" if payload != original else "unchanged bytes"}

    # Preserve the original scientific sources for exact historical inspection.
    # Build products and the private development-document test are excluded.
    snapshot = source / "snapshot"
    archive_path = destination / "scientific-source-snapshot.zip"
    publication_config = workspace / "configs/publication.json"
    allowed = {item["path"] for item in json.loads(publication_config.read_text(encoding="utf-8"))["files"]}
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(snapshot.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts or path.is_relative_to(snapshot / "cpp/build"):
                continue
            if path.name == "test_scientific_spec.py" or path.suffix not in (".py", ".ps1", ".cpp", ".hpp", ".txt", ".json") and path.name != "Makefile":
                continue
            name = path.relative_to(snapshot).as_posix()
            if name not in allowed:
                continue
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())
    records[archive_path.name] = {"path": archive_path.name, "portable_sha256": sha(archive_path.read_bytes()),
                                  "transformation": "reviewed original measured sources, exact bytes; no binaries/private release or document tooling"}

    # Fingerprint maps include manifest text: refresh only transformed inputs.
    for path in destination.glob("jobs/*/profile.json"):
        profile = json.loads(path.read_text(encoding="utf-8"))
        updated = False
        for container in (profile, profile.get("metadata", {})):
            for key in ("fingerprints_before", "fingerprints_after"):
                fingerprints = container.get(key)
                if not fingerprints:
                    continue
                for name, old_digest in list(fingerprints.get("input_sha256", {}).items()):
                    for record in records.values():
                        if record.get("original_sha256") == old_digest and record["portable_sha256"] != old_digest:
                            fingerprints["input_sha256"][name] = record["portable_sha256"]
                            updated = True
        if updated:
            path.write_text(json.dumps(profile, indent=2, allow_nan=False) + "\n", encoding="utf-8")
            name = path.relative_to(destination).as_posix()
            records[name]["portable_sha256"] = sha(path.read_bytes())
            records[name]["transformation"] += "; transformed-input digest pointers refreshed"

    # Stopped workers may still contain completely checked methods. Preserve
    # their pointer digests when a referenced metadata file was transformed.
    for path in destination.glob("jobs/*/profile.json"):
        profile = json.loads(path.read_text(encoding="utf-8"))
        changed = False
        root = path.parent
        for case in profile.get("cases", []):
            for key in ("input", "python_golden", "full_cpp_evidence"):
                if key in case:
                    new_digest = sha((root / case[key]).read_bytes())
                    if case[key + "_sha256"] != new_digest:
                        case[key + "_sha256"] = new_digest
                        changed = True
            for sample in case.get("samples", []):
                if "evidence" in sample:
                    new_digest = sha((root / sample["evidence"]).read_bytes())
                    if sample["evidence_sha256"] != new_digest:
                        sample["evidence_sha256"] = new_digest
                        changed = True
        if changed:
            path.write_text(json.dumps(profile, indent=2, allow_nan=False) + "\n", encoding="utf-8")
            name = path.relative_to(destination).as_posix()
            records[name]["portable_sha256"] = sha(path.read_bytes())
            records[name]["transformation"] += "; transformed evidence pointers refreshed"

    history = json.loads((destination / "jobs.json").read_text(encoding="utf-8"))
    for attempt in history:
        if attempt["status"] == "completed":
            directory = destination / attempt["output"]
            attempt["evidence_sha256"] = {path.relative_to(directory).as_posix(): sha(path.read_bytes())
                                          for path in sorted(directory.rglob("*")) if path.is_file()}
    (destination / "jobs.json").write_text(json.dumps(history, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    records["jobs.json"]["portable_sha256"] = sha((destination / "jobs.json").read_bytes())
    records["jobs.json"]["transformation"] += "; portable evidence digests refreshed"
    provenance = {"format_version": 1, "scope": "portable copy of recorded local timing evidence",
                  "policy": "scientific numeric observations unchanged; original digests retained; local path/host labels replaced; symbolic paths are not executable paths",
                  "files": [records[name] for name in sorted(records)]}
    (destination / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    original_report, portable_report = analyze(source), analyze(destination)
    if original_report != portable_report:
        raise ValueError("portable transformation changed derived timing/scientific observations")
    return portable_report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = export(args.campaign.resolve(), args.output.resolve(), Path(__file__).resolve().parents[1])
    print(json.dumps({"completed_jobs": result["completed_jobs"], "verified_files": result["verified_files"]}))
