from __future__ import annotations
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from tkinter import ttk

from PIL import Image
from app.project_storage import Project
from app.ui.design import apply_styles
from app.ui.export_section import ExportSection

ROOT=Path(__file__).resolve().parents[1]

class ApprovedTerminologyTests(unittest.TestCase):
    def test_approved_scientific_ui_copy_and_stale_phrases(self):
        expected={
            "app/ui/module_hub.py":[
                "Large-scale biological image annotation with human review and optional AI assistance",
                "Mark and count anatomical structures in X-ray images.",
            ],
            "app/ui/project_section.py":["Create a project or open an existing MorphoLabel project."],
            "app/ui/measurements_section.py":[
                "To measure distances in millimetres, calibrate each sample group using a known reference distance.",
                "Convert pixel distances to millimetres using a known reference distance.",
                "Required for measurements in millimetres.",
            ],
            "app/ui/export_section.py":[
                "Export landmark coordinates as TPS, CSV or MorphoJ-compatible text. This direct export is not restricted to human-verified images.",
                "Export named linear measurements as a table. This direct export may include eligible unverified images.",
                "Output contains the project measurement definitions and their values for eligible images.",
                "One specimen per row, with landmark coordinates, sample and source-file information. Suitable for R and Excel.",
                "Landmark coordinates in original-image pixels, for TPS-compatible morphometric software.",
                "One landmark per row, including annotation state and provenance.",
                "Numeric landmark coordinates for complete specimens. A companion CSV identifies samples and source files.",
                "Direct landmark and measurement exports may also include eligible records that have not been human-verified.",
                "Export landmark coordinates and measurements for downstream analysis.",
                "For a final reviewed dataset, choose Export analysis dataset and keep Verified only (default).",
                "The analysis dataset includes specimen identities, project definitions and information about missing or omitted values.",
            ],
            "app/calibration_workflow.py":[
                "Calibrate each sample group using a known reference distance in millimetres.",
                "The same calibration is applied to every image in this group. All images must have the same effective image scale.",
                "Calibration converts pixel distances into millimetres.",
                "For each sample group, choose an image containing a known reference length.",
                "This calibration applies to all images in the group and is valid only if their effective image scale is identical.",
            ],
            "app/ui/model_accuracy.py":[
                "P90 manual-to-manual displacement (% of configuration span)",
                "P90 AI-to-manual displacement (% of configuration span)",
                "AI-to-manual P90 / manual-to-manual P90",
                "Configuration span is the greatest distance between two present landmarks in the reference configuration.",
                "Landmarks used only for linear measurements are excluded.",
                "Switch to GM-only to exclude landmarks used only for linear measurements.",
                '"CLASSICAL":"Linear measurements"',
            ],
            "app/modules/landmarks.py":[
                "Human P90 measures disagreement between repeated manual placements.",
                "Both are normalized by landmark configuration span.",
                "The AI/Human ratio is descriptive, not a formal accuracy score.",
                "AI-to-human disagreement is smaller than manual-to-manual disagreement on this control set.",
                "AI-to-human and manual-to-manual disagreement have equal P90 values on this control set.",
            ],
            "app/xray_schema.py":[
                "Record whether the biological structure is present or absent.",
                "Use Not visible when its state cannot be assessed from the radiograph.",
                "Calculate straight-line distance in normalized crop coordinates (dimensionless).",
                "This is not a physical measurement in millimetres.",
                "Inclusion of the boundary depends on the selected rule.",
                "including the elements associated with both boundaries.",
            ],
            "app/xray_structures_ui.py":[
                "4. Check and verify",
                "Verify specimen records the current annotations as human-verified.",
                "Mean marker distance",
                "Marker distances are calculated between nearest unmatched markers within each structure class, using normalized crop coordinates.",
                "They are dimensionless and do not represent physical distances.",
            ],
            "app/xray_crop_ui.py":[
                "Check each crop, head direction and ventral orientation.",
                "Check the suggested crop frames, head direction and ventral orientation; then confirm.",
                "Blue indicates the head; orange indicates the ventral side.",
            ],
            "app/modules/xray_counts.py":[
                "Before excludes the boundary element.",
                "Count between includes both boundary elements.",
                "Independent reference marks are associated with the nearest element of the ordered series.",
                "A fixed numerical offset, if defined, is added to the calculated count.",
                "Check the displayed order before interpreting direction-dependent counts or positions.",
            ],
        }
        for relative,phrases in expected.items():
            source=(ROOT/relative).read_text(encoding="utf-8")
            for phrase in phrases:
                with self.subTest(file=relative,phrase=phrase):self.assertIn(phrase,source)
        stale=(
            "Annotate large image collections with AI",
            "Mark and count skeletal structures in X-ray images.",
            "Create a project or open an existing portable MorphoLabel project.",
            "To obtain millimetres or other physical units",
            "Set a known distance once per sample",
            "P90 between two blind manual placements",
            "CLASSICAL-only landmarks are excluded",
            "Human P90: your repeat-placement error.",
            "Mean marker difference",
            "Blue shows the head; orange shows the belly.",
        )
        sources="\n".join(p.read_text(encoding="utf-8") for p in (ROOT/"app").rglob("*.py"))
        for phrase in stale:self.assertNotIn(phrase,sources)

    def test_display_labels_change_without_changing_schema_codes_or_trait_ids(self):
        editor=(ROOT/"app/schema_editor.py").read_text(encoding="utf-8")
        self.assertIn('"CL":"Linear measurements"',editor)
        self.assertIn('("role","Use",190,False)',editor)
        self.assertIn('ROLE_CODES={"BT":"BOTH","GM":"GM","CL":"CLASSICAL"}',editor)
        source=(ROOT/"app/xray_schema.py").read_text(encoding="utf-8")
        for method in ('"id":"count"','"id":"count_to"','"id":"count_between"','"id":"presence"','"id":"distance"'):
            self.assertIn(method,source)

