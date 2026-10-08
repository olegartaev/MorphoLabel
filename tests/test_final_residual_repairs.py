"""Six bounded RC2 repair groups, using persisted state and real Tk callbacks."""
import copy
import gc
import hashlib
import json
import time
import tkinter as tk
import unittest
import zipfile
from pathlib import Path
from tkinter import ttk
from unittest.mock import patch
from types import SimpleNamespace
from PIL import Image

from app.ai_package import AIPackageError, export_model_package, import_model_package
from app.calibration_workflow import CalibrationWorkflow
from app.landmark_dataset import v2_human_final_eligible_image_ids
from app.landmark_training_workflow import available_training_parents
from app.project_storage import Project, landmark_model_schema_compatible, schema_hash
from app.schema_editor import SchemaEditor
from app.ui.context import UIContext
from app.xray_crop import crop_from_geometry
from app.xray_project import XRayProject
from app.xray_structures_ui import XRayStructureWorkspace
from tests.current_fixtures import make_reviewed_crop
from tests import test_rc1_repair_invariants as rc1
children=rc1.children


class FinalResidualRepairTests(unittest.TestCase):
    def setUp(self):
        rc1.RC1RepairInvariants.setUp(self)
        # Dispose Tk reference cycles on the UI thread before a later test
        # starts a worker; Tcl finalizers may not run on that worker.
        self.addCleanup(gc.collect)
    landmark = rc1.RC1RepairInvariants.landmark
    xray = rc1.RC1RepairInvariants.xray

    def tk_root(self):
        root=tk.Tk();root.geometry("1280x720+0+0")
        self.addCleanup(root.destroy)
        errors=[];root.report_callback_exception=lambda *args:errors.append(args)
        self.addCleanup(lambda:self.assertEqual([],errors))
        root.update()
        return root

    def click(self,root,button):
        root.update();self.assertTrue(button.winfo_ismapped())
        button.event_generate("<Enter>")
        button.event_generate("<ButtonPress-1>",x=5,y=5)
        button.event_generate("<ButtonRelease-1>",x=5,y=5)
        root.update()

    def pump(self,root,condition):
        until=time.monotonic()+20
        while not condition():
            root.update();time.sleep(.01)
            self.assertLess(time.monotonic(),until,"Tk worker completion timed out")
        root.update()

    def model(self,p):
        directory=p.models_root/"parent";directory.mkdir(parents=True)
        (directory/"inference_config.py").write_text("default_scope='mmpose'\n")
        (directory/"best_engineering_validation.pth").write_bytes(b"fixture checkpoint")
        (directory/"model.json").write_text(json.dumps({"backend":"rtmpose","schema_sha256":schema_hash(p.schema_path),"result":{"inference_config":"inference_config.py","checkpoint_path":"best_engineering_validation.pth"}}))
        p.register_model("parent","landmark",path=directory.relative_to(p.data_root).as_posix(),active=True)
        return directory

    def scheme(self,name,order=("A","B"),cosmetic=False):
        path=self.root/name
        path.write_text("id;abbr;name;role;category\n"+"".join(f"{i};{abbr};{'Display ' if cosmetic else ''}{abbr};{'GM' if cosmetic else 'BOTH'};{'Group' if cosmetic else ''}\n" for i,abbr in enumerate(order,1)))
        return path

    def test_FINAL_P1_001_portable_identity_roundtrip_cosmetic_and_output_changes(self):
        a,_=self.landmark();directory=self.model(a)
        before={path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in directory.iterdir()}
        first=export_model_package(a,"landmark",self.root/"a.zip")
        b=Project.create("b",self.source,self.root,a.schema_path,source_layout="direct")
        imported=import_model_package(b,first,"landmark");b.set_active_model("landmark",imported)
        b=Project.open(b.root);b.apply_landmark_schema(self.scheme("cosmetic.csv",cosmetic=True))
        b=Project.open(b.root)
        self.assertEqual(imported,b.active_model("landmark")["model_id"])
        self.assertIn(imported,[row["model_id"] for row in available_training_parents(b)])
        second=export_model_package(b,"landmark",self.root/"b.zip")
        c=Project.create("c",self.source,self.root,b.schema_path,source_layout="direct")
        final=import_model_package(c,second,"landmark");c.set_active_model("landmark",final)
        for package in (first,second):
            with zipfile.ZipFile(package) as z:
                self.assertEqual(["A","B"],json.loads(z.read("manifest.json"))["schema_identity"])
                self.assertEqual(["A","B"],json.loads(z.read("artifacts/model.json"))["schema_identity"])
        self.assertEqual(["A","B"],json.loads(Project.open(c.root).model_metadata(final)["metrics_json"])["schema_identity"])
        for order in (("CHANGED","B"),("B","A")):
            b.apply_landmark_schema(self.scheme("changed.csv",order))
            self.assertFalse(landmark_model_schema_compatible(b,b.model_metadata(imported)))
            self.assertEqual((),available_training_parents(b))
            with self.assertRaises(ValueError):b.active_model("landmark")
        self.assertEqual(before,{path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in directory.iterdir()})

    def test_FINAL_P1_001_existing_import_embedded_evidence_and_unknown_legacy(self):
        a,_=self.landmark();self.model(a);package=export_model_package(a,"landmark",self.root/"a.zip")
        b=Project.create("b",self.source,self.root,a.schema_path,source_layout="direct")
        ident=import_model_package(b,package,"landmark");model=b.model_metadata(ident)
        metrics=json.loads(model["metrics_json"])
        # Reconstruct an already-imported current-format model with only its
        # historical package/scheme, and no explicit semantic fields.
        metrics.pop("schema_identity");m=metrics["package_manifest"]
        m.pop("schema_identity");m["model_metadata"].pop("schema_identity")
        m["training_statistics"].pop("schema_identity")
        with b.transaction() as db:db.execute("UPDATE models SET metrics_json=? WHERE model_id=?",(json.dumps(metrics),ident))
        info_path=b.data_root/model["path"]/"model.json";info=json.loads(info_path.read_text());info.pop("schema_identity");info_path.write_text(json.dumps(info))
        b.apply_landmark_schema(self.scheme("cosmetic.csv",cosmetic=True))
        self.assertTrue(landmark_model_schema_compatible(Project.open(b.root),b.model_metadata(ident)))
        unknown={**model,"metrics_json":"{}","path":None,"dataset_manifest_path":None}
        self.assertFalse(landmark_model_schema_compatible(b,unknown))
        broken=copy.deepcopy(metrics);broken["package_manifest"]["project_schemes"]["landmarks"]["sha256"]="broken"
        self.assertFalse(landmark_model_schema_compatible(b,{**unknown,"metrics_json":json.dumps(broken)}))

    def test_FINAL_P1_001_disagreeing_package_identity_is_rejected_atomically(self):
        a,_=self.landmark();self.model(a);package=export_model_package(a,"landmark",self.root/"a.zip")
        with zipfile.ZipFile(package) as z:contents={name:z.read(name) for name in z.namelist()}
        manifest=json.loads(contents["manifest.json"]);manifest["schema_identity"]=["B","A"]
        contents["manifest.json"]=json.dumps(manifest).encode()
        bad=self.root/"bad.zip"
        with zipfile.ZipFile(bad,"w") as z:
            for name,data in contents.items():z.writestr(name,data)
        b=Project.create("b",self.source,self.root,a.schema_path,source_layout="direct")
        old=b.schema_path.read_bytes()
        with self.assertRaises(AIPackageError):import_model_package(b,bad,"landmark")
        self.assertEqual([],b.models("landmark"));self.assertEqual(old,b.schema_path.read_bytes())

    def test_FINAL_P2_001_save_as_exposes_apply_through_Tk_events_and_reopen(self):
        p,_=self.landmark();root=self.tk_root();editor=SchemaEditor(root,p.schema_path,project=p)
        root.update();self.assertFalse(editor.apply_button.winfo_ismapped())
        editor.rows[0]["name"]="Cosmetic name";editor.dirty=True
        target=self.root/"external.csv"
        save_as=next(w for w in children(editor) if isinstance(w,ttk.Button) and w.cget("text")=="Save As...")
        before=(editor.path,editor.dirty,editor.delimiter)
        with patch("app.schema_editor.filedialog.asksaveasfilename",return_value=""):self.click(root,save_as)
        self.assertEqual(before,(editor.path,editor.dirty,editor.delimiter))
        with patch("app.schema_editor.filedialog.asksaveasfilename",return_value=str(target)):self.click(root,save_as)
        self.assertEqual(target,editor.path);self.assertFalse(editor.dirty)
        self.assertTrue(editor.apply_button.winfo_ismapped());self.assertFalse(editor.apply_button.instate(["disabled"]))
        self.assertNotEqual("Cosmetic name",p.schema[0]["name"])
        self.click(root,editor.apply_button)
        self.assertEqual("Cosmetic name",Project.open(p.root).schema[0]["name"])
        self.assertFalse(editor.apply_button.winfo_ismapped());editor.destroy()

    def test_FINAL_P2_001_failed_save_as_preserves_editor_path_and_dirty_state(self):
        p,_=self.landmark();root=self.tk_root();editor=SchemaEditor(root,p.schema_path,project=p)
        editor.rows[0]["abbr"]="";editor.dirty=True;before=(editor.path,editor.delimiter,editor.dirty)
        with patch("app.schema_editor.filedialog.asksaveasfilename",return_value=str(self.root/"bad.csv")),patch("app.schema_editor.messagebox.showerror"):
            self.assertFalse(editor.save_as())
        self.assertEqual(before,(editor.path,editor.delimiter,editor.dirty));editor.destroy()

    def test_FINAL_P2_002_bulk_complete_draft_matches_single_status_and_verify(self):
        p,ident=self.landmark()
        p.save_landmark(ident,1,10,20,"manual");p.save_landmark(ident,2,30,40,"manual")
        p.save_annotation_draft(ident)
        root=self.tk_root()
        from app.ui.photo_list_panel import PhotoListPanel
        from app.ui.tooltips import Tooltip
        context=UIContext(p);context.refresh()
        sidebar=PhotoListPanel(root,context,lambda *_:None,Tooltip(root));sidebar.pack(fill="both",expand=True);sidebar.refresh();root.update()
        self.assertEqual("yellow",sidebar.canvas.rows[0]["status"])
        self.assertIn("needs review",sidebar.canvas.rows[0]["tooltip"])
        for current in (p,Project.open(p.root)):
            rows=current.catalog_rows();row=next(row for row in rows if row["image_id"]==ident)
            self.assertEqual("yellow",row["status_color"]);self.assertFalse(row["human_verified"])
            self.assertEqual(row["status_color"],current.catalog_row(ident)["status_color"])
            self.assertFalse(current.annotation_status(ident)["verified"])
            self.assertNotIn(ident,v2_human_final_eligible_image_ids(current))
            context=UIContext(current);context.refresh();self.assertEqual(0,context.landmark_counts()["Human verified"])
        p.mark_checked(ident);self.assertIsNone(p.annotation_draft(ident))
        self.assertEqual("green",p.catalog_rows()[0]["status_color"])
        self.assertIn(ident,v2_human_final_eligible_image_ids(p))
        sidebar.context.refresh(force=True);sidebar.refresh();root.update()
        self.assertEqual("green",sidebar.canvas.rows[0]["status"])

    def test_FINAL_P2_002_bulk_machine_confirmation_matches_single_without_N_plus_one(self):
        p,ident=self.landmark()
        points=[{"landmark_id":1,"x":10,"y":20},{"landmark_id":2,"x":30,"y":40}]
        p.save_machine_landmarks(ident,points,model_id="fixture",prediction_run_id="first");p.mark_checked(ident)
        queries=[];connect=p.connect
        def traced_connect():
            db=connect();db.set_trace_callback(queries.append);return db
        def bulk():
            queries.clear()
            with patch.object(p,"connect",side_effect=traced_connect),patch.object(p,"annotation_status",side_effect=AssertionError("N+1 status")),patch.object(p,"model_metadata",side_effect=AssertionError("N+1 model")):
                rows=p.catalog_rows()
            return rows,len([q for q in queries if q.lstrip().upper().startswith("SELECT")])
        rows,one_count=bulk();self.assertEqual("green",rows[0]["status_color"])
        for index in range(4):Image.new("RGB",(160,100)).save(self.source/f"extra{index}.png")
        p.scan_originals()
        for row in p.catalog_rows():
            if row["image_id"]==ident:continue
            make_reviewed_crop(p,row["image_id"],160,100)
            p.save_machine_landmarks(row["image_id"],points,model_id="fixture",prediction_run_id="first");p.mark_checked(row["image_id"])
        rows,many_count=bulk();self.assertEqual(one_count,many_count)
        self.assertTrue(all(row["status_color"]=="green" for row in rows))
        # Corrupted/stale confirmation is not repaired by a persisted review bit.
        with p.transaction() as db:db.execute("UPDATE landmarks SET prediction_run_id='changed' WHERE image_id=?",(ident,))
        self.assertEqual("yellow",p.annotation_status(ident)["color"])
        rows,_=bulk();self.assertEqual("yellow",next(row for row in rows if row["image_id"]==ident)["status_color"])

    def test_FINAL_P2_003_predict_all_decline_review_refreshes_list_counts_selection(self):
        p,first=self.xray();plate=p.source_images()[0]["image_id"]
        for _ in range(17):p.add_manual_specimen(plate,crop_from_geometry(80,50,160,100,0,(160,100),algorithm="manual"))
        root=self.tk_root();host=ttk.Frame(root);host.pack(fill="both",expand=True)
        model={"model_id":"fixture"}
        with patch.object(p,"active_structure_model",return_value=model),patch("app.xray_structures_ui._current_prediction_allowed",return_value=True):
            workspace=XRayStructureWorkspace(host,p,initial_specimen_id=first);root.update()
            workspace._refresh_workflow=lambda:None
            self.assertEqual(18,p.annotation_summary()["unstarted"])
            workspace.specimen_list.canvas.yview_moveto(.4);root.update()
            yview=workspace.specimen_list.canvas.yview()[0]
            def predict(project,ids,**kwargs):
                success=[]
                for sid in ids:
                    project.seed_structure_predictions(sid,[{"structure_id":"objects","x":.4,"y":.5}],"fixture",allow_verified=True)
                    success.append({"specimen_id":sid,"saved":1})
                return {"success":success,"failures":[]}
            with patch("app.xray_structures_ui.threading.Thread",side_effect=lambda **kwargs:SimpleNamespace(start=kwargs["target"])),patch("app.xray_structures_ui.predict_structures",side_effect=predict),patch("app.xray_structures_ui.messagebox.askyesno",return_value=False) as review,patch("app.xray_structures_ui.messagebox.showinfo"):
                workspace.predict_current_structure();self.pump(root,lambda:not workspace._busy)
                self.assertEqual("Draft: 1",workspace.summary_labels["draft"].cget("text"))
                self.assertEqual("Not started: 17",workspace.summary_labels["unstarted"].cget("text"))
                expected_drafts=len({first}|set(p.select_structure_prediction_ids(2)))
                workspace.predict_structure_batch(2);self.pump(root,lambda:not workspace._busy)
                self.assertEqual(f"Draft: {expected_drafts}",workspace.summary_labels["draft"].cget("text"))
                trigger=ttk.Button(root,command=lambda:workspace.predict_structure_batch(None));trigger.pack()
                self.click(root,trigger);self.pump(root,lambda:not workspace._busy)
                self.assertEqual(2,review.call_count)
                self.assertEqual("Draft: 18",workspace.summary_labels["draft"].cget("text"))
                self.assertEqual("Not started: 0",workspace.summary_labels["unstarted"].cget("text"))
                self.assertTrue(all(row["status_color"]=="yellow" for row in workspace.specimen_list.rows()))
                self.assertEqual(first,workspace.selected_specimen_id)
                self.assertAlmostEqual(yview,workspace.specimen_list.canvas.yview()[0],places=4)
                workspace.predict_current_structure();self.pump(root,lambda:not workspace._busy)
                self.assertEqual("Draft: 18",workspace.summary_labels["draft"].cget("text"))
            self.assertEqual(18,XRayProject(p.root).annotation_summary()["draft"])
            host.destroy()

    def test_FINAL_P2_004_crop_confirm_and_next_updates_live_ready_label(self):
        from app.ui.shell import ProductionShell
        p,ident=self.landmark()
        with p.transaction() as db:db.execute("UPDATE crops SET human_verified=0 WHERE image_id=?",(ident,))
        Image.new("RGB",(160,100)).save(self.source/"second.png");p.scan_originals()
        context=UIContext(p,section="crop");context.refresh()
        ids=[row["image_id"] for row in context.rows]
        p.set_ui_state("crop_active_batch",{"batch_id":"repair","batch_type":"training","ids":ids,"completed_ids":[],"position":0})
        with patch("app.ui.shell.first_run_setup_required",return_value=False),patch("tkinter.messagebox.showinfo"):
            shell=ProductionShell(module_states={"landmarks":{"context":context}});self.addCleanup(shell.destroy)
            shell.open_module("landmarks");shell.update();runtime=shell._active_module_runtime;view=runtime.current_view
            self.assertEqual("Ready: 0",view.crop_training_ready_label.cget("text"))
            button=ttk.Button(shell,command=view.next_batch);button.pack()
            for ready in (1,2):
                self.pump(shell,lambda:view.canvas.ready_for(context.current()["image_id"]))
                button.invoke();shell.update()
                self.assertEqual(f"Ready: {ready}",view.crop_training_ready_label.cget("text"))
                self.assertEqual(ready,context.crop_counts()["Train ready"])
            self.assertTrue(p.get_ui_state("crop_active_batch")["finished"])
            self.assertEqual(2,len(Project.open(p.root).crop_training_rows()))

    def test_FINAL_P3_001_calibration_geometry_and_actions_fit_nine_Tk_views(self):
        p,ident=self.landmark();root=self.tk_root()
        for width,height in ((1280,720),(1600,900),(1920,1080)):
            for scaling in (1.,1.25,1.5):
                with self.subTest(view=(width,height),scaling=scaling):
                    root.tk.call("tk","scaling",scaling*96/72)
                    area=(0,0,width,height)
                    with patch("app.calibration_workflow.work_area",return_value=area),patch("app.ui.dialogs.work_area",return_value=area):
                        dialog=CalibrationWorkflow(root,p);root.update()
                        self.assertLessEqual(dialog.winfo_rooty()+dialog.winfo_height(),height)
                        self.assertLessEqual(dialog.winfo_rootx()+dialog.winfo_width(),width)
                        for button in (w for w in children(dialog) if isinstance(w,ttk.Button)):
                            self.assertTrue(button.winfo_ismapped())
                            self.assertGreater(button.winfo_height(),15)
                            self.assertLessEqual(button.winfo_rooty()+button.winfo_height(),height)
                        self.assertGreater(dialog.canvas.winfo_height(),100)
                        self.assertEqual((1,1),tuple(map(int,dialog.resizable())))
                        dialog.close();root.update()
