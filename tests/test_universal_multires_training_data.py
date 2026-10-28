"""Core-only tests for universal training data: no CUDA or human fish labels."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from PIL import Image

from ai_runtime.universal_multires_training_data import (
    _check_manifest,project_points,build_tile_manifest)
from ai_runtime.universal_multires import make_tiles


class UniversalTrainingDataTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.rows={}
        for name in ("a","b","c","d"):
            p=self.root/(name+".png")
            Image.new("RGB",(200,80),(40,50,60)).save(p)
            self.rows[name]={
                "specimen_id":name,"image_id":"plate_"+name,
                "path":str(p),
                "points":[{"structure_id":"cell_center","x":.5,"y":.5},
                          {"structure_id":"leaf_tip","x":.82,"y":.45}],
                "visibility":{"cell_center":"complete","leaf_tip":"partial"}
            }
        self.manifest={
            "structures":[{"id":"cell_center","repeated":True},
                          {"id":"leaf_tip","repeated":False}],
            "schema_digest":"some_original_contract",
            "train":[self.rows["a"],self.rows["b"]],
            "val":[self.rows["c"],self.rows["d"]]}

    def test_generic_crop_and_points(self):
        before=copy.deepcopy(self.manifest)
        original_sha={p.name:hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in self.root.glob("*.png")}
        result=build_tile_manifest(self.manifest,self.root/"new_dataset")
        manifest=json.loads(Path(result["manifest"]).read_text())
        self.assertEqual((len(manifest["train"]),len(manifest["val"])),(16,16))
        self.assertEqual(manifest["input_size"],[768,384])
        self.assertEqual(result["source_plates_train"],2)
        self.assertEqual(result["source_plates_val"],2)
        self.assertEqual(manifest["schema_digest"],"some_original_contract")
        self.assertEqual(manifest["tile_training_protocol"]["source_channel_order"],
                         ["cell_center","leaf_tip"])
        self.assertTrue(all(r["image_id"] in ("plate_a","plate_b") for r in manifest["train"]))
        self.assertTrue(all(r["image_id"] in ("plate_c","plate_d") for r in manifest["val"]))
        self.assertTrue(all(r["visibility"]["leaf_tip"]=="partial"
                            for r in manifest["train"]+manifest["val"]))
        for r in manifest["train"]+manifest["val"]:
            self.assertTrue(Path(r["path"]).is_file())
            for p in r["points"]:
                self.assertTrue(0<=p["x"]<=1 and 0<=p["y"]<=1)
        self.assertEqual(self.manifest,before)
        self.assertEqual(original_sha,{p.name:hashlib.sha256(p.read_bytes()).hexdigest()
                                      for p in self.root.glob("*.png")})

    def test_split_leak_prohibited(self):
        m=copy.deepcopy(self.manifest)
        m["val"][0]["image_id"]=m["train"][0]["image_id"]
        with self.assertRaisesRegex(ValueError,"Source plate"):
            build_tile_manifest(m,self.root/"new_dataset")
        self.assertFalse((self.root/"new_dataset").exists())

    def test_bad_annotation_refused_before_writes(self):
        m=copy.deepcopy(self.manifest)
        m["train"][0]["points"][0]["x"]=1.02
        with self.assertRaisesRegex(ValueError,"coordinates"):
            build_tile_manifest(m,self.root/"new_dataset")
        self.assertFalse((self.root/"new_dataset").exists())

    def test_overwrite_refused(self):
        target=self.root/"new_dataset"
        build_tile_manifest(self.manifest,target)
        with self.assertRaises(FileExistsError):
            build_tile_manifest(self.manifest,target)

    def test_bad_visibility(self):
        m=copy.deepcopy(self.manifest)
        m["val"][0]["visibility"]["leaf_tip"]="invented"
        with self.assertRaisesRegex(ValueError,"visibility"):
            _check_manifest(m)

    def test_tiling_does_not_need_truth(self):
        points=[{"structure_id":"cell_center","x":.5,"y":.5}]
        tiles=make_tiles(200,80)
        containing=sum(bool(project_points(points,t,200,80)) for t in tiles)
        self.assertGreater(containing,1)
        self.assertEqual(len(tiles),8)

if __name__=="__main__":
    unittest.main()
