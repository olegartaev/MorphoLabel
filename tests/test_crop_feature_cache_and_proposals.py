import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

from app.crop_training import train_project
from app.normalization_pipeline import prepare_crop_result, commit_crop_result
from app.crop_workflow import apply_reviewed_crop
from app.project_storage import Project


class CropFeatureCacheAndProposalTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.source = self.root / "source"; self.source.mkdir()
        self.schema = self.root / "schema.csv"
        self.schema.write_text("id,abbr,name,role\n1,A,A,BOTH\n", encoding="utf-8")
        for index in range(5):
            Image.new("RGB", (96 + index, 64 + index), (20 + index, 40, 80)).save(self.source / f"{index}.jpg")
        self.project = Project.create("p", self.source, self.root / "data", self.schema, source_types=["jpg"])
        for row in self.project.catalog_rows():
            ident = row["image_id"]
            developed = self.project.cache_root / "developed" / f"{ident}.png"
            developed.parent.mkdir(parents=True, exist_ok=True)
            Image.open(self.project.image_path(ident)).convert("RGB").save(developed)
            self.project.save_reviewed_crop(ident, {
                "developed_full_relpath": f"cache/developed/{ident}.png",
                "standardized_relpath": f"cache/standardized/{ident}.png",
                "crop_bounds": [4, 4, 80, 54], "rotation_degrees": 0.0,
                "transform": {"original_width": 96, "original_height": 64, "rotation_degrees": 0.0,
                              "center_x": 48.0, "center_y": 32.0, "crop_left": 4,
                              "crop_top": 4, "output_width": 76, "output_height": 50},
                "normalization_status": "PASS", "source_sha256": None,
            })

    def test_cache_misses_use_bounded_map_and_warm_cache_avoids_png_decode(self):
        import app.crop_training as training
        from app.crop_parallel import bounded_map as real_map
        calls = []
        def observed(items, worker, **kwargs):
            calls.append(tuple(row["image_id"] for row in items))
            yield from real_map(items, worker, **kwargs)
        with patch("app.crop_parallel.bounded_map", observed):
            cold = train_project(self.project)
        self.assertEqual(5, cold["timings"]["feature_cache_misses"])
        self.assertEqual(0, cold["timings"]["feature_cache_hits"])
        self.assertEqual(1, len(calls))
        self.assertEqual(5, len(calls[0]))
        with patch("app.crop_training._feature_image", side_effect=AssertionError("warm cache decoded PNG")):
            warm = train_project(self.project)
        self.assertEqual(0, warm["timings"]["feature_cache_misses"])
        self.assertEqual(5, warm["timings"]["feature_cache_hits"])

    def test_developed_cache_mutation_does_not_invalidate_source_keyed_feature(self):
        train_project(self.project)
        row = self.project.crop_training_rows()[0]
        Image.new("RGB", (120, 80), (200, 20, 20)).save(row["developed_path"])
        with patch("app.crop_training._feature_image", side_effect=AssertionError("derived PNG changed cache identity")):
            result = train_project(self.project)
        self.assertEqual(0, result["timings"]["feature_cache_misses"])
        self.assertEqual(5, result["timings"]["feature_cache_hits"])

    def test_warm_feature_cache_survives_developed_png_deletion(self):
        train_project(self.project)
        for row in self.project.crop_training_rows():
            Path(row["developed_path"]).unlink()
        with patch("app.crop_training._feature_image", side_effect=AssertionError("warm cache decoded source")):
            result = train_project(self.project)
        self.assertEqual(0, result["timings"]["feature_cache_misses"])
        self.assertEqual(5, result["timings"]["feature_cache_hits"])
        self.assertFalse(any((self.project.cache_root / "developed").glob("*.png")))

    def test_cold_training_can_decode_source_without_materializing_developed_png(self):
        for row in self.project.crop_training_rows():
            Path(row["developed_path"]).unlink()
        result = train_project(self.project)
        self.assertTrue(result["trained"])
        self.assertEqual(5, result["timings"]["feature_cache_misses"])
        self.assertFalse(any((self.project.cache_root / "developed").glob("*.png")))

    def test_switching_crop_model_keeps_model_independent_feature_cache(self):
        train_project(self.project)
        folder=self.project.data_root / "ai" / "models" / "crop_model_v777";folder.mkdir(parents=True)
        np.savez_compressed(folder / "model.npz", weights=np.zeros((769,4),dtype=np.float32))
        self.project.register_model("crop_model_v777", "crop", path="ai/models/crop_model_v777", metrics={}, active=True)
        with patch("app.crop_training._feature_image", side_effect=AssertionError("model switch decoded developed PNG")):
            rerun=train_project(self.project)
        self.assertEqual(5, rerun["timings"]["feature_cache_hits"])

    def test_learned_bulk_proposal_skips_full_resolution_developed_png_until_review(self):
        from app.crop_editor_async_v2 import load_project_developed
        row = self.project.catalog_rows()[0]; ident = row["image_id"]
        developed_path=self.project.cache_root / "developed" / f"{ident}.png"
        developed_path.unlink()
        metadata_path=self.project.cache_root / "metadata" / f"{ident}.developed.json"
        if metadata_path.exists():metadata_path.unlink()
        model_dir = self.project.data_root / "ai" / "models" / "crop_model_v001"; model_dir.mkdir(parents=True)
        weights=np.zeros((769,4),dtype=np.float32);weights[0]=[.1,.1,.9,.9]
        np.savez_compressed(model_dir / "model.npz", weights=weights)
        self.project.register_model("crop_model_v001", "crop", path="ai/models/crop_model_v001", metrics={}, active=True)
        result = prepare_crop_result(self.project.image_path(ident), project=self.project, force=True, image_id_value=ident)
        self.assertTrue(result["proposal_only"])
        self.assertFalse(result["developed_cache_materialized"])
        self.assertEqual((96,64),(result["original_width"],result["original_height"]))
        self.assertFalse(developed_path.exists())
        commit_crop_result(self.project,result,provenance="automatic")
        saved=self.project.record_ai_crop_prediction(ident,result,"crop_model_v001")
        self.assertIn(saved["qc_result"],{"OK","REVIEW","BAD"})
        full,_proxy=load_project_developed(self.project,ident)
        self.assertEqual((96,64),full.size)
        self.assertTrue(developed_path.is_file())

    def test_learned_proposal_writes_neither_mask_nor_standard_until_review(self):
        from app.crop_editor_async_v2 import load_project_developed
        row = self.project.catalog_rows()[0]; ident = row["image_id"]
        model_dir = self.project.data_root / "ai" / "models" / "crop_model_v001"; model_dir.mkdir(parents=True)
        weights=np.zeros((769,4),dtype=np.float32);weights[0]=[.1,.1,.9,.9]
        np.savez_compressed(model_dir / "model.npz", weights=weights)
        self.project.register_model("crop_model_v001", "crop", path="ai/models/crop_model_v001", metrics={}, active=True)
        result = prepare_crop_result(self.project.image_path(ident), project=self.project, force=True, image_id_value=ident)
        self.assertTrue(result["proposal_only"])
        self.assertFalse((self.project.cache_root / "masks" / f"{ident}.png").exists())
        self.assertFalse((self.project.cache_root / "standardized" / f"{ident}.png").exists())
        commit_crop_result(self.project, result, provenance="automatic")
        self.project.record_ai_crop_prediction(ident, result, "crop_model_v001")
        developed,_proxy=load_project_developed(self.project,ident)
        apply_reviewed_crop(self.project, ident, developed, result["crop_bounds"], 0.0,
                            self.project.cache_root / "standardized" / f"{ident}.png", self.project.image_path(ident))
        self.assertTrue((self.project.cache_root / "standardized" / f"{ident}.png").is_file())
        self.assertEqual("ai_accepted", self.project.crop_record(ident)["provenance"])
