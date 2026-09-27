import hashlib, shutil, tempfile, unittest
from pathlib import Path
from app.project_storage import Project, load_schema, migrate_legacy

def schema(path, rows):
 path.write_text("id,abbr,name\n"+"\n".join(f"{a},{b},{c}" for a,b,c in rows)+"\n",encoding="utf-8")

class ProjectStorageTests(unittest.TestCase):
 def setUp(self):
  self.tmp=Path(tempfile.mkdtemp());self.src=self.tmp/"source";self.src.mkdir();(self.src/"s").mkdir();(self.src/"s"/"a.jpg").write_bytes(b"image bytes");self.schema=self.tmp/"schema.csv";schema(self.schema,[(1,"A","one"),(3,"C","three"),(7,"G","seven")])
 def tearDown(self): shutil.rmtree(self.tmp)
 def new(self,name="P"): return Project.create(name,self.src,self.tmp,self.schema)
 def image_id(self,p):
  c=p.connect()
  try:return c.execute("SELECT image_id FROM images").fetchone()[0]
  finally:c.close()
 def test_create_reopen_and_schema_three(self):
  p=self.new();self.assertTrue((p.data_root/"project.sqlite").exists());self.assertTrue((p.root/"landmark_schema.csv").exists());self.assertEqual([r["id"] for r in Project.open(p.root).schema],[1,2,3]);self.assertEqual(p.count("images"),1)
 def test_schema_25_and_arbitrary(self):
  schema(self.schema,[(i,f"P{i}",f"n{i}") for i in range(1,26)]);self.assertEqual(len(self.new().schema),25)
  schema(self.schema,[(2,"b","B"),(50,"z","Z")]);self.assertEqual([r["id"] for r in self.new("P2").schema],[1,2])
 def test_invalid_schemas(self):
  schema(self.schema,[(1,"A","a"),(1,"B","b")]);self.assertEqual([x["abbr"] for x in load_schema(self.schema)],["A","B"])
  schema(self.schema,[(1,"A","a"),(2,"A","b")]);self.assertRaises(ValueError,load_schema,self.schema)
  self.schema.write_text("id,name\n1,a\n",encoding="utf-8");self.assertRaises(ValueError,load_schema,self.schema)
 def test_save_reopen_move_and_lowest_missing_identity(self):
  p=self.new();image_id=self.image_id(p);p.save_landmark(image_id,3,10,11,"manual");p.save_landmark(image_id,3,20,21,"corrected")
  values=Project.open(p.root).load_landmarks(image_id);self.assertEqual(set(values),{3});self.assertEqual((values[3]["x_standardized"],values[3]["y_standardized"]),(20,21))
  present={1,3};self.assertEqual(next(x["id"] for x in p.schema if x["id"] not in present),2)
 def test_relink_cache_deletion_export_and_model_schema_guard(self):
  p=self.new();image_id=self.image_id(p);p.save_landmark(image_id,3,1,2,"manual");out=p.export_landmarks();self.assertIn("3",out.read_text(encoding="utf-8"))
  shutil.rmtree(p.cache_root);self.assertEqual(p.load_landmarks(image_id)[3]["x_standardized"],1);(p.cache_root/"developed").mkdir(parents=True);self.assertTrue(p.image_path(image_id).exists())
  moved=self.tmp/"moved";shutil.copytree(self.src,moved);result=p.relink(moved);self.assertEqual(result["matched"],1);self.assertTrue(p.image_path(image_id).exists())
  self.assertRaises(ValueError,p.register_model,"bad","landmark",schema_digest="wrong");self.assertTrue(p.backup().exists())
 def test_legacy_migration_preserves_coordinate_ids(self):
  p=self.new();image_id=self.image_id(p);legacy=self.tmp/"legacy";d=legacy/"work"/"s"/"landmarks";d.mkdir(parents=True);(d/f"{image_id}.json").write_text('{"image_id":"'+image_id+'","points":{"P3":{"landmark_id":"P3","x_standardized":4,"y_standardized":5,"state":"manual"}}}',encoding="utf-8")
  migrate_legacy(p,legacy);row=p.load_landmarks(image_id)[3];self.assertEqual((row["x_standardized"],row["y_standardized"]),(4,5))

 def test_catalog_rows_bulk_matches_canonical_landmark_status_without_per_image_status_calls(self):
  p=self.new("bulk");image_id=self.image_id(p)
  p.save_landmark(image_id,1,10,11,"manual",provenance="manual")
  p.save_landmark(image_id,3,None,None,"missing",provenance="manual")
  expected=p.annotation_status(image_id)
  original=p.annotation_status
  def forbidden(_image_id):
   raise AssertionError("catalog_rows must not call annotation_status per image")
  p.annotation_status=forbidden
  try:row=p.catalog_rows()[0]
  finally:p.annotation_status=original
  self.assertEqual(expected["expected"],row["expected_landmarks"])
  self.assertEqual(expected["placed"],row["placed"])
  self.assertEqual(expected["human_placed"],row["human_placed"])
  self.assertEqual(expected["missing_ids"],row["missing_ids"])
  self.assertEqual(expected["color"],row["status_color"])

 def test_direct_layout_includes_nested_source_paths(self):
  nested=self.src/"s"/"nested"/"deeper";nested.mkdir(parents=True);(nested/"b.jpg").write_bytes(b"nested image")
  p=Project.create("nested",self.src,self.tmp,self.schema,source_layout="direct")
  rows={row["relative_path"]:row for row in p.catalog_rows()}
  self.assertIn("s/nested/deeper/b.jpg",rows)
  self.assertEqual("s",rows["s/nested/deeper/b.jpg"]["locality"])

 def test_reopen_refreshes_deleted_source_availability_without_losing_history(self):
  p=self.new("missing_source");image_id=self.image_id(p);source=p.image_path(image_id)
  p.save_landmark(image_id,1,10,11,"manual",provenance="manual")
  source.unlink()
  reopened=Project.open(p.root)
  with reopened.transaction() as c:row=dict(c.execute("SELECT active,source_available FROM images WHERE image_id=?",(image_id,)).fetchone())
  self.assertEqual(1,row["active"])
  self.assertEqual(0,row["source_available"])
  self.assertIsNone(reopened.image_path(image_id))
  self.assertEqual(10,reopened.load_landmarks(image_id)[1]["x_standardized"])

 def test_reopen_of_unchanged_current_project_is_database_noop(self):
  p=self.new("stable_open");image_id=self.image_id(p)
  for ident in (1,2,3):
   p.save_landmark(image_id,ident,float(ident),float(ident+1),"manual",provenance="manual")
  p.mark_checked(image_id)
  reopened=Project.open(p.root)
  with reopened.transaction() as c:
   before_review=c.execute("SELECT human_verified,updated_at FROM image_review WHERE image_id=?",(image_id,)).fetchone()
  before=hashlib.sha256(reopened.path.read_bytes()).hexdigest()
  reopened_again=Project.open(reopened.root)
  after=hashlib.sha256(reopened_again.path.read_bytes()).hexdigest()
  with reopened_again.transaction() as c:
   after_review=c.execute("SELECT human_verified,updated_at FROM image_review WHERE image_id=?",(image_id,)).fetchone()
  self.assertEqual(before,after)
  self.assertEqual(tuple(before_review),tuple(after_review))

 def test_reopen_writes_source_availability_only_when_presence_changes(self):
  p=self.new("availability_delta");image_id=self.image_id(p)
  stable=Project.open(p.root)
  before=hashlib.sha256(stable.path.read_bytes()).hexdigest()
  self.assertEqual(before,hashlib.sha256(Project.open(stable.root).path.read_bytes()).hexdigest())
  source=stable.image_path(image_id);source.unlink()
  reopened=Project.open(stable.root)
  self.assertNotEqual(before,hashlib.sha256(reopened.path.read_bytes()).hexdigest())
  with reopened.transaction() as c:
   self.assertEqual(0,c.execute("SELECT source_available FROM images WHERE image_id=?",(image_id,)).fetchone()[0])

 def test_source_filter_excludes_service_folders_and_non_selected_types(self):
  (self.src/"png").mkdir();(self.src/"png"/"bad.png").write_bytes(b"bad")
  (self.src/"_Points").mkdir();(self.src/"_Points"/"v.1.png").write_bytes(b"ref")
  (self.src/"s"/"a.nef").write_bytes(b"raw")
  p=Project.create("filtered",self.src,self.tmp,self.schema,source_types=["nef"])
  self.assertEqual(p.count("images"),2)
  included,excluded=p.catalog_candidates(["nef"])
  self.assertEqual([x["path"] for x in included],["s/a.jpg","s/a.nef"])
  self.assertTrue(any(x["path"]=="_Points/v.1.png" for x in excluded))

if __name__=="__main__":unittest.main()