class ExportNativeSaveDialogTests(unittest.TestCase):
    def setUp(self):
        self.interp=tk.Tcl();self.section=ExportSection.__new__(ExportSection);self.section.shell=self.interp

    def test_cancel_and_default_wide_custom_filename(self):
        from app.ui.export_section import _LANDMARK_FORMATS
        from unittest.mock import patch
        fmt=_LANDMARK_FORMATS["Wide CSV"]
        custom=Path(tempfile.gettempdir())/"fish_study.csv"
        with patch("app.ui.export_section.filedialog.asksaveasfilename",return_value=str(custom)) as save:
            target,kind=self.section._save_as("Export landmarks",fmt["initial"],[(fmt["filter"],fmt["pattern"])],fmt["extension"],fmt["filter"])
        self.assertEqual(str(custom),target);self.assertEqual(fmt["filter"],kind)
        self.assertEqual("landmarks_wide.csv",save.call_args.kwargs["initialfile"])
        self.assertEqual(".csv",save.call_args.kwargs["defaultextension"])
        with patch("app.ui.export_section.filedialog.asksaveasfilename",return_value=""):
            target,_=self.section._save_as("Export landmarks",fmt["initial"],[(fmt["filter"],fmt["pattern"])],fmt["extension"],fmt["filter"])
        self.assertEqual("",target)

    def test_bad_extension_reopens_dialog_and_never_silently_changes_confirmed_target(self):
        from app.ui.export_section import _LANDMARK_FORMATS
        from unittest.mock import patch
        fmt=_LANDMARK_FORMATS["Wide CSV"]
        wrong=Path(tempfile.gettempdir())/"user_table.tps";final=Path(tempfile.gettempdir())/"user_table.csv"
        with patch("app.ui.export_section.filedialog.asksaveasfilename",side_effect=[str(wrong),str(final)]) as save, patch("app.ui.export_section.messagebox.showinfo") as notice:
            target,_=self.section._save_as("Export landmarks",fmt["initial"],[(fmt["filter"],fmt["pattern"])],fmt["extension"],fmt["filter"])
        self.assertEqual(str(final),target);self.assertEqual(2,save.call_count);notice.assert_called_once()
        self.assertEqual("user_table.csv",save.call_args_list[1].kwargs["initialfile"])

class ExportTkLayoutTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name);source=root/"source";source.mkdir()
        Image.new("RGB",(80,40),(125,125,125)).save(source/"sample.jpg")
        schema=root/"schema.csv";schema.write_text("id,abbr,name,role,category\n1,A,Anterior,BOTH,Head\n2,T,Tail,BOTH,Tail\n",encoding="utf-8")
        self.project=Project.create("UI export",source,root,schema,source_layout="direct")
        try:self.root=tk.Tk()
        except tk.TclError as exc:self.skipTest(f"Tk display unavailable: {exc}")
        self.addCleanup(self.root.destroy);self.root.title("Export layout test")
        apply_styles(self.root,ttk.Style(self.root))
        self.icons=[];self.background_calls=[]
        context=SimpleNamespace(project=self.project,rows=self.project.catalog_rows())
        shell=SimpleNamespace(context=context,tip=SimpleNamespace(bind=lambda *_args:None),tk=self.root.tk,_root=self.root._root)
        shell.ui_icon=lambda _name,_size:self._icon()
        shell.control_button=lambda parent,text,command,help_text,**kwargs:ttk.Button(parent,text=text,command=command,**kwargs)
        shell._run_background_task=self._run_task
        self.section=ExportSection(shell,self.root);self.section.render();self.pump()

    def _icon(self):
        image=tk.PhotoImage(master=self.root,width=1,height=1);self.icons.append(image);return image

    def _run_task(self,*args):
        worker=args[-2];complete=args[-1]
        result=worker(lambda _message:None);self.background_calls.append(result);complete(result)

    def pump(self):
        for _ in range(3):self.root.update_idletasks();self.root.update()

    def test_real_tk_export_controls_defaults_actions_and_actual_wide_export(self):
        self.assertTrue(self.section.format_selector.winfo_exists())
        self.assertEqual("readonly",str(self.section.format_selector.cget("state")))
        self.assertEqual("Wide CSV",self.section.landmark_format.get())
        self.assertEqual(("Wide CSV","TPS","Long CSV","MorphoJ"),tuple(self.section.format_selector.cget("values")))
        self.assertEqual("all",self.section.landmark_mode.get())
        self.assertEqual("Primary.TButton",self.section.landmark_export_button.cget("style"))
        self.assertTrue(self.section.analysis_export_button.winfo_exists())
        self.assertGreater(self.section.analysis_export_button.winfo_y(),self.section.landmark_export_button.winfo_y())
        self.assertNotEqual("Primary.TButton",self.section.measurements_export_button.cget("style"))
        self.assertIn(str(self.project.root),self.section.project_folder_label.cget("text"))
        with patch("app.ui.export_section.filedialog.asksaveasfilename",return_value=""):
            self.section.landmark_export_button.invoke();self.pump()
        self.assertEqual([],self.background_calls)
        output=Path(self.temp.name)/"landmarks_wide.csv"
        with patch("app.ui.export_section.filedialog.asksaveasfilename",return_value=str(output)) as save, patch("app.ui.export_section.messagebox.showinfo"):
            self.section.landmark_export_button.invoke();self.pump()
        self.assertTrue(output.is_file());self.assertEqual("landmarks_wide.csv",save.call_args.kwargs["initialfile"])
        self.assertEqual(".csv",save.call_args.kwargs["defaultextension"])
        self.assertEqual(1,len(self.background_calls))
        self.section.landmark_format.set("MorphoJ");self.section.format_selector.event_generate("<<ComboboxSelected>>");self.pump()
        self.assertIn("Numeric landmark coordinates",self.section.format_description_label.cget("text"))

    def test_calibration_and_accuracy_dialog_geometry_at_all_requested_scales(self):
        from app.calibration_workflow import CalibrationWorkflow
        from app.ui.model_accuracy import LandmarkAccuracyDialog
        image_id=self.project.catalog_rows()[0]["image_id"]
        developed=self.project.cache_root/"developed";developed.mkdir(parents=True,exist_ok=True)
        Image.new("RGB",(80,40),(120,120,120)).save(developed/f"{image_id}.png")
        calibration=CalibrationWorkflow(self.root,self.project)
        self.addCleanup(calibration.close);self.pump()
        metrics={"aggregate":{"p90_error_percent":0.4},"aggregate_by_scope":{"gm":{"p90_error_percent":0.3}},"per_landmark":{},"per_landmark_by_scope":{"gm":{}}}
        accuracy=LandmarkAccuracyDialog(self.root,self.project,"model-test",metrics,metrics)
        self.addCleanup(accuracy.destroy);self.pump()
        from app.xray_structures_ui import XRayStructureWorkspace
        repeatability={"run":{"annotation1_verified":2,"annotation2_verified":1,"total":2},"structures":[]}
        proxy=SimpleNamespace(root=self.root,project=SimpleNamespace(structure_repeatability_metrics=lambda _run_id:repeatability))
        XRayStructureWorkspace.show_repeatability_results(proxy);self.pump()
        repeat_dialog=next(w for w in self.root.winfo_children() if isinstance(w,tk.Toplevel) and w.title()=="Human repeatability")
        repeat_subtitle=next(w for w in repeat_dialog.winfo_children()[0].winfo_children() if isinstance(w,ttk.Label) and "Marker distances are calculated" in str(w.cget("text")))
        for width,height in ((1280,720),(1600,900),(1920,1080)):
            for scaling in (1.0,1.25,1.5):
                with self.subTest(size=(width,height),scaling=scaling):
                    self.root.tk.call("tk","scaling",scaling);self.root.geometry(f"{width}x{height}+0+0");self.pump()
                    for window,widgets in (
                        (calibration,(calibration.calibration_subtitle,calibration.calibration_scale_note,calibration.save_button,calibration.save_next_button)),
                        (accuracy,(accuracy.scope_note,)),
                        (repeat_dialog,(repeat_subtitle,)),
                    ):
                        for widget in widgets:
                            self.assertTrue(widget.winfo_viewable(),str(widget))
                            self.assertGreater(widget.winfo_width(),10)
                            self.assertLessEqual(widget.winfo_rootx()+widget.winfo_width(),window.winfo_rootx()+window.winfo_width()+1)
                            self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(),window.winfo_rooty()+window.winfo_height()+1)
                    def descendants(widget):
                        for child in widget.winfo_children():
                            yield child
                            yield from descendants(child)
                    close=next(w for w in descendants(accuracy) if isinstance(w,ttk.Button) and w.cget("text")=="Close")
                    self.assertTrue(close.winfo_viewable())
                    self.assertLessEqual(close.winfo_rooty()+close.winfo_height(),accuracy.winfo_rooty()+accuracy.winfo_height()+1)
                    repeat_close=next(w for w in descendants(repeat_dialog) if isinstance(w,ttk.Button) and w.cget("text")=="Close")
                    self.assertTrue(repeat_close.winfo_viewable())
                    self.assertLessEqual(repeat_close.winfo_rooty()+repeat_close.winfo_height(),repeat_dialog.winfo_rooty()+repeat_dialog.winfo_height()+1)

    def test_each_format_selector_choice_opens_correct_filter_name_and_real_exporter(self):
        from app.ui.export_section import _LANDMARK_FORMATS
        for name,fmt in _LANDMARK_FORMATS.items():
            with self.subTest(format=name):
                self.section.landmark_format.set(name);self.section.format_selector.event_generate("<<ComboboxSelected>>");self.pump()
                target=Path(self.temp.name)/fmt["initial"]
                with patch("app.ui.export_section.filedialog.asksaveasfilename",return_value=str(target)) as save, patch("app.ui.export_section.messagebox.showinfo"):
                    self.section.landmark_export_button.invoke();self.pump()
                self.assertTrue(target.is_file())
                self.assertEqual(fmt["initial"],save.call_args.kwargs["initialfile"])
                self.assertEqual(fmt["extension"],save.call_args.kwargs["defaultextension"])
                self.assertEqual([(fmt["filter"],fmt["pattern"])],save.call_args.kwargs["filetypes"])
        self.assertEqual(4,len(self.background_calls))

    def test_measurements_text_dialog_keeps_user_basename_and_uses_tab_delimiter(self):
        target=Path(self.temp.name)/"my_measurements.txt"
        def choose_text(**kwargs):
            kwargs["typevariable"].set("Tab-delimited text (*.txt)")
            return str(target)
        with patch("app.ui.export_section.filedialog.asksaveasfilename",side_effect=choose_text) as save, patch("app.ui.export_section.export_measurements",return_value={"rows":0,"path":target}) as export, patch("app.ui.export_section.messagebox.showinfo"):
            self.section.measurements_export_button.invoke();self.pump()
        self.assertEqual("measurements.csv",save.call_args.kwargs["initialfile"])
        self.assertEqual([("CSV (*.csv)","*.csv"),("Tab-delimited text (*.txt)","*.txt")],save.call_args.kwargs["filetypes"])
        self.assertEqual(str(target),export.call_args.kwargs["target"])
        self.assertEqual("\t",export.call_args.kwargs["delimiter"])

    def test_all_resolution_and_scaling_combinations_keep_export_controls_reachable(self):
        for width,height in ((1280,720),(1600,900),(1920,1080)):
            for scaling in (1.0,1.25,1.5):
                with self.subTest(size=(width,height),scaling=scaling):
                    self.root.tk.call("tk","scaling",scaling);self.root.geometry(f"{width}x{height}+0+0");self.pump()
                    for widget in (self.section.project_folder_label,self.section.format_selector,self.section.landmark_export_button,self.section.analysis_export_button,self.section.measurements_export_button):
                        self.assertTrue(widget.winfo_viewable(),str(widget))
                        self.assertGreater(widget.winfo_width(),10)
                        self.assertLessEqual(widget.winfo_rootx()+widget.winfo_width(),self.root.winfo_rootx()+self.root.winfo_width()+1)
                        self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(),self.root.winfo_rooty()+self.root.winfo_height()+1)
                    self.assertLessEqual(self.section.measurements_export_button.winfo_rooty()+self.section.measurements_export_button.winfo_height(),self.root.winfo_rooty()+self.root.winfo_height()+1)

if __name__=="__main__":unittest.main()
