"""Safe adapter for the optional high-resolution continued-training workflow."""
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import zipfile

from .runtime_paths import resource_path
from .process_utils import hidden_window_kwargs, terminate_process_tree


class HighResolutionTrainingError(RuntimeError):
    pass


class HighResolutionTrainingCancelled(HighResolutionTrainingError):
    pass


def is_universal_multires_model(project, model_id: str) -> bool:
    """True only for a compatible, hash-validated Native + Detail model."""
    from ai_runtime.universal_multires import pipeline_components

    model = next((row for row in project.structure_models() if row["model_id"] == str(model_id)), None)
    if model is None or not _model_schema_matches(project, model):
        return False
    try:
        metadata = json.loads((project.root / str(model["metadata_path"])).read_text(encoding="utf-8"))
        pipeline = metadata.get("inference_pipeline") or {}
        return pipeline.get("mode") == "tiled_native" and set(pipeline_components(metadata)) == {"native", "detail"}
    except (OSError, ValueError, KeyError, TypeError):
        return False


def _model_schema_matches(project, model):
    from .xray_structure_ai import _scheme_matches_model
    return _scheme_matches_model(project, model)


def create_read_only_source_project_copy(project, source_model_id: str, destination: Path) -> Path:
    """Copy SQLite + the chosen model; point copied DB at original images read-only."""
    destination = Path(destination).resolve()
    if destination.exists():
        raise FileExistsError(destination)
    model = next((row for row in project.structure_models() if row["model_id"] == str(source_model_id)), None)
    if model is None or not is_universal_multires_model(project, source_model_id):
        raise HighResolutionTrainingError("Select a compatible Native Full + ROI Detail model first.")
    source_images = project.source.resolve()
    if not source_images.is_dir():
        raise FileNotFoundError(f"The source image folder is unavailable: {source_images}")
    model_file = (project.root / str(model["path"])).resolve()
    metadata_file = (project.root / str(model["metadata_path"])).resolve()
    models_root = project.models_root.resolve()
    if models_root not in model_file.parents or models_root not in metadata_file.parents:
        raise HighResolutionTrainingError("The selected model files are outside the managed model directory.")
    if not model_file.is_file() or not metadata_file.is_file():
        raise FileNotFoundError("The selected model package is incomplete.")
    model_directory = model_file.parent
    if metadata_file.parent != model_directory:
        raise HighResolutionTrainingError("Model components must be stored together for safe copying.")

    destination.mkdir(parents=True)
    (destination / "models").mkdir()
    try:
        source_db = sqlite3.connect(project.db_path.resolve().as_uri() + "?mode=ro", uri=True)
        copied_db = sqlite3.connect(str(destination / "xray_project.sqlite3"))
        try:
            source_db.backup(copied_db)
        finally:
            copied_db.close()
            source_db.close()
        copied_model_dir = destination / "models" / model_directory.name
        shutil.copytree(model_directory, copied_model_dir)
        connection = sqlite3.connect(str(destination / "xray_project.sqlite3"))
        try:
            with connection:
                connection.execute("UPDATE meta SET value=? WHERE key='source'", (str(source_images),))
                connection.execute("UPDATE meta SET value='external_v0' WHERE key='source_storage'")
        finally:
            connection.close()
        return destination
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise


def run_high_resolution_training(
    project,
    source_model_id: str,
    output_zip: Path,
    *,
    python_executable: Path,
    progress,
    cancelled: threading.Event,
    epochs_native: int = 18,
    epochs_detail: int = 18,
) -> dict:
    """Run the prepared script against a temporary copy; never write project DB."""
    output_zip = Path(output_zip).resolve()
    project_root = project.root.resolve()
    if output_zip.exists():
        raise FileExistsError(output_zip)
    if output_zip == project_root or project_root in output_zip.parents:
        raise HighResolutionTrainingError("Save the candidate ZIP outside the active project folder.")
    if not is_universal_multires_model(project, source_model_id):
        raise HighResolutionTrainingError("The selected parent is not a compatible Native + Detail model.")
    script = resource_path("tools", "train_universal_multires.py")
    if not script.is_file():
        raise HighResolutionTrainingError("The high-resolution training tool is not included in this build.")

    output_zip.parent.mkdir(parents=True, exist_ok=True)
    log_lines: list[str] = []
    with tempfile.TemporaryDirectory(prefix="morpholabel_highres_project_") as temporary:
        project_copy = Path(temporary) / "project_copy"
        create_read_only_source_project_copy(project, source_model_id, project_copy)
        command = [
            str(python_executable), str(script), "--project-copy", str(project_copy),
            "--source-model", str(source_model_id), "--output", str(output_zip),
            "--epochs-native", str(int(epochs_native)), "--epochs-detail", str(int(epochs_detail)),
            "--device", "cuda:0",
        ]
        environment = os.environ.copy()
        root = str(script.resolve().parents[1])
        environment["PYTHONPATH"] = root + (os.pathsep + environment["PYTHONPATH"] if environment.get("PYTHONPATH") else "")
        process = subprocess.Popen(
            command, cwd=root, env=environment, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
            bufsize=1, **hidden_window_kwargs(),
        )
        messages: queue.Queue = queue.Queue()

        def read_output():
            try:
                for line in process.stdout:
                    messages.put(line.rstrip())
            finally:
                messages.put(None)

        reader = threading.Thread(target=read_output, daemon=True, name="morpholabel-highres-output")
        reader.start()
        ended = False
        while process.poll() is None:
            if cancelled.wait(0.2):
                terminate_process_tree(process)
                ended = True
                break
        reader.join(timeout=2)
        if process.stdout is not None:
            process.stdout.close()
            while True:
                try:
                    line = messages.get_nowait()
                except queue.Empty:
                    break
                if line is not None:
                    log_lines.append(line)
                    progress(line)
        while True:
            try:
                line = messages.get_nowait()
            except queue.Empty:
                break
            if line is None:
                continue
            log_lines.append(line)
            progress(line)
        if ended:
            output_zip.unlink(missing_ok=True)
            raise HighResolutionTrainingCancelled("High-resolution training was cancelled.")
        return_code = process.wait()
        if return_code != 0:
            output_zip.unlink(missing_ok=True)
            detail = "\n".join(log_lines[-16:]) or f"training process exit code {return_code}"
            raise HighResolutionTrainingError(detail)
        if not output_zip.is_file():
            raise HighResolutionTrainingError("Training finished without producing a model ZIP.")
        with zipfile.ZipFile(output_zip) as archive:
            if archive.testzip() is not None:
                output_zip.unlink(missing_ok=True)
                raise HighResolutionTrainingError("The candidate ZIP failed its CRC check.")
            manifest = json.loads(archive.read("manifest.json"))
        return {"path": output_zip, "model_id": str(manifest.get("model_id") or ""),
                "sha256": __import__("hashlib").sha256(output_zip.read_bytes()).hexdigest(),
                "log": log_lines}
