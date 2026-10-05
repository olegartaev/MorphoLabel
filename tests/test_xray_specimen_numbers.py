"""Specimen numbering must preserve scientific identities and verified data."""
import csv
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from PIL import Image
from app.xray_project import XRayProject, _db_connection
from app.xray_schema import bundled_scheme
from app.xray_crop import crop_from_geometry
from app.xray_crop_ui import PlateCropEditSession, XRayCropWorkspace
from app.xray_trait_export import export_trait_rows
from app.xray_specimen_identity import specimen_display_id


class SpecimenNumberTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        root=Path(temp.name);source=root/"source";source.mkdir()
        Image.new("L",(800,400),100).save(source/"plate.png")
        self.project=XRayProject.create("numbers",source,root,bundled_scheme("phoxinus_vertebral_counts"))
        self.image=self.project.source_images()[0]["image_id"]
        self.crop=crop_from_geometry(400,100,700,100,0,(800,400),algorithm="manual")
        self.one=self.project.add_manual_specimen(self.image,self.crop)
        self.two=self.project.add_manual_specimen(self.image,crop_from_geometry(400,300,700,100,0,(800,400),algorithm="manual"))
        self.project.confirm_plate(self.image)

    def test_code_only_edit_keeps_verified_annotations_crop_and_prediction_history(self):
        self.project.seed_structure_predictions(self.one,[
            {"structure_id":"vertebra","x":.3,"y":.5},
            {"structure_id":"preanal_pterygiophore","x":.4,"y":.6},
            {"structure_id":"first_caudal","x":.6,"y":.5},
            {"structure_id":"last_predorsal","x":.3,"y":.5},
        ],"original-model")
        self.project.verify_annotations(self.one)
        before=self.project.specimen(self.one);annotations=self.project.annotations(self.one)
        prediction_history=self.project.annotation_events(self.one)
        session=PlateCropEditSession(self.project.specimens(self.image),self.one)
        self.assertTrue(session.rename_selected("AB-001"))
        self.project.apply_plate_crop_edits(self.image,**session.changes())
        reopened=XRayProject(self.project.root);after=reopened.specimen(self.one)
        self.assertEqual(before["ordinal"],after["ordinal"]);self.assertEqual(before["label"],after["label"])
        self.assertEqual("AB-001",after["specimen_code"])
        for key in ("crop","crop_status","crop_source","model_id","excluded"):
            self.assertEqual(before[key],after[key],key)
        self.assertEqual(annotations,reopened.annotations(self.one))
        self.assertEqual(prediction_history,reopened.annotation_events(self.one))
        self.assertEqual("verified",reopened.annotation_run(self.one)["status"])
        self.assertTrue(reopened.source_image(self.image)["crop_reviewed"])
        export_trait_rows(reopened,self.project.root/"numbers.csv")
        with (self.project.root/"numbers.csv").open(encoding="utf-8-sig",newline="") as stream:
            rows=list(csv.DictReader(stream))
        exported=next(row for row in rows if row["specimen_id"]==self.one)
        self.assertEqual("1",exported["ordinal"]);self.assertEqual("AB-001",exported["specimen_code"])

    def test_duplicate_and_invalid_codes_do_not_mutate_project(self):
        before=self.project.specimen(self.one);events=self.project.crop_events(self.one)
        for value in ("2","", "   ","A\n1","A\t1","x"*129):
            with self.assertRaises((ValueError,OverflowError)):
                self.project.apply_plate_crop_edits(self.image,edits=[{"specimen_id":self.one,"specimen_code":value}])
            self.assertEqual(before,self.project.specimen(self.one))
            self.assertEqual(events,self.project.crop_events(self.one))

    def test_new_crop_retains_code_and_removed_code_can_be_reused(self):
        session=PlateCropEditSession(self.project.specimens(self.image),self.one)
        session.delete_selected();new=session.add(self.crop);session.rename_selected("1")
        result=self.project.apply_plate_crop_edits(self.image,**session.changes())
        self.assertEqual("1",specimen_display_id(self.project.specimen(result["id_map"][new])))
        self.assertTrue(self.project.specimen(self.one)["excluded"])

    def test_hover_updates_context_without_selecting_another_specimen(self):
        session=PlateCropEditSession(self.project.specimens(self.image),self.one)
        session.items[self.two]["specimen_code"]="Fish-02"
        label=Mock();workspace=SimpleNamespace(preview=True,_drag_mode=None,session=session,
            _badge_at=lambda x,y:None,canvas=Mock(),_original=lambda x,y:(x,y),_inside=XRayCropWorkspace._inside,crop_value=label)
        workspace._show_specimen_context=lambda item:XRayCropWorkspace._show_specimen_context(workspace,item)
        XRayCropWorkspace._canvas_hover(workspace,SimpleNamespace(x=400,y=300))
        label.configure.assert_called_with(text="Fish-02")
        self.assertEqual(self.one,session.selected_id)
        XRayCropWorkspace._canvas_hover(workspace,SimpleNamespace(x=0,y=0))
        label.configure.assert_called_with(text="1")

    def test_session_validates_before_changing_code(self):
        session=PlateCropEditSession(self.project.specimens(self.image),self.one)
        for value in ("2","","  ","A\r1","x"*129):
            with self.assertRaises(ValueError):session.rename_selected(value)
        self.assertFalse(session.dirty);self.assertEqual(1,session.item()["ordinal"])


    def test_codes_keep_leading_zeros_and_unicode(self):
        for code in ("0012", "Fish A-12", "Образец-007", "0"):
            session=PlateCropEditSession(self.project.specimens(self.image),self.one)
            session.rename_selected(code)
            self.project.apply_plate_crop_edits(self.image,**session.changes())
            self.assertEqual(code,specimen_display_id(self.project.specimen(self.one)))
            self.assertEqual(1,self.project.specimen(self.one)["ordinal"])

    def test_legacy_project_migrates_without_changing_ids_or_ordinals(self):
        with _db_connection(self.project.db_path) as db:
            db.execute("ALTER TABLE specimens DROP COLUMN specimen_code")
        reopened=XRayProject(self.project.root)
        self.assertEqual(self.one,reopened.specimen(self.one)["specimen_id"])
        self.assertEqual("1",specimen_display_id(reopened.specimen(self.one)))
        self.assertEqual("",reopened.specimen(self.one)["specimen_code"])

    def test_clicking_badge_selects_and_opens_editor_without_dragging(self):
        session=PlateCropEditSession(self.project.specimens(self.image),self.one)
        workspace=SimpleNamespace(preview=True,selected_image_id=self.image,session=session,_badge_at=lambda x,y:self.two,
            _notify_selection=Mock(),_refresh_flip_controls=Mock(),_draw=Mock(),_edit_specimen_id=Mock())
        XRayCropWorkspace._canvas_down(workspace,SimpleNamespace(x=10,y=10))
        self.assertEqual(self.two,session.selected_id)
        workspace._edit_specimen_id.assert_called_once()
        self.assertFalse(hasattr(workspace,"_drag_mode"))


    def test_new_default_ids_do_not_collide_with_custom_numeric_codes(self):
        self.project.apply_plate_crop_edits(self.image,edits=[{"specimen_id":self.one,"specimen_code":"3"}])
        session=PlateCropEditSession(self.project.specimens(self.image))
        new=session.add(self.crop)
        self.assertEqual("4",specimen_display_id(session.item(new)))
        result=self.project.apply_plate_crop_edits(self.image,**session.changes())
        self.assertEqual("4",specimen_display_id(self.project.specimen(result["id_map"][new])))

    def test_legacy_duplicate_ordinals_do_not_block_naming_another_crop(self):
        three=self.project.add_manual_specimen(self.image,self.crop)
        with _db_connection(self.project.db_path) as db:
            db.execute("UPDATE specimens SET ordinal=1 WHERE image_id=?",(self.image,))
        self.project.apply_plate_crop_edits(self.image,edits=[{"specimen_id":three,"specimen_code":"AB-003"}])
        self.assertEqual("AB-003",specimen_display_id(self.project.specimen(three)))
        self.assertEqual(1,self.project.specimen(three)["ordinal"])
