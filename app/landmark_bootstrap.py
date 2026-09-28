"""Resolve and cache the official OpenMMLab AP-10K RTMPose bootstrap."""
from __future__ import annotations

import hashlib
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .ai_component import component_manifest, component_root_for_runtime
from .ai_delivery import ensure_ai_runtime
from .runtime_paths import is_frozen


@dataclass(frozen=True)
class BootstrapSpec:
    config_path: Path
    checkpoint_path: Path
    input_size: tuple
    provenance: str
    checksum: str
    runtime_python: Path


def _progress(callback, detail):
    if callback:
        callback("BOOTSTRAP MODEL", detail)


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _download_verified_checkpoint(url, target, expected_sha256, progress_callback=None):
    if not str(url).startswith("https://download.openmmlab.com/"):
        raise RuntimeError("Refusing an untrusted RTMPose bootstrap checkpoint URL")
    expected = str(expected_sha256 or "").lower()
    if len(expected) != 64 or any(ch not in "0123456789abcdef" for ch in expected):
        raise RuntimeError("RTMPose bootstrap checkpoint SHA256 is missing or invalid")
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)

    if target.is_file():
        if _sha256(target) == expected:
            return target
        target.unlink()

    if is_frozen():
        from .first_run_setup import ai_download_consent_granted
        if not ai_download_consent_granted():
            raise RuntimeError(
                "AI bootstrap model is not installed yet. Open AI → Set up AI support… "
                "to review and approve the required download."
            )

    temporary = target.with_suffix(target.suffix + ".part")
    temporary.unlink(missing_ok=True)
    digest = hashlib.sha256()
    received = 0
    request = urllib.request.Request(
        str(url),
        headers={"User-Agent": "MorphoLabel managed bootstrap"},
    )
    _progress(progress_callback, "Downloading the official OpenMMLab RTMPose bootstrap model…")
    try:
        with urllib.request.urlopen(request, timeout=60) as response, temporary.open("wb") as output:
            total = response.headers.get("Content-Length") if getattr(response, "headers", None) else None
            total = int(total) if total and str(total).isdigit() else 0
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                output.write(block)
                digest.update(block)
                received += len(block)
                if total:
                    _progress(progress_callback, f"Downloading bootstrap model… {min(100, int(received * 100 / total))}%")
    except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"Could not download the official RTMPose bootstrap model: {exc}") from exc
    if digest.hexdigest() != expected:
        temporary.unlink(missing_ok=True)
        raise RuntimeError("Downloaded RTMPose bootstrap checkpoint failed SHA256 verification")
    os.replace(temporary, target)
    _progress(progress_callback, "Bootstrap model downloaded and verified.")
    return target


def resolve_landmark_bootstrap(project, progress_callback=None):
    runtime, _ = ensure_ai_runtime(project=project, progress=progress_callback)
    managed_root = component_root_for_runtime(runtime)
    if managed_root is not None:
        manifest = component_manifest(managed_root)
        config = managed_root / str(manifest.get("bootstrap_config") or "")
        checkpoint = managed_root / str(manifest.get("bootstrap_checkpoint") or "")
        if not config.is_file():
            raise RuntimeError("Managed AI component RTMPose bootstrap config is unavailable")
        checkpoint = _download_verified_checkpoint(
            manifest.get("bootstrap_checkpoint_url"),
            checkpoint,
            manifest.get("bootstrap_checkpoint_sha256"),
            progress_callback,
        )
        checksum = str(manifest["bootstrap_checkpoint_sha256"]).lower()
        return BootstrapSpec(
            config,
            checkpoint,
            (512, 256),
            "official OpenMMLab MMPose AP-10K RTMPose-M downloaded from upstream and SHA256 verified",
            checksum,
            runtime,
        )

    # Developer/legacy runtimes may still carry their bootstrap assets beside
    # the runtime. Never download into an unmanaged runtime implicitly.
    root = runtime.parents[1]
    config = next(iter((root / "vendor" / "mmpose" / "configs" / "animal_2d_keypoint" / "rtmpose" / "ap10k").glob(
        "rtmpose-m_8xb64-210e_ap10k-256x256.py"
    )), None)
    checkpoint = next(iter((root / "assets").glob("rtmpose-m_ap10k_*.pth")), None)
    if not config or not checkpoint or not config.is_file() or not checkpoint.is_file():
        raise RuntimeError(
            "Official RTMPose AP-10K bootstrap is unavailable beside the resolved developer AI runtime."
        )
    return BootstrapSpec(
        config,
        checkpoint,
        (512, 256),
        "official MMPose AP-10K RTMPose-M local developer runtime asset",
        _sha256(checkpoint),
        runtime,
    )
