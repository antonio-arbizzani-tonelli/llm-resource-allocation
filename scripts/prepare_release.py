"""Export a reviewed file allowlist and its SHA256 manifest into a new directory.

The development configuration can map editorial sources to public paths. The
exported configuration uses those public files directly, so a fresh clone can
verify and export itself without the development workspace or Git history.
"""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = "configs/publication.json"
MANIFEST_PATH = "release-manifest.json"
TEXT_SUFFIXES = {".py", ".ps1", ".md", ".toml", ".json", ".yml", ".yaml", ".cpp", ".hpp", ".txt", ".sh", ".csv"}


def relative_file(value: str) -> str:
    """Require a portable relative file path without traversal or Git metadata."""
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise ValueError(f"invalid publication path: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(
        part in ("", ".", "..") or part.endswith((" ", "."))
        for part in value.split("/")
    ) or path.parts[0].casefold() == ".git":
        raise ValueError(f"invalid publication path: {value!r}")
    return path.as_posix()


def prepare_files(root: Path, config_path: Path) -> tuple[dict[str, bytes], dict]:
    """Read all approved inputs before writing and identify every exported byte."""
    specification = json.loads(config_path.read_text(encoding="utf-8"))
    if specification.get("format_version") != 1 or not specification.get("files"):
        raise ValueError("expected publication format 1 with a nonempty file list")
    entries = specification["files"]
    paths = [relative_file(entry["path"]) for entry in entries]
    if len({path.casefold() for path in paths}) != len(paths):
        raise ValueError("duplicate publication destinations")
    if MANIFEST_PATH.casefold() in {path.casefold() for path in paths} or CONFIG_PATH not in paths:
        raise ValueError("configuration must be delivered; generated manifest is reserved")
    payloads = {}
    records = []
    for entry, path in zip(entries, paths, strict=True):
        source_name = relative_file(entry.get("source", path))
        source = (root / source_name).resolve()
        if not source.is_relative_to(root.resolve()) or not source.is_file():
            raise ValueError(f"missing or external source: {source_name}")
        original = source.read_bytes()
        if path == CONFIG_PATH:
            standalone = {**specification, "files": [{"path": item} for item in paths]}
            payload = (json.dumps(standalone, indent=2, ensure_ascii=False) + "\n").encode()
        elif PurePosixPath(path).parts[0] != "benchmarks" and (
            source.suffix.lower() in TEXT_SUFFIXES or source.name in ("Makefile", ".gitignore", ".gitattributes")
        ):
            payload = original.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        else:
            # Historical observations retain the bytes identified by their own hashes.
            payload = original
        payloads[path] = payload
        records.append({"path": path, "bytes": len(payload),
                        "sha256": hashlib.sha256(payload).hexdigest()})
    return payloads, {"format_version": 1, "scope": specification["scope"],
                      "file_count": len(records), "files": records}


def export_release(root: Path, configuration: Path, destination: Path) -> dict:
    """Create a new export, preserving source files and existing destinations."""
    destination = destination.resolve()
    protected = (".git", "src", "tests", "docs", "scripts", "configs", "cpp", "benchmarks", "examples", ".github")
    if destination == root.resolve() or any(destination.is_relative_to(root / name) for name in protected):
        raise ValueError("destination must be separate from source directories")
    if destination.exists():
        raise ValueError("destination already exists; choose a new directory")
    payloads, manifest = prepare_files(root, configuration)
    destination.mkdir(parents=True, exist_ok=False)
    for path, payload in payloads.items():
        target = destination / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    (destination / MANIFEST_PATH).write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / CONFIG_PATH)
    parser.add_argument("--output", type=Path, default=ROOT / "build/release")
    parser.add_argument("--check", action="store_true", help="verify allowlisted inputs without writing")
    args = parser.parse_args()
    try:
        if args.check:
            _, manifest = prepare_files(ROOT, args.config)
            recorded = ROOT / MANIFEST_PATH
            if recorded.exists() and json.loads(recorded.read_text(encoding="utf-8")) != manifest:
                raise ValueError("delivered files differ from release-manifest.json")
        else:
            manifest = export_release(ROOT, args.config, args.output)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Release preparation failed: {error}", file=sys.stderr)
        return 1
    print(f"{'Verified' if args.check else 'Exported'} {manifest['file_count']} publication files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
