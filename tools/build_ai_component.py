"""Build a self-contained Windows MorphoLabel AI component from pinned upstream assets."""
from __future__ import annotations
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
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
    constraints = work / "constraints.txt"
    constraints.write_text(
        "\n".join((
            f"numpy=={packages['numpy']}",
            f"opencv-python=={packages['opencv_python']}",
            f"scipy=={packages['scipy']}",
        )) + "\n",
        encoding="utf-8",
    )
    common = ["--disable-pip-version-check", "-c", constraints]
    run([python, "-m", "pip", "install", "--disable-pip-version-check", "--upgrade", "pip==24.3.1"])
    run([python, "-m", "pip", "install", *common,
         f"numpy=={packages['numpy']}", f"opencv-python=={packages['opencv_python']}",
         f"scipy=={packages['scipy']}"])
    run([python, "-m", "pip", "install", *common,
         f"torch=={packages['torch']}", f"torchvision=={packages['torchvision']}",
         "--index-url", packages["torch_index_url"]])
    run([python, "-m", "pip", "install", *common, f"mmengine=={packages['mmengine']}"])
    run([python, "-m", "pip", "install", *common, f"mmcv=={packages['mmcv']}",
         "-f", packages["mmcv_find_links"]])
    # MMPose 1.3.2 metadata still declares chumpy although the MMPose source
    # does not import it and our RTMPose/AP-10K path does not use it. chumpy's
    # legacy build fails under modern isolated pip builds, so install the
    # required 2D runtime dependencies explicitly and MMPose without metadata deps.
    run([python, "-m", "pip", "install", *common,
         f"json_tricks=={packages['json_tricks']}", f"munkres=={packages['munkres']}",
         f"xtcocotools=={packages['xtcocotools']}"])
    run([python, "-m", "pip", "install", *common, "--no-deps", f"mmpose=={packages['mmpose']}"])

    source_tmp = work / "mmpose-source"
    source_tmp.mkdir(parents=True)
    run(["git", "-C", source_tmp, "init"])
    run(["git", "-C", source_tmp, "remote", "add", "origin", spec["mmpose_source"]["repo_url"]])
    run(["git", "-C", source_tmp, "fetch", "--depth", "1", "origin", spec["mmpose_source"]["commit"]])
    run(["git", "-C", source_tmp, "checkout", "--detach", "FETCH_HEAD"])
    tracked = subprocess.run(
        ["git", "-C", str(source_tmp), "ls-files", "-z"],
        check=True, capture_output=True,
    ).stdout.split(b"\0")
    vendor = runtime / "vendor" / "mmpose"
    vendor.mkdir(parents=True)
    for raw_name in tracked:
        if not raw_name:
            continue
        relative = Path(os.fsdecode(raw_name))
        source = source_tmp / relative
        destination = vendor / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
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
    if not str(info.get("numpy", "")).startswith(packages["numpy"]):
        raise RuntimeError(f"numpy version mismatch: {info.get('numpy')} != {packages['numpy']}")
    if not str(info.get("opencv", "")).startswith(packages["opencv_python"].split(".84")[0]):
        raise RuntimeError(f"opencv version mismatch: {info.get('opencv')} != {packages['opencv_python']}")
    # Import and parse the exact bootstrap configuration so missing runtime
    # dependencies fail in CI before an archive is published.
    smoke = (
        "from mmengine.config import Config; "
        "from mmpose.utils import register_all_modules; "
        "register_all_modules(); "
        f"Config.fromfile(r'{str(runtime / config_rel)}'); "
        "print('BOOTSTRAP_CONFIG_PASS')"
    )
    run([python, "-c", smoke])
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
