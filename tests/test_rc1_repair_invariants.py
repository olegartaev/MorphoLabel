"""Minimized RC1 witnesses and neighboring scientific/persistence invariants."""
import copy
import csv
import hashlib
import importlib.util
import json
import os
import sqlite3
import tempfile
import tkinter as tk
import unittest
from contextlib import closing,contextmanager
from pathlib import Path
from tkinter import ttk
from unittest.mock import patch

from PIL import Image
from app.project_storage import Project
from app.results_export import _atomic_text,parse_tps
from app.rtmpose_dataset import generate_smoke_config
from app.xray_crop import crop_from_geometry,oriented_crop
from app.xray_crop_package import export_crop_model_package,import_crop_model_package
from app.xray_detector import train_detector
from app.xray_project import XRayProject
from app.xray_schema import blank_scheme,bundled_scheme,calculate_trait_values,scientific_scheme_hash
from app.xray_structure_ai import _legacy_structure_schema_contract,_scheme_matches_model,structure_schema_digest,predict_structures
from app.xray_structures_ui import XRayStructureWorkspace,_current_prediction_allowed
from tests.current_fixtures import make_reviewed_crop
from tests.documentation_contract import assert_public_readme_contract


def count_scheme():
    scheme=blank_scheme("Witness")
    scheme["structures"]=[{"id":"objects","name":"Objects","repeated":True}]
    scheme["traits"]=[
        {"id":"double","abbr":"DOUBLE","method":"derived","structures":[],"rule":{"depends_on":["n"],"expression":"n*2"}},
        {"id":"n","abbr":"N","method":"count","structures":["objects"],"rule":{}},
    ]
    return scheme


def children(widget):
    for child in widget.winfo_children():
        yield child
        yield from children(child)


