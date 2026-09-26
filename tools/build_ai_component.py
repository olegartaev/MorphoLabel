"""Build a self-contained Windows MorphoLabel AI component from pinned upstream assets."""
from __future__ import annotations
import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def run(command, **kwargs):
    print("+", " ".join(map(str, command)), flush=True)
    subprocess.run([str(part) for part in command], check=True, **kwargs)

def download(url, target):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    print("download", url, "->", target, flush=True)
    urllib.request.urlretrieve(url, target)
    return target

def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

def main():
    if os.name != "nt":
        raise SystemExit("AI component builder currently supports Windows only")
    spec_path = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "ai_runtime" / "windows-cu121-component.json")
    output = Path(sys.argv[2] if len(sys.argv) > 2 else ROOT / "dist" / "ai-component")
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    version = spec["component_version"]
    work = ROOT / "build" / "ai-component"
    if work.exists():
        shutil.rmtree(work)
    runtime = work / "runtime"
    downloads = work / "downloads"
    runtime.mkdir(parents=True)

    installer = download(spec["python"]["installer_url"], downloads / "python-installer.exe")
    run([installer, "/quiet", "InstallAllUsers=0", f"TargetDir={runtime}",
         "Include_pip=1", "Include_launcher=0", "AssociateFiles=0", "Shortcuts=0",
         "PrependPath=0", "Include_test=0", "Include_doc=0"])
    python = runtime / "python.exe"
    if not python.is_file():
        raise RuntimeError("managed Python installation did not create python.exe")

    packages = spec["packages"]
    run([python, "-m", "pip", "install", "--disable-pip-version-check", "--upgrade", "pip==24.3.1"])
    run([python, "-m", "pip", "install", "--disable-pip-version-check", f"numpy=={packages['numpy']}"])
    run([python, "-m", "pip", "install", "--disable-pip-version-check",
         f"torch=={packages['torch']}", f"torchvision=={packages['torchvision']}",
         "--index-url", packages["torch_index_url"]])
    run([python, "-m", "pip", "install", "--disable-pip-version-check", f"mmengine=={packages['mmengine']}"])
    run([python, "-m", "pip", "install", "--disable-pip-version-check", f"mmcv=={packages['mmcv']}",
         "-f", packages["mmcv_find_links"]])
    run([python, "-m", "pip", "install", "--disable-pip-version-check", f"mmpose=={packages['mmpose']}"])

    source_zip = download(spec["mmpose_source"]["archive_url"], downloads / "mmpose.zip")
    source_tmp = work / "mmpose-source"
    with zipfile.ZipFile(source_zip) as archive:
        archive.extractall(source_tmp)
    roots = [path for path in source_tmp.iterdir() if path.is_dir()]
    if len(roots) != 1:
        raise RuntimeError("unexpected MMPose source archive layout")
    vendor = runtime / "vendor" / "mmpose"
    vendor.parent.mkdir(parents=True)
    shutil.move(str(roots[0]), str(vendor))
    if not (vendor / "tools" / "train.py").is_file():
        raise RuntimeError("MMPose training source tools/train.py is missing")

    checkpoint_rel = Path(spec["bootstrap"]["checkpoint_relative_path"])
    checkpoint = download(spec["bootstrap"]["checkpoint_url"], runtime / checkpoint_rel)
    config_rel = Path(spec["bootstrap"]["config_relative_path"])
    if not (runtime / config_rel).is_file():
        raise RuntimeError("official AP-10K RTMPose config is missing from pinned MMPose source")

    freeze = subprocess.run([str(python), "-m", "pip", "freeze"], check=True, text=True, capture_output=True).stdout.splitlines()
    manifest = {
        "component_format": 1,
        "component_version": version,
        "platform": spec["platform"],
        "python_relative_path": "python.exe",
        "bootstrap_config": config_rel.as_posix(),
        "bootstrap_checkpoint": checkpoint_rel.as_posix(),
        "bootstrap_checkpoint_sha256": sha256(checkpoint),
        "mmpose_source": "vendor/mmpose",
        "mmpose_source_commit": spec["mmpose_source"]["commit"],
        "packages": freeze,
    }
    (runtime / "component.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    runner = ROOT / "ai_runtime" / "rtmpose_runner.py"
    result = subprocess.run([str(python), str(runner), "info"], input="{}", text=True, capture_output=True, check=True)
    info = json.loads(next(line for line in reversed(result.stdout.splitlines()) if line.strip()))
    for key, expected in {
        "torch": packages["torch"], "torchvision": packages["torchvision"],
        "mmengine": packages["mmengine"], "mmcv": packages["mmcv"], "mmpose": packages["mmpose"],
    }.items():
        if not str(info.get(key, "")).startswith(str(expected)):
            raise RuntimeError(f"{key} version mismatch: {info.get(key)} != {expected}")

    output.mkdir(parents=True, exist_ok=True)
    archive_base = output / f"MorphoLabel-AI-Windows-x64-{version}"
    archive = Path(shutil.make_archive(str(archive_base), "zip", runtime))
    checksum = sha256(archive)
    (output / "SHA256SUMS.txt").write_text(f"{checksum}  {archive.name}\n", encoding="utf-8")
    (output / "AI_BUILD_INFO.json").write_text(json.dumps({
        "archive": archive.name,
        "archive_sha256": checksum,
        "archive_bytes": archive.stat().st_size,
        "runtime_info": info,
        "component_manifest": manifest,
    }, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"archive": str(archive), "sha256": checksum, "bytes": archive.stat().st_size, "runtime": info}, indent=2))

if __name__ == "__main__":
    main()
