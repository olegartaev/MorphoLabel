import json
import shutil
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from ai_runtime.xray_detector_runner import _best_validation_metrics

import cv2
import numpy as np
from PIL import Image

from app.xray_crop import HYBRID_ALGORITHM_VERSION, crop_from_geometry, merge_detector_proposals, proposals_from_detector_boxes
from app.xray_crop_ui import PlateCropEditSession, XRayCropWorkspace, apply_and_confirm_plate
from app.ai_hardware import HardwareProfile
from app.xray_detector import MIN_TRAINING_PLATES, detector_performance_settings, prepare_training_dataset
from app.xray_project import XRayProject
from app.xray_orientation import ORIENTATION_CONFIDENCE_THRESHOLD, apply_orientation_prediction, prepare_orientation_dataset
from app.xray_schema import blank_scheme, bundled_scheme


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

    def test_crop_workspace_status_is_set_based_and_matches_project_truth(self):
        ids=[row["image_id"] for row in self.project.source_images()]
        crop=crop_from_geometry(450,240,500,160,0,(900,480),algorithm="manual")
        specimen=self.project.add_manual_specimen(ids[0],crop)
        self.project.confirm_plate(ids[0])
        self.project.replace_model_proposals(ids[1],[crop],"xray_crop_model_v001")
        with patch.object(self.project,"specimens",side_effect=AssertionError("no per-plate traversal")), \
             patch.object(self.project,"source_images",side_effect=AssertionError("no Python catalog traversal")):
            status=self.project.crop_workspace_status()
            summary=self.project.crop_summary()
        self.assertEqual(5,status["plates"])
        self.assertEqual(1,status["verified_plates"])
        self.assertEqual(1,status["training_plates"])
        self.assertEqual(1,status["training_specimens"])
        self.assertEqual(1,status["orientation_training"])
        self.assertEqual(1,status["ai_pending_plates"])
        self.assertEqual(3,status["uncropped_plates"])
        self.assertEqual(3,status["prediction_candidates"])
        self.assertEqual(2,status["specimens"])
        self.assertEqual(1,status["confirmed"])
        self.assertEqual(1,status["review"])
        self.assertEqual(status["verified_plates"],summary["verified_plates"])
        self.assertEqual("confirmed",self.project.specimen(specimen)["crop_status"])

    def test_crop_queue_current_item_is_position_not_arbitrary_membership(self):
        state={"ids":["plate-a","plate-b","plate-c"],"position":1}
        self.assertEqual("plate-b",XRayCropWorkspace._batch_current_id(state))
        self.assertEqual("",XRayCropWorkspace._batch_current_id({"ids":[],"position":4}))

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
        dataset=prepare_training_dataset(self.project,"xray_crop_model_v001",seed=7,workspace_root=self.root/"scratch")
        self.assertEqual(MIN_TRAINING_PLATES,len(dataset["plate_ids"]))
        self.assertEqual(MIN_TRAINING_PLATES,dataset["training_specimens"])
        train=json.loads(dataset["train_json"].read_text(encoding="utf-8"))
        val=json.loads(dataset["val_json"].read_text(encoding="utf-8"))
        self.assertEqual([{"id":1,"name":"specimen"}],train["categories"])
        self.assertGreater(len(train["annotations"]),0);self.assertGreater(len(val["annotations"]),0)
        self.assertTrue(all((dataset["root"]/item["file_name"]).is_file() for item in train["images"]+val["images"]))

    def test_project_compaction_removes_only_disposable_ai_scratch(self):
        model_dir=self.project.models_root/"xray_crop_model_v999";(model_dir/"dataset"/"images").mkdir(parents=True)
        (model_dir/"dataset"/"images"/"copy.png").write_bytes(b"x"*128)
        (model_dir/"work_b8").mkdir();(model_dir/"work_b8"/"epoch_10.pth").write_bytes(b"x"*256)
        (model_dir/"model.pth").write_bytes(b"final");(model_dir/"config.py").write_text("# final",encoding="utf-8")
        old_cache=self.project.cache_root/"xray_detector";old_cache.mkdir();(old_cache/"plate.png").write_bytes(b"x"*64)
        result=self.project.compact_disposable_ai_artifacts()
        self.assertGreaterEqual(result["removed_files"],3)
        self.assertFalse((model_dir/"dataset").exists());self.assertFalse((model_dir/"work_b8").exists());self.assertFalse(old_cache.exists())
        self.assertEqual(b"final",(model_dir/"model.pth").read_bytes());self.assertTrue((model_dir/"config.py").is_file())

    def test_detector_validation_metrics_report_best_real_logged_epoch(self):
        work=self.root/"metrics";path=work/"20261002_010203"/"vis_data"/"scalars.json";path.parent.mkdir(parents=True)
        path.write_text(
            '{"epoch":1,"coco/bbox_mAP":0.31,"coco/bbox_mAP_50":0.55}\n'
            '{"epoch":2,"coco/bbox_mAP":0.47,"coco/bbox_mAP_50":0.71,"coco/bbox_mAP_75":0.44}\n'
            '{"epoch":3,"coco/bbox_mAP":0.42,"coco/bbox_mAP_50":0.68}\n',
            encoding="utf-8",
        )
        metrics=_best_validation_metrics(work)
        self.assertEqual(0.47,metrics["coco/bbox_mAP"])
        self.assertEqual(0.71,metrics["coco/bbox_mAP_50"])
        self.assertEqual(0.44,metrics["coco/bbox_mAP_75"])

    def test_orientation_prediction_assigns_raw_sides_and_requires_review_when_uncertain(self):
        crop=crop_from_geometry(450,240,400,140,0,(900,480),algorithm="manual")
        strong=apply_orientation_prediction(crop,{"head_right_probability":0.9,"bottom_down_probability":0.1},{"head":"left","bottom":"down"},"m1")
        self.assertEqual("right",strong["head_side"]);self.assertEqual("top",strong["bottom_side"]);self.assertEqual("model",strong["orientation_source"])
        weak=apply_orientation_prediction(crop,{"head_right_probability":0.55,"bottom_down_probability":0.52},{"head":"left","bottom":"down"},"m1",ORIENTATION_CONFIDENCE_THRESHOLD)
        self.assertEqual("model_review",weak["orientation_source"]);self.assertIn("orientation_uncertain",weak["qc"]);self.assertEqual("review",weak["confidence"])

    def test_orientation_dataset_uses_only_human_verified_truth_and_balances_flips(self):
        ids=[row["image_id"] for row in self.project.source_images()[:2]]
        for image_id in ids:
            crop=crop_from_geometry(450,240,400,140,0,(900,480),algorithm="manual")
            self.project.add_manual_specimen(image_id,crop);self.project.confirm_plate(image_id)
        rows=self.project.orientation_training_rows();self.assertEqual(2,len(rows))
        # duplicate verified examples so the orientation learner crosses its small-data safety gate
        for image_id in ids:
            for x in (300,600):
                crop=crop_from_geometry(x,240,220,100,0,(900,480),algorithm="manual")
                self.project.add_manual_specimen(image_id,crop)
            self.project.confirm_plate(image_id)
        dataset=prepare_orientation_dataset(self.project,self.root/"orientation",seed=3)
        self.assertTrue(dataset["enabled"]);self.assertGreaterEqual(dataset["train_examples"],4);self.assertGreaterEqual(dataset["val_examples"],4)

    def test_model_registry_preserves_parent_lineage_and_active_version(self):
        ids=[row["image_id"] for row in self.project.source_images()[:3]]
        self.project.register_crop_model("xray_crop_model_v001","models/v1/model.pth","models/v1/config.py",None,{"mAP":0.5},ids,10,activate=True)
        self.project.register_crop_model("xray_crop_model_v002","models/v2/model.pth","models/v2/config.py","xray_crop_model_v001",{"mAP":0.6},ids,12,activate=True)
        active=self.project.active_crop_model()
        self.assertEqual("xray_crop_model_v002",active["model_id"])
        self.assertEqual("xray_crop_model_v001",active["parent_model_id"])
        self.assertEqual(2,len(self.project.crop_models()))

    def test_model_registry_can_activate_and_safely_delete_leaf_model_files(self):
        ids=[row["image_id"] for row in self.project.source_images()[:2]]
        for version,parent,active in (("xray_crop_model_v001",None,True),("xray_crop_model_v002","xray_crop_model_v001",True)):
            folder=self.project.models_root/version;folder.mkdir(parents=True)
            (folder/"model.pth").write_bytes(b"weights");(folder/"config.py").write_text("# config",encoding="utf-8")
            self.project.register_crop_model(version,f"models/{version}/model.pth",f"models/{version}/config.py",parent,{"mAP":0.5},ids,3,activate=active)
        with self.assertRaisesRegex(ValueError,"training parent"):
            self.project.delete_crop_model("xray_crop_model_v001")
        active=self.project.activate_crop_model("xray_crop_model_v001")
        self.assertEqual("xray_crop_model_v001",active["model_id"])
        self.project.delete_crop_model("xray_crop_model_v002")
        self.assertFalse((self.project.models_root/"xray_crop_model_v002").exists())
        self.assertEqual("xray_crop_model_v001",self.project.active_crop_model()["model_id"])

    def test_clearing_plate_crops_archives_coordinate_annotations_and_unconfirms_plate(self):
        self.project.save_scheme(bundled_scheme("phoxinus_vertebral_counts"),"test fixture")
        image_id=self.project.source_images()[0]["image_id"]
        crop=crop_from_geometry(450,240,620,190,0,(900,480),algorithm="manual")
        specimen_id=self.project.add_manual_specimen(image_id,crop);self.project.confirm_plate(image_id)
        self.project.add_annotation(specimen_id,"vertebra",0.35,0.5)
        self.assertEqual(1,len(self.project.annotations(specimen_id,1)))
        self.assertEqual(1,self.project.remove_all_plate_crops(image_id))
        self.assertEqual([],self.project.specimens(image_id))
        self.assertEqual("rejected",self.project.specimen(specimen_id)["crop_status"])
        self.assertEqual([],self.project.annotations(specimen_id,1))
        self.assertEqual("crop_removed",self.project.annotation_archives(specimen_id)[0]["reason"])
        self.assertFalse(self.project.source_image(image_id)["crop_reviewed"])
        self.assertEqual([],self.project.training_plates())

    def test_apply_plate_crop_edits_is_explicit_and_keeps_plate_unverified(self):
        image_id=self.project.source_images()[0]["image_id"]
        first=crop_from_geometry(300,220,300,120,0,(900,480),algorithm="heuristic")
        second=crop_from_geometry(650,260,280,110,0,(900,480),algorithm="heuristic")
        self.project.replace_auto_proposals(image_id,[first,second],"heuristic")
        rows=self.project.specimens(image_id)
        changed=crop_from_geometry(320,220,310,120,3,(900,480),algorithm="manual")
        added=crop_from_geometry(450,390,220,90,0,(900,480),algorithm="manual")
        result=self.project.apply_plate_crop_edits(
            image_id,
            edits=[{"specimen_id":rows[0]["specimen_id"],"crop":changed}],
            new_crops=[{"client_id":"draft:1","crop":added}],
            removed_ids=[rows[1]["specimen_id"]],
        )
        self.assertEqual({"updated":1,"added":1,"removed":1}, {key:result[key] for key in ("updated","added","removed")})
        self.assertIn("draft:1",result["id_map"])
        active=self.project.specimens(image_id)
        self.assertEqual(2,len(active));self.assertTrue(all(item["crop_status"]=="proposed" for item in active))
        self.assertTrue(all(item["crop_source"]=="manual" for item in active))
        self.assertEqual([],self.project.training_plates())
        self.project.confirm_plate(image_id)
        self.assertEqual(1,len(self.project.training_plates()))

    def test_manual_pending_crop_is_protected_from_model_prediction(self):
        image_id=self.project.source_images()[0]["image_id"]
        crop=crop_from_geometry(450,240,400,140,0,(900,480),algorithm="manual")
        self.project.apply_plate_crop_edits(image_id,new_crops=[{"client_id":"draft:1","crop":crop}])
        self.assertNotIn(image_id,self.project.prediction_candidate_ids())
        result=self.project.replace_model_proposals(image_id,[crop],"xray_crop_model_v001")
        self.assertEqual(1,result["protected"])
        active=self.project.specimens(image_id)
        self.assertEqual(1,len(active));self.assertEqual("manual",active[0]["crop_source"])

    def test_plate_edit_session_keeps_selection_until_explicit_delete(self):
        crop=crop_from_geometry(450,240,400,140,0,(900,480),algorithm="manual")
        session=PlateCropEditSession([{"specimen_id":"s1","crop":crop,"ordinal":1,"label":"one"}])
        session.select("s1");moved=crop_from_geometry(460,240,400,140,0,(900,480),algorithm="manual")
        session.update_selected(moved)
        self.assertEqual("s1",session.selected_id);self.assertTrue(session.dirty)
        draft=session.add(crop);self.assertEqual(draft,session.selected_id)
        self.assertTrue(session.delete_selected());self.assertIsNone(session.selected_id)
        self.assertNotIn(draft,[item["specimen_id"] for item in session.active_items()])
        session.select("s1");session.delete_selected()
        self.assertEqual(["s1"],session.changes()["removed_ids"])

    def test_xray_detector_uses_first_run_hardware_profile_defaults(self):
        hardware=HardwareProfile(
            cpu_model="test",physical_cores=8,logical_cores=16,ram_bytes=32*1024**3,
            gpu_model="GPU",gpu_vram_mib=12_288,gpu_driver="x",cuda_available=True,
            cuda_runtime="12.1",acceleration="CUDA",gpu_free_mib=10_000,
        )
        settings=detector_performance_settings(hardware)
        self.assertEqual("cuda:0",settings["training"]["device"])
        self.assertGreaterEqual(settings["training"]["batch_size"],8)
        self.assertTrue(settings["training"]["mixed_precision"])
        self.assertTrue(settings["training"]["pin_memory"])
        self.assertEqual("cuda:0",settings["inference"]["device"])
        self.assertFalse(settings["inference"]["mixed_precision"])

    def test_apply_action_persists_and_human_confirms_whole_plate(self):
        image_id=self.project.source_images()[0]["image_id"]
        crop=crop_from_geometry(450,240,500,160,0,(900,480),algorithm="manual")
        session=PlateCropEditSession();session.add(crop)
        selected=apply_and_confirm_plate(self.project,image_id,session)
        self.assertTrue(selected)
        self.assertTrue(self.project.source_image(image_id)["crop_reviewed"])
        active=self.project.specimens(image_id)
        self.assertEqual(1,len(active));self.assertEqual("confirmed",active[0]["crop_status"])
        self.assertEqual(1,len(self.project.training_plates()))

    def test_batch_selection_samples_the_global_pool_reproducibly(self):
        pool=[f"plate_{index:02d}" for index in range(12)]
        selected=XRayProject._sample_crop_plate_ids(pool,5,seed=42)
        self.assertEqual(selected,XRayProject._sample_crop_plate_ids(pool,5,seed=42))
        self.assertEqual(5,len(set(selected)))
        self.assertTrue(set(selected).issubset(pool))
        self.assertNotEqual(pool[:5],selected)

    def test_training_and_prediction_batches_sample_all_eligible_plates(self):
        all_ids=[row["image_id"] for row in self.project.source_images()]
        expected=XRayProject._sample_crop_plate_ids(all_ids,3)
        self.assertEqual(expected,self.project.select_training_plate_ids(3))
        crop=crop_from_geometry(450,240,620,190,0,(900,480),algorithm="test")
        self.project.replace_model_proposals(all_ids[0],[crop],"xray_crop_model_v001")
        prediction_pool=self.project.prediction_candidate_ids()
        expected_prediction=XRayProject._sample_crop_plate_ids(prediction_pool,3)
        self.assertEqual(expected_prediction,self.project.select_prediction_plate_ids(3))

    def test_ai_review_queue_uses_seeded_randomized_plate_order(self):
        ids=[row["image_id"] for row in self.project.source_images()]
        crop=crop_from_geometry(450,240,620,190,0,(900,480),algorithm="test")
        for image_id in ids:self.project.replace_model_proposals(image_id,[crop],"xray_crop_model_v001")
        selected=self.project.select_ai_review_plate_ids()
        self.assertEqual(selected,self.project.select_ai_review_plate_ids())
        self.assertEqual(set(ids),set(selected))
        self.assertNotEqual(ids,selected)


