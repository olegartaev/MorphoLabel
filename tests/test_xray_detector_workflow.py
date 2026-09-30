import json
import shutil
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from app.xray_crop import crop_from_geometry, proposals_from_detector_boxes
from app.xray_detector import MIN_TRAINING_PLATES, prepare_training_dataset
from app.xray_project import XRayProject
from app.xray_schema import blank_scheme


class XRayDetectorWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(tempfile.mkdtemp());self.source=self.root/"source";self.source.mkdir()
        for index in range(5):
            image=np.full((480,900),25,np.uint8)
            cv2.ellipse(image,(450,240),(260,65),(-8+index*4),0,360,220,-1)
            Image.fromarray(image).save(self.source/f"plate_{index}.png")
        destination=self.root/"projects";destination.mkdir()
        self.project=XRayProject.create("xray",self.source,destination,blank_scheme("test"))

    def tearDown(self):
        shutil.rmtree(self.root,ignore_errors=True)

    def _confirm(self,image_id,index=0):
        crop=crop_from_geometry(450,240,620,190,-8+index*4,(900,480),algorithm="manual")
        self.project.add_manual_specimen(image_id,crop)
        self.project.confirm_plate(image_id)

    def test_human_confirmed_plate_is_only_training_authority(self):
        ids=[row["image_id"] for row in self.project.source_images()]
        crop=crop_from_geometry(450,240,620,190,0,(900,480),algorithm="manual")
        self.project.add_manual_specimen(ids[0],crop)
        self.assertEqual(0,len(self.project.training_plates()))
        self.project.confirm_plate(ids[0])
        self.assertEqual(1,len(self.project.training_plates()))
        self.assertEqual(1,self.project.training_specimen_count())

    def test_model_proposals_do_not_become_truth_until_plate_confirmation(self):
        image_id=self.project.source_images()[0]["image_id"]
        crop=crop_from_geometry(450,240,620,190,0,(900,480),confidence="high",algorithm="rtmdet-tiny-v1")
        self.project.replace_model_proposals(image_id,[crop],"xray_crop_model_v001")
        self.assertEqual(0,len(self.project.training_plates()))
        self.assertEqual([image_id],self.project.ai_review_plate_ids())
        self.project.confirm_plate(image_id)
        self.assertEqual(1,len(self.project.training_plates()))
        self.assertEqual([],self.project.ai_review_plate_ids())

    def test_prediction_candidates_allow_old_heuristics_but_not_pending_model_output(self):
        ids=[row["image_id"] for row in self.project.source_images()]
        crop=crop_from_geometry(450,240,620,190,0,(900,480),algorithm="heuristic")
        self.project.replace_auto_proposals(ids[0],[crop],"heuristic")
        self.assertIn(ids[0],self.project.prediction_candidate_ids())
        self.project.replace_model_proposals(ids[1],[crop],"xray_crop_model_v001")
        self.assertNotIn(ids[1],self.project.prediction_candidate_ids())

    def test_coco_training_export_uses_confirmed_plates_only(self):
        rows=self.project.source_images()
        for index,row in enumerate(rows[:MIN_TRAINING_PLATES]):self._confirm(row["image_id"],index)
        dataset=prepare_training_dataset(self.project,"xray_crop_model_v001",seed=7)
        self.assertEqual(MIN_TRAINING_PLATES,len(dataset["plate_ids"]))
        self.assertEqual(MIN_TRAINING_PLATES,dataset["training_specimens"])
        train=json.loads(dataset["train_json"].read_text(encoding="utf-8"))
        val=json.loads(dataset["val_json"].read_text(encoding="utf-8"))
        self.assertEqual([{"id":1,"name":"specimen"}],train["categories"])
        self.assertGreater(len(train["annotations"]),0);self.assertGreater(len(val["annotations"]),0)
        self.assertTrue(all((dataset["root"]/item["file_name"]).is_file() for item in train["images"]+val["images"]))

    def test_model_registry_preserves_parent_lineage_and_active_version(self):
        ids=[row["image_id"] for row in self.project.source_images()[:3]]
        self.project.register_crop_model("xray_crop_model_v001","models/v1/model.pth","models/v1/config.py",None,{"mAP":0.5},ids,10,activate=True)
        self.project.register_crop_model("xray_crop_model_v002","models/v2/model.pth","models/v2/config.py","xray_crop_model_v001",{"mAP":0.6},ids,12,activate=True)
        active=self.project.active_crop_model()
        self.assertEqual("xray_crop_model_v002",active["model_id"])
        self.assertEqual("xray_crop_model_v001",active["parent_model_id"])
        self.assertEqual(2,len(self.project.crop_models()))

    def test_batch_selection_round_robins_source_series(self):
        images=[
            {"image_id":"a1","relative_path":"A/1.tif"},
            {"image_id":"a2","relative_path":"A/2.tif"},
            {"image_id":"b1","relative_path":"B/1.tif"},
            {"image_id":"b2","relative_path":"B/2.tif"},
            {"image_id":"c1","relative_path":"C/1.tif"},
        ]
        self.assertEqual(["a1","b1","c1","a2"],XRayProject._round_robin_series(images,4))


