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

from app.ui.design import apply_styles, structure_prediction_text, prediction_stamp, sidebar_width_for_window, dialog_width_for_columns, model_selector_width
from app.modules.landmarks import LandmarksRuntime
from app.ui.tooltips import Tooltip
from app.xray_crop import crop_from_geometry
from app.xray_crop_ui import PlateCropEditSession, XRayCropWorkspace
from app.xray_project import XRayProject, _db_connection
from app.xray_schema import bundled_scheme
from app.xray_structures_ui import XRayStructureWorkspace
from app.xray_specimen_identity import specimen_display_id


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
        shell=object.__new__(LandmarksRuntime)
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

    def test_model_selector_width_keeps_long_release_model_ids_readable(self):
        self.assertEqual(20,model_selector_width(("v006",)))
        self.assertEqual(36,model_selector_width(("xray_structure_model_v006_20261004",)))
        self.assertEqual(48,model_selector_width(("x"*80,)))

    def test_workflow_dock_uses_real_tabs_with_one_open_stage(self):
        source=(Path(__file__).resolve().parents[1]/"app/ui/workflow.py").read_text(encoding="utf-8")
        self.assertIn("ttk.Notebook(self,style='Workflow.TNotebook')",source)
        self.assertIn("self.notebook.add(card,**options)",source)
        self.assertIn("self.notebook.select(self._cards[self._selected_card])",source)
        self.assertIn("'Training data':'Start examples'",source)
        self.assertIn("self.notebook.bind('<Motion>',self._tab_motion",source)
        separator=source[source.index("def add_command_separator"):source.index("def build_help_button")]
        self.assertIn("ttk.Separator",separator)

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
        self.addCleanup(self._close_tk_fixture)
        self.root.geometry("980x650+0+0");apply_styles(self.root,ttk.Style(self.root))
        self.errors=[];self.root.report_callback_exception=lambda *args:self.errors.append(args)
        errors=patch("tkinter.messagebox.showerror",side_effect=lambda title,text,**kw:(_ for _ in ()).throw(AssertionError(f"{title}: {text}")))
        errors.start();self.addCleanup(errors.stop)
        self.host=ttk.Frame(self.root);self.host.pack(fill="both",expand=True)

    def _close_tk_fixture(self):
        # These tests use bare Tk rather than ProductionShell's owned teardown.
        # Drop fixture references and collect widget cycles on the Tk thread,
        # before a later parallel test can finalize their Variables on a worker.
        import gc
        root=self.root;self.root=None;self.host=None
        root.destroy();del root
        gc.collect()

    def test_fixture_releases_variables_before_background_collection(self):
        import gc
        import threading
        import weakref
        workspace=XRayStructureWorkspace(self.host,self.project);self.pump()
        references=[weakref.ref(workspace.pass_no),weakref.ref(workspace.specimen_list.sample_query)]
        del workspace
        self.doCleanups()
        self.assertTrue(all(reference() is None for reference in references))
        errors=[]
        with patch('sys.unraisablehook',side_effect=lambda event:errors.append(str(event.exc_value))):
            worker=threading.Thread(target=gc.collect);worker.start();worker.join()
        self.assertEqual([],errors)

    def pump(self):
        for _ in range(8):self.root.update_idletasks();self.root.update()
        self.assertEqual([],self.errors)

    def assert_visible(self,widget):
        self.assertTrue(widget.winfo_viewable(),str(widget))
        self.assertGreater(widget.winfo_width(),10)
        self.assertGreaterEqual(widget.winfo_rootx(),self.root.winfo_rootx())
        self.assertLessEqual(widget.winfo_rootx()+widget.winfo_width(),self.root.winfo_rootx()+self.root.winfo_width())

    def test_tooltip_is_destroyed_when_its_widget_is_destroyed(self):
        tip=Tooltip(self.root);button=ttk.Button(self.host,text="Transient");button.pack();self.pump()
        tip.bind(button,"temporary help");tip.schedule(button,"temporary help")
        if tip.job:
            self.root.after_cancel(tip.job);tip.job=None
        tip.owner=button;tip._show(button,"temporary help");self.pump()
        self.assertIsNotNone(tip.window)
        button.destroy();self.pump()
        self.assertIsNone(tip.window);self.assertIsNone(tip.owner)

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
        dock=workspace.workflow_dock
        for index,_tab in enumerate(dock._tabs):
            dock._select_card(index);self.pump()
            self.assertTrue(dock._cards[index].winfo_viewable())
            self.assertEqual(index,dock.notebook.index("current"))
        self.assertGreater(workspace.canvas.winfo_height(),120)
        dock._toggle();self.pump();self.assertGreater(workspace.canvas.winfo_height(),300)

    def test_crop_apply_disables_when_verified_and_reenables_after_real_edit(self):
        workspace=XRayCropWorkspace(self.host,self.project);self.pump()
        self.assertIn("disabled",workspace.apply_button.state())
        self.assertTrue(workspace.session.flip_horizontal())
        workspace._set_save_status();self.pump()
        self.assertNotIn("disabled",workspace.apply_button.state())
        self.assertEqual("SAVED",workspace.apply_current());self.pump()
        self.assertIn("disabled",workspace.apply_button.state())

    def test_structure_verify_disables_until_annotation_changes(self):
        self.seed();workspace=XRayStructureWorkspace(self.host,self.project);self.pump()
        workspace._load_specimen(self.ids[0]);self.pump()
        self.assertTrue(workspace.verify_current());self.pump()
        self.assertIn("disabled",workspace.apply_button.state())
        point=self.project.annotations(self.ids[0])[0]
        self.project.move_annotation(point["annotation_id"],.23,.52)
        workspace._after_edit();self.pump()
        self.assertNotIn("disabled",workspace.apply_button.state())

    def test_verify_next_keeps_existing_validation_and_advances_only_after_confirmation(self):
        self.project.start_structure_batch(2);workspace=XRayStructureWorkspace(self.host,self.project);self.pump()
        current=workspace.selected_specimen_id
        with patch("app.xray_structures_ui.messagebox.showwarning") as warning:
            workspace.verify_next();warning.assert_called_once()
        self.assertEqual(current,workspace.selected_specimen_id)
        self.seed();workspace._load_specimen(self.ids[0]);self.pump();workspace.verify_next();self.pump()
        self.assertEqual("verified",self.project.annotation_run(self.ids[0])["status"])
        self.assertEqual(self.ids[1],workspace.selected_specimen_id)


    def assert_selected_row_visible(self,canvas):
        self.assertTrue(canvas.curselection())
        y=canvas.curselection()[0]*canvas.row_height
        top=canvas.canvasy(0);bottom=top+canvas.winfo_height()
        self.assertGreaterEqual(y,top-1)
        self.assertLessEqual(y+canvas.row_height,bottom+1)

    def test_late_selection_stays_visible_across_crops_structures_and_export(self):
        from app.modules.xray_counts import XRayCountsRuntime
        source=Path(self.temp.name)/"source"
        for i in range(40):Image.new("L",(900,480),90).save(source/f"plate_extra_{i:02d}.png")
        self.project.scan_source()
        for row in self.project.source_images():
            if not self.project.specimens(row["image_id"]):
                self.project.add_manual_specimen(row["image_id"],self.crop)
                self.project.confirm_plate(row["image_id"])
        item=self.project.structure_specimens()[-1]
        ident=item["specimen_id"]
        self.project.apply_plate_crop_edits(item["image_id"],edits=[{"specimen_id":ident,"specimen_code":"AB-001"}])
        self.project.set_current_selection(item["image_id"],ident)
        host=SimpleNamespace(container=self.host,state={"project":self.project})
        runtime=XRayCountsRuntime();runtime.stage="crops";runtime.render(host)
        self.addCleanup(runtime.close)
        for stage in ("crops","structures","export","crops","structures","export"):
            runtime._select(stage);self.pump()
            self.assertEqual(ident,self.project.current_selection()["specimen_id"])
            if stage=="crops":
                self.assert_selected_row_visible(runtime._workspace.plate_list.canvas)
                self.assertEqual("AB-001",runtime._workspace.crop_value.cget("text"))
            elif stage=="structures":
                self.assert_selected_row_visible(runtime._workspace.specimen_list.canvas)
                self.assertEqual("AB-001",runtime._workspace.specimen_value.cget("text"))
            else:
                def descendants(widget):
                    for child in widget.winfo_children():
                        yield child
                        yield from descendants(child)
                tree=next(w for w in descendants(self.host) if isinstance(w,ttk.Treeview))
                self.assertEqual((ident,),tree.selection());self.assertTrue(tree.bbox(ident))
                self.assertEqual("AB-001",tree.set(ident,"fish"))

    def test_specimen_dialog_saves_text_and_shows_invalid_input_inline(self):
        from app.ui.specimen_id_dialog import SpecimenIDDialog
        workspace=XRayCropWorkspace(self.host,self.project);self.pump()
        old=workspace.session.selected_id
        def operate():
            dialog=next(w for w in self.root.winfo_children() if isinstance(w,SpecimenIDDialog))
            dialog.value.set("");dialog.ok()
            self.assertTrue(dialog.winfo_exists());self.assertIn("Enter a specimen ID",dialog.error.cget("text"))
            dialog.value.set("AB-001");dialog.ok()
        self.root.after(100,operate)
        workspace._edit_specimen_id();self.pump()
        self.assertEqual("AB-001",specimen_display_id(self.project.specimen(old)))
        self.assertEqual("AB-001",workspace.crop_value.cget("text"))
        def cancel():
            dialog=next(w for w in self.root.winfo_children() if isinstance(w,SpecimenIDDialog))
            dialog.value.set("Unsaved");dialog.cancel()
        self.root.after(100,cancel);workspace._edit_specimen_id();self.pump()
        self.assertEqual("AB-001",specimen_display_id(self.project.specimen(old)))

    def test_selection_idle_callback_is_cancelled_when_view_closes(self):
        from app.photo_list import PhotoListCanvas
        canvas=PhotoListCanvas(self.host);canvas.pack()
        canvas.set_rows([{"text":str(i)} for i in range(50)])
        canvas.selection_set(49);canvas.reveal_selection();canvas.destroy();self.pump()

    def test_hub_caps_layout_at_reference_size_and_preserves_artwork(self):
        from app.ui.module_hub import ModuleHub, _HUB_MAX_SIZE
        from app.extensions.builtins import module_registry
        from app.ui.icons import tk_icon
        images=[Path(__file__).resolve().parents[1]/"app/resources/module_covers"/name for name in ("landmarks.png","xray_traits.png")]
        before=[hashlib.sha256(path.read_bytes()).digest() for path in images]
        shell=SimpleNamespace(tip=Tooltip(self.root),open_module=Mock(),show_about=Mock(),
            ui_icon=lambda name,size:tk_icon(self.root,name,size),
            control_button=lambda parent,text,command,help_text:ttk.Button(parent,text=text,command=command))
        hub=ModuleHub(shell,self.host,module_registry());hub.render()
        for size in ("1600x900","1920x1080"):
            self.root.geometry(size+"+0+0");self.pump()
            self.assertEqual(_HUB_MAX_SIZE,(hub.content.winfo_width(),hub.content.winfo_height()))
            stage=hub.content.master
            self.assertLessEqual(abs(hub.content.winfo_x()-(stage.winfo_width()-hub.content.winfo_width())/2),1)
        self.root.geometry("980x650+0+0");self.pump()
        self.assertEqual((980,650),(hub.content.winfo_width(),hub.content.winfo_height()))
        self.assertEqual(before,[hashlib.sha256(path.read_bytes()).digest() for path in images])


if __name__=="__main__":unittest.main()
