"""QA2 minimized witnesses and neighboring persisted-state regressions."""
import copy
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from PIL import Image
from app.project_storage import Project
from tkinter import ttk
from app.xray_project import XRayProject
from app.xray_schema import blank_scheme, normalize_scheme, scientific_scheme_hash
from app.export_formats import export_landmark_tps
from app.landmark_attention_queue import classify, display_summary, start
from app.landmark_ai_workflow import create_stage, workflow_current
from app.landmark_dataset import v2_human_final_eligible_image_ids
from app.calibration_workflow import CalibrationWorkflow
from app.landmark_training_workflow import validation_metrics
from app.rtmpose_backend import RTMPoseBackend, RTMPoseModelSpec, RTMPoseRuntimeError
from tests import test_rc1_repair_invariants as rc1


class QA2RepairInvariants(unittest.TestCase):
    setUp = rc1.RC1RepairInvariants.setUp
    landmark = rc1.RC1RepairInvariants.landmark
    xray = rc1.RC1RepairInvariants.xray

    def manual(self):
        p, ident = self.landmark()
        p.save_landmark(ident,1,10,20,"manual")
        p.save_landmark(ident,2,30,40,"manual")
        p.mark_checked(ident)
        return p,ident

    def state_assertions(self,p,ident,verified):
        status=p.annotation_status(ident)
        self.assertEqual(verified,status["verified"])
        self.assertEqual("green" if verified else "yellow",status["color"])
        self.assertEqual(verified,p.landmark_ai_review_ready(ident))
        self.assertEqual(verified,ident in v2_human_final_eligible_image_ids(p))
        self.assertEqual("resolved" if verified else "landmarks",classify(p,ident)["stage"])

    def test_QA2_P1_001_unicode_second_tps_writer_and_ascii_bytes(self):
        p,ident=self.manual()
        target=export_landmark_tps(p,target=self.root/"u.tps")
        data=target.read_bytes();self.assertFalse(data.startswith(b"\xef\xbb\xbf"))
        self.assertIn("IMAGE=образец.png",data.decode("utf-8").splitlines())
        with p.transaction() as c:c.execute("UPDATE images SET original_name='specimen.png' WHERE image_id=?",(ident,))
        ascii_data=export_landmark_tps(p,target=self.root/"ascii.tps").read_bytes()
        self.assertEqual(data.replace("образец.png".encode(),b"specimen.png"),ascii_data)
        expected=f"LM=2\n10.00000 20.00000\n30.00000 40.00000\nIMAGE=specimen.png\nID={ident}\n"
        old_writer=self.root/"old-ascii.tps";old_writer.write_text(expected,encoding="ascii")
        self.assertEqual(old_writer.read_bytes(),ascii_data)

    def test_tps_atomic_failure_preserves_previous_export(self):
        p,_=self.manual();target=self.root/"old.tps";target.write_bytes(b"old")
        with patch("app.io.os.replace",side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):export_landmark_tps(p,target=target)
        self.assertEqual(b"old",target.read_bytes());self.assertEqual([],list(self.root.glob("old.*.tmp")))

    def test_QA2_P1_002_optional_scheme_names_and_scientific_rejection(self):
        scheme=blank_scheme();scheme["structures"]=[{"id":i} for i in "abc"]
        scheme["traits"]=[{"id":"theta","method":"angle","structures":list("abc")}]
        value=normalize_scheme(scheme);self.assertEqual("theta",value["traits"][0]["name"])
        self.assertEqual(list("abc"),[s["name"] for s in value["structures"]])
        named=copy.deepcopy(value);named["traits"][0]["name"]="Angle label"
        self.assertEqual(scientific_scheme_hash(value),scientific_scheme_hash(named))
        p,sid=self.xray(scheme)
        for name,(x,y) in zip("abc",[(.2,.2),(.5,.5),(.8,.2)]):p.add_annotation(sid,name,x,y)
        p.verify_annotations(sid);reopened=XRayProject(p.root)
        self.assertAlmostEqual(115.989233583833,reopened.trait_rows()[0]["trait_values"]["theta"])
        for replacement in (None,"abc",[],["missing"]):
            bad=copy.deepcopy(scheme);bad["traits"][0]["structures"]=replacement
            with self.subTest(replacement=replacement),self.assertRaises(ValueError):normalize_scheme(bad)

    def test_QA2_P1_003_typed_ui_boundary_preserves_science_and_legitimate_shapes(self):
        p,ident=self.manual();xr,_=self.xray()
        for project,keys in ((p,("crop_active_batch","landmark_attention_queue","landmark_ai_workflow","landmark_prediction_review_sessions","landmark_suspicious_review")),(xr,("xray_crop_active_batch","xray_structure_active_batch","xray_result_review_queue"))):
            for key in keys:
                for bad in ([],[1],"bad",42,None,{"position":"bad"},{"image_ids":"bad"},{"sessions":[1]},{"proposals":[1]},{"review_meta":[1]},{"landmark_ids":"bad"}):
                    project.set_ui_state(key,bad);default={}
                    with self.subTest(key=key,bad=bad),self.assertLogs(level="WARNING"):
                        self.assertIs(default,project.get_ui_state(key,default))
            project.set_ui_state("workspace_sidebar_sash",[200,600]);self.assertEqual([200,600],project.get_ui_state("workspace_sidebar_sash"))
            project.set_ui_state("crop_enabled",False);self.assertFalse(project.get_ui_state("crop_enabled",True))
            proposals={"proposals":{"image":[12,8,108,72]},"proposal_rotations":{"image":30.0}}
            project.set_ui_state("crop_active_batch",proposals)
            self.assertEqual(proposals,project.get_ui_state("crop_active_batch",{}))
        self.state_assertions(p,ident,True)

    def test_QA2_P2_003_complete_manual_draft_is_not_verified_after_reopen(self):
        p,ident=self.manual();p.save_annotation_draft(ident)
        with p.transaction() as c:c.execute("UPDATE image_review SET human_verified=1 WHERE image_id=?",(ident,))
        for project in (p,Project.open(p.root)):self.state_assertions(project,ident,False)

    def test_QA2_P2_002_attention_keeps_complete_draft_until_explicit_verification(self):
        p,ident=self.manual();p.save_annotation_draft(ident)
        self.assertEqual("landmarks",classify(p,ident)["stage"])
        p.mark_checked(ident);self.assertIsNone(p.annotation_draft(ident));self.state_assertions(p,ident,True)

    def test_QA2_P2_004_attention_summary_reclassifies_stale_stage_for_verify_next(self):
        p,ident=self.manual();p.save_annotation_draft(ident)
        start(p,[ident])
        value=p.get_ui_state("landmark_attention_queue");value["current_stage"]=None;p.set_ui_state("landmark_attention_queue",value)
        self.assertEqual("landmarks",display_summary(p)["stage"])
        self.assertIsNotNone(p.annotation_draft(ident));self.assertFalse(p.annotation_status(ident)["verified"])

    def test_QA2_P2_001_new_run_same_coordinates_invalidates_confirmation_and_history(self):
        p,ident=self.landmark();points=[{"landmark_id":1,"x":10,"y":20},{"landmark_id":2,"x":30,"y":40}]
        p.save_machine_landmarks(ident,points,model_id="parent",prediction_run_id="run1");p.mark_checked(ident)
        self.state_assertions(p,ident,True)
        p.save_machine_landmarks(ident,points,model_id="parent",prediction_run_id="run2")
        for project in (p,Project.open(p.root)):self.state_assertions(project,ident,False)
        with p.transaction() as c:
            self.assertEqual(0,c.execute("SELECT human_verified FROM image_review WHERE image_id=?",(ident,)).fetchone()[0])
            history=[json.loads(r[0]) for r in c.execute("SELECT accepted_json FROM corrections WHERE image_id=?",(ident,))]
        self.assertTrue(any(row.get("prediction_run_id")=="run2" for row in history))
        p.mark_checked(ident);self.state_assertions(p,ident,True)

    def test_neighbor_verification_missing_corrected_crop_and_scheme_flags(self):
        p,ident=self.manual()
        for key in ("landmark_crop_review_required","landmark_scheme_review_required"):
            with p.transaction() as c:c.execute("INSERT INTO image_attributes(image_id,attribute_key,value,updated_at) VALUES(?,?,?,'now')",(ident,key,"true"))
            self.state_assertions(p,ident,False);p.mark_checked(ident);self.state_assertions(p,ident,True)
        p.save_landmark(ident,2,None,None,"missing");p.mark_checked(ident)
        self.state_assertions(Project.open(p.root),ident,True)

    def test_QA2_P1_004_landmark_export_import_reexport_canonical_artifacts(self):
        from tests.test_separate_ai_model_packages import SeparateModelPackageTests
        from app.ai_package import export_model_package,import_model_package
        fixture=SeparateModelPackageTests();fixture.setUp();self.addCleanup(fixture.tearDown)
        first=fixture.temp/"first.zip";export_model_package(fixture.project,"landmark",first)
        b=fixture.target();ident=import_model_package(b,first,"landmark");b.set_active_model("landmark",ident)
        b=Project.open(b.root);second=fixture.temp/"second.zip";export_model_package(b,"landmark",second)
        c=Project.create("third",fixture.source,fixture.temp,fixture.schema,source_layout="direct")
        final=import_model_package(c,second,"landmark")
        source=fixture.landmark;dest=c.data_root/c.model_metadata(final)["path"]
        for name in ("inference_config.py","best_engineering_validation.pth"):
            self.assertEqual(hashlib.sha256((source/name).read_bytes()).digest(),hashlib.sha256((dest/name).read_bytes()).digest())

    def backend(self,body):
        runner=self.root/"runner.py";runner.write_text(body,encoding="utf-8")
        return RTMPoseBackend(RTMPoseModelSpec("m","h",runner,runner),runtime_python=Path(sys.executable),runner_path=runner)

    def test_QA2_P1_005_frozen_like_foreign_modules_and_heartbeat_are_bounded(self):
        # A foreign frozen app module deliberately fails if imported from app cwd.
        frozen=self.root/"_internal";frozen.mkdir();(frozen/"pickle.py").write_text("raise RuntimeError('foreign Python312 extension')")
        old=Path.cwd()
        try:
            os.chdir(frozen)
            b=self.backend("import pickle,json,sys,os\njson.load(sys.stdin)\nprint(json.dumps({'cwd':os.getcwd(),'ok':True}))")
            result=b._invoke("probe",{});self.assertTrue(result["ok"]);self.assertNotEqual(str(frozen),result["cwd"])
        finally:os.chdir(old)
        b=self.backend("import json,sys,time\njson.load(sys.stdin)\nwhile True:\n print('RANK_PROGRESS 0 4',file=sys.stderr,flush=True);time.sleep(.02)")
        started=time.monotonic()
        with self.assertRaisesRegex(RTMPoseRuntimeError,"stalled"):b._invoke("probe_many",{},no_progress_timeout=.4)
        self.assertLess(time.monotonic()-started,5)

    def test_preflight_cancel_terminates_owned_worker(self):
        import ctypes
        child_pid_file=self.root/"child.pid"
        body=f"import subprocess,json,sys,time,pathlib\njson.load(sys.stdin)\np=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])\npathlib.Path({str(child_pid_file)!r}).write_text(str(p.pid))\ntime.sleep(60)"
        backend=self.backend(body);backend.cancel_event=threading.Event()
        timer=threading.Timer(.7,backend.cancel_event.set);timer.start();self.addCleanup(timer.cancel)
        started=time.monotonic()
        with self.assertRaisesRegex(RTMPoseRuntimeError,"cancelled"):backend._invoke("probe_many",{},no_progress_timeout=10)
        self.assertLess(time.monotonic()-started,5)
        self.assertTrue(child_pid_file.is_file())
        if os.name=="nt":
            handle=ctypes.windll.kernel32.OpenProcess(0x100000,False,int(child_pid_file.read_text()))
            if handle:
                try:self.assertEqual(0,ctypes.windll.kernel32.WaitForSingleObject(handle,2000))
                finally:ctypes.windll.kernel32.CloseHandle(handle)

    @unittest.skipUnless(os.name=="nt", "Windows taskkill fallback")
    def test_preflight_cancel_terminates_owned_worker_when_taskkill_is_denied(self):
        real_run=subprocess.run;denied=[]
        def run(command,**kwargs):
            if command[0]=="taskkill":
                denied.append(command)
                return subprocess.CompletedProcess(command,1,b"",b"ERROR: Access denied\r\n")
            return real_run(command,**kwargs)
        with patch("app.process_utils.subprocess.run",side_effect=run):
            self.test_preflight_cancel_terminates_owned_worker()
        self.assertEqual(1,len(denied))

    def test_QA2_P3_001_metric_reader_uses_saved_engineering_validation(self):
        p,_=self.landmark();directory=p.models_root/"m";directory.mkdir(parents=True)
        (directory/"model.json").write_text(json.dumps({"result":{"engineering_validation":{"p90_error_percent":1.234},"best_epoch":21}}))
        model={"path":directory.relative_to(p.data_root).as_posix(),"metrics_json":"{}"}
        self.assertEqual((1.234,21),(validation_metrics(model,p)["p90_error_percent"],validation_metrics(model,p)["best_epoch"]))
        self.assertEqual(2,validation_metrics({"metrics_json":'{"p90_error_percent":2}'})["p90_error_percent"])

    def calibration(self):
        p,ident=self.landmark();Image.new("RGB",(160,100)).save(self.source/"second.png");p.scan_originals()
        for row in p.catalog_rows():
            path=p.cache_root/"developed"/(row["image_id"]+".png");path.parent.mkdir(parents=True,exist_ok=True);Image.new("RGB",(160,100)).save(path)
        root=tk.Tk();root.geometry("900x620+-1800+430");root.withdraw();self.addCleanup(root.destroy)
        dialog=CalibrationWorkflow(root,p);dialog.withdraw();self.addCleanup(lambda:dialog.close() if dialog.winfo_exists() else None)
        return p,root,dialog

    def test_QA2_P2_006_calibration_browsing_save_cancel_reference(self):
        p,root,d=self.calibration();a=d.row()["image_id"];d.points=[(10,10),(110,10)];self.assertTrue(d._save_current())
        d.other_image();b=d.row()["image_id"];self.assertNotEqual(a,b);self.assertEqual(a,p.locality_calibration(d.locality())["calibration_reference_image_id"])
        d.load();self.assertEqual(a,d.row()["image_id"])
        d.other_image();d.points=[(20,20),(120,20)];self.assertTrue(d._save_current());d.load();self.assertEqual(b,d.row()["image_id"])
        self.assertEqual(b,Project.open(p.root).locality_calibration(d.locality())["calibration_reference_image_id"])

    def test_QA2_P2_007_calibration_notifies_persisted_measurement_refresh(self):
        from app.modules.landmarks import LandmarksRuntime
        from app.ui.context import UIContext
        from app.ui.measurements_section import MeasurementsSection
        p,root,d=self.calibration();d.close()
        root.context=UIContext(p);root.current_view=MeasurementsSection(root,root)
        root.current_view.summary=ttk.Label(root)
        root.current_view.refresh_definitions()
        self.assertIn("Calibrated 0/1",root.current_view.summary.cget("text"))
        dialog=LandmarksRuntime.open_calibration(root);dialog.withdraw()
        try:
            dialog.points=[(10,10),(110,10)];self.assertTrue(dialog._save_current())
            self.assertIn("Calibrated 1/1",root.current_view.summary.cget("text"))
            self.assertEqual(10,Project.open(p.root).locality_calibration(dialog.locality())["scale"])
        finally:dialog.close()

    def test_QA2_P1_006_initial_batch_without_controls_resumes_and_advances(self):
        p,ident=self.landmark();state=create_stage(p,"INITIAL_TRAINING",1,allow_small=True)
        for project in (p,Project.open(p.root)):
            state,current,position,_=workflow_current(project)
            self.assertEqual("INITIAL_TRAINING",state["stage"]);self.assertEqual(ident,current);self.assertEqual([],state["control_image_ids"])
        p.save_landmark(ident,1,10,20,"manual");p.save_landmark(ident,2,30,40,"manual");p.mark_checked(ident)
        self.assertIsNone(workflow_current(p)[1])

    def test_QA2_P2_005_specimen_delta_updates_row_without_selection_or_scroll_loss(self):
        from app.xray_structures_ui import XRaySpecimenListPanel
        p,sid=self.xray();root=tk.Tk();root.withdraw();self.addCleanup(root.destroy)
        panel=XRaySpecimenListPanel(root,p,lambda _sid:None,SimpleNamespace(bind=lambda *_args:None));panel.refresh();panel.select(sid,reveal=False)
        before_selection=panel.canvas.curselection();before_scroll=panel.canvas.yview()
        p.add_annotation(sid,"objects",.2,.5)
        with patch.object(panel,"_catalog",side_effect=AssertionError("full refresh")):self.assertTrue(panel.refresh_specimen(sid))
        self.assertEqual("yellow",panel.canvas.rows[0]["status"]);self.assertEqual(before_selection,panel.canvas.curselection());self.assertEqual(before_scroll,panel.canvas.yview())
        self.assertEqual("draft",XRayProject(p.root).annotation_run(sid)["status"])