class RC1RepairInvariants(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.source=self.root/"source";self.source.mkdir()
        Image.new("RGB",(160,100)).save(self.source/"образец.png")
        self.env=patch.dict(os.environ,{"LOCALAPPDATA":str(self.root/"state")});self.env.start();self.addCleanup(self.env.stop)

    def xray(self,scheme=None,name="xr"):
        project=XRayProject.create(name,self.source,self.root,scheme or count_scheme())
        image=project.source_images()[0]["image_id"]
        sid=project.add_manual_specimen(image,crop_from_geometry(80,50,160,100,0,(160,100),algorithm="manual"))
        project.confirm_plate(image)
        return project,sid

    def landmark(self):
        schema=self.root/"schema.csv";schema.write_text("id,abbr,name,role\n1,A,Alpha,BOTH\n2,B,Beta,BOTH\n",encoding="utf-8")
        project=Project.create("lm",self.source,self.root,schema,source_layout="direct")
        ident=project.catalog_rows()[0]["image_id"];make_reviewed_crop(project,ident,160,100)
        return project,ident

    def exported(self,project,name="export.csv",verified=True):
        from app.xray_trait_export import export_trait_rows
        target=self.root/name;export_trait_rows(project,target,verified_only=verified)
        with target.open(encoding="utf-8-sig",newline="") as stream:rows=list(csv.DictReader(stream))
        return target.read_bytes(),rows

    def test_rectangular_angle_uses_oriented_pixels_through_persist_reopen_export(self):
        scheme=blank_scheme("Angles");scheme["structures"]=[{"id":sid} for sid in "abc"]
        scheme["traits"]=[{"id":"angle","method":"angle","structures":list("abc")},{"id":"distance","method":"distance","structures":["a","c"]}]
        p,sid=self.xray(scheme)
        points=[(.2,.2),(.5,.5),(.8,.2)]
        for name,(x,y) in zip("abc",points):p.add_annotation(sid,name,x,y)
        p.verify_annotations(sid)
        self.assertAlmostEqual(115.989233583833,p.recalculate_trait_results(sid)["values"]["angle"],places=9)
        root=p.root;del p;p=XRayProject(root)
        self.assertEqual(points,[(a["x"],a["y"]) for a in p.annotations(sid)])
        self.assertEqual("verified",p.annotation_run(sid)["status"])
        self.assertAlmostEqual(115.989233583833,p.trait_rows()[0]["trait_values"]["angle"],places=9)
        _,rows=self.exported(p);self.assertAlmostEqual(115.989233583833,float(rows[0]["angle"]),places=9)
        self.assertAlmostEqual(.6,float(rows[0]["distance"]),places=12)
        with closing(sqlite3.connect(p.db_path)) as c:
            stored=c.execute("SELECT value_text FROM trait_results WHERE specimen_id=? AND trait_id='angle'",(sid,)).fetchone()[0]
        self.assertAlmostEqual(115.989233583833,float(stored),places=3)

    def test_angle_square_and_horizontal_vertical_orientation_preserve_geometry(self):
        scheme=blank_scheme();scheme["structures"]=[{"id":sid} for sid in "abc"]
        scheme["traits"]=[{"id":"angle","method":"angle","structures":list("abc")}]
        rows=[{"structure_id":sid,"x":x,"y":y} for sid,(x,y) in zip("abc",[(.2,.2),(.5,.5),(.8,.2)])]
        self.assertAlmostEqual(90,calculate_trait_values(scheme,rows,crop_size=(100,100))["angle"])
        for rotation in (0,90,-90):
            crop=crop_from_geometry(80,50,160,100,rotation,(160,100))
            self.assertEqual((160,100),oriented_crop(Image.new("RGB",(160,100)),crop).size)
            self.assertAlmostEqual(115.989233583833,calculate_trait_values(scheme,rows,crop_size=(160,100))["angle"],places=9)
        transposed=[{**row,"x":row["y"],"y":row["x"]} for row in rows]
        self.assertAlmostEqual(115.989233583833,calculate_trait_values(scheme,transposed,crop_size=(100,160))["angle"],places=9)

    def test_derived_base_display_order_is_independent_after_reopen_and_export(self):
        for index in (0,1):
            scheme=count_scheme()
            if index:scheme["traits"].reverse()
            p,sid=self.xray(scheme,f"order{index}")
            for x in (.2,.4):p.add_annotation(sid,"objects",x,.5)
            p.verify_annotations(sid);root=p.root;del p;p=XRayProject(root)
            self.assertEqual({"n":2,"double":4},p.trait_rows()[0]["trait_values"])
            _,rows=self.exported(p);self.assertEqual(("2","4"),(rows[0]["N"],rows[0]["DOUBLE"]))

    def test_multilevel_derived_cycle_and_cycle_dependents_never_reuse_values(self):
        scheme=count_scheme()
        scheme["traits"].insert(0,{"id":"quad","method":"derived","rule":{"depends_on":["double"],"expression":"double*2"}})
        for ident,other in (("cycle_a","cycle_b"),("cycle_b","cycle_a"),("cycle_child","cycle_a")):
            scheme["traits"].append({"id":ident,"method":"derived","rule":{"depends_on":[other],"expression":other+"+1"}})
        scheme["traits"].append({"id":"unsafe","method":"derived","rule":{"expression":"__import__('os')"}})
        values=calculate_trait_values(scheme,[{"structure_id":"objects","x":.2,"y":.5},{"structure_id":"objects","x":.4,"y":.5}])
        self.assertEqual((2,4,8),(values["n"],values["double"],values["quad"]))
        for ident in ("cycle_a","cycle_b","cycle_child","unsafe"):self.assertIsNone(values[ident])
        scheme["traits"][1]["rule"]["expression"]="missing+1"
        values=calculate_trait_values(scheme,[{"structure_id":"objects","x":.2,"y":.5}])
        self.assertIsNone(values["double"]);self.assertIsNone(values["quad"])

    def test_cosmetic_scheme_version_preserves_verified_runs_results_repeatability_and_export(self):
        p,sid=self.xray();p.add_annotation(sid,"objects",.2,.5);p.verify_annotations(sid)
        from app.xray_structure_ai import _verified_truth
        before_training=_verified_truth(p)
        first=p.active_scheme_record();before_run=p.annotation_run(sid);before_annotations=p.annotations(sid)
        before_export,_=self.exported(p);repeat=p.start_structure_repeatability(1,seed=7)
        with closing(sqlite3.connect(p.db_path)) as c:before_results=c.execute("SELECT * FROM trait_results").fetchall()
        changed=p.scheme;changed["name"]="Renamed display";p.save_scheme(changed)
        root=p.root;del p;p=XRayProject(root)
        self.assertNotEqual(first["version_id"],p.active_scheme_record()["version_id"])
        self.assertEqual(first["scientific_version_id"],p.active_scheme_record()["scientific_version_id"])
        self.assertEqual(before_run,p.annotation_run(sid));self.assertEqual(before_annotations,p.annotations(sid))
        self.assertEqual(before_training,_verified_truth(p))
        self.assertEqual({"n":1,"double":2},p.trait_rows()[0]["trait_values"])
        self.assertEqual(1,p.annotation_summary()["verified"])
        self.assertEqual(before_export,self.exported(p)[0]);self.assertTrue(p.structure_repeatability()["schema_current"])
        with closing(sqlite3.connect(p.db_path)) as c:self.assertEqual(before_results,c.execute("SELECT * FROM trait_results").fetchall())
        self.assertEqual(2,len(p.schema_history()));self.assertEqual(repeat["run_id"],p.structure_repeatability()["run_id"])

    def test_scientific_change_invalidates_current_results_preserving_old_history_and_crops(self):
        p,sid=self.xray();p.add_annotation(sid,"objects",.2,.5);p.verify_annotations(sid)
        old=p.annotation_run(sid);crop=p.specimen(sid)["crop"]
        changed=p.scheme;changed["traits"][1]["rule"]["offset"]=3;p.save_scheme(changed)
        root=p.root;del p;p=XRayProject(root)
        self.assertIsNone(p.annotation_run(sid));self.assertEqual(0,p.annotation_summary()["verified"])
        self.assertEqual({"n":None,"double":None},p.trait_rows()[0]["trait_values"])
        self.assertEqual([],self.exported(p)[1]);self.assertEqual(crop,p.specimen(sid)["crop"])
        with closing(sqlite3.connect(p.db_path)) as c:
            self.assertEqual("verified",c.execute("SELECT status FROM annotation_runs WHERE run_id=?",(old["run_id"],)).fetchone()[0])
            self.assertEqual(1,c.execute("SELECT COUNT(*) FROM annotations WHERE run_id=?",(old["run_id"],)).fetchone()[0])
        p.add_annotation(sid,"objects",.2,.5);p.verify_annotations(sid)
        self.assertEqual({"n":4,"double":8},p.trait_rows()[0]["trait_values"])

    def test_scientific_contract_excludes_only_presentation_and_keeps_rules_requiredness_and_models(self):
        scheme=count_scheme();original=scientific_scheme_hash(scheme)
        cosmetic=copy.deepcopy(scheme);cosmetic["description"]="new description";cosmetic["name"]="new name"
        cosmetic["traits"].reverse();cosmetic["structures"][0].update(name="Displayed",shape="diamond",color="#fff",hotkey="Q")
        self.assertEqual(original,scientific_scheme_hash(cosmetic))
        for section,key,value in (("structures","required",False),("structures","annotation","polygon"),("structures","repeated",False),("structures","model_extension",2),("traits","structures",[]),("traits","rule",{"offset":2}),("traits","method","presence")):
            changed=copy.deepcopy(scheme);changed[section][0 if section=="structures" else 1][key]=value
            if section=="traits" and key=="structures":
                with self.assertRaises(ValueError):scientific_scheme_hash(changed)
            else:self.assertNotEqual(original,scientific_scheme_hash(changed),(section,key))
        changed=copy.deepcopy(scheme);changed["traits"][0]["rule"]["expression"]="n*3"
        self.assertNotEqual(original,scientific_scheme_hash(changed))

    def test_unicode_landmark_tps_and_metadata_survive_reopen_without_bom(self):
        p,ident=self.landmark();p.save_landmark(ident,1,10,20,"manual");p.save_landmark(ident,2,20,20,"manual")
        p.set_attribute(ident,"note","Кириллица");p.mark_checked(ident)
        root=p.root;del p;p=Project.open(root);outputs=p.sync_results()
        for key in ("tps","specimens"):
            data=outputs[key].read_bytes();self.assertFalse(data.startswith(b'\xef\xbb\xbf'));data.decode("utf-8")
        self.assertIn("IMAGE=образец.png",outputs["tps"].read_text(encoding="utf-8"))
        self.assertIn("Кириллица",outputs["specimens"].read_text(encoding="utf-8"))
        self.assertEqual(1,len(parse_tps(outputs["tps"])))
        path=self.root/"ascii.tps";_atomic_text(path,"LM=1\n10.00000 20.00000\nIMAGE=fish.png\n")
        self.assertEqual(b"LM=1\n10.00000 20.00000\nIMAGE=fish.png\n",path.read_bytes())

    def test_malformed_ui_queues_return_default_without_rewriting_scientific_or_ui_rows(self):
        p,ident=self.landmark();p.save_landmark(ident,1,10,20,"manual")
        for key in ("crop_active_batch","landmark_active_batch"):
            with p.transaction() as c:c.execute("INSERT INTO project(key,value) VALUES(?,?)",("ui."+key,'{"ids":['))
        before=p.load_landmarks(ident);root=p.root;del p;p=Project.open(root)
        default={"ids":[]}
        for key in ("crop_active_batch","landmark_active_batch"):
            with self.assertLogs("app.project_storage",level="WARNING"):self.assertIs(default,p.get_ui_state(key,default))
            with p.transaction() as c:self.assertEqual('{"ids":[',c.execute("SELECT value FROM project WHERE key=?",("ui."+key,)).fetchone()[0])
        self.assertEqual(before,p.load_landmarks(ident));p.sync_results()

    def test_unfinished_complete_landmark_draft_stays_unverified_until_explicit_finish(self):
        p,ident=self.landmark();p.save_annotation_draft(ident,"placement",0)
        p.save_landmark(ident,1,10,20,"manual");p.save_landmark(ident,2,20,20,"manual");p.clear_checked(ident)
        self.assertFalse(p._auto_verify_if_fully_human(ident))
        root=p.root;del p;p=Project.open(root)
        self.assertTrue(p.annotation_status(ident)["complete"]);self.assertFalse(p.annotation_status(ident)["verified"])
        self.assertIsNotNone(p.annotation_draft(ident));p.mark_checked(ident)
        del p;p=Project.open(root);self.assertTrue(p.annotation_status(ident)["verified"]);self.assertIsNone(p.annotation_draft(ident));p.sync_results()

    def test_legacy_complete_human_coordinates_without_workflow_state_still_backfill(self):
        p,ident=self.landmark();p.save_landmark(ident,1,10,20,"manual");p.save_landmark(ident,2,20,20,"manual");p.clear_checked(ident)
        p=Project.open(p.root);self.assertTrue(p.annotation_status(ident)["verified"])

    def test_portable_base_without_train_cfg_loads_ordinary_epoch_loop(self):
        manifest=self.root/"dataset.json";manifest.write_text(json.dumps({"format_version":1,"dataset_id":"d","schema_sha256":"h","schema_landmarks":[{"landmark_id":1,"abbr":"A"}],"images":[]}),encoding="utf-8")
        for inherited in (False,True):
            base=self.root/f"base{inherited}.py"
            base.write_text("default_scope='mmpose'\nmodel=dict(type='TopdownPoseEstimator',backbone=dict(type='CSPNeXt',init_cfg=None),head=dict(type='RTMCCHead',out_channels=1))\ntest_pipeline=[dict(type='LoadImage')]\n"+("train_cfg=dict(type='IterBasedTrainLoop',max_iters=10)\n" if inherited else ""),encoding="utf-8")
            child=generate_smoke_config(manifest,data_root=self.root,train_coco=self.root/"train.json",val_coco=self.root/"val.json",output_path=self.root/f"child{inherited}.py",base_config=base,base_checkpoint=self.root/"weights.pth")
            self.assertIn("custom_imports = None",child.read_text(encoding="utf-8"))
            if importlib.util.find_spec("mmengine"):
                from mmengine.config import Config
                cfg=Config.fromfile(str(child));self.assertNotIn("_delete_",cfg.train_cfg);self.assertNotIn("max_iters",cfg.train_cfg)
                self.assertEqual("EpochBasedTrainLoop",cfg.train_cfg.type)
            else:
                # Exercise the actual generated Python conditional with a base
                # namespace; runtime QA additionally loads through MMEngine.
                import ast
                tree=ast.parse(child.read_text(encoding="utf-8"));tree.body=[node for node in tree.body if not (isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=="_base_" for t in node.targets))]
                scope={"_base_":{"train_cfg":{}} if inherited else {}}
                exec(compile(tree,str(child),"exec"),scope)
                self.assertEqual(inherited,"_delete_" in scope["train_cfg"])

    def test_landmark_training_refuses_registered_import_id_before_creating_child_files(self):
        from app.rtmpose_backend import train_project
        from app.project_storage import schema_hash
        from types import SimpleNamespace
        p,_=self.landmark();ident="rtmpose_v004"
        p.register_model(ident,"landmark",path=f"models/landmark/{ident}")
        before=p.model_metadata(ident)
        backend=SimpleNamespace(model_id=ident,schema_sha256=schema_hash(p.schema_path))
        with patch("app.rtmpose_backend.verify_dataset",return_value={"ok":True}):
            with self.assertRaisesRegex(FileExistsError,"registered model"):train_project(p,"witness",backend)
        self.assertFalse((p.data_root/"ai/models"/ident).exists())
        self.assertEqual(before,Project.open(p.root).model_metadata(ident))

    def test_release_documentation_public_contract_and_user_guide(self):
        root=Path(__file__).resolve().parents[1];assert_public_readme_contract(self,(root/"README.md").read_text(encoding="utf-8"))
        guide=(root/"docs/USER_GUIDE.md").read_text(encoding="utf-8").lower()
        for required in ("landmarks","x-ray","provenance","license","citation","1.0.0-rc.1"):self.assertIn(required,guide)

    def crop_parent(self,p):
        directory=p.models_root/"xray_crop_model_v004";directory.mkdir()
        (directory/"model.pth").write_bytes(b"immutable parent")
        (directory/"config.py").write_text("model=dict(type='RTMDet')\ntest_pipeline=[dict(type='LoadImageFromFile')]\n",encoding="utf-8")
        p.register_crop_model(directory.name,str((directory/"model.pth").relative_to(p.root)),str((directory/"config.py").relative_to(p.root)),None,{},[],0)
        return directory

    def fake_crop_training(self,p,**kwargs):
        checkpoint=self.root/"trained.pth";checkpoint.write_bytes(b"new child weights")
        config=self.root/"trained.py";config.write_text("model=dict(type='RTMDet')\ntest_pipeline=[dict(type='LoadImageFromFile')]\n",encoding="utf-8")
        plate_ids=[row["image_id"] for row in p.source_images()]
        dataset={"root":self.root,"train_json":self.root/"train.json","val_json":self.root/"val.json","plate_ids":plate_ids,"training_specimens":1,"train_plates":1,"val_plates":1}
        settings={"hardware":{},"training":{"batch_size":1,"device":"cpu","workers":0}}
        def orientation(project,model_id,staging,*args,**extra):
            self.assertNotEqual(project.models_root/model_id,staging)
            self.assertFalse((project.models_root/model_id).exists())
            return {"orientation/enabled":False}
        with patch("app.xray_detector.detector_performance_settings",return_value=settings),patch("app.xray_detector.ensure_ai_runtime",return_value=("runtime",None)),patch("app.xray_detector.prepare_training_dataset",return_value=dataset),patch("app.xray_detector._run",return_value={"checkpoint":str(checkpoint),"config":str(config)}),patch("app.xray_detector.train_orientation_model",side_effect=orientation):
            return train_detector(p,epochs=1,**kwargs)

    def test_crop_imported_v004_duplicate_imports_train_unique_child_keep_parent_hash_and_lineage(self):
        p,sid=self.xray();parent=self.crop_parent(p);original={path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in parent.iterdir()}
        package=self.root/"parent.zip";export_crop_model_package(p,package,parent.name)
        for _ in range(2):import_crop_model_package(p,package)
        self.assertEqual(3,len(p.crop_models()))
        result=self.fake_crop_training(p,parent_model_id=parent.name)
        self.assertNotEqual(parent.name,result["model_id"])
        root=p.root;del p;p=XRayProject(root)
        self.assertEqual(parent.name,p.active_crop_model()["parent_model_id"])
        self.assertEqual(original,{path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in parent.iterdir()})
        self.assertFalse(list(p.models_root.glob(".*.training-*")))
        exported=self.root/"child.zip";export_crop_model_package(p,exported)
        imported=import_crop_model_package(p,exported);self.assertNotEqual(imported,result["model_id"])
        self.exported(p,verified=False)

    def test_crop_model_id_allocator_respects_registry_gaps_and_orphan_directories(self):
        p,_=self.xray();self.crop_parent(p)
        self.assertEqual("xray_crop_model_v001",p.next_crop_model_id())
        (p.models_root/"xray_crop_model_v001").mkdir()
        p.register_crop_model("xray_crop_model_v002","external/model.pth","external/config.py",None,{},[],0)
        self.assertEqual("xray_crop_model_v003",p.next_crop_model_id())
        (p.models_root/"xray_crop_model_v003").mkdir()
        self.assertEqual("xray_crop_model_v005",p.next_crop_model_id())

    def test_crop_registration_failure_removes_only_new_child_and_preserves_parent(self):
        p,_=self.xray();parent=self.crop_parent(p);before=(parent/"model.pth").read_bytes();child=p.next_crop_model_id()
        with patch.object(p,"register_crop_model",side_effect=sqlite3.IntegrityError("injected registry failure")):
            with self.assertRaises(sqlite3.IntegrityError):self.fake_crop_training(p,parent_model_id=parent.name)
        self.assertFalse((p.models_root/child).exists());self.assertEqual(before,(parent/"model.pth").read_bytes())
        self.assertEqual(parent.name,XRayProject(p.root).active_crop_model()["model_id"])
        self.assertFalse(list(p.models_root.glob(".*.training-*")))

    def test_atomic_model_publish_refuses_late_collision_and_never_removes_older_target(self):
        from app.model_publication import staged_model_directory
        target=self.root/"models"/"child"
        with self.assertRaises(FileExistsError):
            with staged_model_directory(target) as (stage,publish):
                (stage/"model.pth").write_bytes(b"new")
                target.mkdir();(target/"model.pth").write_bytes(b"older")
                publish()
        self.assertEqual(b"older",(target/"model.pth").read_bytes())
        self.assertEqual([target],list(target.parent.iterdir()))

    def test_crop_import_late_destination_collision_preserves_the_other_artifact(self):
        from app.model_publication import staged_model_directory
        p,_=self.xray();parent=self.crop_parent(p);package=self.root/"parent.zip";export_crop_model_package(p,package,parent.name)
        targets=[]
        @contextmanager
        def collide(target):
            with staged_model_directory(target) as value:
                target.mkdir();(target/"model.pth").write_bytes(b"another immutable model")
                targets.append(target)
                yield value
        with patch("app.xray_crop_package.staged_model_directory",collide):
            with self.assertRaises(FileExistsError):import_crop_model_package(p,package)
        self.assertEqual(b"another immutable model",(targets[0]/"model.pth").read_bytes())
        self.assertEqual(1,len(p.crop_models()))

    def test_structure_training_registration_failure_cleans_new_child_and_keeps_parent(self):
        from app.xray_structure_ai import train_structure_model
        from types import SimpleNamespace
        p,_=self.xray();parent=p.models_root/"xray_structure_model_v007";parent.mkdir()
        checkpoint=parent/"model.pth";checkpoint.write_bytes(b"parent bytes")
        metadata=parent/"model.json";metadata.write_text(json.dumps({"backend":"resnet18_heatmap_v1"}),encoding="utf-8")
        digest=structure_schema_digest(p.scheme)
        p.register_structure_model(parent.name,str(checkpoint.relative_to(p.root)),str(metadata.relative_to(p.root)),None,digest,"resnet18_heatmap_v1",{})
        child=p.next_structure_model_id()
        weights=self.root/"child.pth";weights.write_bytes(b"child bytes")
        info=self.root/"child.json";info.write_text(json.dumps({"backend":"resnet18_heatmap_v1"}),encoding="utf-8")
        backend=SimpleNamespace(train=lambda payload,timeout:{"checkpoint":str(weights),"metadata":str(info)})
        dataset={"manifest":self.root/"manifest.json","membership":[],"dataset_hash":"h","training_specimens":8,"validation_specimens":2,"training_plates":3,"validation_plates":1}
        performance={"training":{"batch_size":1,"workers":0,"device":"cpu"}}
        with patch("app.xray_structure_ai._structure_backend",return_value=backend),patch("app.xray_structure_ai.structure_performance_settings",return_value=performance),patch("app.xray_structure_ai.prepare_structure_training_dataset",return_value=dataset),patch.object(p,"register_structure_model",side_effect=sqlite3.IntegrityError("registry failed")):
            with self.assertRaises(sqlite3.IntegrityError):train_structure_model(p,parent_model_id=parent.name)
        self.assertEqual(b"parent bytes",checkpoint.read_bytes());self.assertFalse((p.models_root/child).exists())
        self.assertEqual(parent.name,XRayProject(p.root).active_structure_model()["model_id"])

    def test_legacy_v007_semantic_selector_current_batch_and_parent_eligibility_survive_reopen(self):
        scheme=bundled_scheme("phoxinus_vertebral_counts");p,sid=self.xray(scheme)
        legacy=copy.deepcopy(scheme)
        for item in legacy["structures"]:item.pop("learning_relation",None);item.pop("reuse_from",None)
        contract=_legacy_structure_schema_contract(legacy)
        digest=hashlib.sha256(json.dumps(contract,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
        self.assertNotEqual(digest,structure_schema_digest(p.scheme))
        directory=p.models_root/"xray_structure_model_v007";directory.mkdir()
        (directory/"model.pth").write_bytes(b"checkpoint")
        (directory/"model.json").write_text(json.dumps({"backend":"resnet18_heatmap_v1","schema_digest":digest,"schema_contract":contract}),encoding="utf-8")
        p.register_structure_model(directory.name,str((directory/"model.pth").relative_to(p.root)),str((directory/"model.json").relative_to(p.root)),None,digest,"resnet18_heatmap_v1",{})
        for _ in range(2):
            p=XRayProject(p.root);model=p.active_structure_model()
            self.assertTrue(_scheme_matches_model(p,model));self.assertTrue(_current_prediction_allowed(p,sid,model,1))
            root=tk.Tk();root.withdraw()
            try:
                from app.ui.design import apply_styles
                apply_styles(root,ttk.Style(root));frame=ttk.Frame(root);frame.pack()
                view=XRayStructureWorkspace(frame,p,initial_specimen_id=sid);root.update_idletasks()
                self.assertIn(directory.name,view.prediction_model_box.cget("values"))
                self.assertEqual("readonly",str(view.prediction_model_box.cget("state")))
                self.assertEqual(directory.name,view.prediction_model_choice.get())
                self.assertIn(directory.name,view.training_parent_box.cget("values"))
                for button in (view.predict_current_button,view.structure_predict_next_button,view.structure_predict_all_button):self.assertEqual("normal",str(button.cget("state")))
            finally:root.destroy()
        cosmetic=p.scheme;cosmetic["name"]="Cosmetic";p.save_scheme(cosmetic);self.assertTrue(_scheme_matches_model(p,model))
        changed=p.scheme;changed["structures"][0]["required"]=False;p.save_scheme(changed)
        self.assertFalse(_scheme_matches_model(p,model));self.assertFalse(_current_prediction_allowed(p,sid,model,1))
        with self.assertRaisesRegex(RuntimeError,"incompatible"):predict_structures(p,[sid])

    def test_ai_setup_prestart_hides_progress_and_click_reveals_work_prevents_double_start(self):
        from app.ui.shell import ProductionShell
        from app.ui.design import apply_styles
        from types import MethodType
        root=tk.Tk();root.withdraw();apply_styles(root,ttk.Style(root))
        # Real Tk dialog, with only its worker thread stubbed: no installation.
        commands={}
        def button(self,parent,text,command,*args,**kwargs):
            commands[text]=command
            return ttk.Button(parent,text=text,command=command)
        root.control_button=MethodType(button,root)
        try:
            with patch("app.ui.shell.ai_setup_complete",return_value=False),patch("app.ui.shell.threading.Thread") as thread:
                ProductionShell._show_first_run_setup(root);root.update_idletasks()
                dialog=next(w for w in root.winfo_children() if isinstance(w,tk.Toplevel))
                widgets=list(children(dialog));labels=[str(w.cget("text")) for w in widgets if isinstance(w,ttk.Label)]
                self.assertIn("✓ Ready",labels);self.assertIn("Ready to install AI support · 7 AI components waiting",labels)
                self.assertFalse(any("%" in label for label in labels))
                bars=[w for w in widgets if isinstance(w,ttk.Progressbar)]
                self.assertEqual(2,len(bars));self.assertTrue(all(not w.winfo_manager() for w in bars));thread.assert_not_called()
                start=next(w for w in widgets if isinstance(w,ttk.Button) and w.cget("text")=="Install AI support")
                start.invoke();commands["Install AI support"]()
                self.assertEqual(1,thread.call_count);thread.return_value.start.assert_called_once()
                self.assertTrue(all(w.winfo_manager()=="grid" for w in bars))
                self.assertTrue(any("%" in str(w.cget("text")) for w in children(dialog) if isinstance(w,ttk.Label)))
        finally:root.destroy()
