import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from app.analysis_export import SCOPE_ALL, SCOPE_VERIFIED, export_analysis_bundle
from app.export_formats import export_landmark_tps
from app.measurements import export_measurements
from app.project_storage import Project
from app.results_export import parse_tps
from app.transforms import Transform
from unittest.mock import patch

class AnalysisExportBundleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = self.root / "photos"
        self.source.mkdir()
        for name in ("рыба_один.png", "fish_two.png", "fish_three.png"):
            Image.new("RGB", (100, 80), (50, 90, 120)).save(self.source / name)
        self.schema = self.root / "scheme.csv"
        rows = ["id,abbr,name,role"]
        rows += [f"{i},P{i},Point {i},{'GM' if i <= 20 else 'CLASSICAL'}" for i in range(1, 26)]
        self.schema.write_text("\n".join(rows) + "\n", encoding="utf-8")
        self.project = Project.create("project", self.source, self.root, self.schema, source_layout="direct")
        self.images = self.project.catalog_rows()
        self.verified, self.unverified, self.excluded = self.images
        tr = Transform(100, 80, 25, 50, 40, 10, 5, 80, 70)
        with self.project.transaction() as c:
            c.execute("INSERT INTO crops(image_id,transform_json,rotation_degrees,status,provenance,updated_at) VALUES (?,?,?,?,?,?)",
                      (self.verified["image_id"], json.dumps(tr.__dict__), 25, "ready", "manual", "test"))
        for ident in range(1, 25):
            self.project.save_landmark(self.verified["image_id"], ident, ident + .25, ident + .5, "manual", "manual")
        self.project.save_landmark(self.verified["image_id"], 25, None, None, "missing", "missing")
        self.project.set_locality_calibration(self.verified.get("locality") or self.verified.get("sample_id"),
                                              self.verified["image_id"], 2.0, "mm", {"mm_per_pixel": .5})
        for ident in range(1, 26):
            self.project.save_landmark(self.unverified["image_id"], ident, ident, ident + 1, "auto", "machine",
                                       model_id="test-model", reviewed=False)
        self.project.delete_landmark(self.unverified["image_id"], 25)
        self.project.save_annotation_draft(self.unverified["image_id"], "landmarks", 1)
        self.project.exclude_image(self.excluded["image_id"], "test_exclusion")
        definitions = "Use,Abbr,Name,Point1,Point2,Point1Abbr,Point2Abbr\n1,Len,Length,1,20,P1,P20\n1,Tip,Tip distance,24,25,P24,P25\n"
        (self.project.root / "measurement_schema.csv").write_text(definitions, encoding="utf-8")
        self.dest = self.root / "bundle"

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def sha(path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    def run_bundle(self, scope=SCOPE_VERIFIED):
        return export_analysis_bundle(self.project, self.dest, scope=scope)

    def test_verified_default_snapshot_crosswalk_manifest_and_omission_states(self):
        db_hash = self.sha(self.project.path)
        photo_hash = self.sha(self.source / "рыба_один.png")
        result = self.run_bundle()
        self.assertEqual(self.sha(self.project.path), db_hash)
        self.assertEqual(self.sha(self.source / "рыба_один.png"), photo_hash)
        self.assertEqual(result["counts"]["selected_for_scope"], 1)
        with (self.dest / "specimens.csv").open(encoding="utf-8", newline="") as stream:
            rows = {r["image_id"]: r for r in csv.DictReader(stream)}
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[self.verified["image_id"]]["selected_for_export"], "true")
        self.assertEqual(rows[self.verified["image_id"]]["source_hash_status"], "not_verified")
        self.assertTrue(any("рыба" in r["filename"] for r in rows.values()))
        with (self.dest / "landmarks_wide_ALL.csv").open(encoding="utf-8", newline="") as stream:
            wide = list(csv.DictReader(stream))
        self.assertEqual({r["specimen_id"] for r in wide}, {r["specimen_id"] for r in rows.values() if r["selected_for_export"]=="true"})
        self.assertEqual(rows[self.unverified["image_id"]]["draft_status"], "draft")
        self.assertEqual(rows[self.unverified["image_id"]]["selected_for_export"], "false")
        self.assertEqual(rows[self.excluded["image_id"]]["excluded"], "true")
        manifest = json.loads((self.dest / "manifest.json").read_text(encoding="utf-8"))
        self.assertTrue(manifest["dataset_snapshot"]["shared_by_all_exports"])
        self.assertFalse(manifest["source_hash_policy"]["verification_requested"])
        for name, meta in manifest["files"].items():
            self.assertEqual((self.dest / name).stat().st_size, meta["size_bytes"])
            self.assertEqual(self.sha(self.dest / name), meta["sha256"])
        with (self.dest / "omissions.csv").open(encoding="utf-8", newline="") as stream:
            omissions = list(csv.DictReader(stream))
        reasons = {(r["image_id"], r["reason"]) for r in omissions}
        self.assertIn((self.unverified["image_id"], "not_human_verified"), reasons)
        self.assertIn((self.excluded["image_id"], "excluded"), reasons)
        self.assertTrue(any(r["image_id"] == self.verified["image_id"] and "explicit_missing_landmark_ids=25" in r["reason"] for r in omissions))
        self.assertEqual(rows[self.unverified["image_id"]]["unresolved_landmark_ids"], "25")

    def test_all_scope_group_order_coordinate_and_measurement_oracles(self):
        result = self.run_bundle(SCOPE_ALL)
        self.assertEqual(result["counts"]["selected_for_scope"], 2)
        block = parse_tps(self.dest / "landmarks_all.tps")[0]
        transform = Transform(100, 80, 25, 50, 40, 10, 5, 80, 70)
        expected = transform.standardized_to_original(1.25, 1.5)
        self.assertAlmostEqual(block["coordinates"][0][0], expected[0], places=5)
        self.assertAlmostEqual(block["coordinates"][0][1], expected[1], places=5)
        self.assertEqual(block["coordinates"][-1], (-1.0, -1.0))
        self.assertEqual(block["ID"], self.verified["image_id"])
        self.assertEqual(len(parse_tps(self.dest / "landmarks_GM.tps")[0]["coordinates"]), 20)
        self.assertEqual(len(parse_tps(self.dest / "landmarks_CLASSICAL.tps")[0]["coordinates"]), 5)
        for filename, columns in (("landmarks_MorphoJ_GM.txt", 41), ("landmarks_MorphoJ_CLASSICAL.txt", 11), ("landmarks_MorphoJ_ALL.txt", 51)):
            with (self.dest / filename).open(encoding="utf-8", newline="") as stream:
                header = next(csv.reader(stream, delimiter="\t"))
            self.assertEqual(len(header), columns)
        with (self.dest / "measurements.csv").open(encoding="utf-8", newline="") as stream:
            measures = {r["image_id"]: r for r in csv.DictReader(stream)}
        p1 = transform.standardized_to_original(1.25, 1.5)
        p20 = transform.standardized_to_original(20.25, 20.5)
        expected_mm = ((p1[0]-p20[0])**2 + (p1[1]-p20[1])**2)**.5 * .5
        self.assertEqual(measures[self.verified["image_id"]]["Len_mm"], f"{expected_mm:.2f}")
        self.assertEqual(measures[self.unverified["image_id"]]["Len_mm"], f"{(722**.5*.5):.2f}")
        self.assertEqual(measures[self.verified["image_id"]]["Tip_mm"], "")
        self.assertEqual(measures[self.unverified["image_id"]]["Tip_mm"], "")
        with (self.dest / "omissions.csv").open(encoding="utf-8", newline="") as stream:
            omissions = list(csv.DictReader(stream))
        self.assertTrue(any(r["image_id"] == self.unverified["image_id"] and r["output_format"] == "TPS" and "unresolved_landmark_ids=25" in r["reason"] for r in omissions))
        self.assertTrue(any(r["image_id"] == self.unverified["image_id"] and r["output_format"] == "measurements" and r["group"] == "Tip" and r["reason"] == "missing_endpoint_landmark_ids=25" for r in omissions))
        with (self.dest / "transforms.csv").open(encoding="utf-8", newline="") as stream:
            transforms = {r["image_id"]:r for r in csv.DictReader(stream)}
        self.assertEqual(transforms[self.unverified["image_id"]]["transform_status"], "identity_no_crop")

    def test_existing_tps_contract_remains_byte_compatible_for_all_scope(self):
        direct = self.root / "direct.tps"
        export_landmark_tps(self.project, target=direct)
        self.run_bundle(SCOPE_ALL)
        self.assertEqual(direct.read_bytes(), (self.dest / "landmarks_all.tps").read_bytes())

    def test_failed_build_never_publishes_partial_directory(self):
        with patch("app.analysis_export.export_morphoj_text", side_effect=RuntimeError("synthetic failure")):
            with self.assertRaises(RuntimeError):
                self.run_bundle(SCOPE_ALL)
        self.assertFalse(self.dest.exists())
        self.assertFalse(list(self.root.glob(".bundle.staging-*")))

    def test_optional_source_hash_is_export_time_only_and_never_written_back(self):
        db_hash = self.sha(self.project.path)
        result = export_analysis_bundle(self.project, self.dest, scope=SCOPE_ALL, verify_sources=True)
        with (self.dest / "specimens.csv").open(encoding="utf-8", newline="") as stream:
            rows = {r["image_id"]: r for r in csv.DictReader(stream)}
        self.assertEqual(rows[self.verified["image_id"]]["source_hash_status"], "verified_at_export_time")
        self.assertEqual(len(rows[self.verified["image_id"]]["source_sha256"]), 64)
        self.assertEqual(self.sha(self.project.path), db_hash)
        manifest = json.loads((self.dest / "manifest.json").read_text(encoding="utf-8"))
        self.assertTrue(manifest["source_hash_policy"]["verification_requested"])
        self.assertFalse(manifest["source_hash_policy"]["new_hashes_written_to_project"])

    def test_gui_export_button_runs_default_verified_bundle_event_path(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from app.ui import export_section as ui_module

        class Var:
            def __init__(self, value=None, **_): self.value=value
            def get(self): return self.value
            def set(self, value): self.value=value

        widgets=[]
        class Widget:
            def __init__(self, *args, **kwargs):
                self.command=kwargs.get("command"); self.text=kwargs.get("text")
                self.kwargs=kwargs; widgets.append(self)
                variable=kwargs.get("textvariable")
                if variable is not None: variable.set(str(self.root))
            root=Path(self.root if hasattr(self,"root") else ".")
            def pack(self,*a,**k): pass
            def grid(self,*a,**k): pass
            def focus_set(self): pass
            def title(self,*a): pass
            def transient(self,*a): pass
            def resizable(self,*a): pass
            def destroy(self): pass

        class Shell:
            def __init__(self): self.context=SimpleNamespace(project=self_project); self.completed=None
            def _run_background_task(self,_title,_message,worker,done):
                result=worker(lambda _message: None); self.completed=result; done(result)

        self.dest = self.root / "from_gui"
        Widget.root = self.root
        self_project=self.project
        shell=Shell()
        view=ui_module.ExportSection.__new__(ui_module.ExportSection)
        view.shell=shell; view.context=shell.context
        replacements={
            "tk.Toplevel":Widget, "tk.StringVar":Var, "tk.BooleanVar":Var,
            "ttk.Frame":Widget, "ttk.Label":Widget, "ttk.Radiobutton":Widget,
            "ttk.Checkbutton":Widget, "ttk.Entry":Widget, "ttk.Button":Widget,
            "messagebox.showinfo":lambda *a,**k:None,
        }
        patches=[patch("app.ui.export_section."+name,value) for name,value in replacements.items()]
        for item in patches: item.start()
        try:
            view.analysis_dataset()
            export_button=next(w for w in widgets if w.text=="Export")
            export_button.command()
        finally:
            for item in reversed(patches): item.stop()
        self.assertIsNotNone(shell.completed)
        self.assertEqual(shell.completed["counts"]["selected_for_scope"],1)
        self.assertTrue(shell.completed["path"].is_dir())

    def test_existing_destination_is_never_overwritten(self):
        self.dest.mkdir()
        sentinel = self.dest / "keep.txt"
        sentinel.write_text("prior bundle", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            self.run_bundle()
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "prior bundle")

if __name__ == "__main__":
    unittest.main()
