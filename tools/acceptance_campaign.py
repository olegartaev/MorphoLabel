"""One-shot destructive acceptance campaign for a disposable MorphoLabel project copy.

This is developer tooling, not a user-facing application feature.  The parent
process isolates every scenario so one crash/hang cannot stop later scenarios.
Only the explicitly supplied project copy may be modified.  Original source
images are fingerprinted by metadata before/after and are never read for hash
content by this runner.
"""
from __future__ import annotations

import argparse
import faulthandler
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMAGE_EXTENSIONS = {".nef", ".jpg", ".jpeg", ".png", ".tif", ".tiff"}
EXPECTED_COPY_TOKENS = ("copy", "копия", "acceptance", "test")
DEFAULT_VERSION = "0.5.0-beta.2"


def _now():
    return datetime.now(timezone.utc).isoformat()


def _jsonable(value):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (set, frozenset, tuple)):
        return list(value)
    raise TypeError(type(value).__name__)


def _write_json(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, default=_jsonable),
        encoding="utf-8",
    )


def _inside(path, root):
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def _load_config(project_root):
    path = Path(project_root) / "project.yaml"
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("project.yaml is not an object")
    return value


def _validate_destructive_target(project_root, output_root):
    project_root = Path(project_root).resolve()
    output_root = Path(output_root).resolve()
    if not project_root.is_dir():
        raise RuntimeError(f"project copy does not exist: {project_root}")
    required = [project_root / "project.yaml", project_root / "landmark_schema.csv"]
    if not all(path.is_file() for path in required):
        raise RuntimeError("target is not a structurally valid MorphoLabel project")
    db = project_root / "project_data" / "project.sqlite"
    if not db.is_file():
        db = project_root / "project.sqlite"
    if not db.is_file():
        raise RuntimeError("project SQLite database is missing")
    folded = str(project_root).casefold()
    if not any(token in folded for token in EXPECTED_COPY_TOKENS):
        raise RuntimeError("refusing destructive campaign: project path is not visibly marked as a copy/test")
    cfg = _load_config(project_root)
    source_root = Path(str(cfg.get("source_root") or "")).expanduser().resolve()
    if source_root == project_root:
        raise RuntimeError("refusing destructive campaign: source root equals project root")
    if _inside(output_root, project_root) or _inside(output_root, source_root):
        raise RuntimeError("campaign output must be outside both project copy and source root")
    return db, source_root


def source_metadata_fingerprint(source_root):
    root = Path(source_root)
    digest = hashlib.sha256()
    count = 0
    total_bytes = 0
    if not root.is_dir():
        return {"exists": False, "count": 0, "bytes": 0, "digest": None}
    items = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.casefold() not in IMAGE_EXTENSIONS:
            continue
        stat = path.stat()
        rel = path.relative_to(root).as_posix()
        items.append((rel, stat.st_size, stat.st_mtime_ns))
    for rel, size, mtime_ns in sorted(items, key=lambda item: item[0].casefold()):
        digest.update(rel.encode("utf-8", errors="surrogatepass"))
        digest.update(b"\0")
        digest.update(str(size).encode("ascii"))
        digest.update(b"\0")
        digest.update(str(mtime_ns).encode("ascii"))
        digest.update(b"\n")
        count += 1
        total_bytes += int(size)
    return {"exists": True, "count": count, "bytes": total_bytes, "digest": digest.hexdigest()}


def _kill_tree(proc):
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=20,
                check=False,
            )
        else:
            proc.kill()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def run_process(name, command, *, timeout, env, scenario_dir):
    scenario_dir = Path(scenario_dir)
    scenario_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    stdout_path = scenario_dir / "stdout.txt"
    stderr_path = scenario_dir / "stderr.txt"
    with stdout_path.open("w", encoding="utf-8", errors="replace") as out, stderr_path.open(
        "w", encoding="utf-8", errors="replace"
    ) as err:
        proc = subprocess.Popen(
            [str(part) for part in command],
            stdout=out,
            stderr=err,
            cwd=str(ROOT),
            env=env,
            text=True,
        )
        timed_out = False
        try:
            code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_tree(proc)
            try:
                code = proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                code = None
    elapsed = time.monotonic() - started
    status = "HANG" if timed_out else ("PASS" if code == 0 else "FAIL")
    return {
        "name": name,
        "status": status,
        "returncode": code,
        "elapsed_seconds": round(elapsed, 3),
        "stdout": str(stdout_path),
        "stderr": str(stderr_path),
    }


