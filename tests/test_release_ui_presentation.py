"""Release UI regression checks against real project data and Tk widgets."""
import hashlib
import sqlite3
import tempfile
import tkinter as tk
from pathlib import Path
from types import SimpleNamespace
from tkinter import ttk
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from app.ui.design import apply_styles, structure_prediction_text, prediction_stamp, sidebar_width_for_window, dialog_width_for_columns
from app.ui.shell import ProductionShell
from app.xray_crop import crop_from_geometry
from app.xray_crop_ui import PlateCropEditSession, XRayCropWorkspace
from app.xray_project import XRayProject, _db_connection
from app.xray_schema import bundled_scheme
from app.xray_structures_ui import XRayStructureWorkspace


class _ProjectFixture:
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name);source=root/"source";source.mkdir()
        image=Image.new("L",(900,480),90)
        image.paste(210,(240,120,660,360))
        for i in (1,2):image.save(source/f"plate_{i}.png")
        destination=root/"projects";destination.mkdir()
        self.project=XRayProject.create("preview",source,destination,bundled_scheme("phoxinus_vertebral_counts"))
        self.crop=crop_from_geometry(450,240,700,260,0,(900,480),algorithm="manual")
        self.ids=[]
        for image in self.project.source_images():
            self.ids.append(self.project.add_manual_specimen(image["image_id"],self.crop))
            self.project.confirm_plate(image["image_id"])

    def seed(self,pass_no=1,model="actual-model-v003",allow_verified=False):
        return self.project.seed_structure_predictions(self.ids[0],[
            {"structure_id":"vertebra","x":.2,"y":.5},
            {"structure_id":"first_caudal","x":.55,"y":.5},
            {"structure_id":"last_predorsal","x":.35,"y":.5},
            {"structure_id":"preanal_pterygiophore","x":.6,"y":.62},
        ],model,pass_no=pass_no,allow_verified=allow_verified)


