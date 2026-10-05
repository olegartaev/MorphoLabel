"""Scientific fingerprints captured at 3d1c303, before runtime separation.

Projects are generated outside the checkout. Only portable, normalized JSON
fingerprints are checked in; timestamps, temporary paths and generated IDs are
normalized for the static oracle. Reopen checks additionally compare exact rows.
"""
import hashlib
import csv
import io
import base64
import json
import re
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path

from app.measurements import save_measurements
from app.operator_qc import (create_repeat_session, set_repeat_landmark,
                             complete_repeat_session, evaluate_operator_sessions,
                             save_operator_report)
from app.landmark_attention_queue import start
from app.project_storage import Project
from app.xray_project import XRayProject
from app.xray_structure_ai import structure_schema_digest
from app.xray_result_qc import build_result_qc, start_result_review_queue
from tests import test_release_torture as fixtures
from tests.current_fixtures import make_reviewed_crop

ORACLE = Path(__file__).with_name("fixtures") / "architecture_baseline.json"
LEGACY = ORACLE.with_name("architecture_legacy.json")


def persisted_rows(project, *, include_ui=True):
    path = project.db_path if isinstance(project, XRayProject) else project.path
    with closing(sqlite3.connect(path)) as db:
        db.row_factory = sqlite3.Row
        tables = [r[0] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {table: [dict(row) for row in db.execute(f'SELECT * FROM "{table}" ORDER BY rowid')]
                for table in tables if include_ui or table != "ui_state"}


class ArchitectureCompatibilityTests(unittest.TestCase):
    setUp = fixtures.ReleaseTortureTests.setUp
    complete_xray = fixtures.ReleaseTortureTests.complete_xray
    export_bytes = fixtures.ReleaseTortureTests.export_bytes

    def test_materialized_pre_refactor_storage_and_sidecars(self):
        bundle = json.loads(LEGACY.read_text(encoding="utf-8"))
        self.assertEqual("3d1c30367458d22a378abf1f675a0b59d74a4ae9", bundle["start_sha"])
        for name, p in (("landmark", self.landmark), ("xray", self.xray)):
            path = p.path if name == "landmark" else p.db_path
            # Only disposable test projects are overwritten, never repository data.
            self.assertTrue(path.is_relative_to(self.root))
            path.unlink()
            sql = bundle[name]["sql"].replace("<TEMP>", str(self.root))
            with closing(sqlite3.connect(path)) as db:
                db.executescript(sql)
                for table, rows in bundle[name]["rows"].items():
                    for row in rows:
                        columns = ','.join(f'"{key}"' for key in row)
                        values = [v.replace("<TEMP>", str(self.root)) if isinstance(v, str) else v for v in row.values()]
                        db.execute(f'INSERT INTO "{table}" ({columns}) VALUES ({",".join("?" for _ in row)})', values)
                db.commit()
            for relative, data in bundle[name]["files"].items():
                target = p.root / relative
                self.assertTrue(target.resolve().is_relative_to(self.root.resolve()))
                target.parent.mkdir(parents=True, exist_ok=True)
                content = base64.b64decode(data)
                content = content.replace(b"<TEMP_ESC>", json.dumps(str(self.root))[1:-1].encode())
                target.write_bytes(content.replace(b"<TEMP>", str(self.root).encode()))
        self.landmark = Project.open(self.landmark.root)
        self.xray = XRayProject(self.xray.root)
        self.specimens = bundle["specimens"]
        self.landmark_repeat = bundle["landmark_repeat"]
        self.xray_repeat = self.xray.structure_repeatability(bundle["xray_repeat"])
        self.assertEqual(json.loads(ORACLE.read_text(encoding="utf-8")), self.snapshot())
        for p in (self.landmark, self.xray):
            before = persisted_rows(p)
            output = self.export_bytes(p)
            reopened = Project.open(p.root) if isinstance(p, Project) else XRayProject(p.root)
            self.assertEqual(before, persisted_rows(reopened))
            self.assertEqual(output, self.export_bytes(reopened))

    def populate(self):
        p = self.landmark
        for image_id in self.landmark_ids:
            make_reviewed_crop(p, image_id, 160, 100)
            p.save_landmark(image_id, 1, 10, 10, "manual")
            p.save_landmark(image_id, 2, 16, 18, "manual")
            p.mark_checked(image_id)
        locality = p.catalog_rows()[0]["locality"]
        p.set_locality_calibration(locality, self.landmark_ids[0], 2, "mm", {})
        save_measurements(p, [{"abbr": "LEN", "name": "Length", "point1": 1, "point2": 2}])
        manifest = p.data_root / "ai" / "datasets" / "frozen" / "manifest.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps({"schema_landmarks": p.schema, "images": self.landmark_ids}), encoding="utf-8")
        for ident, parent in (("old_lm_parent", None), ("old_lm_child", "old_lm_parent")):
            p.register_model(ident, "landmark", path=f"models/{ident}", active=True,
                             dataset_id="frozen", parent_model_id=parent,
                             dataset_manifest_path="ai/datasets/frozen/manifest.json")
        p.register_model("old_crop", "crop", path="models/old_crop", active=True)
        p.set_ui_state("crop_active_batch", {"ids": self.landmark_ids, "position": 1})
        start(p, self.landmark_ids, batch_id="compatibility")
        session = create_repeat_session(p, self.landmark_ids[0])
        sid = session["repeat_session_id"]
        set_repeat_landmark(p, sid, 1, 11, 10)
        set_repeat_landmark(p, sid, 2, 16, 18)
        complete_repeat_session(p, sid)
        save_operator_report(p, evaluate_operator_sessions(p, [sid]), "frozen_qc")
        self.landmark_repeat = sid
        p.set_ui_state("compatibility_repeat", {"session_id": sid, "report": "frozen_qc"})

        p = self.xray
        p.set_current_selection(specimen_id=self.specimens[1])
        for sid in self.specimens:
            self.complete_xray(sid)
        p.save_scheme(p.scheme, "Pre-refactor scheme version")
        self.xray_repeat = p.start_structure_repeatability(2, seed=17)
        for sid in self.xray_repeat["ids"]:
            for number in (self.xray_repeat["annotation1_pass_no"], self.xray_repeat["annotation2_pass_no"]):
                self.complete_xray(sid, number, .01)
        membership = [{"specimen_id": sid, "split": "val" if i < 2 else "train"}
                      for i, sid in enumerate(self.specimens)]
        for ident, parent in (("old_xr_parent", None), ("old_xr_child", "old_xr_parent")):
            p.register_structure_model(ident, f"models/{ident}/model.pth", f"models/{ident}/model.json",
                                       parent, structure_schema_digest(p.scheme), "resnet18_heatmap_v1",
                                       {"frozen_metric": .75}, membership)
        p.set_ui_state("xray_crop_active_batch", {"ids": self.plates, "position": 1})
        p.set_ui_state("xray_structure_active_batch", {"ids": self.specimens, "position": 1, "pass_no": 1})
        start_result_review_queue(p, build_result_qc(p)["issues"])

    def snapshot(self):
        ids = {}
        # Map generated IDs by creation order, shared by storage and exports.
        for i, sid in enumerate(self.specimens):
            ids[sid] = f"<specimen-{i}>"
        ids[self.landmark_repeat] = "<landmark-repeat>"
        ids[self.xray_repeat["run_id"]] = "<xray-repeat>"

        def clean(value):
            if isinstance(value, dict):
                return {k: ("<mtime>" if k == "mtime_ns" else clean(v)) for k, v in value.items()}
            if isinstance(value, (list, tuple)):
                return [clean(v) for v in value]
            if isinstance(value, bytes):
                value = value.decode("utf-8-sig")
            if not isinstance(value, str):
                return value
            for old, new in ids.items():
                value = value.replace(old, new)
            def generated(match):
                token = match.group(0)
                return ids.setdefault(token, f"<generated-{len(ids)}>")
            value = re.sub(r"(?<![0-9a-f])[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?![0-9a-f])|(?<![0-9a-f])[0-9a-f]{32}(?![0-9a-f])", generated, value)
            value = value.replace(str(self.root), "<TEMP>").replace(self.root.as_posix(), "<TEMP>")
            value = re.sub(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:\+00:00)?", "<TIME>", value)
            return value

        def digest(value):
            return hashlib.sha256(json.dumps(clean(value), ensure_ascii=False, sort_keys=True).encode()).hexdigest()

        result = {}
        for name, p in (("landmark", self.landmark), ("xray", self.xray)):
            rows = persisted_rows(p)
            output = self.export_bytes(p)
            if name == "xray":
                # The frozen oracle predates user-assigned IDs. Prove that the
                # additive field has its legacy default, then compare every
                # original column and export byte against the unchanged oracle.
                for row in rows["specimens"]:
                    self.assertEqual("", row.pop("specimen_code"))
                reader = csv.DictReader(io.StringIO(output.decode("utf-8-sig"), newline=""))
                self.assertIn("specimen_code", reader.fieldnames)
                legacy = io.StringIO(newline="")
                writer = csv.DictWriter(legacy, fieldnames=[key for key in reader.fieldnames if key != "specimen_code"])
                writer.writeheader()
                for row in reader:
                    self.assertEqual(row["ordinal"], row.pop("specimen_code"))
                    writer.writerow(row)
                output = legacy.getvalue().encode("utf-8-sig")
            result[name] = {"tables": {k: {"rows": len(v), "sha256": digest(v)} for k, v in rows.items()},
                            "export_sha256": digest(output)}
        return result

    def test_pre_refactor_fingerprints_and_exact_reopen(self):
        self.populate()
        self.assertEqual(json.loads(ORACLE.read_text(encoding="utf-8")), self.snapshot())
        before = [persisted_rows(p) for p in (self.landmark, self.xray)]
        exported = [self.export_bytes(p) for p in (self.landmark, self.xray)]
        frozen = {path: path.read_bytes() for path in (self.landmark.data_root / "ai").rglob("*.json")}
        for _ in range(5):
            self.landmark = Project.open(self.landmark.root)
            self.xray = XRayProject(self.xray.root)
            self.assertEqual(before, [persisted_rows(p) for p in (self.landmark, self.xray)])
            self.assertEqual(exported, [self.export_bytes(p) for p in (self.landmark, self.xray)])
            self.assertEqual(frozen, {path: path.read_bytes() for path in frozen})
            self.assertEqual("old_lm_parent", self.landmark.active_model("landmark")["parent_model_id"])
            self.assertEqual("old_xr_parent", self.xray.active_structure_model()["parent_model_id"])


if __name__ == "__main__":
    unittest.main()
