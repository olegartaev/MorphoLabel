"""Follow-up regressions through actual workflows, persistence and real Tk."""
import copy
import json
import math
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PIL import Image
from app.project_storage import Project
from app.ai_package import export_model_package, import_model_package
from app.crop_training_batch import prepare_crop_training_images
from app.normalization_pipeline import prepare_crop_result
from app.ui.crop_canvas import CropCanvasController
from app.xray_project import XRayProject
from app.xray_schema import blank_scheme
from tests import test_final_model_transfer as model_fixtures
from tests import test_final_functional_hardening as tk_fixtures


class FollowupWorkflowTests(unittest.TestCase):
    setUp=model_fixtures.FinalModelTransferTests.setUp
    structure_package=model_fixtures.FinalModelTransferTests.structure_package

    def known_crop(self):
        directory=self.project.models_root/"rotation_crop";directory.mkdir()
        weights=np.zeros((769,6));weights[0]=[.1,.1,.9,.9,math.sin(math.radians(30)),math.cos(math.radians(30))]
        np.savez_compressed(directory/"model.npz",weights=weights)
        (directory/"model_manifest.json").write_text(json.dumps({"backend":"numpy_ridge_image_regression","input":"32x24 grayscale","output_schema":{"version":2}}),encoding="utf-8")
        self.project.register_model("rotation_crop","crop",path=directory.relative_to(self.project.data_root).as_posix(),active=True)

    def test_imported_crop_activates_and_actual_batch_preserves_rotation(self):
        self.known_crop();package=self.root/"crop.zip";export_model_package(self.project,"crop",package)
        target=Project.create("target",self.source,self.root,self.schema,source_layout="direct")
        local=import_model_package(target,package,"crop")
        self.assertEqual(local,(target.active_model("crop") or {}).get("model_id"))
        rows=target.catalog_rows()
        for row in rows:
            with Image.open(target.image_path(row["image_id"])) as image:image.save(target.cache_root/"developed"/f"{row['image_id']}.png")
        prepared=prepare_crop_training_images(target,rows)
        target.set_ui_state("crop_active_batch",{"proposals":prepared["proposals"],"proposal_rotations":prepared["proposal_rotations"]})
        canvas=SimpleNamespace()
        for row in rows:
            with Image.open(target.image_path(row["image_id"])) as image:
                bounds,angle=CropCanvasController._crop_state(canvas,target,row["image_id"],image)
                expected=prepare_crop_result(self.project.image_path(row["image_id"]),project=self.project,force=True,image_id_value=row["image_id"])
                self.assertEqual(expected["crop_bounds"],bounds);self.assertAlmostEqual(30,angle,places=10)
                from app.crop_workflow import apply_reviewed_crop
                from app.landmark_frames import restore_standardized_frame
                destination=target.cache_root/"standardized"/f"{row['image_id']}.png"
                apply_reviewed_crop(target,row["image_id"],image.convert("RGB"),bounds,angle,destination,target.image_path(row["image_id"]))
                pixels=np.asarray(image.convert("RGB").rotate(angle,resample=Image.Resampling.BICUBIC,expand=False,fillcolor=(255,255,255)).crop(bounds))
            reopened=Project.open(target.root);record=reopened.crop_record(row["image_id"])
            self.assertAlmostEqual(30,record["rotation_degrees"],places=10)
            destination.unlink();restore_standardized_frame(reopened,row["image_id"])
            with Image.open(destination) as frame:np.testing.assert_array_equal(pixels,np.asarray(frame))

    def test_materialized_model_proposal_pixels_agree_with_persisted_rotation(self):
        self.known_crop();row=self.project.catalog_rows()[0];ident=row["image_id"]
        result=prepare_crop_result(self.project.image_path(ident),project=self.project,force=True,image_id_value=ident,materialize_learned=True)
        with Image.open(self.project.image_path(ident)) as source:
            expected=source.convert("RGB").rotate(result["rotation_degrees"],resample=Image.Resampling.BICUBIC,expand=False,fillcolor=(255,255,255)).crop(result["crop_bounds"])
        with Image.open(self.project.resolve_data_path(result["standardized_relpath"])) as actual:
            np.testing.assert_array_equal(np.asarray(expected),np.asarray(actual))

    def test_prepared_cache_cannot_hide_a_newly_activated_crop_model(self):
        self.known_crop();row=self.project.catalog_rows()[0];ident=row["image_id"];source=self.project.image_path(ident)
        prepare_crop_result(source,project=self.project,image_id_value=ident,materialize_learned=True)
        directory=self.project.models_root/"changed_crop";directory.mkdir()
        weights=np.zeros((769,6));weights[0]=[.2,.2,.8,.8,math.sin(math.radians(-20)),math.cos(math.radians(-20))]
        np.savez_compressed(directory/"model.npz",weights=weights)
        self.project.register_model("changed_crop","crop",path=directory.relative_to(self.project.data_root).as_posix(),active=True)
        result=prepare_crop_result(source,project=self.project,image_id_value=ident,materialize_learned=True)
        self.assertEqual("changed_crop",result["crop_model_version"])
        self.assertAlmostEqual(-20,result["rotation_degrees"],places=10)

    def test_measurement_definition_roundtrip_by_abbreviation_and_reject_unknown(self):
        from app.measurements import save_measurements,export_measurement_definitions,import_measurement_definitions,load_measurements
        schema=self.root/"two.csv";schema.write_text("id,abbr,name,role\n1,A,Alpha,BOTH\n2,B,Beta,BOTH\n",encoding="utf-8")
        source=Project.create("measure_source",self.source,self.root,schema,source_layout="direct")
        save_measurements(source,[{"use":True,"abbr":"AB","name":"Distance, full","point1":1,"point2":2}])
        target_schema=self.root/"reordered.csv";target_schema.write_text("id,abbr,name,role\n1,B,Beta,BOTH\n2,A,Alpha,BOTH\n",encoding="utf-8")
        target=Project.create("measure_target",self.source,self.root,target_schema,source_layout="direct")
        path=self.root/"definitions.csv";export_measurement_definitions(source,path)
        import_measurement_definitions(target,path)
        row=load_measurements(Project.open(target.root))[0]
        self.assertEqual(("A","B",2,1),(row["point1_abbr"],row["point2_abbr"],row["point1"],row["point2"]))
        before=(target.root/"measurement_schema.csv").read_bytes()
        path.write_text(path.read_text(encoding="utf-8").replace(",A,B",",UNKNOWN,B"),encoding="utf-8")
        with self.assertRaises(ValueError):import_measurement_definitions(target,path)
        self.assertEqual(before,(target.root/"measurement_schema.csv").read_bytes())

    def test_legacy_measurement_export_resolves_historical_endpoints_without_loss(self):
        from app.measurements import export_measurement_definitions,import_measurement_definitions,load_measurements
        schema=self.root/"two.csv";schema.write_text("id,abbr,name,role\n1,A,Alpha,BOTH\n2,B,Beta,BOTH\n",encoding="utf-8")
        source=Project.create("legacy_measure",self.source,self.root,schema,source_layout="direct")
        definitions=source.root/"measurement_schema.csv"
        definitions.write_text('Use,Abbr,Name,Point1,Point2\n1,AB,"Distance, full",1,2\n',encoding="utf-8")
        original=definitions.read_bytes();target=Project.create("portable_measure",self.source,self.root,schema,source_layout="direct")
        package=self.root/"portable.csv";export_measurement_definitions(source,package)
        import_measurement_definitions(target,package)
        self.assertEqual(original,definitions.read_bytes())
        self.assertEqual(("A","B"),(load_measurements(target)[0]["point1_abbr"],load_measurements(target)[0]["point2_abbr"]))
        definitions.write_text("Use,Abbr,Name,Point1,Point2\n1,AB,Distance,1,99\n",encoding="utf-8")
        before=package.read_bytes()
        with self.assertRaises(ValueError):export_measurement_definitions(source,package)
        self.assertEqual(before,package.read_bytes())

    def test_structure_package_applies_embedded_traits_and_preserves_prior_history(self):
        from app.xray_structure_ai import import_structure_model_package
        self.xray.set_orientation_policy({"head":"right","bottom":"up"})
        package=self.structure_package()
        target=XRayProject.create("blank_target",self.source,self.root,blank_scheme())
        before=target.active_scheme_record()["version_id"]
        local=import_structure_model_package(target,package)
        reopened=XRayProject(target.root)
        self.assertEqual(self.xray.scheme,reopened.scheme)
        self.assertEqual(self.xray.orientation_policy,reopened.orientation_policy)
        self.assertIn(before,{r["version_id"] for r in reopened.schema_history()})
        self.assertEqual(local,reopened.structure_models()[0]["model_id"])
        with zipfile.ZipFile(package) as archive:
            self.assertIn("trait_scheme",json.loads(archive.read("manifest.json")))

    def test_imported_model_scheme_preserves_annotations_and_rolls_back_on_registry_failure(self):
        from app.xray_project import _db_connection
        from app.xray_structure_ai import import_structure_model_package
        from app.xray_crop import crop_from_geometry
        package=self.structure_package();old=copy.deepcopy(self.scheme);old["structures"].reverse()
        target=XRayProject.create("annotated_target",self.source,self.root,old)
        image=target.source_images()[0]["image_id"]
        specimen=target.add_manual_specimen(image,crop_from_geometry(60,40,100,60,0,(120,80),algorithm="manual"))
        target.confirm_plate(image)
        target.add_annotation(specimen,"vertebra",.4,.5,1)
        with _db_connection(target.db_path) as c:before=c.execute("SELECT * FROM annotations").fetchall();c.execute("CREATE TRIGGER fail_model BEFORE INSERT ON xray_structure_models BEGIN SELECT RAISE(ABORT,'registry failure'); END")
        history=target.schema_history();previous=target.scheme
        with self.assertRaisesRegex(Exception,"registry failure"):import_structure_model_package(target,package)
        self.assertEqual(history,target.schema_history());self.assertEqual(previous,target.scheme)
        with _db_connection(target.db_path) as c:c.execute("DROP TRIGGER fail_model")
        import_structure_model_package(target,package)
        with _db_connection(target.db_path) as c:self.assertEqual(before,c.execute("SELECT * FROM annotations").fetchall())
        target.save_scheme(old,"Restore prior scheme for review")
        self.assertEqual(.4,target.annotations(specimen,1)[0]["x"])

    def test_crop_package_applies_traits_policy_and_activates_without_overwriting_old_state(self):
        from app.xray_crop_package import export_crop_model_package,import_crop_model_package
        from app.xray_project import _db_connection
        directory=self.xray.models_root/"crop_portable";directory.mkdir()
        (directory/"model.pth").write_bytes(b"weights");(directory/"config.py").write_text("model=dict(type='RTMDet')\n",encoding="utf-8")
        self.xray.set_orientation_policy({"head":"right","bottom":"up"})
        self.xray.register_crop_model("crop_portable","models/crop_portable/model.pth","models/crop_portable/config.py",None,{},(),0)
        package=self.root/"crop_portable.zip";export_crop_model_package(self.xray,package)
        target=XRayProject.create("crop_blank",self.source,self.root,blank_scheme(),orientation_policy={"head":"none","bottom":"none"})
        history=target.schema_history();policy=target.orientation_policy
        with _db_connection(target.db_path) as c:c.execute("CREATE TRIGGER fail_crop BEFORE INSERT ON xray_crop_models BEGIN SELECT RAISE(ABORT,'registry failure'); END")
        with self.assertRaisesRegex(Exception,"registry failure"):import_crop_model_package(target,package)
        self.assertEqual(history,target.schema_history());self.assertEqual(policy,target.orientation_policy)
        with _db_connection(target.db_path) as c:c.execute("DROP TRIGGER fail_crop")
        local=import_crop_model_package(target,package);target=XRayProject(target.root)
        self.assertEqual(local,target.active_crop_model()["model_id"]);self.assertEqual(self.xray.scheme,target.scheme)
        self.assertEqual(self.xray.orientation_policy,target.orientation_policy)
        self.assertEqual(policy,target.active_crop_model()["metrics"]["previous_orientation_policy"])

    def test_crop_import_cannot_flip_existing_annotation_frame(self):
        from app.xray_crop_package import export_crop_model_package,import_crop_model_package
        from app.xray_crop import crop_from_geometry
        directory=self.xray.models_root/"rotated_crop";directory.mkdir()
        (directory/"model.pth").write_bytes(b"weights");(directory/"config.py").write_text("model={}\n",encoding="utf-8")
        self.xray.set_orientation_policy({"head":"right","bottom":"up"})
        self.xray.register_crop_model("rotated_crop","models/rotated_crop/model.pth","models/rotated_crop/config.py",None,{},(),0)
        package=self.root/"rotated_crop.zip";export_crop_model_package(self.xray,package)
        target=XRayProject.create("annotated_crop_target",self.source,self.root,self.scheme)
        image=target.source_images()[0]["image_id"];specimen=target.add_manual_specimen(image,crop_from_geometry(60,40,100,60,0,(120,80),algorithm="manual"))
        target.confirm_plate(image);target.add_annotation(specimen,"vertebra",.4,.5,1)
        before=target.annotations(specimen,1);policy=target.orientation_policy;history=target.schema_history()
        from app.xray_structure_ai import import_structure_model_package
        for importer,archive in ((import_crop_model_package,package),(import_structure_model_package,self.structure_package())):
            with self.assertRaisesRegex(ValueError,"orientation"):importer(target,archive)
            self.assertEqual(policy,target.orientation_policy);self.assertEqual(before,target.annotations(specimen,1))
            self.assertEqual(history,target.schema_history());self.assertEqual([],target.crop_models());self.assertEqual([],target.structure_models())


