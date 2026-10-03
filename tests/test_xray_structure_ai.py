import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image

from app.xray_crop import crop_from_geometry
from app.xray_project import XRayProject
from app.xray_schema import bundled_scheme
from app.xray_structure_ai import (
    MODEL_PACKAGE_FORMAT,
    export_structure_model_package,
    import_structure_model_package,
    prepare_structure_training_dataset,
    structure_schema_digest,
)
from app.xray_structures_ui import _current_prediction_allowed


class XRayStructureAIWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(tempfile.mkdtemp())
        self.source=self.root/"source";self.source.mkdir()
        for index in range(4):
            image=np.full((360,900),25,np.uint8)
            image[120:240,120:780]=150+index*5
            Image.fromarray(image).save(self.source/f"plate_{index}.png")
        destination=self.root/"projects";destination.mkdir()
        self.project=XRayProject.create(
            "xray",self.source,destination,bundled_scheme("phoxinus_vertebral_counts")
        )

    def tearDown(self):
        shutil.rmtree(self.root,ignore_errors=True)

    def _add_specimen(self,image_id,cx):
        crop=crop_from_geometry(cx,180,320,110,0,(900,360),algorithm="manual")
        return self.project.add_manual_specimen(image_id,crop)

    def _verify_structure_truth(self,specimen_id,offset=0.0):
        v1=self.project.add_annotation(specimen_id,"vertebra",0.22+offset,0.50,1)
        v2=self.project.add_annotation(specimen_id,"vertebra",0.43+offset,0.50,1)
        self.project.assign_annotation_role(v2,"first_caudal")
        self.project.assign_annotation_role(v1,"last_predorsal")
        self.project.add_annotation(specimen_id,"preanal_pterygiophore",0.58+offset,0.67,1)
        self.project.verify_annotations(specimen_id,1)

    def _eight_verified(self):
        specimens=[]
        for plate_index,row in enumerate(self.project.source_images()):
            first=self._add_specimen(row["image_id"],300)
            second=self._add_specimen(row["image_id"],620)
            self.project.confirm_plate(row["image_id"])
            self._verify_structure_truth(first,0.00)
            self._verify_structure_truth(second,0.01)
            specimens.extend((first,second))
        return specimens

    def test_training_dataset_uses_only_verified_truth_and_splits_by_source_plate(self):
        specimens=self._eight_verified()
        dataset=prepare_structure_training_dataset(self.project,self.root/"scratch",seed=7)
        self.assertEqual(8,len(dataset["membership"]))
        self.assertEqual(set(specimens),{row["specimen_id"] for row in dataset["membership"]})
        train_images={row["image_id"] for row in dataset["membership"] if row["split"]=="train"}
        val_images={row["image_id"] for row in dataset["membership"] if row["split"]=="val"}
        self.assertTrue(train_images);self.assertTrue(val_images);self.assertFalse(train_images & val_images)
        manifest=json.loads(dataset["manifest"].read_text(encoding="utf-8"))
        self.assertEqual([768,256],manifest["input_size"])
        specs={item["id"]:item for item in manifest["structures"]}
        self.assertEqual(["vertebra"],specs["first_caudal"]["reuse_from"])
        self.assertEqual(["vertebra"],specs["last_predorsal"]["reuse_from"])
        self.assertNotIn("reuse_from",specs["preanal_pterygiophore"])
        self.assertEqual(structure_schema_digest(self.project.scheme),manifest["schema_digest"])
        self.assertEqual(
            dataset["dataset_hash"],
            prepare_structure_training_dataset(self.project,self.root/"scratch2",seed=7)["dataset_hash"],
        )

    def test_training_manifest_preserves_visibility_and_dataset_hash_tracks_it(self):
        specimens=self._eight_verified()
        baseline=prepare_structure_training_dataset(self.project,self.root/"baseline",seed=7)
        target=specimens[0]
        self.project.set_structure_visibility(target,"preanal_pterygiophore","partial",1)
        self.project.verify_annotations(target,1)
        changed=prepare_structure_training_dataset(self.project,self.root/"changed",seed=7)
        self.assertNotEqual(baseline["dataset_hash"],changed["dataset_hash"])
        manifest=json.loads(changed["manifest"].read_text(encoding="utf-8"))
        rows=list(manifest["train"])+list(manifest["val"])
        row=next(item for item in rows if item["specimen_id"]==target)
        self.assertEqual("partial",row["visibility"]["preanal_pterygiophore"])
        self.assertEqual(2,manifest["format_version"])

    def test_ai_seed_is_draft_review_not_training_truth_and_reuses_shared_roles(self):
        image_id=self.project.source_images()[0]["image_id"]
        specimen_id=self._add_specimen(image_id,450);self.project.confirm_plate(image_id)
        result=self.project.seed_structure_predictions(specimen_id,[
            {"structure_id":"vertebra","x":0.25,"y":0.50,"score":0.92},
            {"structure_id":"vertebra","x":0.50,"y":0.50,"score":0.95},
            {"structure_id":"first_caudal","x":0.505,"y":0.501,"score":0.88},
            {"structure_id":"last_predorsal","x":0.252,"y":0.499,"score":0.86},
            {"structure_id":"preanal_pterygiophore","x":0.63,"y":0.66,"score":0.90},
        ],"xray_structure_model_v001")
        self.assertFalse(result["protected"])
        self.assertEqual("draft",self.project.annotation_run(specimen_id,1)["status"])
        self.assertEqual(2,len(self.project.annotation_roles(specimen_id,1)))
        self.assertIn(specimen_id,self.project.structure_ai_review_ids())
        self.assertIn(specimen_id,self.project.structure_prediction_candidate_ids())
        refreshed=self.project.seed_structure_predictions(specimen_id,[
            {"structure_id":"vertebra","x":0.30,"y":0.50,"score":0.90},
            {"structure_id":"vertebra","x":0.52,"y":0.50,"score":0.92},
            {"structure_id":"first_caudal","x":0.521,"y":0.501,"score":0.87},
            {"structure_id":"last_predorsal","x":0.301,"y":0.499,"score":0.86},
            {"structure_id":"preanal_pterygiophore","x":0.62,"y":0.66,"score":0.88},
        ],"xray_structure_model_v002")
        self.assertFalse(refreshed["protected"])
        self.assertEqual("draft",self.project.annotation_run(specimen_id,1)["status"])
        self.project.verify_annotations(specimen_id,1)
        protected=self.project.seed_structure_predictions(specimen_id,[],"xray_structure_model_v003")
        self.assertTrue(protected["protected"])
        self.assertEqual("verified",self.project.annotation_run(specimen_id,1)["status"])
        self.assertNotIn(specimen_id,self.project.structure_prediction_candidate_ids())
        verified_before=[dict(row) for row in self.project.effective_annotations(specimen_id,1,"human")]
        replaced=self.project.seed_structure_predictions(specimen_id,[
            {"structure_id":"vertebra","x":0.34,"y":0.50,"score":0.93},
            {"structure_id":"vertebra","x":0.55,"y":0.50,"score":0.92},
            {"structure_id":"first_caudal","x":0.551,"y":0.501,"score":0.88},
            {"structure_id":"last_predorsal","x":0.341,"y":0.499,"score":0.86},
            {"structure_id":"preanal_pterygiophore","x":0.64,"y":0.66,"score":0.90},
        ],"xray_structure_model_v004",allow_verified=True)
        self.assertFalse(replaced["protected"])
        self.assertEqual("draft",self.project.annotation_run(specimen_id,1)["status"])
        archives=self.project.annotation_archives(specimen_id)
        self.assertTrue(archives)
        self.assertEqual("predict_current_replace_verified",archives[-1]["reason"])
        self.assertEqual("verified",archives[-1]["status"])
        archived_base=archives[-1]["annotations"]
        self.assertEqual(len(self.project.annotations(specimen_id,1,"human")),replaced["annotations"])
        self.assertGreaterEqual(len(archived_base),3)
        self.assertTrue(any(row.get("role_structure_ids") for row in archived_base))

    def test_ai_seed_can_initialize_repeatability_pass_without_touching_main_truth(self):
        image_id=self.project.source_images()[0]["image_id"]
        specimen_id=self._add_specimen(image_id,450);self.project.confirm_plate(image_id)
        self._verify_structure_truth(specimen_id)
        main_before=[dict(row) for row in self.project.effective_annotations(specimen_id,1,"human")]
        result=self.project.seed_structure_predictions(specimen_id,[
            {"structure_id":"vertebra","x":0.31,"y":0.50,"score":0.91},
            {"structure_id":"preanal_pterygiophore","x":0.62,"y":0.67,"score":0.89},
        ],"xray_structure_model_v001",pass_no=3)
        self.assertFalse(result["protected"]);self.assertEqual(3,result["pass_no"])
        self.assertEqual("draft",self.project.annotation_run(specimen_id,3,"human")["status"])
        self.assertEqual(main_before,self.project.effective_annotations(specimen_id,1,"human"))
        self.assertIn(specimen_id,self.project.structure_prediction_candidate_ids(3))

    def test_predict_current_tracks_both_repeatability_passes_without_overwriting_either(self):
        image_id=self.project.source_images()[0]["image_id"]
        specimen_id=self._add_specimen(image_id,450);self.project.confirm_plate(image_id)
        self._verify_structure_truth(specimen_id)
        run=self.project.start_structure_repeatability(1,seed=7)
        model={"model_id":"test-model"};p1=int(run["annotation1_pass_no"]);p2=int(run["annotation2_pass_no"])
        self.assertTrue(_current_prediction_allowed(self.project,specimen_id,model,p1))
        self.assertFalse(_current_prediction_allowed(self.project,specimen_id,model,p2))
        predictions=[
            {"structure_id":"vertebra","x":0.22,"y":0.50,"score":0.9},
            {"structure_id":"vertebra","x":0.43,"y":0.50,"score":0.9},
            {"structure_id":"first_caudal","x":0.43,"y":0.50,"score":0.9},
            {"structure_id":"last_predorsal","x":0.22,"y":0.50,"score":0.9},
            {"structure_id":"preanal_pterygiophore","x":0.58,"y":0.67,"score":0.9},
        ]
        self.project.seed_structure_predictions(specimen_id,predictions,"test-model",pass_no=p1)
        self.assertEqual("draft",self.project.annotation_run(specimen_id,p1)["status"])
        self.project.verify_annotations(specimen_id,p1)
        run=self.project.structure_repeatability(run["run_id"])
        self.assertTrue(_current_prediction_allowed(self.project,specimen_id,model,p2))
        p1_before=self.project.effective_annotations(specimen_id,p1)
        self.project.seed_structure_predictions(specimen_id,predictions,"test-model",pass_no=p2)
        self.assertEqual("draft",self.project.annotation_run(specimen_id,p2)["status"])
        self.assertEqual(p1_before,self.project.effective_annotations(specimen_id,p1))
        self.project.verify_annotations(specimen_id,p2)
        self.assertEqual("completed",self.project.structure_repeatability(run["run_id"])["status"])

    def test_structure_model_registry_preserves_lineage_activation_and_membership(self):
        digest=structure_schema_digest(self.project.scheme)
        image_id=self.project.source_images()[0]["image_id"]
        specimen=self._add_specimen(image_id,450);self.project.confirm_plate(image_id)
        for model_id,parent,active in (
            ("xray_structure_model_v001",None,True),
            ("xray_structure_model_v002","xray_structure_model_v001",True),
        ):
            directory=self.project.models_root/model_id;directory.mkdir(parents=True)
            (directory/"model.pth").write_bytes(b"weights")
            (directory/"model.json").write_text("{}",encoding="utf-8")
            self.project.register_structure_model(
                model_id,
                str((directory/"model.pth").relative_to(self.project.root)),
                str((directory/"model.json").relative_to(self.project.root)),
                parent,digest,"resnet18_heatmap_v1",{"structure/macro_f1":0.7},
                ({"specimen_id":specimen,"split":"train"},),
                activate=active,
            )
        self.assertEqual("xray_structure_model_v002",self.project.active_structure_model()["model_id"])
        self.assertEqual("train",self.project.structure_model_membership("xray_structure_model_v001")[0]["split"])
        with self.assertRaisesRegex(ValueError,"training parent"):
            self.project.delete_structure_model("xray_structure_model_v001")
        self.project.activate_structure_model("xray_structure_model_v001")
        self.project.delete_structure_model("xray_structure_model_v002")
        self.assertEqual("xray_structure_model_v001",self.project.active_structure_model()["model_id"])

    def test_portable_structure_package_round_trip_has_no_training_membership_or_paths(self):
        digest=structure_schema_digest(self.project.scheme);model_id="xray_structure_model_v001"
        directory=self.project.models_root/model_id;directory.mkdir(parents=True)
        (directory/"model.pth").write_bytes(b"portable-weights")
        metadata={
            "format_version":1,"backend":"resnet18_heatmap_v1","input_size":[768,256],"output_stride":2,
            "structures":[{"id":item["id"],"name":item["name"],"repeated":bool(item.get("repeated"))} for item in self.project.scheme["structures"]],
            "thresholds":{item["id"]:0.3 for item in self.project.scheme["structures"]},
            "schema_digest":digest,"model_id":model_id,"dataset_hash":"abc123",
            "training_specimens":12,"validation_specimens":3,
        }
        (directory/"model.json").write_text(json.dumps(metadata),encoding="utf-8")
        self.project.register_structure_model(
            model_id,str((directory/"model.pth").relative_to(self.project.root)),
            str((directory/"model.json").relative_to(self.project.root)),None,digest,"resnet18_heatmap_v1",
            {"structure/macro_f1":0.75,"private_path":"D:/secret/project"},
            (),training_specimen_count=12,validation_specimen_count=3,activate=True,
        )
        package=self.root/"structure-ai.zip";export_structure_model_package(self.project,package,model_id)
        with zipfile.ZipFile(package) as archive:
            names=set(archive.namelist())
            manifest=json.loads(archive.read("manifest.json"))
            text=b"\n".join(archive.read(name) for name in names if not name.endswith(".pth"))
        self.assertEqual({"manifest.json","artifacts/model.pth","artifacts/model.json"},names)
        self.assertEqual(MODEL_PACKAGE_FORMAT,manifest["package_format"])
        self.assertNotIn(b"D:/secret/project",text)
        self.assertNotIn(b"specimen_id",text)
        other_source=self.root/"other_source";other_source.mkdir()
        Image.fromarray(np.full((200,400),80,np.uint8)).save(other_source/"one.png")
        other_root=self.root/"other_projects";other_root.mkdir()
        other=XRayProject.create("other",other_source,other_root,bundled_scheme("phoxinus_vertebral_counts"))
        imported=import_structure_model_package(other,package)
        self.assertEqual(model_id,imported)
        row=next(item for item in other.structure_models() if item["model_id"]==imported)
        self.assertFalse(row["active"])
        self.assertTrue((other.root/row["path"]).is_file())
        other.activate_structure_model(imported)
        self.assertEqual(imported,other.active_structure_model()["model_id"])


class XRayStructureAIContractTests(unittest.TestCase):
    def test_heatmap_target_has_exact_positive_peak_and_partial_supervision_mask(self):
        from ai_runtime.xray_structure_runner import _gaussian
        target=np.zeros((1,16,16),dtype=np.float32)
        supervision=np.zeros_like(target)
        _gaussian(target,0,5.35,6.65,supervision=supervision)
        self.assertEqual(1.0,float(target.max()))
        self.assertGreater(float(supervision.sum()),0.0)
        border=np.zeros((1,16,16),dtype=np.float32)
        _gaussian(border,0,16.2,-0.4)
        self.assertEqual(1.0,float(border.max()))

    def test_dense_repeated_points_use_narrower_targets_without_changing_sparse_or_single_points(self):
        from ai_runtime.xray_structure_runner import _adaptive_point_sigma
        self.assertAlmostEqual(1.12,_adaptive_point_sigma([(0,0),(3.2,0),(6.4,0)],True),places=6)
        self.assertEqual(0.75,_adaptive_point_sigma([(0,0),(1.6,0),(3.2,0)],True))
        self.assertEqual(2.0,_adaptive_point_sigma([(0,0),(8,0),(16,0)],True))
        self.assertEqual(2.0,_adaptive_point_sigma([(0,0)],True))
        self.assertEqual(2.0,_adaptive_point_sigma([(0,0),(2,0)],False))

    def test_structure_model_metadata_records_adaptive_point_target_encoding(self):
        root=Path(__file__).resolve().parents[1]
        runner=(root/"ai_runtime/xray_structure_runner.py").read_text(encoding="utf-8")
        host=(root/"app/xray_structure_ai.py").read_text(encoding="utf-8")
        self.assertIn('TARGET_ENCODING = "adaptive_point_heatmap_v1"',runner)
        self.assertIn('"target_encoding": {',runner)
        self.assertIn('"target_encoding"',host)

    def test_structure_heatmap_loss_balances_each_schema_structure_channel(self):
        root=Path(__file__).resolve().parents[1]
        runner=(root/"ai_runtime/xray_structure_runner.py").read_text(encoding="utf-8")
        self.assertIn('TRAINING_OBJECTIVE = "per_structure_balanced_focal_v1"',runner)
        self.assertIn("positive_counts = positive.sum(dim=reduce_dims)",runner)
        self.assertIn("supervised_counts = mask.sum(dim=reduce_dims)",runner)
        self.assertIn("per_structure = torch.where(positive_counts > 0, with_positive, negative_only)",runner)
        self.assertIn("valid.sum().clamp(min=1.0)",runner)
        self.assertNotIn("positives = positive.sum()\n    return (positive_loss.sum() + negative_loss.sum())",runner)

    def test_role_candidate_coordinates_follow_declared_base_structure(self):
        from ai_runtime.xray_structure_runner import _role_base_coordinates
        structures=[
            {"id":"series","repeated":True},
            {"id":"role","repeated":False,"reuse_from":["series"]},
            {"id":"independent","repeated":False},
        ]
        detected=[
            [(0.9,3,4),(0.8,7,8)],
            [(0.7,99,99)],
            [(0.6,12,13)],
        ]
        self.assertEqual(((3,4),(7,8)),_role_base_coordinates(structures[1],structures,detected))
        self.assertEqual((),_role_base_coordinates(structures[2],structures,detected))

    def test_prediction_contract_refreshes_any_unverified_draft_but_protects_verified(self):
        root=Path(__file__).resolve().parents[1]
        project=(root/"app/xray_project.py").read_text(encoding="utf-8")
        host=(root/"app/xray_structure_ai.py").read_text(encoding="utf-8")
        self.assertIn("if str(row.get(\"annotation_status\") or \"\")==\"verified\":continue",project)
        self.assertIn("structure_prediction_candidate_ids(self,pass_no=1)",project)
        self.assertIn("if run and str(run.get(\"status\") or \"\")==\"verified\"",project)
        self.assertIn("pass_no=1",host)
        self.assertIn("allow_verified=False",host)
        self.assertIn("structure_prediction_candidate_ids(pass_no)",host)
        self.assertIn("allow_verified=bool(allow_verified)",host)

    def test_runner_is_variable_count_heatmap_model_without_anatomy_changing_flips(self):
        root=Path(__file__).resolve().parents[1]
        runner=(root/"ai_runtime/xray_structure_runner.py").read_text(encoding="utf-8")
        self.assertIn("resnet18",runner)
        self.assertIn("max_pool2d",runner)
        self.assertIn("structure.get(\"repeated\")",runner)
        self.assertIn("_role_base_coordinates",runner)
        self.assertIn('"intensity_inversion"',runner)
        self.assertIn('{"complete", "absent"}',runner)
        self.assertIn('{"partial", "not_visible"}',runner)
        self.assertIn("supervision",runner)
        self.assertNotIn("RandomHorizontalFlip",runner)
        self.assertNotIn("RandomVerticalFlip",runner)

    def test_structures_ui_has_current_prediction_landmarks_style_repeatability_and_menu_transfer(self):
        root=Path(__file__).resolve().parents[1]
        ui=(root/"app/xray_structures_ui.py").read_text(encoding="utf-8")
        for text in (
            "Predict current","Human repeatability","Repeat…","Sample size",
            "Annotation 1","Annotation 2","Start new sample",
            "Models…","Check results…","one portable file",
        ):
            self.assertIn(text,ui)
        self.assertIn("_repeatability_diagram",ui)
        self.assertIn("_open_repeatability_pass",ui)
        self.assertIn("start_structure_repeatability",ui)
        self.assertIn("structure_repeatability_metrics",ui)
        self.assertIn("pass_no=pass_no",ui)
        self.assertIn("_marker_visibility_buttons",ui)
        self.assertIn("_marker_visibility_vars",ui)
        self.assertIn("add_radiobutton",ui)
        self.assertIn("_VISIBILITY_SYMBOLS",ui)
        self.assertIn("can_predict=_current_prediction_allowed(self.project,self.selected_specimen_id,model,self.pass_no.get())",ui)
        load=ui[ui.index("    def _load_specimen(self,specimen_id):"):ui.index("    def _clear(self):")]
        self.assertIn("self._refresh_summary()",load)
        self.assertIn("allow_verified=True",ui)
        self.assertIn("current verified annotation will be archived first",ui)
        self.assertNotIn('text="Visibility:"',ui)
        self.assertNotIn('ttk.Button(train_actions,text="Export trained AI…"',ui)
        self.assertNotIn('ttk.Button(train_actions,text="Import trained AI…"',ui)

    def test_structures_ui_exposes_training_prediction_review_and_portable_models(self):
        root=Path(__file__).resolve().parents[1]
        ui=(root/"app/xray_structures_ui.py").read_text(encoding="utf-8")
        for text in (
            "Train Structure AI","Models…","Predict next","Predict all","Review AI",
            "human-verified pass 1",
        ):
            self.assertIn(text,ui)
        self.assertIn("train_structure_model",ui)
        self.assertIn("predict_structures",ui)
        self.assertIn("export_structure_model_package",ui)
        self.assertIn("import_structure_model_package",ui)


if __name__=="__main__":
    unittest.main()
