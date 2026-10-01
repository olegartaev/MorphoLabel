"""Read-only, path-redacting model artifact inventory.

Pass only approved artifact roots. The JSON emitted to stdout contains no source
paths or parent-directory names. Checkpoints are hashed as bytes; optional safe
inspection uses torch.load(weights_only=True) and never falls back to pickle.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

WEIGHT_NAMES = {"model.npz"}
SAFE_SIBLINGS = {
    "model.json", "model_manifest.json", "environment.json", "config.py",
    "inference_config.py", "finalization.json", "validation_metrics.json",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return {}
    return value if isinstance(value, dict) else {}


def safe_checkpoint_summary(path: Path) -> dict:
    """Inspect tensors only; safe unpickler refusal is reported without fallback."""
    try:
        import torch

        value = torch.load(path, map_location="cpu", weights_only=True)
        top = list(value) if isinstance(value, dict) else []
        state = value.get("state_dict", value.get("model", value)) if isinstance(value, dict) else value
        tensors = [(str(k), v) for k, v in state.items() if hasattr(v, "shape")] if isinstance(state, dict) else []
        return {
            "status": "safe_load_pass",
            "top_level_keys": top,
            "tensor_count": len(tensors),
            "parameter_count": sum(int(t.numel()) for _, t in tensors),
            "first_tensors": [{"name": k, "shape": list(t.shape)} for k, t in tensors[:5]],
            "last_tensors": [{"name": k, "shape": list(t.shape)} for k, t in tensors[-5:]],
        }
    except Exception as exc:  # Do not expose paths or exception payloads.
        return {"status": "safe_load_refused", "error_type": type(exc).__name__}


def is_candidate(path: Path) -> bool:
    name = path.name.lower()
    return path.suffix.lower() in {".pt", ".pth", ".onnx", ".ckpt", ".npz"} and (
        name in WEIGHT_NAMES or name.startswith("best")
    )


def candidate_record(path: Path, candidate_id: str, inspect: bool) -> dict:
    siblings = sorted(
        child.name for child in path.parent.iterdir()
        if child.is_file() and (child.name in SAFE_SIBLINGS or re.fullmatch(r"epoch_\d+\.pth", child.name))
    )
    metadata = safe_json(path.parent / "model.json") or safe_json(path.parent / "model_manifest.json")
    environment = safe_json(path.parent / "environment.json")
    record = {
        "anonymous_model_id": candidate_id,
        "file_type": path.suffix.lower(),
        "size_bytes": path.stat().st_size,
        "sha256": sha256(path),
        "modified_utc": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
        "sibling_filenames": siblings,
        "config_present": any(name in siblings for name in ("config.py", "inference_config.py")),
        "metadata_present": bool(metadata),
        "backend": metadata.get("backend"),
        "architecture": metadata.get("model_info", {}).get("backend") or metadata.get("backend"),
        "input_size": metadata.get("input_size") or metadata.get("input"),
        "output_schema": metadata.get("output_schema") or metadata.get("output"),
        "training_examples": metadata.get("training_examples"),
        "metrics": metadata.get("metrics"),
        "framework_versions": {
            key: environment.get(key) for key in ("torch", "mmengine", "mmcv", "mmpose") if environment.get(key)
        },
    }
    if path.suffix.lower() in {".pt", ".pth"}:
        record["safe_checkpoint_inspection"] = (
            safe_checkpoint_summary(path) if inspect else {"status": "not_attempted"}
        )
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("roots", nargs="+", type=Path, help="approved local model artifact roots")
    parser.add_argument("--safe-inspect", type=Path, help="checkpoint to inspect using weights_only=True; no unsafe fallback")
    parser.add_argument("--output", type=Path, help="optional destination for the redacted JSON snapshot")
    args = parser.parse_args()

    files: set[Path] = set()
    for root in args.roots:
        if root.is_file() and is_candidate(root):
            files.add(root.resolve())
        elif root.is_dir():
            files.update(path.resolve() for path in root.rglob("*") if path.is_file() and is_candidate(path))
    ordered = sorted(files, key=lambda item: str(item).casefold())
    inspect_path = args.safe_inspect.resolve() if args.safe_inspect else None
    output = {
        "format_version": 1,
        "source_paths_included": False,
        "candidate_count": len(ordered),
        "candidates": [
            candidate_record(path, f"legacy_model_{index:03d}", path == inspect_path)
            for index, path in enumerate(ordered, 1)
        ],
    }
    rendered = json.dumps(output, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
        print(f"Wrote redacted snapshot with {len(ordered)} candidates.")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
