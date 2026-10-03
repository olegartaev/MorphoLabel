import math
import shutil
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from app.xray_crop import ALGORITHM_VERSION, aligned_crop, canonical_orientation_flips, crop_from_geometry, detect_specimens, oriented_crop
from app.xray_project import XRayProject
from app.xray_crop_ui import PlateCropEditSession, crop_flip_button_state
from app.modules.xray_counts import orientation_preview_transform
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


class XRayCropCanonicalizationTests(unittest.TestCase):
    def test_orientation_preview_whole_object_transform_and_neutral_options(self):
        self.assertEqual({"flip_x":True,"flip_y":True,"show_head":True,"show_tail":True,"show_bottom":True,"neutral":False},orientation_preview_transform("right","up"))
        self.assertFalse(orientation_preview_transform("none","down")["show_head"])
        self.assertFalse(orientation_preview_transform("none","down")["show_tail"])
        self.assertFalse(orientation_preview_transform("left","none")["show_bottom"])
        self.assertTrue(orientation_preview_transform("none","none")["neutral"])

    def test_orientation_policy_flips_only_the_required_axes(self):
        crop=crop_from_geometry(50,30,60,20,0,(100,60),orientation_policy={"head":"left","bottom":"down"})
        self.assertEqual((False,False),canonical_orientation_flips(crop,{"head":"left","bottom":"down"}))
        crop["head_side"]="right";self.assertEqual((True,False),canonical_orientation_flips(crop,{"head":"left","bottom":"down"}))
        crop["bottom_side"]="top";self.assertEqual((True,True),canonical_orientation_flips(crop,{"head":"left","bottom":"down"}))

    def test_aligned_crop_keeps_raw_anatomical_side_before_canonical_flip(self):
        arr=np.zeros((60,100),np.uint8);arr[20:40,20:80]=40;arr[25:35,20:35]=220
        image=Image.fromarray(arr)
        crop=crop_from_geometry(50,30,60,20,0,(100,60),orientation_policy={"head":"left","bottom":"down"})
        raw=np.asarray(aligned_crop(image,crop));self.assertGreater(float(raw[:,0:15].mean()),float(raw[:,-15:].mean()))

    def test_oriented_crop_is_canonical_and_keeps_source_unchanged(self):
        arr=np.zeros((60,100),np.uint8);arr[20:40,20:80]=40;arr[25:35,20:35]=220
        image=Image.fromarray(arr);before=np.asarray(image).copy()
        crop=crop_from_geometry(50,30,60,20,0,(100,60),orientation_policy={"head":"left","bottom":"down"})
        shown=np.asarray(oriented_crop(image,crop,{"head":"left","bottom":"down"}))
        self.assertEqual((20,60),shown.shape)
        self.assertGreater(float(shown[:,0:15].mean()),float(shown[:,-15:].mean()))
        self.assertTrue(np.array_equal(before,np.asarray(image)))
        crop["head_side"]="right";flipped=np.asarray(oriented_crop(image,crop,{"head":"left","bottom":"down"}))
        self.assertGreater(float(flipped[:,-15:].mean()),float(flipped[:,0:15].mean()))


class XRayCropOrientationSessionTests(unittest.TestCase):
    def test_horizontal_and_vertical_flips_are_independent_human_orientation_edits(self):
        crop=crop_from_geometry(50,30,60,20,0,(100,60),orientation_policy={"head":"left","bottom":"down"})
        crop["orientation_verified"]=True
        session=PlateCropEditSession(({"specimen_id":"s1","ordinal":1,"crop":crop},),"s1")
        self.assertTrue(session.flip_horizontal())
        self.assertEqual("right",session.item()["crop"]["head_side"]);self.assertEqual("bottom",session.item()["crop"]["bottom_side"])
        self.assertFalse(session.item()["crop"]["orientation_verified"])
        self.assertTrue(session.flip_vertical())
        self.assertEqual("right",session.item()["crop"]["head_side"]);self.assertEqual("top",session.item()["crop"]["bottom_side"])
        self.assertEqual("human",session.item()["crop"]["orientation_source"])
        moved=crop_from_geometry(55,30,60,20,0,(100,60),orientation_policy={"head":"left","bottom":"down"})
        session.update_selected(moved)
        self.assertEqual("right",session.item()["crop"]["head_side"]);self.assertEqual("top",session.item()["crop"]["bottom_side"])
        self.assertTrue(session.dirty)


