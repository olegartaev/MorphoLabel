import inspect
import shutil
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from app.landmark_review import adaptive_review_workers, scan_project, _structural_warnings_snapshot
from app.project_storage import Project


class _FailingExecutor:
 def __init__(self, **_kwargs):
  raise RuntimeError("simulated worker startup failure")


class ReviewScanParallelTests(unittest.TestCase):
 def setUp(self):
  self.tmp=Path(tempfile.mkdtemp());source=self.tmp/"source";source.mkdir()
  for index in range(4):(source/f"fish_{index}.jpg").write_bytes(b"x")
  schema=self.tmp/"schema.csv";schema.write_text("id,abbr,name,role\n1,A,One,BOTH\n2,B,Two,BOTH\n",encoding="utf8")
  self.project=Project.create("p",source,self.tmp,schema,source_layout="direct")
  self.rows=self.project.catalog_rows()
  for index,row in enumerate(self.rows):
   Image.new("RGB",(100,100)).save(self.project.cache_root/"standardized"/f"{row['image_id']}.png")
   if index<2:
    self.project.save_landmark(row["image_id"],1,10,10,"manual",provenance="manual")
    self.project.save_landmark(row["image_id"],2,10 if index==0 else 80,10,"manual",provenance="manual")
 def tearDown(self):shutil.rmtree(self.tmp,ignore_errors=True)

 def test_adaptive_worker_count(self):
  self.assertEqual([adaptive_review_workers(n) for n in (1,2,4,8,32)],[1,1,3,7,31])

 def test_serial_and_parallel_results_are_identical_and_read_only(self):
  before=[self.project.load_landmarks(row["image_id"]) for row in self.rows]
  serial=scan_project(self.project,workers=1);parallel=scan_project(self.project,workers=4)
  self.assertEqual(serial["queue"],parallel["queue"])
  self.assertEqual(before,[self.project.load_landmarks(row["image_id"]) for row in self.rows])

 def test_parallel_order_is_deterministic(self):
  first=scan_project(self.project,workers=4)["queue"]
  for _ in range(3):self.assertEqual(first,scan_project(self.project,workers=4)["queue"])

 def test_worker_has_no_project_or_tk_access(self):
  source=inspect.getsource(_structural_warnings_snapshot)
  self.assertNotIn("project.",source);self.assertNotIn("tk.",source)

 def test_worker_startup_failure_falls_back_to_serial(self):
  serial=scan_project(self.project,workers=1)
  recovered=scan_project(self.project,workers=4,executor_factory=_FailingExecutor)
  self.assertTrue(recovered["parallel_fallback"])
  self.assertEqual(serial["queue"],recovered["queue"])

if __name__=="__main__":unittest.main()