class PresentationProjectTests(_ProjectFixture,unittest.TestCase):
    def test_provenance_uses_actual_prediction_event_and_is_read_only(self):
        self.seed();run=self.project.annotation_run(self.ids[0])
        with _db_connection(self.project.db_path) as db:
            db.execute("UPDATE annotation_events SET created_at=? WHERE run_id=? AND action='model_seed'",("2024-01-02T03:04:00",run["run_id"]))
            db.execute("UPDATE annotation_runs SET updated_at=? WHERE run_id=?",("2035-12-31T23:59:00",run["run_id"]))
        before=hashlib.sha256(self.project.db_path.read_bytes()).digest()
        with patch.object(self.project,"active_structure_model",side_effect=AssertionError("active model is not provenance")):
            text=structure_prediction_text(self.project,self.ids[0])
        self.assertIn("actual-model-v003",text);self.assertIn("2024-01-02 03:04",text)
        self.assertNotIn("2035",text)
        self.assertEqual(before,hashlib.sha256(self.project.db_path.read_bytes()).digest())

    def test_provenance_is_scoped_to_pass_and_updated_after_a_new_seed(self):
        self.seed(1,"first-model");self.project.verify_annotations(self.ids[0]);self.seed(7,"repeat-model")
        self.assertIn("repeat-model",structure_prediction_text(self.project,self.ids[0],7))
        self.assertNotIn("repeat-model",structure_prediction_text(self.project,self.ids[0],1))
        self.assertEqual("",structure_prediction_text(self.project,self.ids[0],2))
        self.seed(1,"second-model",allow_verified=True)
        text=structure_prediction_text(self.project,self.ids[0],1)
        self.assertIn("second-model",text);self.assertNotIn("first-model",text)

    def test_edited_and_verified_annotations_keep_the_original_prediction_time(self):
        self.seed();original=structure_prediction_text(self.project,self.ids[0])
        point=self.project.annotations(self.ids[0])[0]
        self.project.move_annotation(point["annotation_id"],.23,.52)
        self.assertEqual(original+" · edited",structure_prediction_text(self.project,self.ids[0]))
        self.project.verify_annotations(self.ids[0])
        self.assertEqual(original+" · human reviewed",structure_prediction_text(self.project,self.ids[0]))

    def test_manual_and_stale_annotations_do_not_get_an_invented_ai_caption(self):
        self.project.add_annotation(self.ids[0],"vertebra",.2,.5)
        self.assertEqual("",structure_prediction_text(self.project,self.ids[0]))
        self.seed();run=self.project.annotation_run(self.ids[0])
        with _db_connection(self.project.db_path) as db:db.execute("UPDATE annotation_runs SET status='stale' WHERE run_id=?",(run["run_id"],))
        self.assertEqual("",structure_prediction_text(self.project,self.ids[0]))
        self.assertIn("time not recorded",prediction_stamp("legacy-model",None))

    def test_closing_structure_queue_keeps_annotations_and_repeatability_state(self):
        self.seed();self.project.verify_annotations(self.ids[0]);self.seed(7,"repeat-model");self.project.start_structure_batch(2)
        self.project.set_ui_state("xray_structure_repeatability",{"sentinel":"existing run"})
        before=[self.project.annotations(self.ids[0],p) for p in (1,7)]
        workspace=SimpleNamespace(project=self.project,_refresh_workflow=Mock())
        XRayStructureWorkspace._close_annotation_batch(workspace)
        self.assertEqual({},self.project.get_ui_state("xray_structure_active_batch"))
        self.assertEqual(before,[self.project.annotations(self.ids[0],p) for p in (1,7)])
        self.assertEqual({"sentinel":"existing run"},self.project.get_ui_state("xray_structure_repeatability"))

    def test_closing_core_navigation_does_not_write_project_data(self):
        batch={"kind":"landmark","text":"1/2"}
        shell=object.__new__(ProductionShell)
        shell.context=SimpleNamespace(project=self.project,section="landmarks")
        shell._persisted_batch_summary=Mock(return_value=batch);shell.render=Mock()
        before=self.project.db_path.read_bytes()
        shell.close_queue_navigation()
        self.assertIsNone(shell._active_batch_summary());self.assertEqual(before,self.project.db_path.read_bytes())
        shell.resume_queue_navigation();self.assertEqual(batch,shell._active_batch_summary())

    def test_crop_caption_reads_recorded_detector_provenance_without_writing(self):
        specimen=self.project.specimen(self.ids[0])
        with _db_connection(self.project.db_path) as db:
            self.project._event(db,self.ids[0],"detect","model",{"model_id":"recorded-crop-model"})
            db.execute("UPDATE crop_events SET created_at=? WHERE specimen_id=? AND action='detect'",("2024-05-06T07:08:00",self.ids[0]))
        workspace=SimpleNamespace(project=self.project,selected_image_id=specimen["image_id"],
            plate_list=SimpleNamespace(_sample=lambda path:"Sample"),
            session=PlateCropEditSession(self.project.specimens(specimen["image_id"])),context_label=Mock(),
            sample_value=Mock(),crop_value=Mock(),prediction_text="",_draw=Mock())
        before=self.project.db_path.read_bytes()
        with patch.object(self.project,"active_crop_model",side_effect=AssertionError("active model is not provenance")):
            XRayCropWorkspace._refresh_plate_context(workspace)
        self.assertIn("recorded-crop-model",workspace.prediction_text);self.assertIn("2024-05-06 07:08",workspace.prediction_text)
        self.assertEqual("Sample",workspace.sample_value.configure.call_args.kwargs["text"])
        self.assertTrue(workspace._draw.called)
        self.assertEqual(before,self.project.db_path.read_bytes())

    def test_release_layout_widths_keep_lists_readable_without_taking_over_the_canvas(self):
        self.assertEqual(284,sidebar_width_for_window(980,320))
        self.assertEqual(442,sidebar_width_for_window(1640,320))
        self.assertLessEqual(sidebar_width_for_window(1920,600),480)
        crop_model_columns=(165,130,165,130,150,170,80)
        self.assertGreaterEqual(dialog_width_for_columns(crop_model_columns,1456,chrome=105),sum(crop_model_columns)+105)
        self.assertLessEqual(dialog_width_for_columns(crop_model_columns,1024,chrome=105),944)

    def test_workflow_dock_equalizes_stage_cards_without_divider_bars(self):
        source=(Path(__file__).resolve().parents[1]/"app/ui/workflow.py").read_text(encoding="utf-8")
        self.assertIn("target_height=max(card.winfo_reqheight() for card in self._cards)",source)
        self.assertIn("uniform='workflow_stage'",source)
        self.assertNotIn("_stage_separators",source)
        self.assertNotIn("sep.grid(row=0,column=column+1",source)
        self.assertIn("card.grid(row=0,column=index,sticky='nsew'",source)

    def test_saved_attention_queue_uses_the_same_compact_strip_language(self):
        source=(Path(__file__).resolve().parents[1]/"app/ui/section_base.py").read_text(encoding="utf-8")
        self.assertIn('style="Attention.TFrame",padding=(6,4)',source)
        self.assertIn('self.button(box,"Continue"',source)
        self.assertIn('self.button(box,"Hide"',source)
        self.assertNotIn('message_label=ttk.Label',source)

    def test_preview_projects_have_real_crop_frames_and_preserve_review_edits(self):
        from tools.design_preview import build_preview_projects
        from app.landmark_frames import crop_frame_record
        preview=Path(self.temp.name)/"isolated-preview"
        core,xray=build_preview_projects(preview);ident=core.catalog_rows()[0]["image_id"]
        self.assertTrue(crop_frame_record(core,ident));self.assertEqual(8,len(xray.specimens()))
        core.save_landmark(ident,1,145,180,"present")
        before=core.load_landmarks(ident)
        again,_=build_preview_projects(preview)
        self.assertEqual(before,again.load_landmarks(ident))
        self.assertTrue(again.root.is_relative_to(preview))


