import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from app.xray_crop import crop_from_geometry
from app.xray_project import XRayProject
from app.xray_schema import bundled_scheme


class XRayStructurePersistenceTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(tempfile.mkdtemp())
        self.source=self.root/"source";self.source.mkdir()
        image=np.tile(np.linspace(15,240,900,dtype=np.uint8),(480,1))
        Image.fromarray(image).save(self.source/"plate_1.png")
        Image.fromarray(image).save(self.source/"plate_2.png")
        destination=self.root/"projects";destination.mkdir()
        self.project=XRayProject.create("xray",self.source,destination,bundled_scheme("phoxinus_vertebral_counts"))
        self.image_ids=[row["image_id"] for row in self.project.source_images()]
        crop=crop_from_geometry(450,240,700,260,0,(900,480),algorithm="manual")
        self.specimen_id=self.project.add_manual_specimen(self.image_ids[0],crop)
        self.project.confirm_plate(self.image_ids[0])

    def tearDown(self):
        shutil.rmtree(self.root,ignore_errors=True)

    def _complete_pass_one(self):
        self.project.add_annotation(self.specimen_id,"vertebra",0.2,0.5,1)
        self.project.add_annotation(self.specimen_id,"vertebra",0.4,0.5,1)
        self.project.add_annotation(self.specimen_id,"first_caudal",0.55,0.5,1,replace_single=True)
        self.project.add_annotation(self.specimen_id,"preanal_pterygiophore",0.6,0.62,1)
        self.project.add_annotation(self.specimen_id,"last_predorsal",0.35,0.5,1,replace_single=True)
        return self.project.verify_annotations(self.specimen_id,1)

    def test_only_human_confirmed_crops_are_structure_eligible(self):
        crop=crop_from_geometry(450,240,700,260,0,(900,480),algorithm="manual")
        unconfirmed=self.project.add_manual_specimen(self.image_ids[1],crop)
        ids=[row["specimen_id"] for row in self.project.structure_specimens(1)]
        self.assertIn(self.specimen_id,ids)
        self.assertNotIn(unconfirmed,ids)

    def test_point_edits_are_normalized_persisted_and_logged(self):
        annotation_id=self.project.add_annotation(self.specimen_id,"vertebra",-2,4,1)
        row=self.project.annotations(self.specimen_id,1)[0]
        self.assertEqual(annotation_id,row["annotation_id"])
        self.assertEqual(0.0,row["x"]);self.assertEqual(1.0,row["y"])
        self.project.move_annotation(annotation_id,0.25,0.35)
        moved=self.project.annotations(self.specimen_id,1)[0]
        self.assertAlmostEqual(0.25,moved["x"]);self.assertAlmostEqual(0.35,moved["y"])
        self.assertTrue(self.project.delete_annotation(annotation_id))
        self.assertEqual([],self.project.annotations(self.specimen_id,1))
        self.assertEqual(["add","move","delete"],[event["action"] for event in self.project.annotation_events(self.specimen_id,1)])

    def test_single_reference_is_replaced_instead_of_duplicated(self):
        first=self.project.add_annotation(self.specimen_id,"first_caudal",0.4,0.5,1,replace_single=True)
        second=self.project.add_annotation(self.specimen_id,"first_caudal",0.6,0.5,1,replace_single=True)
        self.assertEqual(first,second)
        rows=[row for row in self.project.annotations(self.specimen_id,1) if row["structure_id"]=="first_caudal"]
        self.assertEqual(1,len(rows));self.assertAlmostEqual(0.6,rows[0]["x"])
        self.assertEqual(["add","move"],[event["action"] for event in self.project.annotation_events(self.specimen_id,1)])

    def test_verify_requires_all_required_structure_roles(self):
        self.project.add_annotation(self.specimen_id,"vertebra",0.2,0.5,1)
        with self.assertRaisesRegex(ValueError,"Missing required structures"):
            self.project.verify_annotations(self.specimen_id,1)
        result=self._complete_pass_one()
        self.assertEqual("verified",self.project.annotation_run(self.specimen_id,1)["status"])
        self.assertGreaterEqual(result["counts"]["vertebra"],2)
        self.assertEqual("verify",self.project.annotation_events(self.specimen_id,1)[-1]["action"])

    def test_repeatability_pass_two_requires_verified_primary_pass(self):
        with self.assertRaisesRegex(ValueError,"Verify manual pass 1"):
            self.project.add_annotation(self.specimen_id,"vertebra",0.2,0.5,2)
        self._complete_pass_one()
        annotation_id=self.project.add_annotation(self.specimen_id,"vertebra",0.22,0.5,2)
        self.assertIsInstance(annotation_id,int)
        ids=[row["specimen_id"] for row in self.project.structure_specimens(2)]
        self.assertEqual([self.specimen_id],ids)

    def test_new_schema_version_does_not_overwrite_old_annotation_run(self):
        self._complete_pass_one()
        first=self.project.annotation_run(self.specimen_id,1);first_id=first["run_id"]
        edited=self.project.scheme;edited["description"]="new annotation semantics"
        self.project.save_scheme(edited,"schema edit")
        self.assertIsNone(self.project.annotation_run(self.specimen_id,1))
        new_id=self.project.ensure_annotation_run(self.specimen_id,1)
        self.assertNotEqual(first_id,new_id)
        with self.project.db_path.open("rb") as handle:
            self.assertTrue(handle.read(16).startswith(b"SQLite format 3"))


class XRayStructureUIContractTests(unittest.TestCase):
    def test_structures_workspace_is_interactive_and_not_placeholder(self):
        root=Path(__file__).resolve().parents[1]
        ui=(root/"app/xray_structures_ui.py").read_text(encoding="utf-8")
        module=(root/"app/modules/xray_counts.py").read_text(encoding="utf-8")
        for text in (
            "Manual pass","Verify & Next","Specimens","Sample","Specimen crop","Structures to mark",
            "Repeated series","Single reference","Draft autosaved","Click anatomy to place the active structure",
            "delete_selected","move_annotation","replace_single",
        ):
            self.assertIn(text,ui)
        self.assertIn("XRayStructureWorkspace(parent,self.project)",module)
        self.assertNotIn("Specimen image / annotation canvas",module)

    def test_structures_ui_renders_oriented_crop_without_project_image_copy(self):
        root=Path(__file__).resolve().parents[1]
        ui=(root/"app/xray_structures_ui.py").read_text(encoding="utf-8")
        self.assertIn("oriented_crop",ui)
        self.assertIn("crop_normalized_v1",(root/"app/xray_project.py").read_text(encoding="utf-8"))
        self.assertNotIn(".save(",ui)


if __name__=="__main__":
    unittest.main()
