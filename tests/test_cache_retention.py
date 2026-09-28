import shutil
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from app.cache_retention import prune_developed_cache
from app.project_storage import Project


class DevelopedCacheRetentionTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(tempfile.mkdtemp())
        self.source=self.root/"source";self.source.mkdir()
        for index in range(3):
            Image.new("RGB",(80,48),(20+index,30,40)).save(self.source/f"{index}.jpg")
        schema=self.root/"schema.csv";schema.write_text("id,abbr,name\n1,A,Alpha\n",encoding="utf-8")
        self.project=Project.create("p",self.source,self.root/"projects",schema,source_types=["jpg"],source_layout="direct")
        self.ids=[row["image_id"] for row in self.project.catalog_rows()]
        for index,image_id in enumerate(self.ids):
            developed=self.project.cache_root/"developed"/f"{image_id}.png"
            standardized=self.project.cache_root/"standardized"/f"{image_id}.png"
            Image.new("RGB",(80,48),(80,index,20)).save(developed)
            Image.new("RGB",(60,32),(60,index,10)).save(standardized)
            metadata=self.project.cache_root/"metadata"/f"{image_id}.developed.json"
            metadata.parent.mkdir(parents=True,exist_ok=True);metadata.write_text("{}",encoding="utf-8")
            self.project.save_reviewed_crop(image_id,{
                "developed_full_relpath":f"cache/developed/{image_id}.png",
                "standardized_relpath":f"cache/standardized/{image_id}.png",
                "crop_bounds":[10,8,70,40],"rotation_degrees":0.0,
                "transform":{"original_width":80,"original_height":48,"rotation_degrees":0.0,
                             "center_x":40.0,"center_y":24.0,"crop_left":10,"crop_top":8,
                             "output_width":60,"output_height":32},
                "normalization_status":"PASS","source_sha256":None,
            })
        with self.project.transaction() as connection:
            for index,image_id in enumerate(self.ids):
                connection.execute("UPDATE crops SET reviewed_at=?,updated_at=? WHERE image_id=?",
                                   (f"2026-01-01T00:00:0{index}+00:00",f"2026-01-01T00:00:0{index}+00:00",image_id))

    def tearDown(self):
        shutil.rmtree(self.root,ignore_errors=True)

    def test_prune_keeps_recent_and_never_touches_standardized_or_landmarks(self):
        first=self.ids[0]
        self.project.save_landmark(first,1,12,13,"manual",provenance="manual")
        result=prune_developed_cache(self.project,high_bytes=1,target_bytes=0,keep_recent=1)
        self.assertEqual(2,result["removed_files"])
        self.assertTrue((self.project.cache_root/"developed"/f"{self.ids[-1]}.png").is_file())
        self.assertFalse((self.project.cache_root/"developed"/f"{self.ids[0]}.png").exists())
        self.assertFalse((self.project.cache_root/"metadata"/f"{self.ids[0]}.developed.json").exists())
        for image_id in self.ids:
            self.assertTrue((self.project.cache_root/"standardized"/f"{image_id}.png").is_file())
        self.assertEqual(12,self.project.load_landmarks(first)[1]["x_standardized"])

    def test_missing_source_protects_developed_cache(self):
        image_id=self.ids[0]
        source=self.project.image_path(image_id);source.unlink()
        with self.project.transaction() as connection:
            connection.execute("UPDATE images SET source_available=0 WHERE image_id=?",(image_id,))
        prune_developed_cache(self.project,high_bytes=1,target_bytes=0,keep_recent=0)
        self.assertTrue((self.project.cache_root/"developed"/f"{image_id}.png").is_file())


if __name__=="__main__":
    unittest.main()
