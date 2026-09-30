import math
import shutil
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from app.xray_crop import ALGORITHM_VERSION, crop_from_geometry, detect_specimens
from app.xray_project import XRayProject
from app.xray_schema import blank_scheme


class XRayCropDetectionTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root,ignore_errors=True)

    def _plate(self,name="plate.png",dark_fish=False,edge=False,merged=False):
        background,foreground=(235,25) if dark_fish else (20,220)
        image=np.full((800,1200),background,np.uint8)
        fish=[((250,230),(360,90),8),((800,250),(340,80),-7),((520,600),(400,100),4)]
        if merged:fish=[((550,320),(500,100),5),((560,430),(500,100),5)]
        if edge:fish[0]=((30,230),(360,90),8)
        for center,axes,angle in fish:
            cv2.ellipse(image,center,(axes[0]//2,axes[1]//2),angle,0,360,foreground,-1)
            rad=math.radians(angle);tail=(int(center[0]+math.cos(rad)*axes[0]*0.55),int(center[1]+math.sin(rad)*axes[0]*0.55))
            cv2.line(image,center,tail,foreground,12)
        path=self.root/name;Image.fromarray(image).save(path);return path

    def test_detects_both_xray_polarities_and_individual_rotation(self):
        for dark in (False,True):
            proposals=detect_specimens(self._plate(f"plate-{dark}.png",dark_fish=dark))
            self.assertEqual(3,len(proposals))
            angles=[item.angle_degrees for item in proposals]
            self.assertAlmostEqual(8.0,angles[0],delta=1.5)
            self.assertAlmostEqual(-7.0,angles[1],delta=1.5)
            self.assertAlmostEqual(4.0,angles[2],delta=1.5)
            for item in proposals:
                self.assertEqual("high",item.confidence)
                self.assertGreater(item.length,item.width*2.5)
                self.assertEqual(4,len(item.corners))

    def test_touching_source_edge_is_not_silently_accepted(self):
        proposals=detect_specimens(self._plate("edge.png",edge=True))
        self.assertEqual(3,len(proposals))
        self.assertIn("source_incomplete",proposals[0].qc)
        self.assertEqual("review",proposals[0].confidence)

    def test_parallel_merged_component_is_split_without_ml(self):
        proposals=detect_specimens(self._plate("merged.png",merged=True))
        self.assertEqual(2,len(proposals))
        self.assertTrue(all(item.algorithm==ALGORITHM_VERSION for item in proposals))


class XRayCropPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(tempfile.mkdtemp());self.source=self.root/"source";self.source.mkdir()
        image=np.full((500,900),20,np.uint8)
        cv2.ellipse(image,(260,220),(180,45),6,0,360,220,-1)
        cv2.ellipse(image,(650,300),(170,42),-5,0,360,220,-1)
        Image.fromarray(image).save(self.source/"plate.png")
        destination=self.root/"projects";destination.mkdir()
        self.project=XRayProject.create("xray",self.source,destination,blank_scheme("test"))

    def tearDown(self):
        shutil.rmtree(self.root,ignore_errors=True)

    def test_confirmed_crops_survive_redetection_and_edits_have_history(self):
        image_id=self.project.source_images()[0]["image_id"]
        proposals=detect_specimens(self.project.source_image_path(image_id))
        saved=self.project.replace_auto_proposals(image_id,proposals,ALGORITHM_VERSION)
        self.assertEqual(2,saved["high"])
        self.assertEqual(2,self.project.confirm_clear_proposals(image_id))
        before=self.project.specimens(image_id);self.assertEqual(2,len(before))
        first=before[0];crop=dict(first["crop"]);crop["center_x"]+=5
        self.project.update_specimen_crop(first["specimen_id"],crop)
        again=self.project.replace_auto_proposals(image_id,proposals,ALGORITHM_VERSION)
        self.assertEqual(2,again["protected"])
        self.assertEqual(2,len(self.project.specimens(image_id)))
        edited=self.project.specimen(first["specimen_id"])
        self.assertEqual("manual",edited["crop_source"])
        self.assertEqual("confirmed",edited["crop_status"])
        self.assertIn("edit",[event["action"] for event in self.project.crop_events(first["specimen_id"])])
        reopened=XRayProject(self.project.root)
        self.assertEqual(2,len(reopened.specimens(image_id)))

    def test_manual_specimen_and_reject_are_persisted(self):
        image_id=self.project.source_images()[0]["image_id"]
        crop=crop_from_geometry(300,250,300,120,9,(900,500),algorithm="manual")
        specimen_id=self.project.add_manual_specimen(image_id,crop)
        self.assertEqual("confirmed",self.project.specimen(specimen_id)["crop_status"])
        self.project.reject_specimen(specimen_id)
        self.assertEqual([],self.project.specimens(image_id))
        self.assertEqual("rejected",self.project.specimen(specimen_id)["crop_status"])


class XRayCropUIContractTests(unittest.TestCase):
    def test_crop_stage_is_bulk_first_with_manual_exception_fallback(self):
        root=Path(__file__).resolve().parents[1]
        module=(root/"app/modules/xray_counts.py").read_text(encoding="utf-8")
        ui=(root/"app/xray_crop_ui.py").read_text(encoding="utf-8")
        self.assertIn("XRayCropWorkspace",module)
        self.assertNotIn("legacy automatic plate splitter",module)
        for text in ("Auto-crop all plates","Review exceptions","Edit crop…","Add missed specimen","False detection — remove"):
            self.assertIn(text,ui)
        self.assertIn("Existing confirmed crops protected",ui)


if __name__=="__main__":
    unittest.main()