class XRayHybridGeometryTests(unittest.TestCase):
    @staticmethod
    def _proposal(cx,cy,length,width,confidence="high",algorithm="test"):
        return crop_from_geometry(cx,cy,length,width,0,(1200,800),confidence=confidence,algorithm=algorithm)

    def test_hybrid_a_uses_heuristic_geometry_when_detectors_agree(self):
        heuristic=[self._proposal(300,250,400,120)]
        rtmdet=[self._proposal(305,250,520,180,algorithm="rtmdet-tiny-v1")]
        merged=merge_detector_proposals(heuristic,rtmdet)
        self.assertEqual(1,len(merged))
        self.assertAlmostEqual(400.0,merged[0]["length"])
        self.assertAlmostEqual(120.0,merged[0]["width"])
        self.assertEqual("agreed",merged[0]["detector_provenance"]["mode"])
        self.assertEqual(HYBRID_ALGORITHM_VERSION,merged[0]["algorithm"])

    def test_hybrid_a_keeps_rtmdet_only_as_review_and_drops_heuristic_only(self):
        heuristic=[self._proposal(250,250,260,90)]
        rtmdet=[
            self._proposal(250,250,360,140,algorithm="rtmdet-tiny-v1"),
            self._proposal(850,500,300,120,algorithm="rtmdet-tiny-v1"),
        ]
        merged=merge_detector_proposals(heuristic,rtmdet)
        self.assertEqual(2,len(merged))
        review=[item for item in merged if item["detector_provenance"]["mode"]=="rtmdet_only"]
        self.assertEqual(1,len(review))
        self.assertEqual("review",review[0]["confidence"])
        self.assertIn("detector_disagreement",review[0]["qc"])
        only_heuristic=[self._proposal(100,700,200,80)]
        self.assertEqual([],merge_detector_proposals(only_heuristic,[]))

    def test_hybrid_a_center_fallback_matches_low_iou_nested_detection(self):
        heuristic=[self._proposal(400,300,240,70)]
        rtmdet=[self._proposal(400,300,720,260,algorithm="rtmdet-tiny-v1")]
        merged=merge_detector_proposals(heuristic,rtmdet)
        self.assertEqual(1,len(merged))
        self.assertEqual("center_fallback",merged[0]["detector_provenance"]["agreement_rule"])


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
            "Apply crop","1. Training batch","Start first batch","Add next batch","2. Train","Train Crop AI",
            "3. Predict & review","Predict next","Predict all","Review AI crops","Confirm & Next",
            "Drag empty space","<Delete>","WorkflowCard.TLabelframe","PhotoListCanvas","Sample","Plate","Show excluded",
            "NavPrimary.TButton","apply_and_confirm_plate",
        ):self.assertIn(text,ui)
        self.assertNotIn("Selected specimen",ui)
        self.assertNotIn("Edit crop…",ui)
        self.assertNotIn("Add missed specimen",ui)
        self.assertNotIn("Auto-crop all plates",ui)
        self.assertIn("training truth",ui)
        self.assertIn("PlateCropEditSession",ui)
        self.assertIn('status_shape="square"',ui)
        self.assertIn('"#d93025"',ui)
        self.assertIn('"#e6a700"',ui)
        self.assertIn('"#188038"',ui)
        self.assertIn("self.apply_group.grid_forget()",ui)
        self.assertIn('"CropApply.TButton"',ui)
        self.assertIn('style="CropApply.TButton",icon="verify"',ui)
        self.assertIn('"delete_crop",self.delete_selected',ui)
        self.assertIn('"clear_crops",self.clear_plate_crops',ui)
        self.assertIn("self.batch_actions.grid",ui)
        self.assertIn('"<MouseWheel>"',ui)
        self.assertIn("flip_selected_horizontal",ui)
        self.assertIn("flip_selected_vertical",ui)
        self.assertNotIn("rotate_selected_180",ui)
        self.assertIn('"clear_crops",self.clear_plate_crops',ui)
        self.assertIn('"delete_crop",self.delete_selected',ui)
        toolbar=ui[ui.index("self.orientation_actions="):ui.index("self.instruction=ttk.Label")]
        self.assertLess(toolbar.index("self.flip_h_button"),toolbar.index("self.selection_separator"))
        self.assertLess(toolbar.index("self.selection_separator"),toolbar.index("self.delete_crop_button"))
        self.assertLess(toolbar.index("self.delete_crop_button"),toolbar.index("self.clear_plate_button"))
        self.assertIn("self.apply_group=ttk.Frame(actions",ui)
        self.assertIn("self.apply_group.grid(row=0,column=2,sticky=\"e\")",ui)
        self.assertIn("excluded rows stay inspectable/selectable",ui)
        self.assertIn('self.queue_banner=ttk.Frame(main,style="Attention.TFrame"',ui)
        self.assertIn("def continue_batch(self):",ui)
        self.assertIn("def dismiss_batch(self):",ui)
        self.assertIn('self.project.set_ui_state("xray_crop_active_batch",{})',ui)
        self.assertIn("self._queue_active and self.selected_image_id==self._batch_current_id(state)",ui)
        self.assertIn("def flush_pending_edits(self):",ui)
        self.assertIn('self.plate_list.select(self.selected_image_id,reveal=False)',ui)
        self.assertNotIn('self.on_select(row["image_id"]);self.refresh(preserve_scroll=True)',ui)
        module=(root/"app/modules/xray_counts.py").read_text(encoding="utf-8")
        self.assertIn('flush=getattr(self._workspace,"flush_pending_edits",None)',module)
        self.assertIn("self._workspace=XRayCropWorkspace(",module)

    def test_runtime_runner_uses_one_class_rtmdet_tiny_and_coco(self):
        root=Path(__file__).resolve().parents[1]
        runner=(root/"ai_runtime/xray_detector_runner.py").read_text(encoding="utf-8")
        self.assertIn("rtmdet_tiny_8xb32-300e_coco.py",runner)
        self.assertIn("num_classes=1",runner)
        self.assertIn('type="CocoDataset"',runner)
        self.assertIn('save_best="coco/bbox_mAP"',runner)
        self.assertIn("cfg.load_from=initial_checkpoint",runner)
        self.assertIn("ratio_range=(0.8,1.0)",runner)
        self.assertNotIn("ratio_range=(0.8,1.2)",runner)
        self.assertIn('cfg.optim_wrapper.type="AmpOptimWrapper"',runner)
        self.assertIn("pin_memory=pin_memory",runner)
        self.assertIn("simple_infer=[",runner)
        infer=runner[runner.index("simple_infer=["):runner.index("cfg.model.bbox_head.num_classes=1")]
        self.assertNotIn('type="LoadAnnotations"',infer)
        self.assertIn("def predict_many",runner)
        predict_many=runner[runner.index("def predict_many"):runner.index("def predict(payload)")]
        self.assertNotIn("torch.autocast",predict_many)
        self.assertNotIn("dtype=torch.float16",predict_many)
        detector=(root/"app/xray_detector.py").read_text(encoding="utf-8")
        self.assertIn("rtmdet_tiny_coco_pretrained",detector)
        self.assertIn("initial_checkpoint",detector)
        self.assertIn("is_cuda_oom",detector)
        self.assertIn("batch_attempts",detector)
        self.assertIn('"mixed_precision"',detector)
        self.assertIn('"pin_memory"',detector)
        self.assertIn('"predict_many"',detector)
        self.assertIn("merge_detector_proposals",detector)
        self.assertIn("HYBRID_ALGORITHM_VERSION",detector)
        self.assertIn("TemporaryDirectory",detector)
        self.assertIn("compact_disposable_ai_artifacts",detector)
        orientation=(root/"ai_runtime/xray_orientation_runner.py").read_text(encoding="utf-8")
        self.assertIn("mobilenet_v3_small",orientation)
        self.assertIn("train_orientation",orientation)
        self.assertIn("predict_orientation_many",orientation)
        spec=(root/"packaging/morpholabel.spec").read_text(encoding="utf-8")
        self.assertIn("xray_detector_runner.py",spec);self.assertIn("xray_orientation_runner.py",spec)


if __name__=="__main__":
    unittest.main()