def gui_startup_smoke(exe, *, timeout, env, scenario_dir):
    scenario_dir = Path(scenario_dir)
    scenario_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    proc = subprocess.Popen(
        [str(exe)],
        cwd=str(Path(exe).parent),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + min(timeout, 15)
    while time.monotonic() < deadline and proc.poll() is None:
        time.sleep(0.25)
    if proc.poll() is None:
        status = "PASS"
        code = None
        _kill_tree(proc)
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            pass
    else:
        status = "FAIL"
        code = proc.returncode
    return {
        "name": "installed_gui_startup",
        "status": status,
        "returncode": code,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "stdout": None,
        "stderr": None,
    }


def _child_env(output_root):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    local = Path(output_root) / "state" / "local"
    roaming = Path(output_root) / "state" / "roaming"
    local.mkdir(parents=True, exist_ok=True)
    roaming.mkdir(parents=True, exist_ok=True)
    env["LOCALAPPDATA"] = str(local)
    env["APPDATA"] = str(roaming)
    env["PYTHONUNBUFFERED"] = "1"
    return env


def _scenario_project_open(project_root):
    from app.project_storage import Project

    project = Project.open(project_root)
    rows = project.catalog_rows()
    crop = project.active_model_readonly("crop")
    landmark = project.active_model_readonly("landmark")
    return {
        "images": len(rows),
        "excluded": sum(bool(row.get("excluded")) for row in rows),
        "active_crop_model": None if crop is None else crop.get("model_id"),
        "active_landmark_model": None if landmark is None else landmark.get("model_id"),
    }


def _scenario_persistence_roundtrip(project_root):
    from app.project_storage import Project

    key = "_acceptance_campaign_probe"
    value = {"written_at": _now(), "token": "roundtrip"}
    project = Project.open(project_root)
    project.set_ui_state(key, value)
    reopened = Project.open(project_root)
    loaded = reopened.get_ui_state(key)
    if loaded != value:
        raise AssertionError(f"persisted UI state mismatch: {loaded!r}")
    return {"roundtrip": True}


def _scenario_exclusion_roundtrip(project_root):
    from app.project_storage import Project

    project = Project.open(project_root)
    row = next((item for item in project.catalog_rows() if not item.get("excluded")), None)
    if row is None:
        raise RuntimeError("no included image is available")
    image_id = row["image_id"]
    before = project.image_exclusion(image_id)
    project.exclude_image(image_id, "Acceptance test", "temporary roundtrip")
    if not Project.open(project_root).image_exclusion(image_id).get("excluded"):
        raise AssertionError("excluded state did not persist")
    if before.get("excluded"):
        project.exclude_image(image_id, before.get("exclusion_reason") or "Other", before.get("exclusion_note"))
    else:
        project.restore_image(image_id)
    if bool(Project.open(project_root).image_exclusion(image_id).get("excluded")) != bool(before.get("excluded")):
        raise AssertionError("exclusion restore did not persist")
    return {"roundtrip": True}


def _scenario_landmark_roundtrip(project_root):
    from app.project_storage import Project

    project = Project.open(project_root)
    chosen = None
    for row in project.catalog_rows():
        if row.get("excluded"):
            continue
        points = project.load_landmarks(row["image_id"])
        for landmark_id, point in points.items():
            if point.get("state") != "missing" and point.get("x_standardized") is not None and point.get("y_standardized") is not None:
                chosen = (row["image_id"], int(landmark_id), dict(point))
                break
        if chosen:
            break
    if chosen is None:
        raise RuntimeError("no placed landmark is available")
    image_id, landmark_id, old = chosen
    x = float(old["x_standardized"])
    y = float(old["y_standardized"])
    project.save_landmark(image_id, landmark_id, x + 0.125, y, "corrected", "corrected_by_human")
    changed = Project.open(project_root).load_landmarks(image_id)[landmark_id]
    if abs(float(changed["x_standardized"]) - (x + 0.125)) > 1e-9:
        raise AssertionError("landmark correction did not persist")
    project.save_landmark(
        image_id,
        landmark_id,
        x,
        y,
        old.get("state") or "manual",
        old.get("provenance") or "manual",
        model_id=old.get("model_id"),
        predicted_x=old.get("predicted_x"),
        predicted_y=old.get("predicted_y"),
        confidence=old.get("confidence"),
        prediction_run_id=old.get("prediction_run_id"),
        reviewed=bool(old.get("reviewed", 1)),
    )
    restored = Project.open(project_root).load_landmarks(image_id)[landmark_id]
    if abs(float(restored["x_standardized"]) - x) > 1e-9:
        raise AssertionError("landmark restore did not persist")
    return {"roundtrip": True}


def _scenario_exports(project_root):
    from app.measurements import export_measurements
    from app.project_storage import Project
    from app.results_export import export_project_results

    project = Project.open(project_root)
    results = export_project_results(project)
    measurements = export_measurements(project)
    for path in (results["tps"], results["specimens"], measurements["path"]):
        if not Path(path).is_file():
            raise AssertionError(f"export missing: {path}")
    return {
        "result_ready": results.get("ready"),
        "measurement_rows": measurements.get("rows"),
        "measurement_count": measurements.get("measurements"),
    }


def _scenario_counts_lineage(project_root):
    from app.landmark_dataset import training_ready_image_ids
    from app.project_storage import Project

    project = Project.open(project_root)
    crop = project.active_model_readonly("crop")
    landmark = project.active_model_readonly("landmark")
    counts = project.landmark_counts()
    ready = training_ready_image_ids(project)
    return {
        "landmark_counts": counts,
        "training_ready": len(ready),
        "active_crop_model": None if crop is None else crop.get("model_id"),
        "active_landmark_model": None if landmark is None else landmark.get("model_id"),
    }


def _scenario_gui_sections(project_root):
    from app.project_storage import Project
    from app.ui.shell import ProductionShell

    shell = ProductionShell(Project.open(project_root))
    sections = ["project", "crop", "landmarks", "measurements", "export"]
    state = {"index": 0, "opened": []}
    deadline = time.monotonic() + 90

    def step():
        if time.monotonic() > deadline:
            raise TimeoutError("GUI section smoke exceeded internal deadline")
        if shell.context.project is None:
            shell.after(200, step)
            return
        if state["index"] >= len(sections):
            print(json.dumps({"gui_sections": state["opened"]}), flush=True)
            shell.after(500, shell.destroy)
            return
        key = sections[state["index"]]
        shell.select(key)
        shell.update_idletasks()
        state["opened"].append(shell.context.section)
        state["index"] += 1
        shell.after(900, step)

    shell.after(500, step)
    shell.mainloop()
    if state["opened"] != sections:
        raise AssertionError(f"GUI sections mismatch: {state['opened']!r}")
    return {"sections": state["opened"]}


def _scenario_project_ai_inference(project_root):
    from app.ai_batch import active_backend
    from app.landmark_ai_service import LandmarkAIService
    from app.project_storage import Project

    project = Project.open(project_root)
    _model, backend = active_backend(project)
    row = next((item for item in project.catalog_rows() if not item.get("excluded") and item.get("has_crop")), None)
    if row is None:
        raise RuntimeError("no crop-ready image is available for project AI inference")
    service = LandmarkAIService(project, backend)
    request = service._request(row["image_id"])
    prediction = backend.predict(request)
    service._validate(prediction, request)
    if len(prediction.landmarks) != len(project.schema):
        raise AssertionError("project inference landmark count does not match schema")
    return {"landmarks": len(prediction.landmarks), "model_id": backend.model_id}


def _scenario_crop_training_candidate(project_root):
    from app.crop_training import train_project
    from app.project_storage import Project

    project = Project.open(project_root)
    result = train_project(project, seed=260927)
    if not isinstance(result, dict):
        raise AssertionError("crop training returned no result")
    if not result.get("trained"):
        raise RuntimeError(f"crop training did not run: {result.get('reason')}")
    return {
        "trained": True,
        "model_id": result.get("model_id"),
        "training_examples": result.get("training_examples"),
        "new_model_activated": result.get("new_model_activated"),
    }


def _scenario_landmark_training_one_epoch(project_root):
    from app.landmark_training_workflow import prepare_landmark_training, run_landmark_training
    from app.project_storage import Project

    project = Project.open(project_root)
    plan = prepare_landmark_training(
        project,
        seed=260927,
        epochs=1,
        batch_size=1,
        progress_callback=lambda stage, detail: print(f"{stage}: {detail}", flush=True),
    )
    result = run_landmark_training(
        project,
        plan,
        progress_callback=lambda *parts: print(
            "TRAINING: " + " / ".join(str(part) for part in parts), flush=True
        ),
    )
    if result is None:
        raise AssertionError("landmark training returned no result")
    return {
        "model_id": plan.model_id,
        "dataset_id": plan.dataset_id,
        "parent_model_id": plan.parent_model_id,
        "images": len(plan.image_ids),
    }


def _scenario_diagnostic_bundle(project_root):
    from app.diagnostics import create_diagnostic_bundle
    from app.project_storage import Project
    from app.project_runtime import scoped_project

    project = Project.open(project_root)
    with scoped_project(project):
        bundle = create_diagnostic_bundle()
    if not Path(bundle).is_file() or Path(bundle).stat().st_size <= 0:
        raise AssertionError("diagnostic ZIP was not created")
    return {"bundle_bytes": Path(bundle).stat().st_size}


def _scenario_final_reopen(project_root):
    from app.project_storage import Project

    project = Project.open(project_root)
    rows = project.catalog_rows()
    if not rows:
        raise AssertionError("catalog became empty")
    return {
        "images": len(rows),
        "landmarks": project.count("landmarks"),
        "crops": project.count("crops"),
        "models": project.count("models"),
    }


CHILD_SCENARIOS = {
    "project_open": _scenario_project_open,
    "persistence_roundtrip": _scenario_persistence_roundtrip,
    "exclusion_roundtrip": _scenario_exclusion_roundtrip,
    "landmark_roundtrip": _scenario_landmark_roundtrip,
    "exports": _scenario_exports,
    "counts_lineage": _scenario_counts_lineage,
    "gui_sections": _scenario_gui_sections,
    "project_ai_inference": _scenario_project_ai_inference,
    "crop_training_candidate": _scenario_crop_training_candidate,
    "landmark_training_one_epoch": _scenario_landmark_training_one_epoch,
    "diagnostic_bundle": _scenario_diagnostic_bundle,
    "final_reopen": _scenario_final_reopen,
}


def run_child(args):
    scenario_dir = Path(args.scenario_dir)
    scenario_dir.mkdir(parents=True, exist_ok=True)
    dump_path = scenario_dir / "thread_dump.txt"
    dump = dump_path.open("w", encoding="utf-8", errors="replace")
    delay = max(10, int(args.child_timeout * 0.8))
    faulthandler.enable(file=dump, all_threads=True)
    faulthandler.dump_traceback_later(delay, file=dump, exit=False)
    try:
        result = CHILD_SCENARIOS[args.child_scenario](Path(args.project).resolve())
        print(json.dumps({"status": "PASS", "result": result}, ensure_ascii=False, default=_jsonable))
        return 0
    except Exception as exc:
        traceback.print_exc()
        print(json.dumps({"status": "FAIL", "error_type": type(exc).__name__, "error": str(exc)}, ensure_ascii=False))
        return 1
    finally:
        faulthandler.cancel_dump_traceback_later()
        dump.close()


def _tail(path, limit=8000):
    if not path:
        return ""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text[-limit:]


def _sanitize(text, replacements):
    value = str(text)
    for raw, label in replacements:
        if raw:
            value = value.replace(str(raw), label)
            value = value.replace(str(raw).replace("\\", "/"), label)
    return value


def build_support_report(results, *, project_root, source_root, output_root, source_before, source_after, expected_version):
    replacements = [
        (str(project_root), "<PROJECT_COPY>"),
        (str(source_root), "<SOURCE_ROOT>"),
        (str(output_root), "<CAMPAIGN_OUTPUT>"),
        (str(ROOT), "<REPO>"),
        (str(Path.home()), "<HOME>"),
    ]
    compact = []
    for item in results:
        row = {
            "name": item["name"],
            "status": item["status"],
            "returncode": item.get("returncode"),
            "elapsed_seconds": item.get("elapsed_seconds"),
        }
        if item["status"] != "PASS":
            detail = (_tail(item.get("stderr")) + "\n" + _tail(item.get("stdout"))).strip()
            row["failure_tail"] = _sanitize(detail, replacements)
        compact.append(row)
    source_unchanged = source_before == source_after
    return {
        "format_version": 1,
        "created_at": _now(),
        "expected_version": expected_version,
        "scenario_count": len(compact),
        "pass": sum(item["status"] == "PASS" for item in compact),
        "fail": sum(item["status"] == "FAIL" for item in compact),
        "hang": sum(item["status"] == "HANG" for item in compact),
        "source_images": {
            "count_before": source_before.get("count"),
            "count_after": source_after.get("count"),
            "bytes_before": source_before.get("bytes"),
            "bytes_after": source_after.get("bytes"),
            "metadata_unchanged": source_unchanged,
        },
        "scenarios": compact,
    }


def run_campaign(args):
    project_root = Path(args.project).resolve()
    output_root = Path(args.output).resolve()
    setup = Path(args.setup).resolve()
    if not setup.is_file():
        raise RuntimeError(f"published setup is missing: {setup}")
    _db, source_root = _validate_destructive_target(project_root, output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    env = _child_env(output_root)

    source_before = source_metadata_fingerprint(source_root)
    _write_json(output_root / "source_before.json", source_before)

    results = []
    installed = output_root / "installed"
    install_args = [
        setup,
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART",
        f"/DIR={installed}",
    ]
    results.append(run_process(
        "install_published_release",
        install_args,
        timeout=600,
        env=env,
        scenario_dir=output_root / "scenarios" / "install_published_release",
    ))
    exe = installed / "MorphoLabel.exe"

    if exe.is_file():
        results.append(run_process(
            "installed_version",
            [exe, "--version"],
            timeout=60,
            env=env,
            scenario_dir=output_root / "scenarios" / "installed_version",
        ))
        version_out = _tail(results[-1].get("stdout"), 1000).strip()
        if results[-1]["status"] == "PASS" and version_out != args.expected_version:
            results[-1]["status"] = "FAIL"
            results[-1]["version_mismatch"] = version_out
            Path(results[-1]["stderr"]).write_text(
                f"expected {args.expected_version}, got {version_out}\n", encoding="utf-8"
            )
        results.append(run_process(
            "installed_core_self_test",
            [exe, "--self-test"],
            timeout=180,
            env=env,
            scenario_dir=output_root / "scenarios" / "installed_core_self_test",
        ))
        results.append(gui_startup_smoke(
            exe,
            timeout=30,
            env=env,
            scenario_dir=output_root / "scenarios" / "installed_gui_startup",
        ))
        results.append(run_process(
            "published_ai_install",
            [exe, "--install-ai"],
            timeout=2400,
            env=env,
            scenario_dir=output_root / "scenarios" / "published_ai_install",
        ))
        ai_report = output_root / "ai_self_test.json"
        results.append(run_process(
            "published_ai_cuda_inference_training",
            [exe, "--ai-self-test", "--require-cuda", "--include-training", "--diagnostic-report", ai_report],
            timeout=1800,
            env=env,
            scenario_dir=output_root / "scenarios" / "published_ai_cuda_inference_training",
        ))
    else:
        for name in (
            "installed_version",
            "installed_core_self_test",
            "installed_gui_startup",
            "published_ai_install",
            "published_ai_cuda_inference_training",
        ):
            results.append({
                "name": name,
                "status": "FAIL",
                "returncode": None,
                "elapsed_seconds": 0.0,
                "stdout": None,
                "stderr": None,
                "error": "installed executable missing",
            })

    child_timeouts = {
        "project_open": 600,
        "persistence_roundtrip": 300,
        "exclusion_roundtrip": 300,
        "landmark_roundtrip": 300,
        "exports": 900,
        "counts_lineage": 900,
        "gui_sections": 240,
        "project_ai_inference": 900,
        "crop_training_candidate": 2400,
        "landmark_training_one_epoch": 5400,
        "diagnostic_bundle": 300,
        "final_reopen": 900,
    }
    for name, timeout in child_timeouts.items():
        scenario_dir = output_root / "scenarios" / name
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--child-scenario",
            name,
            "--project",
            project_root,
            "--scenario-dir",
            scenario_dir,
            "--child-timeout",
            str(timeout),
        ]
        results.append(run_process(
            name,
            command,
            timeout=timeout,
            env=env,
            scenario_dir=scenario_dir,
        ))

    source_after = source_metadata_fingerprint(source_root)
    _write_json(output_root / "source_after.json", source_after)
    source_guard = {
        "name": "source_images_unchanged",
        "status": "PASS" if source_after == source_before else "FAIL",
        "returncode": 0 if source_after == source_before else 1,
        "elapsed_seconds": 0.0,
        "stdout": None,
        "stderr": None,
    }
    results.append(source_guard)

    uninstaller = installed / "unins000.exe"
    if uninstaller.is_file():
        results.append(run_process(
            "uninstall_published_release",
            [uninstaller, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
            timeout=300,
            env=env,
            scenario_dir=output_root / "scenarios" / "uninstall_published_release",
        ))
    else:
        results.append({
            "name": "uninstall_published_release",
            "status": "FAIL",
            "returncode": None,
            "elapsed_seconds": 0.0,
            "stdout": None,
            "stderr": None,
            "error": "uninstaller missing",
        })

    _write_json(output_root / "campaign-local.json", {
        "created_at": _now(),
        "project_root": str(project_root),
        "source_root": str(source_root),
        "setup": str(setup),
        "expected_version": args.expected_version,
        "results": results,
    })
    support = build_support_report(
        results,
        project_root=project_root,
        source_root=source_root,
        output_root=output_root,
        source_before=source_before,
        source_after=source_after,
        expected_version=args.expected_version,
    )
    _write_json(output_root / "support-report.json", support)
    lines = [
        f"MorphoLabel acceptance campaign — {support['created_at']}",
        f"Expected release: {args.expected_version}",
        "",
    ]
    for item in support["scenarios"]:
        lines.append(f"{item['name']:<42} {item['status']:>4}  {item.get('elapsed_seconds', 0):>8}s")
    lines.extend([
        "",
        f"PASS={support['pass']} FAIL={support['fail']} HANG={support['hang']}",
        f"SOURCE_IMAGES_UNCHANGED={'YES' if support['source_images']['metadata_unchanged'] else 'NO'}",
    ])
    (output_root / "support-summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print((output_root / "support-summary.txt").read_text(encoding="utf-8"))
    return 0 if support["fail"] == 0 and support["hang"] == 0 else 2


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--project")
    parser.add_argument("--setup")
    parser.add_argument("--output")
    parser.add_argument("--expected-version", default=DEFAULT_VERSION)
    parser.add_argument("--child-scenario", choices=tuple(CHILD_SCENARIOS))
    parser.add_argument("--scenario-dir")
    parser.add_argument("--child-timeout", type=int, default=300)
    args = parser.parse_args(argv)
    if args.child_scenario:
        if not args.project or not args.scenario_dir:
            parser.error("--child-scenario requires --project and --scenario-dir")
        return run_child(args)
    if not all((args.project, args.setup, args.output)):
        parser.error("campaign requires --project, --setup and --output")
    return run_campaign(args)


if __name__ == "__main__":
    raise SystemExit(main())