class FollowupTkTests(unittest.TestCase):
    setUp=tk_fixtures.FinalTkHardeningTests.setUp
    make_shell=tk_fixtures.FinalTkHardeningTests.make_shell

    def widgets(self,parent):
        for widget in parent.winfo_children():yield widget;yield from self.widgets(widget)

    def test_samples_fill_available_height_on_first_project_layout_and_reopen(self):
        shell,errors=self.make_shell();shell.deiconify();runtime=shell._active_module_runtime
        for scale in (1,1.25,1.5):
            shell.tk.call("tk","scaling",scale*96/72)
            for width,height in ((1440,1400),(1000,1000)):
                shell.geometry(f"{width}x{height}");shell.update()
                project=Project.create(f"height_{scale}_{width}",self.landmark.source_root,self.root,source_layout="direct")
                for current in (project,Project.open(project.root)):
                    runtime._attach_project(current,current.catalog_rows());shell.update_idletasks();shell.update()
                    view=runtime.current_view
                    samples=next(w for w in self.widgets(runtime.section_host) if w.winfo_class()=="TLabelframe" and w.cget("text")=="Samples")
                    bottom=samples.winfo_rooty()+samples.winfo_height()
                    viewport=view.scroll_canvas
                    self.assertLessEqual(abs(bottom-(viewport.winfo_rooty()+viewport.winfo_height())),4)

    def test_measurement_actions_disabled_until_scheme_and_cancel_preserves_definitions(self):
        from app.measurements import save_measurements
        from app.measurements_ui import MeasurementsWindow,transfer_measurement_definitions
        shell,errors=self.make_shell();runtime=shell._active_module_runtime
        project=Project.create("empty_scheme",self.landmark.source_root,self.root,source_layout="direct")
        runtime._attach_project(project);shell.update()
        frame=next(w for w in self.widgets(runtime.section_host) if w.winfo_class()=="TLabelframe" and w.cget("text")=="Measurement definitions")
        self.assertTrue(all(str(w.cget("state"))=="disabled" for w in self.widgets(frame) if w.winfo_class()=="TButton"))
        dialog=MeasurementsWindow(shell,project);shell.update()
        transfers=[w for w in self.widgets(dialog) if w.winfo_class()=="TButton" and "definitions" in str(w.cget("text"))]
        self.assertEqual(2,len(transfers));self.assertTrue(all(str(w.cget("state"))=="disabled" for w in transfers));dialog.destroy()
        save_measurements(self.landmark,[{"use":True,"abbr":"AB","name":"Distance","point1":1,"point2":2}])
        original=(self.landmark.root/"measurement_schema.csv").read_bytes()
        with patch("app.measurements_ui.filedialog.askopenfilename",return_value="cancel.csv"),patch("app.measurements_ui.messagebox.askyesno",return_value=False):
            self.assertFalse(transfer_measurement_definitions(shell,self.landmark,"import"))
        self.assertEqual(original,(self.landmark.root/"measurement_schema.csv").read_bytes())

    def test_project_shows_models_and_measurement_definitions_without_menu_gate(self):
        shell,errors=self.make_shell();shell.deiconify();shell.geometry("1440x1300");shell.update()
        runtime=shell._active_module_runtime
        texts=[w.cget("text") for w in self.widgets(runtime.section_host) if "text" in w.keys()]
        self.assertIn("Measurement definitions",texts)
        self.assertIn("Crop model",texts);self.assertIn("Landmark model",texts)
        self.assertFalse(any("import" in e["label"].lower() for e in runtime.standard_menu_entries()))
        shell.module_states.setdefault("xray_counts",{})["project"]=self.xray;shell.open_module("xray_counts");shell.update()
        runtime=shell._active_module_runtime
        texts=[w.cget("text") for w in self.widgets(runtime.host.container) if "text" in w.keys()]
        self.assertIn("X-ray Crop model",texts);self.assertIn("X-ray Structure model",texts)
        self.assertFalse(any("import" in e["label"].lower() for e in runtime.standard_menu_entries()))

    def test_xray_scan_runs_in_background_and_live_progress_is_present(self):
        shell,errors=self.make_shell();shell.deiconify()
        shell.module_states.setdefault("xray_counts",{})["project"]=self.xray;shell.open_module("xray_counts");shell.update()
        runtime=shell._active_module_runtime
        import threading
        entered=threading.Event();release=threading.Event();ident=[]
        original=self.xray.scan_source
        def slow_scan():
            ident.append(threading.get_ident());entered.set();release.wait(5);return original()
        try:
            with patch.object(self.xray,"scan_source",side_effect=slow_scan):
                runtime._rescan_source()
                self.assertTrue(entered.wait(1));shell.update()
                self.assertNotEqual(threading.get_ident(),ident[0])
                self.assertTrue(any(w.winfo_class()=="TProgressbar" for w in self.widgets(shell)))
                release.set()
                deadline=time.monotonic()+6
                while any(w.winfo_class()=="TProgressbar" for w in self.widgets(shell)) and time.monotonic()<deadline:shell.update();time.sleep(.01)
                self.assertFalse(any(w.winfo_class()=="TProgressbar" for w in self.widgets(shell)))
        finally:release.set()

    def test_project_import_refreshes_visible_model_and_traits_immediately(self):
        shell,errors=self.make_shell();shell.deiconify()
        shell.module_states.setdefault("xray_counts",{})["project"]=self.xray;shell.open_module("xray_counts");shell.update()
        runtime=shell._active_module_runtime
        def imported(project,path):
            directory=project.models_root/"visible_crop";directory.mkdir()
            (directory/"model.pth").write_bytes(b"weights");(directory/"config.py").write_text("model={}\n",encoding="utf-8")
            project.register_crop_model("visible_crop","models/visible_crop/model.pth","models/visible_crop/config.py",None,{},(),0)
            scheme=copy.deepcopy(project.scheme);scheme["name"]="Imported traits"
            project.save_scheme(scheme)
            return "visible_crop"
        with patch("app.modules.xray_counts.filedialog.askopenfilename",return_value="crop.zip"),patch("app.xray_crop_package.import_crop_model_package",side_effect=imported),patch("app.modules.xray_counts.messagebox.showinfo"):
            runtime._menu_import_crop_ai();shell.update()
        texts=[str(w.cget("text")) for w in self.widgets(runtime.host.container) if "text" in w.keys()]
        self.assertTrue(any("visible_crop" in text for text in texts),texts)
        self.assertTrue(any("Imported traits" in text for text in texts),texts)
        self.assertEqual([],errors)

    def test_remembered_xray_project_loads_with_progress_and_closed_module_ignores_completion(self):
        import threading
        shell,errors=self.make_shell();shell.deiconify()
        shell.module_states.setdefault("xray_counts",{})["project"]=self.xray;shell.open_module("xray_counts");shell.update()
        runtime=shell._active_module_runtime;runtime.project=None;runtime._restore_attempted=False
        entered=threading.Event();release=threading.Event();finished=threading.Event();ident=[]
        def slow_open(path):
            ident.append(threading.get_ident());entered.set();release.wait(5);finished.set();return self.xray
        try:
            with patch("app.modules.xray_counts.last_xray_project",return_value=self.xray.root),patch("app.modules.xray_counts.XRayProject",side_effect=slow_open):
                runtime._restore_last_project()
                self.assertTrue(entered.wait(1));shell.update()
                self.assertNotEqual(threading.get_ident(),ident[0])
                self.assertTrue(any(w.winfo_class()=="TProgressbar" for w in self.widgets(shell)))
                shell.open_module("landmarks");shell.update();release.set()
                self.assertTrue(finished.wait(2));deadline=time.monotonic()+6
                while any(w.winfo_class()=="TProgressbar" for w in self.widgets(shell)) and time.monotonic()<deadline:shell.update();time.sleep(.01)
                self.assertIsNone(runtime.project);self.assertIsNone(runtime.host)
                self.assertFalse(any(w.winfo_class()=="TProgressbar" for w in self.widgets(shell)))
        finally:release.set()
        self.assertEqual([],errors)

    def test_background_progress_poll_is_cancelled_when_dialog_or_shell_closes(self):
        import threading
        import tkinter as tk
        from unittest.mock import Mock
        for close in ("dialog","shell"):
            shell,errors=self.make_shell();entered=threading.Event();release=threading.Event();finished=threading.Event();done=Mock()
            def worker(progress):
                entered.set();release.wait(5);finished.set();return True
            try:
                dialog=shell._run_background_task("Load","Loading images…",worker,done)
                self.assertTrue(entered.wait(1));shell.update()
                jobs=[job for job in shell.tk.call("after","info") if "poll" in str(shell.tk.call("after","info",job))]
                self.assertTrue(jobs)
                if close=="dialog":dialog.destroy()
                else:shell.destroy()
                remaining=set(shell.tk.call("after","info"))
                self.assertFalse(set(jobs)&remaining)
                shell.destroy();release.set();self.assertTrue(finished.wait(2))
                probe=tk.Tk();probe.withdraw()
                try:
                    deadline=time.monotonic()+.2
                    while time.monotonic()<deadline:probe.update();time.sleep(.01)
                finally:probe.destroy()
                done.assert_not_called();self.assertEqual([],errors)
            finally:release.set()

    def test_workspace_import_refreshes_marker_controls_for_applied_scheme(self):
        shell,errors=self.make_shell();shell.deiconify()
        shell.module_states.setdefault("xray_counts",{})["project"]=self.xray;shell.open_module("xray_counts");shell.update()
        runtime=shell._active_module_runtime;runtime._select("structures");shell.update();workspace=runtime._workspace
        def imported(project,path):
            from app.xray_structure_ai import structure_schema_digest
            scheme=copy.deepcopy(project.scheme);scheme["structures"].append({"id":"new_mark","name":"Imported mark","repeated":True})
            project.save_scheme(scheme)
            directory=project.models_root/"visible_structure";directory.mkdir()
            (directory/"model.pth").write_bytes(b"weights");(directory/"model.json").write_text("{}",encoding="utf-8")
            project.register_structure_model("visible_structure","models/visible_structure/model.pth","models/visible_structure/model.json",None,structure_schema_digest(project.scheme),"resnet18_heatmap_v1",{},())
            return "visible_structure"
        with patch("app.xray_structures_ui.filedialog.askopenfilename",return_value="structure.zip"),patch("app.xray_structures_ui.import_structure_model_package",side_effect=imported),patch("app.xray_structures_ui.messagebox.showinfo"):
            workspace.import_structure_ai_file();shell.update()
        self.assertIn("new_mark",workspace._marker_buttons)
        self.assertEqual([],errors)

    def test_orientation_uses_supplied_reference_images_without_changing_policy(self):
        from app.modules.xray_counts import OrientationSetupDialog
        shell,errors=self.make_shell();shell.deiconify()
        dialog=OrientationSetupDialog(shell);shell.update()
        before=(dialog.head.get(),dialog.bottom.get())
        for scale in (1,1.25,1.5):
            shell.tk.call("tk","scaling",scale*96/72)
            for _repeat in (0,1):
                dialog._draw();shell.update()
                images=dialog.preview.find_withtag("orientation_reference")
                self.assertEqual(1,len(images));self.assertEqual("image",dialog.preview.type(images[0]))
                self.assertEqual(before,(dialog.head.get(),dialog.bottom.get()))
                for item in dialog.preview.find_all():
                    if dialog.preview.type(item)=="text":
                        x1,y1,x2,y2=dialog.preview.bbox(item)
                        self.assertGreaterEqual(x1,0);self.assertGreaterEqual(y1,0)
                        self.assertLessEqual(x2,dialog.preview.winfo_width());self.assertLessEqual(y2,dialog.preview.winfo_height())
        dialog.destroy()
