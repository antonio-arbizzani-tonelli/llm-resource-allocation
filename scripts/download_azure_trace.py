"""Download the public Azure 2024 code trace and verify its release checksum."""

import argparse
import hashlib
import json
from pathlib import Path
import time
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
RELEASE_API = "https://api.github.com/repos/Azure/AzurePublicDataset/releases/tags/dataset-llm-2024"
DOCUMENTATION_URL = "https://github.com/Azure/AzurePublicDataset/blob/master/AzureLLMInferenceDataset2024.md"
ASSET_NAME = "AzureLLMInferenceTrace_code_1week.csv"


def file_sha256(path: Path) -> str:
    """Hash a raw file without loading it into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "data/external/azure_2024")
    args = parser.parse_args()
    request = urllib.request.Request(RELEASE_API, headers={"User-Agent": "Pacs-Azure-Replay"})
    with urllib.request.urlopen(request, timeout=60) as response:
        release = json.load(response)
    asset = next(item for item in release["assets"] if item["name"] == ASSET_NAME)
    expected = asset.get("digest")
    if not expected or not expected.startswith("sha256:"):
        raise ValueError("The official release must supply a SHA-256 digest")
    expected = expected.removeprefix("sha256:")
    args.output.mkdir(parents=True, exist_ok=True)
    target = args.output / ASSET_NAME
    if target.exists():
        digest = file_sha256(target)
        if digest != expected or target.stat().st_size != asset["size"]:
            raise ValueError("Existing raw trace differs from the official release; preserved without overwrite")
        print("Existing raw trace matches the official checksum.", flush=True)
    else:
        temporary = target.with_suffix(".csv.partial")
        if temporary.exists():
            raise FileExistsError(f"Incomplete download retained: {temporary}")
        request = urllib.request.Request(asset["browser_download_url"], headers={"User-Agent": "Pacs-Azure-Replay"})
        digest_state = hashlib.sha256()
        size = 0
        last_update = time.monotonic()
        with urllib.request.urlopen(request, timeout=60) as response, temporary.open("xb") as stream:
            while chunk := response.read(4 * 1024 * 1024):
                stream.write(chunk)
                digest_state.update(chunk)
                size += len(chunk)
                if time.monotonic() - last_update >= 10:
                    print(f"Downloaded {size / 1024**2:.1f} / {asset['size'] / 1024**2:.1f} MiB", flush=True)
                    last_update = time.monotonic()
        digest = digest_state.hexdigest()
        if digest != expected or size != asset["size"]:
            raise ValueError("Download failed size/checksum validation; partial file retained")
        temporary.rename(target)
    manifest = {
        "source": "Azure/AzurePublicDataset official release",
        "documentation_url": DOCUMENTATION_URL,
        "release_api_url": RELEASE_API,
        "release_tag": release["tag_name"],
        "release_published_at": release["published_at"],
        "asset_name": ASSET_NAME,
        "asset_id": asset["id"],
        "download_url": asset["browser_download_url"],
        "size_bytes": target.stat().st_size,
        "sha256": digest,
        "license": "CC-BY-4.0",
        "attribution": "Stojkovic et al., DynamoLLM: Designing LLM Inference Clusters for Performance and Energy Efficiency, HPCA 2025",
        "raw_path": str(target.resolve()),
    }
    (args.output / "source_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Verified {target.name}: {target.stat().st_size} bytes; SHA-256 {digest}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
