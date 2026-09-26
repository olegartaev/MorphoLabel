import csv
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image
from app.editor_state import EditorState
from app.project_storage import Project, schema_hash, landmark_model_schema_compatible
from app.ui.landmark_canvas import LandmarkCanvasController


def write_schema(path, rows):
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(("id", "abbr", "name", "role"))
        writer.writerows(rows)


class _Choice:
    def __init__(self, value): self.value = value
    def get(self): return self.value
    def set(self, value): self.value = value


class LandmarkSchemaReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        source = root / "source" / "sample"; source.mkdir(parents=True)
        Image.new("RGB", (30, 20), "white").save(source / "fish.jpg")
        self.schema = root / "schema.csv"
        write_schema(self.schema, [(1, "nos", "Nose", "BOTH"), (2, "glaz", "Eye", "BOTH"), (3, "dors", "Dorsal", "BOTH"), (4, "hvost", "Tail", "BOTH")])
        self.project = Project.create("project", source.parent, root, self.schema, source_layout="direct")
        self.image_id = self.project.catalog_rows()[0]["image_id"]

    def tearDown(self): self.temp.cleanup()

    def catalog(self):
        with self.project.transaction() as c:
            return {row["abbr"]: row["landmark_id"] for row in c.execute("SELECT landmark_id,abbr FROM landmark_schema")}

    def test_empty_catalog_is_seeded_and_manual_cycle_persists(self):
        with self.project.transaction() as c: c.execute("DELETE FROM landmark_schema")
        reopened = Project.open(self.project.root)
        self.project = reopened
        self.assertEqual({"nos": 1, "glaz": 2, "dors": 3, "hvost": 4}, self.catalog())
        self.assertTrue(list((reopened.root / "backups").glob("schema_identity_*")))
        reopened.save_landmark(self.image_id, 2, 11, 12, "manual", "manual")
        reopened.save_landmark(self.image_id, 2, 13, 14, "corrected", "corrected_by_human")
        self.assertEqual((13, 14, "corrected_by_human"), tuple(reopened.load_landmarks(self.image_id)[2][key] for key in ("x_standardized", "y_standardized", "provenance")))
        reopened.delete_landmark(self.image_id, 2)
        self.assertNotIn(2, reopened.load_landmarks(self.image_id))
        reopened.save_landmark(self.image_id, 2, 21, 22, "manual", "manual")
        reopened.save_landmark(self.image_id, 2, None, None, "missing", "missing")
        row = Project.open(reopened.root).load_landmarks(self.image_id)[2]
        self.assertEqual(("missing", None, None), (row["state"], row["x_standardized"], row["y_standardized"]))

    def test_historical_keys_survive_display_reorder(self):
        self.project.save_landmark(self.image_id, 1, 1, 1, "manual", "manual")
        write_schema(self.project.schema_path, [(1, "glaz", "Eye", "BOTH"), (2, "nos", "Nose", "BOTH"), (3, "dors", "Dorsal", "BOTH")])
        reordered = Project.open(self.project.root); self.project = reordered
        reordered.save_landmark(self.image_id, 1, 2, 2, "manual", "manual")
        reordered.save_landmark(self.image_id, 3, 3, 3, "manual", "manual")
        self.assertEqual({"nos": 1, "glaz": 2, "dors": 3, "hvost": 4}, self.catalog())
        with reordered.transaction() as c:
            stored = {row["landmark_abbr"]: row["landmark_id"] for row in c.execute("SELECT landmark_id,landmark_abbr FROM landmarks WHERE image_id=?", (self.image_id,))}
        self.assertEqual({"nos": 1, "glaz": 2, "dors": 3}, stored)
        self.assertEqual({1: "glaz", 2: "nos", 3: "dors"}, {key: row["landmark_abbr"] for key, row in reordered.load_landmarks(self.image_id).items()})

    def test_model_compatibility_uses_ordered_abbreviations_not_raw_csv_bytes(self):
        dataset=self.project.data_root/"ai"/"datasets"/"d";dataset.mkdir(parents=True)
        manifest=dataset/"manifest.json"
        manifest.write_text(json.dumps({
            "format_version":1,
            "dataset_id":"d",
            "schema_sha256":schema_hash(self.project.schema_path),
            "schema_landmarks":[
                {"landmark_id":1,"abbr":"nos","role":"BOTH"},
                {"landmark_id":2,"abbr":"glaz","role":"BOTH"},
                {"landmark_id":3,"abbr":"dors","role":"BOTH"},
                {"landmark_id":4,"abbr":"hvost","role":"BOTH"},
            ],
            "images":[],
        }),encoding="utf-8")
        self.project.register_model("rtmpose_test","landmark",active=True,schema_digest=schema_hash(self.project.schema_path),dataset_id="d",dataset_manifest_path="ai/datasets/d/manifest.json")
        write_schema(self.project.schema_path,[(1,"nos","Snout renamed","GM"),(2,"glaz","Orbit renamed","GM"),(3,"dors","Dorsal renamed","CLASSICAL"),(4,"hvost","Tail renamed","BOTH")])
        reopened=Project.open(self.project.root);self.project=reopened
        model=reopened.active_model("landmark")
        self.assertEqual("rtmpose_test",model["model_id"])
        self.assertTrue(landmark_model_schema_compatible(reopened,model))
        write_schema(reopened.schema_path,[(1,"glaz","Orbit","BOTH"),(2,"nos","Snout","BOTH"),(3,"dors","Dorsal","BOTH"),(4,"hvost","Tail","BOTH")])
        reordered=Project.open(reopened.root);self.project=reordered
        with self.assertRaisesRegex(ValueError,"identities/order"):reordered.active_model("landmark")

    def test_canvas_places_explicit_selected_unresolved_landmark(self):
        canvas = LandmarkCanvasController.__new__(LandmarkCanvasController)
        canvas.image = SimpleNamespace(width=100, height=100); canvas._points = {}; canvas.image_id = self.image_id
        canvas.state = SimpleNamespace(unresolved_ids=frozenset({1, 2, 3, 4}))
        canvas.operator_state = EditorState(point_ids=(1, 2, 3, 4)); canvas.operator_state.select(3)
        canvas.choice = _Choice(3); canvas.context = SimpleNamespace(project=self.project)
        canvas._point = lambda event: (10.0, 20.0); canvas.refresh_authoritative = lambda notify=False: None
        canvas._next = lambda: None; canvas._draw_overlays = lambda: None; canvas._sync_selection = lambda: None; canvas.changed = lambda: None
        canvas._persistence_error = lambda action, exc: self.fail(f"unexpected {action}: {exc}")
        LandmarkCanvasController.place(canvas, SimpleNamespace(x=10, y=20))
        self.assertIn(3, self.project.load_landmarks(self.image_id))
        self.assertNotIn(1, self.project.load_landmarks(self.image_id))


if __name__ == "__main__": unittest.main()