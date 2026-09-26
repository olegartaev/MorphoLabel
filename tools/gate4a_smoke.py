"""Permanent, canonical-source Gate 4a smoke for the first RTMPose landmark model."""
from __future__ import annotations

import hashlib
import json
import shutil
import time
from pathlib import Path

from PIL import Image

from app.ai_batch import backend_for_model
from app.landmark_ai_service import LandmarkAIService
from app.landmark_bootstrap import resolve_landmark_bootstrap
from app.landmark_dataset import v2_human_final_eligible_image_ids
from app.landmark_frames import restore_standardized_frame
from app.transforms import Transform
from app.landmark_training_workflow import prepare_landmark_training, run_landmark_training
from app.project_storage import Project
from app.ui.preferences import last_project


ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "data" / "ai" / "gate4a_smoke"


def _real_project() -> Project:
    path = last_project()
    if path is None:
        raise RuntimeError("No readable MorphoLabel project is selected; open the user project in MorphoLabel first.")
    return Project.open(path)


def _copy_real_training_subset(source: Project, name: str, *, count: int = 6) -> Project:
    """Copy only standardized QA inputs and current final labels into an isolated project."""
    eligible = list(v2_human_final_eligible_image_ids(source))
    if len(eligible) < 4:
        raise RuntimeError(f"Real project has only {len(eligible)} train-ready images; Gate 4a needs at least four.")
    selected = eligible[: min(max(4, count), len(eligible))]
    target = WORK / name
    source_dir = target / "source"
    source_dir.mkdir(parents=True, exist_ok=False)
    copied: dict[str, str] = {}
    for index, image_id in enumerate(selected):
        standardized = source.cache_root / "standardized" / f"{image_id}.png"
        if not standardized.is_file():
            raise RuntimeError(f"Train-ready image has no standardized cache: {image_id}")
        filename = f"smoke_{index:02d}.png"
        shutil.copy2(standardized, source_dir / filename)
        copied[filename] = image_id
    project = Project.create(name, source_dir, target, source.schema_path, source_types=["png"], source_layout="direct")
    by_name = {str(row.get("original_name")): row["image_id"] for row in project.catalog_rows()}
    for filename, original_id in copied.items():
        image_id = by_name.get(filename)
        if image_id is None:
            raise RuntimeError(f"Disposable project did not catalog copied image: {filename}")
        developed = project.cache_root / "developed" / f"{image_id}.png"
        shutil.copy2(source_dir / filename, developed)
        with Image.open(developed) as image:
            width, height = image.size
        transform = Transform(width, height, 0.0, width / 2, height / 2, 0, 0, width, height)
        project.save_reviewed_crop(image_id, {"developed_full_relpath": f"cache/developed/{image_id}.png", "standardized_relpath": f"cache/standardized/{image_id}.png", "crop_bounds": [0, 0, width, height], "rotation_degrees": 0.0, "transform": transform.__dict__, "normalization_status": "PASS"})
        restore_standardized_frame(project, image_id)
        points = source.load_landmarks(original_id)
        for landmark in source.schema:
            ident = int(landmark["id"])
            point = points.get(ident)
            if point is None:
                raise RuntimeError(f"Train-ready source label is missing: {original_id}/{ident}")
            state = str(point.get("state") or "manual")
            project.save_landmark(
                image_id, ident, point.get("x_standardized"), point.get("y_standardized"), state,
                provenance=str(point.get("provenance") or "manual"),
                model_id=point.get("model_id"), predicted_x=point.get("predicted_x"),
                predicted_y=point.get("predicted_y"), confidence=point.get("confidence"),
            )
        project.mark_checked(image_id)
    if project.active_model_readonly("landmark") is not None:
        raise AssertionError("Disposable first-model project unexpectedly has an active landmark model")
    if any(project.model_metadata(f"rtmpose_v{index:03d}") for index in range(1, 4)):
        raise AssertionError("Disposable first-model project unexpectedly has landmark model rows")
    return project


def _assert_bootstrap(plan, project: Project) -> None:
    info = plan.training_settings.get("bootstrap") or {}
    config = Path(info.get("config_path") or "")
    checkpoint = Path(info.get("checkpoint_path") or "")
    if not config.is_file() or not checkpoint.is_file():
        raise RuntimeError("Prepared first-model plan lost its resolved bootstrap assets")
    actual = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    if actual != info.get("checksum"):
        raise RuntimeError("Prepared first-model bootstrap checkpoint checksum changed before training")
    if plan.parent_model_id is not None or plan.model_id != "rtmpose_v001":
        raise AssertionError(f"Expected zero-model rtmpose_v001 plan, got parent={plan.parent_model_id!r} model={plan.model_id!r}")


