"""Optional non-blocking read-only GitHub release checker for MorphoLabel.

No telemetry, downloads, installer execution or project data is sent. Version
metadata is fetched from the official public GitHub release endpoint only.
"""
from __future__ import annotations

import json
import re
from urllib import request

LATEST_RELEASE_API="https://api.github.com/repos/olegartaev/MorphoLabel/releases/latest"
_RELEASE_URL_PREFIX="https://github.com/olegartaev/MorphoLabel/releases/tag/"
_VERSION_RE=re.compile(r"^[vV]?(\d+)\.(\d+)\.(\d+)(?:[-.]?(alpha|beta|a|b|rc)[.-]?(\d+))?$",re.I)


def version_key(value):
    match=_VERSION_RE.fullmatch(str(value).strip())
    if match is None:
        return None
    major,minor,patch,stage,stage_num=match.groups()
    order={"alpha":0,"a":0,"beta":1,"b":1,"rc":2,None:3}
    return (int(major),int(minor),int(patch),order[stage.lower() if stage else None],int(stage_num or 0))


def newer_release(current_version, metadata):
    """Verify official release metadata; return safe opt-in notice or None."""
    if not isinstance(metadata,dict) or metadata.get("draft") or metadata.get("prerelease"):
        return None
    current=version_key(current_version)
    candidate=version_key(metadata.get("tag_name",""))
    url=str(metadata.get("html_url") or "")
    if current is None or candidate is None or candidate<=current:
        return None
    if not url.startswith(_RELEASE_URL_PREFIX):
        return None
    tail=url[len(_RELEASE_URL_PREFIX):]
    if not tail or "/" in tail or "?" in tail or "#" in tail or not re.fullmatch(r"[A-Za-z0-9._-]+",tail):
        return None
    message=str(metadata.get("body") or "").strip()
    if len(message)>600:message=message[:597].rstrip()+"..."
    return {"version":str(metadata["tag_name"]),"url":url,
            "changes":message or "Release notes are available on GitHub."}


def check_for_release(current_version, opener=None):
    """At most one short HTTPS request. Connection errors should be ignored by UI."""
    opener=opener or request.urlopen
    req=request.Request(LATEST_RELEASE_API,headers={
        "Accept":"application/vnd.github+json",
        "User-Agent":"MorphoLabel-release-update-check",
        "X-GitHub-Api-Version":"2022-11-28",
    })
    with opener(req,timeout=4) as stream:
        raw=stream.read(65537)
    if len(raw)>65536:
        raise ValueError("Release metadata too large")
    return newer_release(current_version,json.loads(raw.decode("utf-8")))