class XRayCropViewportContractTests(unittest.TestCase):
    def test_flip_buttons_are_disabled_without_selection_and_enabled_with_crop(self):
        self.assertEqual("disabled",crop_flip_button_state(False))
        self.assertEqual("normal",crop_flip_button_state(True))
        source=(Path(__file__).resolve().parents[1]/"app/xray_crop_ui.py").read_text(encoding="utf-8")
        self.assertIn("state=crop_flip_button_state(bool(self.session.selected_id))",source)
        self.assertIn("self._refresh_flip_controls()",source)

    def test_all_crops_show_clear_boundary_and_compact_orientation(self):
        source=(Path(__file__).resolve().parents[1]/"app/xray_crop_ui.py").read_text(encoding="utf-8")
        self.assertIn("def _draw_crop_brackets",source)
        self.assertIn("blue triangle = head · amber stripe = ventral side",source)
        self.assertIn("def _draw_orientation_markers(self,crop,selected):",source)
        marker=source[source.index("    def _draw_orientation_markers(self,crop,selected):"):source.index("    def _draw_handles(self,crop):")]
        self.assertNotIn("if not selected:return",marker)
        self.assertIn('geometry["bottom_edge"]',marker)
        self.assertIn('fill=ventral,width=4 if selected else 3',marker)
        self.assertIn("head_size=13 if selected else 10",marker)
        self.assertNotIn("create_oval",marker)
        draw=source[source.index("    def _draw(self):"):source.index("    @staticmethod\n    def _orientation_geometry",source.index("    def _draw(self):"))]
        self.assertIn("self._draw_crop_brackets(corners,color)",draw)
        self.assertIn("if selected:",draw)
        self.assertIn('outline="#101b24",fill="",width=3',source)

    def test_crop_workspace_has_landmarks_style_zoom_pan_and_two_icon_flips(self):
        source=(Path(__file__).resolve().parents[1]/"app/xray_crop_ui.py").read_text(encoding="utf-8")
        for text in ('"<MouseWheel>"',"def _wheel(","def _pan_start(","def _pan_motion(","flip_horizontal","flip_vertical","Flip left ↔ right. Use when the head is on the wrong side.","Flip top ↕ bottom. Use when the ventral side is on the wrong side.","#54f0aa","#168ff0","#ffad1f"):
            self.assertIn(text,source)
        self.assertIn('"clear_crops",self.clear_plate_crops',source)
        self.assertNotIn("rotate_180",source);self.assertNotIn("turn180",source)


class XRayCropPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(tempfile.mkdtemp());self.source=self.root/"source";self.source.mkdir()
        image=np.full((500,900),20,np.uint8)
        cv2.ellipse(image,(260,220),(180,45),6,0,360,220,-1)
        cv2.ellipse(image,(650,300),(170,42),-5,0,360,220,-1)
        Image.fromarray(image).save(self.source/"plate.png")
        destination=self.root/"projects";destination.mkdir()
        self.project=XRayProject.create("xray",self.source,destination,blank_scheme("test"))
        self.assertTrue(self.project.is_self_contained)
        self.assertEqual(self.project.root/"source",self.project.source)

    def tearDown(self):
        shutil.rmtree(self.root,ignore_errors=True)

    def test_plate_confirmation_is_training_truth_and_survives_redetection(self):
        image_id=self.project.source_images()[0]["image_id"]
        proposals=detect_specimens(self.project.source_image_path(image_id))
        saved=self.project.replace_auto_proposals(image_id,proposals,ALGORITHM_VERSION)
        self.assertEqual(2,saved["high"])
        self.assertEqual([],self.project.training_plates())
        result=self.project.confirm_plate(image_id)
        self.assertEqual(2,result["specimens"])
        self.assertEqual(1,len(self.project.training_plates()))
        before=self.project.specimens(image_id);first=before[0];crop=dict(first["crop"]);crop["center_x"]+=5
        self.project.update_specimen_crop(first["specimen_id"],crop)
        again=self.project.replace_auto_proposals(image_id,proposals,ALGORITHM_VERSION)
        self.assertEqual(2,again["protected"])
        edited=self.project.specimen(first["specimen_id"])
        self.assertEqual("manual",edited["crop_source"]);self.assertEqual("confirmed",edited["crop_status"])
        self.assertIn("edit",[event["action"] for event in self.project.crop_events(first["specimen_id"])])

    def test_manual_specimen_is_not_truth_until_plate_confirmation(self):
        image_id=self.project.source_images()[0]["image_id"]
        crop=crop_from_geometry(300,250,300,120,9,(900,500),algorithm="manual")
        specimen_id=self.project.add_manual_specimen(image_id,crop)
        self.assertEqual("proposed",self.project.specimen(specimen_id)["crop_status"])
        self.assertEqual([],self.project.training_plates())
        self.project.confirm_plate(image_id)
        self.assertEqual("confirmed",self.project.specimen(specimen_id)["crop_status"])
        self.assertEqual(1,self.project.training_specimen_count())

    def test_project_keeps_its_own_source_after_original_is_removed(self):
        image_id=self.project.source_images()[0]["image_id"];managed=self.project.source_image_path(image_id)
        original=self.source/"plate.png";original.unlink()
        self.assertTrue(managed.is_file())
        with Image.open(managed) as image:self.assertEqual((900,500),image.size)

    def test_reject_is_persisted(self):
        image_id=self.project.source_images()[0]["image_id"]
        crop=crop_from_geometry(300,250,300,120,9,(900,500),algorithm="manual")
        specimen_id=self.project.add_manual_specimen(image_id,crop)
        self.project.reject_specimen(specimen_id)
        self.assertEqual([],self.project.specimens(image_id))
        self.assertEqual("rejected",self.project.specimen(specimen_id)["crop_status"])


if __name__=="__main__":
    unittest.main()
