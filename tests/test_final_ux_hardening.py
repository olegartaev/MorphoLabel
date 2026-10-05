"""Behavioral release regressions on disposable scientific projects and real Tk."""
import tkinter as tk
from tkinter import ttk
import unittest
import time
from pathlib import Path
from unittest.mock import patch

from app.ui.design import apply_styles
from tests import test_release_torture as fixtures


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


class FinalUXHardeningTests(unittest.TestCase):
    setUp = fixtures.ReleaseTortureTests.setUp
    make_shell = fixtures.ReleaseTortureTests.make_shell

    def pump(self, shell):
        for _ in range(6):shell.update_idletasks();shell.update()

    def test_navigation_text_and_queues_fit_minimum_window_at_150_percent(self):
        shell, errors = self.make_shell()
        original_scale=float(shell.tk.call("tk","scaling"));self.addCleanup(lambda:shell.tk.call("tk","scaling",original_scale))
        shell.deiconify();shell.geometry("980x650+0+0")
        shell.tk.call("tk", "scaling", 2.0);apply_styles(shell,shell.style)
        for module in ("landmarks", "xray_counts"):
            shell.open_module(module);self.pump(shell)
            buttons=[w for w in descendants(shell.root) if w.winfo_class() in ("TButton","TMenubutton") and str(w.cget("text")) in ("Modules","Project","Crop","Landmarks","Measurements","Structures","Export","Queues","Menu")]
            self.assertIn("Queues",[w.cget("text") for w in buttons])
            for button in buttons:
                self.assertGreaterEqual(button.winfo_width(),button.winfo_reqwidth(),button.cget("text"))
                self.assertLessEqual(button.winfo_rootx()+button.winfo_width(),shell.winfo_rootx()+shell.winfo_width())
        self.assertEqual([],errors)

    def test_project_scroll_reveals_controls_with_keyboard_and_keeps_science(self):
        from tests.test_architecture_torture import scientific_rows
        shell, errors=self.make_shell();shell.deiconify();shell.geometry("980x650+0+0")
        original_scale=float(shell.tk.call("tk","scaling"));self.addCleanup(lambda:shell.tk.call("tk","scaling",original_scale))
        shell.tk.call("tk", "scaling", 2.0);apply_styles(shell,shell.style)
        before=scientific_rows(self.landmark)
        shell.open_module("landmarks");runtime=shell._active_module_runtime;runtime.select("project");self.pump(shell)
        view=runtime.current_view;canvas=view.scroll_canvas
        use=next(w for w in descendants(shell.root) if w.winfo_class()=="TRadiobutton" and w.cget("text")=="Use Crop")
        use.focus_force();self.pump(shell)
        self.assertGreaterEqual(use.winfo_rooty(),canvas.winfo_rooty())
        self.assertLessEqual(use.winfo_rooty()+use.winfo_height(),canvas.winfo_rooty()+canvas.winfo_height())
        table=next(w for w in descendants(shell.root) if isinstance(w,ttk.Treeview))
        table.focus_force();self.pump(shell)
        self.assertLessEqual(table.winfo_rooty()+table.winfo_height(),canvas.winfo_rooty()+canvas.winfo_height())
        runtime.select("crop");self.pump(shell);runtime.select("project");self.pump(shell)
        self.assertEqual(before,scientific_rows(self.landmark));self.assertEqual([],errors)

    def test_support_menu_invokes_diagnostics_and_refreshes_model_availability(self):
        shell,errors=self.make_shell();shell.open_module("landmarks");self.pump(shell)
        menu_button=next(w for w in descendants(shell.root) if w.winfo_class()=="TMenubutton" and w.cget("text")=="Menu")
        menu=shell.nametowidget(str(menu_button.cget("menu")))
        def submenu(label):
            index=next(i for i in range(menu.index("end")+1) if menu.type(i)=="cascade" and menu.entrycget(i,"label")==label)
            return shell.nametowidget(str(menu.entrycget(index,"menu")))
        support=submenu("Support")
        # Exercise the actual Tcl command, independent of punctuation spelling.
        bundle=Path(self.temp.name)/"diagnostic.zip";bundle.write_bytes(b"synthetic")
        with patch("app.diagnostics.create_diagnostic_bundle",return_value=bundle),patch.object(shell,"_show_diagnostic_report_dialog") as show:
            support.invoke(0);show.assert_called_once()
        runtime=shell._active_module_runtime
        self.assertEqual((),runtime.standard_menu_entries())
        labels=[menu.entrycget(i,"label") for i in range(menu.index("end")+1) if menu.type(i)=="cascade"]
        self.assertNotIn("AI models · import / export",labels);self.assertEqual([],errors)
        from app.ai_delivery import ensure_ai_runtime,AIDeliveryError
        ai=submenu("AI support")
        self.assertTrue(ai.entrycget(0,"label").startswith("Set up AI support"))
        missing=Path(self.temp.name)/"missing-python.exe"
        with patch("app.ai_delivery.resolve_ai_runtime",return_value=(missing,missing)),patch("app.ai_delivery.is_frozen",return_value=True),patch("app.first_run_setup.ai_download_consent_granted",return_value=False):
            with self.assertRaisesRegex(AIDeliveryError,"Menu → AI support → Set up AI support"):
                ensure_ai_runtime()

    def test_large_trait_table_can_scroll_to_last_column_without_changing_export(self):
        import copy
        from tests.test_architecture_torture import scientific_rows
        from app.xray_trait_export import export_trait_rows
        scheme=copy.deepcopy(self.xray.scheme)
        scheme["traits"]=[{"id":f"count_{i}","name":f"Count {i}","method":"count","structures":["objects"],"rule":{}} for i in range(25)]
        self.xray.save_scheme(scheme,"Synthetic wide table")
        before=scientific_rows(self.xray)
        shell,errors=self.make_shell();shell.deiconify();shell.geometry("980x650+0+0")
        shell.open_module("xray_counts");shell._active_module_runtime._select("export");self.pump(shell)
        tree=next(w for w in descendants(shell.root) if isinstance(w,ttk.Treeview))
        self.assertLess(tree.xview()[1],1)
        scroll=next(w for w in descendants(tree.master) if isinstance(w,ttk.Scrollbar) and str(w.cget("orient"))=="horizontal")
        self.assertTrue(scroll.winfo_viewable());tree.xview_moveto(1);self.pump(shell)
        self.assertEqual(1,tree.xview()[1]);self.assertTrue(tree.bbox(self.specimens[0],"status"))
        self.assertEqual("Not started",tree.set(self.specimens[0],"status"))
        export_trait_rows(self.xray,Path(self.temp.name)/"wide.csv")
        self.assertEqual(before,scientific_rows(self.xray));self.assertEqual([],errors)

    def test_specimen_id_enter_and_escape_preserve_exact_saved_code(self):
        from app.ui.specimen_id_dialog import SpecimenIDDialog
        from app.xray_specimen_identity import specimen_display_id
        shell,errors=self.make_shell();shell.deiconify();shell.open_module("xray_counts")
        shell._active_module_runtime._select("crops");self.pump(shell)
        workspace=shell._active_module_runtime._workspace;ident=workspace.session.selected_id
        for code,key in (("0012","<Return>"),("Cancelled code","<Escape>"),("A12","<Return>"),("12-B","<Return>")):
            def operate(value=code,sequence=key):
                dialog=next(w for w in shell.winfo_children() if isinstance(w,SpecimenIDDialog))
                dialog.value.set(value);dialog.entry.focus_force();dialog.entry.event_generate(sequence)
            shell.after(100,operate);workspace._edit_specimen_id();self.pump(shell)
            if key=="<Return>":expected=code
            self.assertEqual(expected,specimen_display_id(self.xray.specimen(ident)))
        self.assertEqual([],errors)

    def test_structure_model_dialog_actions_fit_at_150_percent_without_selection(self):
        shell,errors=self.make_shell();shell.deiconify()
        original_scale=float(shell.tk.call("tk","scaling"));self.addCleanup(lambda:shell.tk.call("tk","scaling",original_scale))
        shell.tk.call("tk","scaling",2.0);apply_styles(shell,shell.style)
        shell.open_module("xray_counts");shell._active_module_runtime._select("structures");self.pump(shell)
        workspace=shell._active_module_runtime._workspace
        workspace.manage_structure_models();self.pump(shell)
        dialog=next(w for w in shell.winfo_children() if isinstance(w,tk.Toplevel) and w.title()=="X-ray structure models")
        dialog.geometry("900x420");self.pump(shell)
        for button in (w for w in descendants(dialog) if isinstance(w,ttk.Button)):
            self.assertGreaterEqual(button.winfo_width(),button.winfo_reqwidth(),button.cget("text"))
            self.assertLessEqual(button.winfo_rootx()+button.winfo_width(),dialog.winfo_rootx()+dialog.winfo_width(),button.cget("text"))
            if button.cget("text") in ("Make active","Compare with human…","Delete…","Export selected…"):
                self.assertIn("disabled",button.state())
        dialog.destroy();self.pump(shell);self.assertEqual([],errors)

    def test_real_canvas_inputs_save_coordinates_and_pan_keeps_science(self):
        from app.ui.crop_canvas import crop_frame_polygon
        from app.project_storage import Project
        from app.xray_project import XRayProject
        shell,errors=self.make_shell();shell.deiconify();shell.geometry("1366x768+0+0")
        def ready(predicate):
            deadline=time.monotonic()+5
            while not predicate() and time.monotonic()<deadline:
                self.pump(shell);time.sleep(.01)
            self.assertTrue(predicate(),"Image did not become ready")
        def gesture(canvas,start,end,button=1):
            canvas.event_generate(f"<ButtonPress-{button}>",x=round(start[0]),y=round(start[1]))
            canvas.event_generate(f"<B{button}-Motion>",x=round(end[0]),y=round(end[1]))
            canvas.event_generate(f"<ButtonRelease-{button}>",x=round(end[0]),y=round(end[1]));self.pump(shell)
        shell.open_module("landmarks");runtime=shell._active_module_runtime;runtime.select("crop");self.pump(shell)
        controller=runtime.current_view.canvas
        ready(lambda:controller.ready_for(runtime.context.current()["image_id"]))
        original=controller.model.left
        corner=controller._screen_source(*crop_frame_polygon(controller.model)[0])
        gesture(controller.canvas,corner,(corner[0]+20,corner[1]+10))
        self.assertGreater(controller.model.left,original)
        self.assertEqual("SAVED",controller.apply())
        ident=runtime.context.current()["image_id"]
        crop=self.landmark.crop_record(ident)
        runtime.select("landmarks");self.pump(shell);controller=runtime.current_view.canvas
        ready(lambda:controller.ready_for(ident))
        point=controller._position(20,20)
        gesture(controller.canvas,point,point)
        point=controller._position(20,20);target=controller._position(30,25)
        gesture(controller.canvas,point,target)
        saved=self.landmark.load_landmarks(ident)[1]
        self.assertAlmostEqual(30,saved["x_standardized"],delta=1)
        self.assertAlmostEqual(25,saved["y_standardized"],delta=1)
        before=self.landmark.load_landmarks(ident)
        gesture(controller.canvas,(150,100),(180,120),3)
        controller.canvas.event_generate("<MouseWheel>",x=150,y=100,delta=120);self.pump(shell)
        self.assertEqual(before,self.landmark.load_landmarks(ident))
        shell.show_module_hub();shell.open_module("xray_counts");runtime=shell._active_module_runtime;runtime._select("structures");self.pump(shell)
        workspace=runtime._workspace;sid=workspace.selected_specimen_id
        workspace.active_structure_id="objects"
        point=workspace._screen(.3,.5);gesture(workspace.canvas,point,point)
        self.assertEqual(1,len(self.xray.annotations(sid)))
        point=workspace._screen(.3,.5);target=workspace._screen(.45,.55)
        gesture(workspace.canvas,point,target)
        saved_xray=self.xray.annotations(sid)
        self.assertAlmostEqual(.45,saved_xray[0]["x"],delta=.01)
        gesture(workspace.canvas,(150,100),(180,120),3)
        workspace.canvas.event_generate("<MouseWheel>",x=150,y=100,delta=120);self.pump(shell)
        self.assertEqual(saved_xray,self.xray.annotations(sid))
        shell.show_module_hub()
        self.assertEqual(before,Project.open(self.landmark.root).load_landmarks(ident))
        self.assertEqual(crop,Project.open(self.landmark.root).crop_record(ident))
        self.assertEqual(saved_xray,XRayProject(self.xray.root).annotations(sid))
        shell.open_module("xray_counts");shell._active_module_runtime._select("structures");self.pump(shell)
        workspace=shell._active_module_runtime._workspace;workspace.selected_annotation_id=saved_xray[0]["annotation_id"]
        workspace.canvas.focus_force();workspace.canvas.event_generate("<Delete>");self.pump(shell)
        self.assertEqual([],self.xray.annotations(sid));self.assertEqual([],errors)

    def test_structure_marker_scroll_and_compact_tabs_preserve_image_at_150_percent(self):
        import copy
        from app.xray_schema import bundled_scheme
        shell,errors=self.make_shell();shell.deiconify();shell.geometry("980x650+0+0")
        original_scale=float(shell.tk.call("tk","scaling"));self.addCleanup(lambda:shell.tk.call("tk","scaling",original_scale))
        shell.tk.call("tk","scaling",2.0);apply_styles(shell,shell.style)
        scheme=copy.deepcopy(bundled_scheme("phoxinus_vertebral_counts"))
        self.xray.save_scheme(scheme,"Synthetic anatomy")
        shell.open_module("xray_counts");shell._active_module_runtime._select("structures");self.pump(shell)
        workspace=shell._active_module_runtime._workspace
        self.assertGreater(workspace.canvas.winfo_height(),120)
        for button in workspace._marker_buttons.values():
            button.focus_force();self.pump(shell)
            self.assertGreaterEqual(button.winfo_rooty(),workspace.marker_canvas.winfo_rooty())
            self.assertLessEqual(button.winfo_rooty()+button.winfo_height(),workspace.marker_canvas.winfo_rooty()+workspace.marker_canvas.winfo_height())
        dock=workspace.workflow_dock
        self.assertEqual("1. Repeatability",dock.notebook.tab(0,"text"))
        for index in range(len(dock._tabs)):
            dock._select_card(index);self.pump(shell)
            self.assertEqual(index,dock.notebook.index("current"))
            self.assertGreater(workspace.canvas.winfo_height(),100)
        self.assertEqual([],errors)

    def test_long_identifiers_have_full_hover_text_and_long_project_name_wraps(self):
        code="Образец с длинным идентификатором "+"1234567890"*8
        self.xray.apply_plate_crop_edits(self.plates[0],edits=[{"specimen_id":self.specimens[0],"specimen_code":code}])
        self.xray.set_current_selection(specimen_id=self.specimens[0])
        name="Biological collection with a long project name "*4
        import json
        config=self.landmark.config;config["name"]=name
        self.landmark.config_path.write_text(json.dumps(config),encoding="utf-8")
        shell,errors=self.make_shell();shell.deiconify();shell.geometry("980x650+0+0")
        original_scale=float(shell.tk.call("tk","scaling"));self.addCleanup(lambda:shell.tk.call("tk","scaling",original_scale))
        shell.tk.call("tk","scaling",2.0);apply_styles(shell,shell.style)
        baseline=shell.bind("<ButtonPress>").strip()
        shell.open_module("xray_counts");shell._active_module_runtime._select("structures");self.pump(shell)
        label=shell._active_module_runtime._workspace.specimen_value
        tip=label.master.context_tooltip
        text=tip._texts[str(label)][1]
        tip.owner=label;tip._show(label,text);self.pump(shell)
        self.assertIsNotNone(tip.window)
        shown=next(w.cget("text") for w in descendants(tip.window) if isinstance(w,ttk.Label))
        self.assertEqual(code,shown)
        shell.show_module_hub();self.pump(shell)
        self.assertIsNone(tip.window);self.assertEqual(baseline,shell.bind("<ButtonPress>").strip())
        shell.open_module("landmarks");self.pump(shell)
        title=next(w for w in descendants(shell.root) if isinstance(w,ttk.Label) and w.cget("text")==name)
        self.assertGreater(title.winfo_height(),40)
        self.assertLessEqual(title.winfo_width(),shell.winfo_width())
        self.assertEqual([],errors)

    def test_every_workflow_action_is_reachable_at_minimum_window_and_150_percent(self):
        from app.ui.workflow import WorkflowDock
        shell,errors=self.make_shell();shell.deiconify();shell.geometry("980x650+0+0")
        original_scale=float(shell.tk.call("tk","scaling"));self.addCleanup(lambda:shell.tk.call("tk","scaling",original_scale))
        shell.tk.call("tk","scaling",2.0);apply_styles(shell,shell.style)
        for module,stages in (("landmarks",("crop","landmarks","measurements")),("xray_counts",("crops","structures"))):
            shell.open_module(module);runtime=shell._active_module_runtime
            for stage in stages:
                (runtime.select if module=="landmarks" else runtime._select)(stage);self.pump(shell)
                dock=next(w for w in descendants(shell.root) if isinstance(w,WorkflowDock))
                for index in range(len(dock._tabs)):
                    dock._select_card(index);self.pump(shell)
                    buttons=[w for w in descendants(dock._cards[index]) if isinstance(w,ttk.Button) and w.winfo_viewable()]
                    self.assertTrue(buttons)
                    for button in buttons:
                        button.focus_force();self.pump(shell)
                        self.assertGreaterEqual(button.winfo_width(),button.winfo_reqwidth(),(module,stage,button.cget("text")))
                        self.assertLessEqual(button.winfo_rootx()+button.winfo_width(),shell.winfo_rootx()+shell.winfo_width())
                        viewport=button.master
                        while not isinstance(viewport,tk.Canvas):viewport=viewport.master
                        self.assertGreaterEqual(button.winfo_rooty(),viewport.winfo_rooty())
                        self.assertLessEqual(button.winfo_rooty()+button.winfo_height(),viewport.winfo_rooty()+viewport.winfo_height(),(module,stage,index,button.cget("text"),viewport.yview(),viewport.cget("scrollregion"),[(str(w),w.winfo_height(),w.winfo_reqheight()) for w in (button.master,button.master.master)]))
                if module=="landmarks" and stage=="landmarks":canvas=runtime.current_view.canvas.canvas
                elif module=="xray_counts":canvas=runtime._workspace.canvas
                else:continue
                self.assertGreater(canvas.winfo_height(),100)
        self.assertEqual([],errors)


if __name__=="__main__":unittest.main()
