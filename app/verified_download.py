"""Streaming, resumable, SHA256-verified model delivery."""
from __future__ import annotations

import hashlib
import http.client
import os
from pathlib import Path
import re
import urllib.error
import urllib.request


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def byte_detail(received, total):
    def amount(value):
        unit = "GB" if value >= 1_000_000_000 else "MB"
        divisor = 1_000_000_000 if unit == "GB" else 1_000_000
        return f"{value / divisor:.2f} {unit}"
    if total:
        return f"{amount(received)} / {amount(total)} · {min(100, int(received * 100 / total))}%"
    return f"{amount(received)} received"


def download_verified(url, target, expected_sha256, *, progress=None, name="starter", expected_bytes=None):
    expected = str(expected_sha256).lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise RuntimeError("Starter SHA256 is missing or invalid")
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file() and sha256_file(target) == expected:
        return target
    partial = target.with_suffix(target.suffix + ".part")
    identity = partial.with_suffix(partial.suffix + ".sha256")
    if identity.exists() and identity.read_text(encoding="ascii") != expected:
        partial.unlink(missing_ok=True)
    identity.write_text(expected, encoding="ascii")
    # A connection can fail after all bytes arrived. Verify before issuing Range.
    if partial.is_file() and sha256_file(partial) == expected:
        os.replace(partial, target)
        identity.unlink(missing_ok=True)
        return target
    received = partial.stat().st_size if partial.exists() else 0
    if expected_bytes and received >= expected_bytes:
        partial.unlink(missing_ok=True)
        received = 0
    headers = {"User-Agent": "MorphoLabel managed starter", "Accept-Encoding": "identity"}
    if received:
        headers["Range"] = f"bytes={received}-"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as response:
            status = getattr(response, "status", None) or 200
            total = expected_bytes
            if status == 206:
                match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("Content-Range", ""))
                if not match or int(match[1]) != received or int(match[2]) < received:
                    raise RuntimeError("Download server returned an invalid resume range; Retry keeps the partial file.")
                total = int(match[3])
            else:
                # Range ignored: restart this asset only.
                received = 0
                length = response.headers.get("Content-Length")
                if length and str(length).isdigit():
                    total = int(length)
            if expected_bytes and total != expected_bytes:
                raise RuntimeError("Starter size does not match the verified upstream asset")
            with partial.open("ab" if received else "wb") as output:
                if progress:
                    progress(f"Downloading {name}… {byte_detail(received, total)}")
                while True:
                    block = response.read(1024 * 1024)
                    if not block:
                        break
                    output.write(block)
                    received += len(block)
                    if progress:
                        progress(f"Downloading {name}… {byte_detail(received, total)}")
            if total and received < total:
                raise RuntimeError("Download interrupted. The partial file was kept; Retry resumes where supported.")
    except (OSError, urllib.error.URLError, http.client.HTTPException) as exc:
        raise RuntimeError("Download interrupted. The partial file was kept; Retry resumes where supported.") from exc
    if sha256_file(partial) != expected:
        partial.unlink(missing_ok=True)
        identity.unlink(missing_ok=True)
        raise RuntimeError("Downloaded starter failed SHA256 verification. Retry will download this asset again.")
    os.replace(partial, target)
    identity.unlink(missing_ok=True)
    return target
