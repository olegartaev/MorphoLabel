import csv
import hashlib
import json
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from tkinter import ttk
from PIL import Image
from app.analysis_export import SCOPE_ALL, SCOPE_VERIFIED, export_analysis_bundle
from app.export_formats import export_landmark_tps
from app.measurements import export_measurements
from app.project_storage import Project
from app.results_export import parse_tps
from app.transforms import Transform
from app.version import __version__
from unittest.mock import patch

def _walk(widget):
    for child in widget.winfo_children():
        yield child
        yield from _walk(child)

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
        self.assertFalse(any(r["image_id"] == self.verified["image_id"] and r["output_format"] in {"wide_csv","long_csv"} for r in omissions))
        with (self.dest / "missing_values.csv").open(encoding="utf-8",newline="") as stream:
            missing_values=list(csv.DictReader(stream))
        self.assertTrue(any(r["image_id"] == self.verified["image_id"] and r["output_format"] == "wide_csv" and r["landmark_id"] == "25" and r["reason"] == "explicitly_missing" for r in missing_values))
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
        self.assertTrue(any(r["image_id"] == self.unverified["image_id"] and r["output_format"] == "MorphoJ" and r["group"] == "ALL" and "unresolved_landmark_ids=25" in r["reason"] for r in omissions))
        self.assertFalse(any(r["image_id"] == self.verified["image_id"] and r["output_format"] in {"wide_csv","long_csv","measurements"} for r in omissions))
        with (self.dest / "missing_values.csv").open(encoding="utf-8",newline="") as stream:
            missing_values=list(csv.DictReader(stream))
        self.assertTrue(any(r["image_id"] == self.unverified["image_id"] and r["output_format"] == "measurements" and r["measurement"] == "Tip" and "unresolved" in r["reason"] for r in missing_values))
        manifest=json.loads((self.dest/"manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["app_version"],__version__)
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

    def test_real_tk_export_dialog_defaults_export_completion_and_cancel(self):
        from types import SimpleNamespace
        from app.ui.export_section import ExportSection
        root=tk.Tk();self.addCleanup(lambda:root.destroy() if root.winfo_exists() else None);root.withdraw()
        root.context=SimpleNamespace(project=self.project,rows=self.project.catalog_rows(),section="landmarks")
        callback_errors=[];root.report_callback_exception=lambda *args:callback_errors.append(args)
        root.tip=SimpleNamespace(bind=lambda *_args,**_kwargs:None)
        root._test_icons=[]
        root.ui_icon=lambda *_args:root._test_icons.append(tk.PhotoImage(master=root,width=2,height=2)) or root._test_icons[-1]
        root.control_button=lambda parent,text,command,_help,**kwargs:ttk.Button(parent,text=text,command=command,**{k:v for k,v in kwargs.items() if k=="style"})
        root.completed=[];root.task_calls=[]
        def run_task(_title,_message,worker,done):
            root.task_calls.append(_title)
            result=worker(lambda _progress:None);root.completed.append(result);done(result)
        root._run_background_task=run_task
        view=ExportSection(root,root);view.render();root.update_idletasks()
        self.assertIs(view.shell,root);self.assertIs(root._run_background_task,run_task)
        page_buttons=[w for w in _walk(root) if isinstance(w,ttk.Button)]
        self.assertTrue(any(w.cget("text")=="Export analysis dataset…" for w in page_buttons))
        view.analysis_dataset();root.update_idletasks()
        dialog=next(w for w in root.winfo_children() if isinstance(w,tk.Toplevel))
        controls=list(_walk(dialog))
        verified=next(w for w in controls if isinstance(w,ttk.Radiobutton) and w.cget("text")=="Verified only (default)")
        all_scope=next(w for w in controls if isinstance(w,ttk.Radiobutton) and w.cget("text").startswith("All ("))
        verify=next(w for w in controls if isinstance(w,ttk.Checkbutton) and w.cget("text").startswith("Verify source files (SHA256"))
        self.assertEqual(root.getvar(verified.cget("variable")),SCOPE_VERIFIED)
        all_scope.invoke();self.assertEqual(root.getvar(all_scope.cget("variable")),SCOPE_ALL)
        verified.invoke();self.assertEqual(root.getvar(verified.cget("variable")),SCOPE_VERIFIED)
        self.assertFalse(bool(root.getvar(verify.cget("variable"))));verify.invoke();self.assertTrue(bool(root.getvar(verify.cget("variable"))));verify.invoke()
        entry=next(w for w in controls if isinstance(w,ttk.Entry));entry.insert(0,str(self.root/"real_tk_output"))
        self.assertEqual(entry.get(),str(self.root/"real_tk_output"))
        export=next(w for w in controls if isinstance(w,ttk.Button) and w.cget("text")=="Export")
        completion=[]
        with patch.object(tk.Tk,"report_callback_exception",lambda _widget,*args:callback_errors.append(args)),patch("app.ui.export_section.messagebox.showinfo",side_effect=lambda *args,**kwargs:completion.append(args)):
            export.invoke();root.update_idletasks()
        self.assertEqual(callback_errors,[])
        self.assertFalse(dialog.winfo_exists());self.assertEqual(len(root.task_calls),1,repr(callback_errors));self.assertEqual(len(root.completed),1,repr(callback_errors))
        result=root.completed[0];self.assertEqual(result["counts"]["selected_for_scope"],1);self.assertTrue(result["path"].is_dir())
        required={"specimens.csv","omissions.csv","missing_values.csv","manifest.json","measurements.csv","landmarks_all.tps","landmarks_GM.tps","landmarks_CLASSICAL.tps","landmarks_wide_ALL.csv","landmarks_long.csv","landmarks_MorphoJ_ALL.txt"}
        self.assertTrue(required.issubset({p.name for p in result["path"].iterdir()}))
        self.assertEqual(completion[0][0],"Analysis dataset exported");self.assertIn("Selected: 1",completion[0][1])
        view.analysis_dataset();root.update_idletasks();cancel_dialog=next(w for w in root.winfo_children() if isinstance(w,tk.Toplevel))
        cancel=next(w for w in _walk(cancel_dialog) if isinstance(w,ttk.Button) and w.cget("text")=="Cancel")
        cancel.invoke();root.update_idletasks();self.assertFalse(cancel_dialog.winfo_exists());self.assertEqual(len(root.completed),1)

    def test_custom_categories_generate_dynamic_group_exports_and_collision_safe_names(self):
        source=self.root/"universal_photos";source.mkdir();Image.new("RGB",(40,30)).save(source/"one.png")
        schema=self.root/"universal_scheme.csv"
        schema.write_text("id,abbr,name,role,category\n1,A,Alpha,BOTH,A/B\n2,B,Beta,BOTH,A?B\n3,C,Gamma,BOTH,Fin\n4,D,Delta,BOTH,Fin\n",encoding="utf-8")
        project=Project.create("universal",source,self.root,schema,source_layout="direct");row=project.catalog_rows()[0]
        for ident in range(1,5):project.save_landmark(row["image_id"],ident,ident+0.25,ident+0.5,"manual","manual")
        project.mark_checked(row["image_id"])
        destination=self.root/"universal_bundle";result=export_analysis_bundle(project,destination)
        manifest=json.loads((destination/"manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["app_version"],__version__)
        self.assertEqual([item["abbreviation"] for item in manifest["schema_identity_and_order"]["ALL"]],["A","B","C","D"])
        self.assertEqual(set(manifest["schema_identity_and_order"]),{"ALL","A/B","A?B","Fin"})
        files=manifest["group_files"]
        self.assertEqual(files["A/B"]["TPS"],"landmarks_A_B.tps")
        self.assertEqual(files["A?B"]["TPS"],"landmarks_A_B__2.tps")
        self.assertEqual(files["Fin"]["wide_csv"],"landmarks_wide_Fin.csv")
        self.assertEqual(sum(line.startswith("LM=") for line in (destination/"landmarks_all.tps").read_text(encoding="utf-8").splitlines()),1)
        for spec in files.values():
            self.assertTrue((destination/spec["TPS"]).is_file());self.assertTrue((destination/spec["wide_csv"]).is_file());self.assertTrue((destination/spec["MorphoJ"]).is_file())
        self.assertFalse(any((destination/name).exists() for name in ("landmarks_GM.tps","landmarks_CLASSICAL.tps")))
        self.assertEqual(result["counts"]["MorphoJ_omitted"],{"ALL":0,"A/B":0,"A?B":0,"Fin":0})

    def test_omissions_match_actual_row_identities_and_missing_values_are_separate(self):
        self.run_bundle(SCOPE_ALL)
        with (self.dest/"omissions.csv").open(encoding="utf-8",newline="") as stream:omissions=list(csv.DictReader(stream))
        with (self.dest/"missing_values.csv").open(encoding="utf-8",newline="") as stream:missing=list(csv.DictReader(stream))
        selected={self.verified["image_id"],self.unverified["image_id"]}
        for filename,fmt in (("landmarks_all.tps","TPS"),("landmarks_MorphoJ_ALL.txt","MorphoJ")):
            if fmt=="TPS":actual={block["ID"] for block in parse_tps(self.dest/filename)}
            else:
                with (self.dest/filename).open(encoding="utf-8",newline="") as stream:actual={row[0] for row in list(csv.reader(stream,delimiter="\t"))[1:]}
            recorded={row["image_id"] for row in omissions if row["output_format"]==fmt and row["group"]=="ALL" and row["record_type"]=="specimen"}
            self.assertEqual(recorded,selected-actual)
        with (self.dest/"landmarks_wide_ALL.csv").open(encoding="utf-8",newline="") as stream:wide_ids={row["specimen_id"] for row in csv.DictReader(stream)}
        with (self.dest/"measurements.csv").open(encoding="utf-8",newline="") as stream:measurement_ids={row["image_id"] for row in csv.DictReader(stream)}
        self.assertEqual(wide_ids,selected);self.assertEqual(measurement_ids,selected)
        self.assertFalse(any(row["output_format"] in {"wide_csv","measurements"} and row["image_id"] in selected for row in omissions))
        with (self.dest/"landmarks_long.csv").open(encoding="utf-8",newline="") as stream:
            long_rows={(row["image_id"],row["landmark_id"]) for row in csv.DictReader(stream)}
        expected={(ident,str(point)) for ident in selected for point in range(1,26)}
        recorded={(row["image_id"],row["landmark_id"]) for row in omissions if row["output_format"]=="long_csv"}
        self.assertEqual(recorded,expected-long_rows)
        self.assertTrue(any(row["image_id"]==self.verified["image_id"] and row["output_format"]=="wide_csv" and row["landmark_id"]=="25" and row["reason"]=="explicitly_missing" for row in missing))
        self.assertTrue(any(row["image_id"]==self.verified["image_id"] and row["output_format"]=="long_csv" and row["landmark_id"]=="25" and row["reason"]=="explicitly_missing" for row in missing))
        self.assertTrue(any(row["image_id"]==self.verified["image_id"] and row["output_format"]=="measurements" and row["measurement"]=="Tip" for row in missing))

    def test_existing_destination_is_never_overwritten(self):
        self.dest.mkdir()
        sentinel = self.dest / "keep.txt"
        sentinel.write_text("prior bundle", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            self.run_bundle()
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "prior bundle")

if __name__ == "__main__":
    unittest.main()
