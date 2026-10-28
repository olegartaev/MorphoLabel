"""Backward compatibility, taxon neutrality and multi-resolution inference tests."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

try:
    import torch
except ImportError:
    torch=None
from PIL import Image

from ai_runtime.universal_multires import (
    PIPELINE,make_tiles,pipeline_components,component_files,
    verify_component_files,merge_logits,predict_one,
)

def meta(mode="tiled"):
    p={"name":PIPELINE,"version":1,"mode":mode,
       "detail":{"checkpoint":"model.pth","input_size":[64,32],"sha256":"a"*64},
       "tiles":{"nx":4,"ny":2,"width_fraction":.38,"height_fraction":.62},
       "fusion_weight":.6}
    if mode=="tiled_native":
        p["native"]={"checkpoint":"native.pth","input_size":[96,32],
                      "sha256":"b"*64,"state_prefix":"base."}
        p["retain_detail_structures"]=["plant_vein"]
    return {"structures":[{"id":"plant_vein","repeated":True},
                          {"id":"cell_nucleus","repeated":False}],
            "input_size":[64,32],"output_stride":2,
            "thresholds":{"plant_vein":.45,"cell_nucleus":.5},
            "inference_pipeline":p}

class TestUniversalMultires(unittest.TestCase):
    def test_whole_frame_covered_without_truth(self):
        t=make_tiles(201,111)
        self.assertEqual((min(x.left for x in t),min(x.top for x in t)),(0,0))
        self.assertEqual((max(x.right for x in t),max(x.bottom for x in t)),(201,111))
        self.assertEqual(len(t),8)

    def test_legacy_model_unmodified(self):
        self.assertEqual(pipeline_components({}),{})
        self.assertEqual(component_files({}),{})

    def test_generic_nonfish_schema(self):
        self.assertEqual(len(pipeline_components(meta())),1)
        self.assertEqual(len(pipeline_components(meta("tiled_native"))),2)

    def test_no_untrusted_paths(self):
        for value in ("../fake.pth","/tmp/fake.pth",r"C:\fake.pth","subdir/model.pth"):
            x=meta()
            x["inference_pipeline"]["detail"]["checkpoint"]=value
            with self.subTest(value=value),self.assertRaises(ValueError):
                pipeline_components(x)

    def test_invalid_structure_retention_rejected(self):
        x=meta("tiled_native")
        x["inference_pipeline"]["retain_detail_structures"]=["nonexistent"]
        with self.assertRaises(ValueError):pipeline_components(x)

    def test_auxiliary_sha256_required(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"detail.pth"
            path.write_bytes(b"example tensor archive")
            x=meta()
            x["inference_pipeline"]["detail"].update(
                checkpoint="detail.pth",sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(len(verify_component_files(x,d)),1)
            path.write_bytes(b"modified")
            with self.assertRaises(ValueError):verify_component_files(x,d)

    @unittest.skipIf(torch is None, 'Optional PyTorch not installed')
    def test_no_tile_is_exact_legacy_fallback(self):
        image=torch.randn(1,2,16,32)
        self.assertIs(merge_logits(image,[],{}),image)
        self.assertIs(merge_logits(image,[object()],{},fusion_weight=0),image)

    @unittest.skipIf(torch is None, 'Optional PyTorch not installed')
    def test_reject_channel_schema_mismatch(self):
        image=torch.zeros(1,2,16,32)
        tile=make_tiles(128,64)[0]
        geom={"scale":.5,"offset_x":0,"offset_y":0,"source_w":128,"source_h":64}
        with self.assertRaises(ValueError):
            merge_logits(image,[(tile,geom,torch.zeros(1,3,16,32))],geom)

    @unittest.skipIf(torch is None, 'Optional PyTorch not installed')
    def test_valid_probability_fusion(self):
        image=torch.zeros(1,2,16,32)
        tile=make_tiles(128,64)[0]
        geom={"scale":.5,"offset_x":0,"offset_y":0,"source_w":128,"source_h":64}
        local={**geom,"source_w":tile.width,"source_h":tile.height}
        out=merge_logits(image,[(tile,local,torch.ones(1,2,16,32))],geom)
        self.assertEqual(out.shape,image.shape)
        self.assertTrue(torch.isfinite(out).all())
        self.assertGreater(float(out.mean()),0)

    @unittest.skipIf(torch is None, 'Optional PyTorch not installed')
    def test_tiled_inference_without_truth(self):
        class MockRuntime:
            @staticmethod
            def _letterbox(im,size):
                return im.resize(size),{"scale":1.,"offset_x":0,"offset_y":0,
                                        "source_w":im.width,"source_h":im.height}
            @staticmethod
            def _tensor(im):return torch.ones(3,im.height,im.width)
            @staticmethod
            def _decode_logits(logits,geometry,meta):
                return [{"structure_id":c["id"],"points":[]} for c in meta["structures"]]
        class MockModel(torch.nn.Module):
            def forward(self,x):
                return torch.ones(x.shape[0],2,x.shape[-2]//2,x.shape[-1]//2)
        with tempfile.TemporaryDirectory() as d:
            im=Path(d)/"specimen.png";Image.new("RGB",(160,64)).save(im)
            p=Path(d)/"model.json";p.write_text(json.dumps(meta()))
            result=predict_one(im,MockModel(),meta(),p,"cpu",MockRuntime)
            self.assertEqual([v["structure_id"] for v in result],["plant_vein","cell_nucleus"])

@unittest.skipIf(torch is None, 'Optional PyTorch not installed')
class TestGenericComposite(unittest.TestCase):
    def test_nonfish_native_and_detail_channel_retention(self):
        class FakeRuntime:
            @staticmethod
            def _letterbox(im,size):
                return im.resize(size),{"source_w":im.width,"source_h":im.height,
                                        "scale":1.,"offset_x":0,"offset_y":0}
            @staticmethod
            def _tensor(im):return torch.ones(3,im.height,im.width)
            @staticmethod
            def _decode_logits(logits,geometry,meta):
                confidence=round(float(logits.mean()))
                return [{"structure_id":k["id"],"points":[{"score":confidence}]}
                        for k in meta["structures"]]
        class Fake(torch.nn.Module):
            def __init__(self,value):
                super().__init__();self.value=value
            def forward(self,x):
                return torch.ones(x.shape[0],2,x.shape[2]//2,x.shape[3]//2)*self.value
        m=meta("tiled_native")
        with tempfile.TemporaryDirectory() as d:
            im=Path(d)/"specimen.png";Image.new("RGB",(160,64)).save(im)
            groups=predict_one(im,Fake(1),m,Path(d)/"model.json","cpu",FakeRuntime,
                               component_models={"detail":Fake(6),"native":Fake(-6)})
            self.assertGreater(groups[0]["points"][0]["score"],0)
            self.assertEqual(groups[1]["points"][0]["score"],-6)

if __name__=="__main__":unittest.main()