class XRayDetectorGeometryTests(unittest.TestCase):
    def test_detector_box_is_never_trimmed_by_rotation_refinement(self):
        root=Path(tempfile.mkdtemp())
        try:
            image=np.full((500,900),20,np.uint8);cv2.ellipse(image,(450,250),(260,55),12,0,360,220,-1)
            path=root/"plate.png";Image.fromarray(image).save(path)
            box=[150,150,760,355]
            proposal=proposals_from_detector_boxes(path,[{"bbox":box,"score":0.9}])[0]
            left,top,right,bottom=proposal.bounds
            self.assertLessEqual(left,box[0]+1);self.assertLessEqual(top,box[1]+1)
            self.assertGreaterEqual(right,box[2]-1);self.assertGreaterEqual(bottom,box[3]-1)
            self.assertEqual("rtmdet-tiny-v1",proposal.algorithm)
        finally:shutil.rmtree(root,ignore_errors=True)


class XRayDetectorContractTests(unittest.TestCase):
    def test_ui_matches_landmark_crop_training_predict_review_shape(self):
        root=Path(__file__).resolve().parents[1]
        ui=(root/"app/xray_crop_ui.py").read_text(encoding="utf-8")
        for text in (
            "1. Training batch","Start first batch","Add next batch","2. Train","Train X-ray crop model",
            "3. Predict & review","Predict next","Predict all remaining","Review AI crops","Confirm plate & Next",
            "drag a corner to resize","yellow handle to rotate",
        ):self.assertIn(text,ui)
        self.assertNotIn("Auto-crop all plates",ui)
        self.assertNotIn("Accept clear crops",ui)
        self.assertIn("training truth",ui)
        self.assertIn('text="Specimens"',ui)
        self.assertIn("_drag_changed",ui)

    def test_runtime_runner_uses_one_class_rtmdet_tiny_and_coco(self):
        root=Path(__file__).resolve().parents[1]
        runner=(root/"ai_runtime/xray_detector_runner.py").read_text(encoding="utf-8")
        self.assertIn("rtmdet_tiny_8xb32-300e_coco.py",runner)
        self.assertIn("num_classes=1",runner)
        self.assertIn('type="CocoDataset"',runner)
        self.assertIn('save_best="coco/bbox_mAP"',runner)
        self.assertIn("cfg.load_from=initial_checkpoint",runner)
        self.assertLess(runner.index('dict(type="LoadAnnotations",with_bbox=True)',runner.index("simple_test=[")),
                        runner.index('dict(type="Resize"',runner.index("simple_test=[")))
        detector=(root/"app/xray_detector.py").read_text(encoding="utf-8")
        self.assertIn("rtmdet_tiny_coco_pretrained",detector)
        self.assertIn("initial_checkpoint",detector)
        self.assertIn("is_cuda_oom",detector)
        self.assertIn("batch_attempts",detector)
        spec=(root/"packaging/morpholabel.spec").read_text(encoding="utf-8")
        self.assertIn("xray_detector_runner.py",spec)


if __name__=="__main__":
    unittest.main()