class PresentationTkTests(_ProjectFixture,unittest.TestCase):
    def setUp(self):
        super().setUp()
        try:self.root=tk.Tk()
        except tk.TclError as exc:self.skipTest(f"Tk display unavailable: {exc}")
        self.addCleanup(self.root.destroy)
        self.root.geometry("980x650+0+0");apply_styles(self.root,ttk.Style(self.root))
        self.errors=[];self.root.report_callback_exception=lambda *args:self.errors.append(args)
        errors=patch("tkinter.messagebox.showerror",side_effect=lambda title,text,**kw:(_ for _ in ()).throw(AssertionError(f"{title}: {text}")))
        errors.start();self.addCleanup(errors.stop)
        self.host=ttk.Frame(self.root);self.host.pack(fill="both",expand=True)

    def pump(self):
        for _ in range(8):self.root.update_idletasks();self.root.update()
        self.assertEqual([],self.errors)

    def assert_visible(self,widget):
        self.assertTrue(widget.winfo_viewable(),str(widget))
        self.assertGreater(widget.winfo_width(),10)
        self.assertGreaterEqual(widget.winfo_rootx(),self.root.winfo_rootx())
        self.assertLessEqual(widget.winfo_rootx()+widget.winfo_width(),self.root.winfo_rootx()+self.root.winfo_width())

    def test_crop_sidebar_and_all_toolbar_actions_fit_a_small_window(self):
        workspace=XRayCropWorkspace(self.host,self.project);self.pump()
        self.assertGreater(workspace.plate_list.winfo_width(),250)
        for button in (workspace.delete_crop_button,workspace.clear_plate_button,workspace.flip_h_button,workspace.flip_v_button,workspace.apply_button):self.assert_visible(button)
        self.assertGreater(workspace.canvas.winfo_height(),180)
        workspace.workflow_dock._toggle();self.pump()
        self.assertGreater(workspace.canvas.winfo_height(),350)

    def test_structures_sidebar_markers_and_workflow_tabs_remain_reachable(self):
        self.seed();workspace=XRayStructureWorkspace(self.host,self.project);self.pump()
        self.assertGreater(workspace.specimen_list.winfo_width(),250)
        for button in (workspace.clear_type_button,workspace.clear_all_button,workspace.apply_button,workspace.display_button):self.assert_visible(button)
        for button in workspace._marker_buttons.values():
            # Marker entries are dictionaries containing their button/state widgets.
            self.assert_visible(button["button"] if isinstance(button,dict) else button)
        for structure_id,button in workspace._marker_buttons.items():
            visibility=workspace._marker_visibility_buttons[structure_id]
            self.assertLessEqual(abs(button.winfo_height()-visibility.winfo_height()),4)
        dock=workspace.workflow_dock;self.assertEqual(1,dock._last_columns)
        for index,tab in enumerate(dock._tabs):
            tab.invoke();self.pump()
            self.assertTrue(dock._cards[index].winfo_viewable())
            self.assertEqual(1,sum(bool(card.winfo_viewable()) for card in dock._cards))
        self.assertGreater(workspace.canvas.winfo_height(),120)
        dock._toggle();self.pump();self.assertGreater(workspace.canvas.winfo_height(),300)

    def test_verify_next_keeps_existing_validation_and_advances_only_after_confirmation(self):
        self.project.start_structure_batch(2);workspace=XRayStructureWorkspace(self.host,self.project);self.pump()
        current=workspace.selected_specimen_id
        with patch("app.xray_structures_ui.messagebox.showwarning") as warning:
            workspace.verify_next();warning.assert_called_once()
        self.assertEqual(current,workspace.selected_specimen_id)
        self.seed();workspace._load_specimen(self.ids[0]);self.pump();workspace.verify_next();self.pump()
        self.assertEqual("verified",self.project.annotation_run(self.ids[0])["status"])
        self.assertEqual(self.ids[1],workspace.selected_specimen_id)


if __name__=="__main__":unittest.main()
