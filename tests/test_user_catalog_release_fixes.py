"""Focused tests for user-reported catalogue and release usability defects."""
from pathlib import Path
import shutil
import tempfile
import unittest
from PIL import Image

from app.xray_project import XRayProject, _db_connection
from app.xray_schema import blank_scheme


class CatalogSafetyTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(tempfile.mkdtemp(prefix="morpholabel_catalog_fix_"))
        self.source=self.root/"incoming"
        self.source.mkdir()
        Image.new("RGB",(12,8),"white").save(self.source/"plate_a.png")
        self.destination=self.root/"projects"
        self.destination.mkdir()
        self.project=XRayProject.create("research",self.source,self.destination,blank_scheme())

    def tearDown(self):
        shutil.rmtree(self.root,ignore_errors=True)

    def test_rescan_reports_new_existing_and_missing_without_deleting_history(self):
        first=self.project.scan_source(report=True)
        self.assertEqual((first["new"],first["already_indexed"],first["missing"]),(0,1,0))
        image_id=self.project.source_images()[0]["image_id"]
        Image.new("RGB",(12,8),"blue").save(self.project.source/"plate_b.png")
        second=self.project.scan_source(report=True)
        self.assertEqual((second["new"],second["already_indexed"],second["missing"]),(1,1,0))
        (self.project.source/"plate_a.png").unlink()
        third=self.project.scan_source(report=True)
        self.assertEqual((third["new"],third["already_indexed"],third["missing"]),(0,1,1))
        self.assertIn(image_id,[row["image_id"] for row in self.project.source_images()])

    def test_rescan_missing_folder_is_not_a_silent_success(self):
        moved=self.project.root/"source_offline"
        self.project.source.rename(moved)
        with self.assertRaises(FileNotFoundError):
            self.project.scan_source(report=True)

    def test_model_numbers_follow_imported_high_water_even_after_delete(self):
        with _db_connection(self.project.db_path) as c:
            self.project._remember_model_number(c,"xray_crop_model_v008","xray_crop_model_v","crop_model_highwater")
            self.project._remember_model_number(c,"xray_structure_model_v012","xray_structure_model_v","structure_model_highwater")
        self.assertEqual(self.project.next_crop_model_id(),"xray_crop_model_v009")
        self.assertEqual(self.project.next_structure_model_id(),"xray_structure_model_v013")
        self.assertEqual(self.project.next_crop_model_id(),"xray_crop_model_v009")

    def test_training_progress_without_model_does_not_invent_used_examples(self):
        self.assertEqual(self.project.crop_training_usage(None),{"used":0,"new":0,"known":True})
        self.assertEqual(self.project.structure_training_usage(None),{"used":0,"new":0,"known":True})


class UIFixContracts(unittest.TestCase):
    def test_results_are_filtered_before_statistics_and_export_scope_is_explicit(self):
        src=(Path(__file__).resolve().parents[1]/"app/modules/xray_counts.py").read_text(encoding="utf-8")
        self.assertIn('("export","Results","xray_export")',src)
        self.assertIn('sample_term in item[1].casefold() and plate_term in item[2].casefold()',src)
        self.assertIn('if math.isfinite(value):values.append(value)',src)
        self.assertIn('lambda:self._export_traits(self._trait_export_scope.get()=="verified")',src)

    def test_structure_training_parent_picker_and_auto_zip(self):
        src=(Path(__file__).resolve().parents[1]/"app/xray_structures_ui.py").read_text(encoding="utf-8")
        self.assertIn("self.training_parent_box=ttk.Combobox",src)
        self.assertIn('Path(tempfile.mkdtemp(prefix="morpholabel_structure_candidate_"))',src)
        self.assertNotIn('title="Save model candidate"',src)

    def test_predict_window_close_is_cancel_not_destroy(self):
        for file in ("xray_crop_ui.py","xray_structures_ui.py"):
            src=(Path(__file__).resolve().parents[1]/"app"/file).read_text(encoding="utf-8")
            self.assertIn('dialog.protocol("WM_DELETE_WINDOW",lambda:(cancel.set()',src)


if __name__=="__main__":
    unittest.main()
