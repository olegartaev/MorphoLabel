"""Download and atomically install the published MorphoLabel managed AI component."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import urllib.error
import urllib.request
from pathlib import Path

from .ai_component import install_component_archive
from .ai_runtime_resolver import resolve_ai_runtime
from .runtime_paths import app_state_dir, is_frozen
from .version import __version__

_RELEASE_ROOT = "https://github.com/olegartaev/MorphoLabel/releases/download"
_MANIFEST_NAME = "MorphoLabel-AI-Windows-x64.json"
_SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


class AIDeliveryError(RuntimeError):
    pass


def _progress(callback, stage, detail):
    if callback:
        callback(stage, detail)


def release_base_url(version=None):
    override = os.environ.get("MORPHOLABEL_AI_RELEASE_BASE")
    if override:
        return override.rstrip("/")
    version = str(version or __version__)
    return f"{_RELEASE_ROOT}/v{version}"


def _request(url):
    return urllib.request.Request(
        url,
        headers={"User-Agent": f"MorphoLabel/{__version__} managed-ai"},
    )


def _fetch_manifest(base_url, *, progress=None):
    url = f"{base_url.rstrip('/')}/{_MANIFEST_NAME}"
    _progress(progress, "AI COMPONENT", "Checking the published AI component…")
    try:
        with urllib.request.urlopen(_request(url), timeout=60) as response:
            raw = response.read()
    except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
        raise AIDeliveryError(f"Could not retrieve the MorphoLabel AI component manifest: {exc}") from exc
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AIDeliveryError("Published AI component manifest is invalid") from exc
    if not isinstance(manifest, dict) or int(manifest.get("format_version", 0)) != 1:
        raise AIDeliveryError("Unsupported AI delivery manifest format")
    if str(manifest.get("platform")) != "windows-x64":
        raise AIDeliveryError("Published AI component is not for Windows x64")
    if str(manifest.get("app_version")) != str(__version__) and not os.environ.get("MORPHOLABEL_AI_RELEASE_BASE"):
        raise AIDeliveryError(
            f"Published AI component targets MorphoLabel {manifest.get('app_version')}, not {__version__}"
        )
    name = str(manifest.get("archive_name") or "")
    if not name or not _SAFE_NAME.fullmatch(name) or Path(name).name != name or not name.lower().endswith(".zip"):
        raise AIDeliveryError("Published AI component archive name is unsafe")
    digest = str(manifest.get("archive_sha256") or "").lower()
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise AIDeliveryError("Published AI component SHA256 is invalid")
    try:
        archive_bytes = int(manifest.get("archive_bytes"))
        installed_bytes = int(manifest.get("installed_bytes") or 0)
    except (TypeError, ValueError) as exc:
        raise AIDeliveryError("Published AI component sizes are invalid") from exc
    if archive_bytes <= 0 or installed_bytes < 0:
        raise AIDeliveryError("Published AI component sizes are invalid")
    raw_parts = manifest.get("parts")
    if raw_parts is None:
        raw_parts = [{"name": name, "bytes": archive_bytes, "sha256": digest}]
    if not isinstance(raw_parts, list) or not raw_parts:
        raise AIDeliveryError("Published AI component part list is invalid")
    parts = []
    seen = set()
    total_part_bytes = 0
    for item in raw_parts:
        if not isinstance(item, dict):
            raise AIDeliveryError("Published AI component part entry is invalid")
        part_name = str(item.get("name") or "")
        if not part_name or not _SAFE_NAME.fullmatch(part_name) or Path(part_name).name != part_name:
            raise AIDeliveryError("Published AI component part name is unsafe")
        if part_name in seen:
            raise AIDeliveryError("Published AI component contains duplicate parts")
        seen.add(part_name)
        part_digest = str(item.get("sha256") or "").lower()
        if not re.fullmatch(r"[0-9a-f]{64}", part_digest):
            raise AIDeliveryError("Published AI component part SHA256 is invalid")
        try:
            part_bytes = int(item.get("bytes"))
        except (TypeError, ValueError) as exc:
            raise AIDeliveryError("Published AI component part size is invalid") from exc
        if part_bytes <= 0 or part_bytes >= 2 * 1024**3:
            raise AIDeliveryError("Published AI component part exceeds the GitHub Release size contract")
        parts.append({"name": part_name, "bytes": part_bytes, "sha256": part_digest})
        total_part_bytes += part_bytes
    if total_part_bytes != archive_bytes:
        raise AIDeliveryError("Published AI component parts do not match archive size")
    manifest["archive_bytes"] = archive_bytes
    manifest["installed_bytes"] = installed_bytes
    manifest["archive_sha256"] = digest
    manifest["archive_name"] = name
    manifest["parts"] = parts
    return manifest


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _download_archive(manifest, base_url, *, progress=None):
    cache = app_state_dir(create=True) / "downloads" / "ai"
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / manifest["archive_name"]
    expected = manifest["archive_sha256"]
    if target.is_file() and target.stat().st_size == manifest["archive_bytes"] and _sha256(target) == expected:
        _progress(progress, "AI COMPONENT", "Using the verified cached AI component…")
        return target

    free = shutil.disk_usage(cache).free
    required = manifest["archive_bytes"] + manifest["installed_bytes"] + 512 * 1024 * 1024
    if free < required:
        raise AIDeliveryError(
            f"Not enough free disk space for the AI component: need about {required / (1024**3):.1f} GB"
        )

    part = target.with_suffix(target.suffix + ".part")
    part.unlink(missing_ok=True)
    full_digest = hashlib.sha256()
    received = 0
    _progress(progress, "AI COMPONENT", "Downloading the verified AI runtime…")
    try:
        with part.open("wb") as output:
            for asset in manifest["parts"]:
                url = f"{base_url.rstrip('/')}/{asset['name']}"
                asset_digest = hashlib.sha256()
                asset_received = 0
                try:
                    response_context = urllib.request.urlopen(_request(url), timeout=60)
                except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
                    raise AIDeliveryError(f"AI component part download failed: {asset['name']}: {exc}") from exc
                with response_context as response:
                    while True:
                        block = response.read(1024 * 1024)
                        if not block:
                            break
                        output.write(block)
                        asset_digest.update(block)
                        full_digest.update(block)
                        asset_received += len(block)
                        received += len(block)
                        pct = min(100, int(received * 100 / manifest["archive_bytes"]))
                        _progress(progress, "AI COMPONENT", f"Downloading AI runtime… {pct}%")
                if asset_received != asset["bytes"]:
                    raise AIDeliveryError(
                        f"AI component part is incomplete: {asset['name']}: {asset_received} of {asset['bytes']} bytes"
                    )
                if asset_digest.hexdigest() != asset["sha256"]:
                    raise AIDeliveryError(f"AI component part failed SHA256 verification: {asset['name']}")
    except Exception:
        part.unlink(missing_ok=True)
        raise

    if received != manifest["archive_bytes"]:
        part.unlink(missing_ok=True)
        raise AIDeliveryError(
            f"AI component download is incomplete: {received} of {manifest['archive_bytes']} bytes"
        )
    if full_digest.hexdigest() != expected:
        part.unlink(missing_ok=True)
        raise AIDeliveryError("AI component assembled archive failed SHA256 verification")
    os.replace(part, target)
    return target


def install_published_ai_component(*, progress=None, release_version=None):
    version = str(release_version or __version__)
    if version.endswith("-dev") and not os.environ.get("MORPHOLABEL_AI_RELEASE_BASE"):
        raise AIDeliveryError(
            "This development build has no published managed AI component. Use a tagged MorphoLabel release."
        )
    base = release_base_url(version)
    manifest = _fetch_manifest(base, progress=progress)
    archive = _download_archive(manifest, base, progress=progress)
    _progress(progress, "AI COMPONENT", "Verifying and installing the AI runtime…")
    try:
        runtime = install_component_archive(
            archive,
            expected_sha256=manifest["archive_sha256"],
            activate=True,
            run_runtime_check=True,
        )
    except Exception as exc:
        raise AIDeliveryError(f"AI component installation failed: {exc}") from exc
    try:
        archive.unlink()
    except OSError:
        pass
    _progress(progress, "AI COMPONENT", "AI runtime installed and verified.")
    return runtime


def ensure_ai_runtime(*, project=None, explicit=None, configured=None, runner_path=None, progress=None):
    runtime, runner = resolve_ai_runtime(
        project=project,
        explicit=explicit,
        configured=configured,
        runner_path=runner_path,
    )
    if runtime.is_file():
        return runtime, runner
    # Source/developer checkouts remain side-effect free. Public frozen builds
    # install the managed component automatically on first AI use.
    if not is_frozen() or explicit is not None or configured is not None:
        return runtime, runner
    install_published_ai_component(progress=progress)
    runtime, runner = resolve_ai_runtime(project=project, runner_path=runner_path)
    if not runtime.is_file():
        raise AIDeliveryError("Managed AI component installed but no runtime could be resolved")
    return runtime, runner