def _gui_preflight(project: Project) -> dict:
    """Exercise the production Landmarks -> Train preflight without starting training."""
    from app.ui.shell import ProductionShell

    shell = ProductionShell(project)
    captured: dict[str, object] = {}
    try:
        shell.select("landmarks")
        view = shell.current_view
        original = view._confirm_training
        view._confirm_training = lambda plan: captured.setdefault("plan", plan)
        view.preflight()
        deadline = time.monotonic() + 180
        while "plan" not in captured and time.monotonic() < deadline:
            shell.update()
            time.sleep(0.05)
        view._confirm_training = original
        if "plan" not in captured:
            raise RuntimeError("Production Landmarks preflight did not reach its confirmation dialog")
        plan = captured["plan"]
        _assert_bootstrap(plan, project)
        return {"eligible": len(plan.image_ids), "model_id": plan.model_id, "parent_model_id": plan.parent_model_id}
    finally:
        for child in tuple(shell.winfo_children()):
            try:
                child.destroy()
            except Exception:
                pass
        shell.destroy()


def _main() -> int:
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True, exist_ok=False)
    source = _real_project()
    bootstrap = resolve_landmark_bootstrap(source)
    if bootstrap.checksum != hashlib.sha256(bootstrap.checkpoint_path.read_bytes()).hexdigest():
        raise RuntimeError("Resolved bootstrap asset failed checksum verification")

    preflight_project = _copy_real_training_subset(source, "gui_preflight")
    gui = _gui_preflight(preflight_project)

    project = _copy_real_training_subset(source, "training")
    plan = prepare_landmark_training(project, seed=424242, batch_size=1, epochs=1)
    _assert_bootstrap(plan, project)
    plan.training_settings.update({"max_epochs": 1, "batch_size": 1, "workers": 0,
                                  "persistent_workers": False, "checkpoint_interval": 1,
                                  "max_keep_ckpts": 1, "smoke": True})
    result = run_landmark_training(project, plan)
    artifact = project.data_root / "ai" / "models" / "rtmpose_v001"
    epoch = artifact / "epoch_1.pth"
    final = artifact / "best_engineering_validation.pth"
    if not epoch.is_file() or epoch.stat().st_size <= 0:
        raise AssertionError("Real one-epoch training did not create epoch_1.pth")
    if not final.is_file() or final.stat().st_size <= 0:
        raise AssertionError("First-model finalization did not create best_engineering_validation.pth")
    active = project.active_model_readonly("landmark")
    if not active or active.get("model_id") != "rtmpose_v001":
        raise AssertionError("Valid first model was not activated")
    registered = project.model_metadata("rtmpose_v001")
    if not registered:
        raise AssertionError("Finalized first model was not registered")
    model, backend = backend_for_model(project, "rtmpose_v001")
    image_id = project.catalog_rows()[0]["image_id"]
    service = LandmarkAIService(project, backend)
    request = service._request(image_id)
    prediction = backend.predict(request)
    returned = [item.landmark_id for item in prediction.landmarks]
    expected = [int(item["id"]) for item in project.schema]
    if prediction.model_id != "rtmpose_v001" or returned != expected:
        raise AssertionError("First-model inference did not return the current schema landmark IDs in order")
    import math
    if not all(math.isfinite(point.x) and math.isfinite(point.y) and (point.confidence is None or math.isfinite(point.confidence)) for point in prediction.landmarks):
        raise AssertionError("First-model inference returned non-finite values")
    later = prepare_landmark_training(project, seed=424243, batch_size=1, epochs=1)
    if later.model_id != "rtmpose_v002" or later.parent_model_id != "rtmpose_v001":
        raise AssertionError("Later model lineage did not start at v002 from v001")
    summary = {
        "source_project": str(source.root), "bootstrap_config": str(bootstrap.config_path),
        "bootstrap_checkpoint": str(bootstrap.checkpoint_path), "gui_preflight": gui,
        "training_result": result, "epoch_checkpoint": str(epoch), "final_checkpoint": str(final),
        "registered": bool(registered), "active_model": active.get("model_id"),
        "inference_model": prediction.model_id, "inference_landmark_ids": returned,
        "later_model": later.model_id, "later_parent": later.parent_model_id,
    }
    (WORK / "result.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(json.dumps(summary, indent=2, default=str))
    return 0


def main() -> int:
    try:
        return _main()
    except BaseException:
        import traceback
        WORK.mkdir(parents=True, exist_ok=True)
        (WORK / "failure.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BaseException:
        import traceback
        WORK.mkdir(parents=True, exist_ok=True)
        (WORK / "failure.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise
