"""Inference-equivalence and transfer-dialog contracts; no source data in ZIPs."""
import copy
import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
from PIL import Image
from app.ai_package import export_model_package, import_model_package
from app.crop_training import train_project, predict
from app.crop_workflow import apply_reviewed_crop
from app.project_storage import Project
from app.xray_project import XRayProject
from app.xray_schema import bundled_scheme
from app.xray_structure_ai import structure_schema_digest, export_structure_model_package, import_structure_model_package, XRayStructurePackageError


class FinalModelTransferTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="final_transfer_");self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.source=self.root/"source";self.source.mkdir()
        for i in range(6):
            a=np.random.default_rng(i).integers(0,255,(80,120,3),dtype=np.uint8)
            Image.fromarray(a).save(self.source/f"fish_{i}.png")
        self.schema=self.root/"schema.csv";self.schema.write_text("id,abbr,name,role\n1,A,Alpha,BOTH\n",encoding="utf-8")
        self.project=Project.create("source_project",self.source,self.root,self.schema,source_layout="direct")
        self.scheme=bundled_scheme("phoxinus_vertebral_counts")
        for item in self.scheme["structures"]:
            item.pop("learning_relation",None);item.pop("reuse_from",None)
        self.xray=XRayProject.create("xray",self.source,self.root,self.scheme)

    def test_trained_landmark_crop_prediction_roundtrip_and_imported_parent(self):
        for i,row in enumerate(self.project.catalog_rows()):
            with Image.open(self.project.image_path(row["image_id"])) as source:base=source.convert("RGB")
            base.save(self.project.cache_root/"developed"/f"{row['image_id']}.png")
            with patch.object(self.project,"_auto_reserve_crop_holdout",return_value=False):
                apply_reviewed_crop(self.project,row["image_id"],base,(10+i,8,105,70-i),i*3,self.project.cache_root/"standardized"/f"{row['image_id']}.png",self.project.image_path(row["image_id"]))
        trained=train_project(self.project,seed=7);self.assertTrue(trained["trained"])
        before=[]
        for path in sorted(self.source.glob("*.png")):
            with Image.open(path) as image:before.append(predict(image,project=self.project)[0])
        package=self.root/"crop.zip";export_model_package(self.project,"crop",package)
        target=Project.create("target",self.source,self.root,self.schema,source_layout="direct")
        local=import_model_package(target,package,"crop");target.set_active_model("crop",local)
        target=Project.open(target.root)
        for expected,path in zip(before,sorted(self.source.glob("*.png"))):
            with Image.open(path) as image:actual,used=predict(image,project=target)
            np.testing.assert_allclose(expected["bounds"],actual["bounds"],atol=1e-12,rtol=0)
            self.assertAlmostEqual(expected["rotation_degrees"],actual["rotation_degrees"],places=12)
            self.assertEqual(local,used)
        with zipfile.ZipFile(package) as archive:
            model=json.loads(archive.read("artifacts/model_manifest.json"))
            self.assertNotIn("training_image_ids",model);self.assertEqual("32x24 grayscale",model["input"])
        for i,row in enumerate(target.catalog_rows()):
            with Image.open(target.image_path(row["image_id"])) as image:base=image.convert("RGB")
            with patch.object(target,"_auto_reserve_crop_holdout",return_value=False):
                apply_reviewed_crop(target,row["image_id"],base,(10+i,8,105,70-i),i*3,target.cache_root/"standardized"/f"{row['image_id']}.png",target.image_path(row["image_id"]))
        child=train_project(target,seed=17,parent_model_id=local)
        self.assertTrue(child["trained"])
        self.assertEqual(local,Project.open(target.root).model_metadata(child["model_id"])["parent_model_id"])

    def test_explicit_crop_model_uses_selected_weights_when_another_is_active(self):
        for ident,bounds in (("selected",[.1,.2,.8,.9]),("active",[.2,.3,.7,.8])):
            directory=self.project.models_root/ident;directory.mkdir()
            weights=np.zeros((769,6));weights[0]=[*bounds,0,1]
            np.savez_compressed(directory/"model.npz",weights=weights)
            self.project.register_model(ident,"crop",path=directory.relative_to(self.project.data_root).as_posix(),active=True)
        with Image.open(self.source/"fish_0.png") as image:
            actual,used=predict(image,model_id="selected",project=self.project)
            active,_=predict(image,project=self.project)
        np.testing.assert_allclose(actual["bounds"],[.1,.2,.8,.9],atol=1e-12,rtol=0)
        self.assertEqual("selected",used)
        self.assertFalse(np.array_equal(actual["bounds"],active["bounds"]))

    def structure_package(self):
        directory=self.xray.models_root/"structure_test";directory.mkdir()
        digest=structure_schema_digest(self.scheme)
        (directory/"model.pth").write_bytes(b"deterministic-structure-weights")
        (directory/"model.json").write_text(json.dumps({"backend":"resnet18_heatmap_v1","schema_digest":digest,"structures":self.scheme["structures"]}),encoding="utf-8")
        self.xray.register_structure_model("structure_test",str((directory/"model.pth").relative_to(self.xray.root)),str((directory/"model.json").relative_to(self.xray.root)),None,digest,"resnet18_heatmap_v1",{},())
        package=self.root/"structure.zip";export_structure_model_package(self.xray,package)
        return package

    def test_semantic_structure_scheme_legacy_implicit_roles_equal_explicit(self):
        explicit=copy.deepcopy(self.scheme)
        for item in explicit["structures"]:
            if item["id"] in {"first_caudal","last_predorsal"}:
                item["learning_relation"]="role_on_structure";item["reuse_from"]=["vertebra"]
        self.assertEqual(structure_schema_digest(self.scheme),structure_schema_digest(explicit))
        package=self.structure_package()
        explicit["name"]="Display only";explicit["traits"].reverse()
        target=XRayProject.create("other_xray",self.source,self.root,explicit)
        local=import_structure_model_package(target,package);target.activate_structure_model(local)
        self.assertEqual(local,XRayProject(target.root).active_structure_model()["model_id"])
        changed=copy.deepcopy(explicit);changed["structures"].reverse()
        other=XRayProject.create("incompatible",self.source,self.root,changed)
        import_structure_model_package(other,package)
        self.assertEqual(self.xray.scheme,other.scheme)

    def test_structure_versioned_legacy_proof_and_digest_disagreement_rejection(self):
        from app.xray_structure_ai import _legacy_structure_schema_contract, structure_schema_contract
        package=self.structure_package()
        with zipfile.ZipFile(package) as archive:original={n:archive.read(n) for n in archive.namelist()}
        legacy=_legacy_structure_schema_contract(self.scheme)
        legacy_digest=hashlib.sha256(json.dumps(legacy,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
        explicit=copy.deepcopy(self.scheme)
        for item in explicit["structures"]:
            if item["id"] in {"first_caudal","last_predorsal"}:item.update(learning_relation="role_on_structure",reuse_from=["vertebra"])
        for case in ("legacy_proven","legacy_unknown","disagreement","topology","targets"):
            contents=dict(original);manifest=json.loads(contents["manifest.json"]);meta=json.loads(contents["artifacts/model.json"])
            if case.startswith("legacy"):
                manifest["schema_digest"]=meta["schema_digest"]=legacy_digest
                if case=="legacy_proven":manifest["schema_contract"]=meta["schema_contract"]=legacy
                else:
                    manifest.pop("schema_contract",None);meta.pop("schema_contract",None)
                    manifest.pop("trait_scheme",None);manifest.pop("trait_scheme_sha256",None)
            if case=="disagreement":meta["schema_digest"]="different"
            if case in {"topology","targets"}:
                contract=copy.deepcopy(manifest["schema_contract"])
                if case=="topology":contract["role_compatibility"]["vertebra"]=[]
                else:contract["structures"][0]["repeated"]=False
                manifest["schema_contract"]=meta["schema_contract"]=contract
                digest=hashlib.sha256(json.dumps(contract,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
                manifest["schema_digest"]=meta["schema_digest"]=digest
            contents["artifacts/model.json"]=json.dumps(meta).encode();manifest["files"]["artifacts/model.json"]=hashlib.sha256(contents["artifacts/model.json"]).hexdigest()
            contents["manifest.json"]=json.dumps(manifest).encode();archive_path=self.root/f"{case}.zip"
            with zipfile.ZipFile(archive_path,"w") as archive:
                for name,data in contents.items():archive.writestr(name,data)
            target=XRayProject.create(case,self.source,self.root,explicit)
            with self.subTest(case=case):
                if case=="legacy_proven":
                    local=import_structure_model_package(target,archive_path);target.activate_structure_model(local)
                    self.assertEqual(structure_schema_digest(explicit),XRayProject(target.root).active_structure_model()["schema_digest"])
                else:
                    with self.assertRaises(XRayStructurePackageError):import_structure_model_package(target,archive_path)
                    self.assertFalse(target.structure_models())

    def test_xray_all_dialogs_use_current_name_and_unified_menu(self):
        from app.modules.xray_counts import XRayCountsRuntime
        from app.model_transfer import model_package_filename
        self.assertEqual("crop_bad_name.zip",model_package_filename({"model_id":"crop:bad/name"}))
        self.xray.register_crop_model("current_crop_7","x","y",None,{},(),0)
        self.structure_package()
        runtime=XRayCountsRuntime();runtime.project=self.xray
        runtime.host=SimpleNamespace(container=SimpleNamespace(winfo_toplevel=lambda:None))
        self.assertEqual((),runtime.standard_menu_entries())
        for kind,ident in (("crop","current_crop_7"),("structure","structure_test")):
            with patch("app.modules.xray_counts.filedialog.askopenfilename",return_value="") as dialog:
                getattr(runtime,f"_menu_import_{kind}_ai")()
                self.assertEqual(ident+".zip",dialog.call_args.kwargs["initialfile"])
            with patch("app.modules.xray_counts.filedialog.asksaveasfilename",return_value="") as dialog:
                getattr(runtime,f"_menu_export_{kind}_ai")()
                self.assertEqual(ident+".zip",dialog.call_args.kwargs["initialfile"])
        from app.xray_structures_ui import XRayStructureWorkspace
        workspace=SimpleNamespace(project=self.xray,root=None)
        with patch("app.xray_structures_ui.filedialog.askopenfilename",return_value="") as dialog:
            XRayStructureWorkspace.import_structure_ai_file(workspace)
            self.assertEqual("structure_test.zip",dialog.call_args.kwargs["initialfile"])
        with patch("app.xray_structures_ui.filedialog.asksaveasfilename",return_value="") as dialog:
            XRayStructureWorkspace.export_active_structure_ai(workspace)
            self.assertEqual("structure_test.zip",dialog.call_args.kwargs["initialfile"])

    def test_detector_package_preserves_effective_nested_inference_pipeline(self):
        from app.xray_crop_package import _portable_config
        path=self.root/"config.py"
        path.write_text("model=dict(type='RTMDet')\ntest_pipeline=[dict(type='Resize',scale=(800,800))]\ntest_dataloader=dict(dataset=dict(type='CocoDataset',data_root='private',pipeline=[dict(type='Resize',scale=(640,640))]))\n",encoding="utf-8")
        # Inspect plain config declarations without executing Python from ZIP.
        import ast
        tree=ast.parse(_portable_config(path))
        effective=next(n for n in tree.body if isinstance(n,ast.Assign) and n.targets[0].id=="test_pipeline")
        self.assertIn("640",ast.unparse(effective));self.assertNotIn("800",ast.unparse(effective))
        self.assertNotIn(b"private",_portable_config(path))

    def test_default_model_filename_dialog_arguments_and_crop_import_activation(self):
        from app.modules.landmarks import LandmarksRuntime
        from app.ui.context import UIContext
        dummy=SimpleNamespace(context=UIContext(self.project),render=lambda:None)
        self.project.register_model("crop_name_7","crop",active=True)
        self.project.register_model("landmark_name_9","landmark",active=True)
        for kind,ident in (("crop","crop_name_7"),("landmark","landmark_name_9")):
            with patch("app.modules.landmarks.filedialog.asksaveasfilename",return_value="") as dialog:
                LandmarksRuntime._export_model(dummy,kind)
                self.assertEqual(ident+".zip",dialog.call_args.kwargs["initialfile"])
            with patch("app.modules.landmarks.filedialog.askopenfilename",return_value="") as dialog:
                LandmarksRuntime._import_model(dummy,kind)
                self.assertEqual(ident+".zip",dialog.call_args.kwargs["initialfile"])
        with patch("app.modules.landmarks.filedialog.askopenfilename",return_value="model.zip"), \
             patch("app.modules.landmarks.import_model_package",return_value="crop_name_7"), \
             patch("app.modules.landmarks.messagebox.showinfo"), \
             patch.object(self.project,"set_active_model",wraps=self.project.set_active_model) as activate:
            LandmarksRuntime._import_model(dummy,"crop")
            activate.assert_called_once_with("crop","crop_name_7")

    def test_xray_crop_transfer_roundtrip_real_inference_path_and_security(self):
        from app import xray_crop_package as transfer
        from app.xray_detector import predict_plates
        directory=self.xray.models_root/"crop_test";directory.mkdir()
        (directory/"model.pth").write_bytes(b"detector-weights")
        (directory/"config.py").write_text("model=dict(type='RTMDet')\n",encoding="utf-8")
        (directory/"orientation_model.pth").write_bytes(b"orientation-weights")
        (directory/"orientation.json").write_text(json.dumps({"backend":"mobilenet_v3_small_imagenet_transfer_v1","axes":{"head":True,"bottom":True},"input_size":224}),encoding="utf-8")
        metrics={"orientation/enabled":True,"orientation/model_path":str((directory/"orientation_model.pth").relative_to(self.xray.root)),"orientation/meta_path":str((directory/"orientation.json").relative_to(self.xray.root))}
        self.xray.register_crop_model("crop_test",str((directory/"model.pth").relative_to(self.xray.root)),str((directory/"config.py").relative_to(self.xray.root)),None,metrics,(),6)
        def detector(runtime,mode,payload,timeout):
            self.assertEqual(b"detector-weights",Path(payload["checkpoint"]).read_bytes())
            return {"results":[{"detections":[{"bbox":[10,10,105,65],"score":.9}]} for p in payload["images"]]}
        def orient(runtime,mode,payload,timeout):
            self.assertEqual(b"orientation-weights",Path(payload["checkpoint"]).read_bytes())
            return {"results":[{"head_right_probability":.9,"bottom_down_probability":.1} for p in payload["images"]]}
        def run(project):
            with patch("app.xray_detector.ensure_ai_runtime",return_value=("test-runtime",{})),patch("app.xray_detector._run",side_effect=detector),patch("app.xray_orientation._run",side_effect=orient):
                result=predict_plates(project,[r["image_id"] for r in project.source_images()])
                self.assertEqual(6,result["success"]);self.assertFalse(result["failures"])
                return [[dict(s["crop"]) for s in project.specimens(r["image_id"])] for r in result["results"]]
        before=run(self.xray)
        package=self.root/"xray_crop.zip";transfer.export_crop_model_package(self.xray,package)
        target=XRayProject.create("crop_target",self.source,self.root,self.scheme)
        local=transfer.import_crop_model_package(target,package);target.activate_crop_model(local)
        reopened=XRayProject(target.root);after=run(reopened)
        for plates in (before,after):
            for plate in plates:
                for proposal in plate:proposal.pop("orientation_model_id",None)
        self.assertEqual(before,after)
        second=transfer.import_crop_model_package(target,package);self.assertNotEqual(local,second)
        with zipfile.ZipFile(package) as archive:
            self.assertFalse(any(name.endswith((".png",".sqlite")) for name in archive.namelist()))
            original={n:archive.read(n) for n in archive.namelist()}
        for case in ("checksum","type","traversal","detector","orientation","orientation_claim"):
            contents=dict(original);manifest=json.loads(contents["manifest.json"])
            if case=="checksum":contents["artifacts/model.pth"]+=b"bad"
            if case=="type":manifest["package_format"]="wrong"
            if case=="traversal":manifest["files"]["artifacts/../escape"]=hashlib.sha256(b"bad").hexdigest();contents["artifacts/../escape"]=b"bad"
            if case=="detector":contents.pop("artifacts/model.pth")
            if case=="orientation":contents.pop("artifacts/orientation_model.pth")
            if case=="orientation_claim":manifest["orientation"]=False
            contents["manifest.json"]=json.dumps(manifest).encode()
            corrupt=self.root/f"bad_{case}.zip"
            with zipfile.ZipFile(corrupt,"w") as archive:
                for name,data in contents.items():archive.writestr(name,data)
            with self.subTest(case=case),self.assertRaises(transfer.XRayCropPackageError):transfer.import_crop_model_package(target,corrupt)
