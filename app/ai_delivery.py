"""Download and atomically install the published MorphoLabel managed AI component."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
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
_DOWNLOAD_RETRIES = 4
_DOWNLOAD_BLOCK_BYTES = 1024 * 1024


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


def _request(url, *, range_start=None):
    headers={"User-Agent": f"MorphoLabel/{__version__} managed-ai"}
    if range_start is not None and int(range_start) > 0:
        headers["Range"]=f"bytes={int(range_start)}-"
    return urllib.request.Request(url,headers=headers)


def _response_status(response):
    status=getattr(response,"status",None)
    if status is None:
        getter=getattr(response,"getcode",None)
        status=getter() if callable(getter) else 200
    return int(status or 200)


def _hash_segment(path,start,length):
    digest=hashlib.sha256();read=0
    with Path(path).open("rb") as handle:
        handle.seek(int(start))
        remaining=int(length)
        while remaining>0:
            block=handle.read(min(_DOWNLOAD_BLOCK_BYTES,remaining))
            if not block:break
            digest.update(block);read+=len(block);remaining-=len(block)
    return digest.hexdigest(),read


def _truncate(path,size):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    mode="r+b" if path.exists() else "w+b"
    with path.open(mode) as handle:
        handle.truncate(int(size))


def _validated_partial_size(path,parts,archive_bytes):
    path=Path(path)
    if not path.is_file():return 0
    size=path.stat().st_size
    if size<0 or size>int(archive_bytes):
        _truncate(path,0);return 0
    offset=0
    for asset in parts:
        end=offset+int(asset["bytes"])
        if size<end:break
        digest,read=_hash_segment(path,offset,asset["bytes"])
        if read!=int(asset["bytes"]) or digest!=asset["sha256"]:
            _truncate(path,offset)
            return offset
        offset=end
    return size


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
    if target.exists():
        target.unlink(missing_ok=True)

    part = target.with_suffix(target.suffix + ".part")
    received = _validated_partial_size(part, manifest["parts"], manifest["archive_bytes"])
    if received:
        pct=min(100,int(received*100/manifest["archive_bytes"]))
        _progress(progress,"AI COMPONENT",f"Resuming AI runtime download… {pct}%")

    free = shutil.disk_usage(cache).free
    remaining = max(0, manifest["archive_bytes"] - received)
    required = remaining + manifest["installed_bytes"] + 512 * 1024 * 1024
    if free < required:
        raise AIDeliveryError(
            f"Not enough free disk space for the AI component: need about {required / (1024**3):.1f} GB"
        )

    _progress(progress, "AI COMPONENT", "Downloading the verified AI runtime…")
    offset=0
    transient=(OSError,urllib.error.URLError,urllib.error.HTTPError)
    for asset in manifest["parts"]:
        asset_bytes=int(asset["bytes"]);asset_end=offset+asset_bytes
        if received>=asset_end:
            offset=asset_end
            continue
        if received<offset:
            _truncate(part,offset);received=offset

        attempts=0
        while received<asset_end:
            attempts+=1
            local_offset=received-offset
            url=f"{base_url.rstrip('/')}/{asset['name']}"
            try:
                request=_request(url,range_start=local_offset if local_offset else None)
                with urllib.request.urlopen(request,timeout=60) as response:
                    # Some servers/proxies ignore Range and return 200. In that
                    # case restart only this release part, never earlier verified parts.
                    if local_offset and _response_status(response)!=206:
                        _truncate(part,offset);received=offset;local_offset=0
                    mode="r+b" if part.exists() else "w+b"
                    with part.open(mode) as output:
                        output.seek(received)
                        while received<asset_end:
                            block=response.read(min(_DOWNLOAD_BLOCK_BYTES,asset_end-received))
                            if not block:break
                            output.write(block);received+=len(block)
                            pct=min(100,int(received*100/manifest["archive_bytes"]))
                            _progress(progress,"AI COMPONENT",f"Downloading AI runtime… {pct}%")
                        output.flush()
            except transient as exc:
                if attempts>=_DOWNLOAD_RETRIES:
                    pct=min(100,int(received*100/manifest["archive_bytes"]))
                    raise AIDeliveryError(
                        f"AI component download was interrupted after {pct}%; "
                        f"the partial download was kept and will resume next time: {exc}"
                    ) from exc
                _progress(progress,"AI COMPONENT","Connection interrupted; resuming AI runtime download…")
                time.sleep(min(4,attempts))
                continue

            if received<asset_end:
                if attempts>=_DOWNLOAD_RETRIES:
                    pct=min(100,int(received*100/manifest["archive_bytes"]))
                    raise AIDeliveryError(
                        f"AI component part remained incomplete after retries at {pct}%; "
                        "the partial download was kept and will resume next time"
                    )
                _progress(progress,"AI COMPONENT","Connection ended early; resuming AI runtime download…")
                time.sleep(min(4,attempts))
                continue

            digest,read=_hash_segment(part,offset,asset_bytes)
            if read!=asset_bytes or digest!=asset["sha256"]:
                _truncate(part,offset);received=offset
                if attempts>=_DOWNLOAD_RETRIES:
                    raise AIDeliveryError(
                        f"AI component part failed SHA256 verification after retries: {asset['name']}"
                    )
                _progress(progress,"AI COMPONENT","Downloaded AI part failed verification; retrying that part…")
                time.sleep(min(4,attempts))
                continue
            break
        offset=asset_end

    if received != manifest["archive_bytes"] or part.stat().st_size != manifest["archive_bytes"]:
        raise AIDeliveryError(
            f"AI component download is incomplete: {received} of {manifest['archive_bytes']} bytes"
        )
    if _sha256(part) != expected:
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
    # may download the managed component only after explicit user consent.
    if not is_frozen() or explicit is not None or configured is not None:
        return runtime, runner
    from .first_run_setup import ai_download_consent_granted
    if not ai_download_consent_granted():
        raise AIDeliveryError(
            "AI support is not installed yet. Open AI → Set up AI support… "
            "to review and approve the required downloads."
        )
    install_published_ai_component(progress=progress)
    runtime, runner = resolve_ai_runtime(project=project, runner_path=runner_path)
    if not runtime.is_file():
        raise AIDeliveryError("Managed AI component installed but no runtime could be resolved")
    return runtime, runner
