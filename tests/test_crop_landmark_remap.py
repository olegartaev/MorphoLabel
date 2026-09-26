import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from app.project_storage import Project
from app.transforms import Transform
from app.crop_workflow import apply_reviewed_crop, reviewed_crop_change


class CropLandmarkRemapTests(unittest.TestCase):
 def setUp(self):
  self.tmp=Path(tempfile.mkdtemp());self.source=self.tmp/'source';self.source.mkdir();Image.new('RGB',(100,100),'white').save(self.source/'fish.jpg')
  schema=self.tmp/'schema.csv';schema.write_text('id,abbr,name,role\n1,A,Alpha,BOTH\n2,B,Beta,BOTH\n3,C,Gamma,BOTH\n',encoding='utf-8')
  self.project=Project.create('p',self.source,self.tmp,schema,source_layout='direct');self.image_id=self.project.catalog_rows()[0]['image_id']
  self.old=Transform(100,100,0,50,50,0,0,100,100);self.project.save_crop(self.image_id,{'crop_bounds':[0,0,100,100],'rotation_degrees':0,'transform':self.old.__dict__})
 def tearDown(self):shutil.rmtree(self.tmp,ignore_errors=True)
 def put(self,ident,x,y,**extra):self.project.save_landmark(self.image_id,ident,x,y,extra.pop('state','manual'),**extra)
 def remap(self,new):return self.project.remap_landmarks_for_transform(self.image_id,self.old,new)
 def test_translation_keeps_original_position_and_v9_no_longer_blocks_open(self):
  self.put(1,30,40,provenance='manual');new=Transform(100,100,0,50,50,10,5,80,90);self.remap(new);row=self.project.load_landmarks(self.image_id)[1]
  self.assertEqual((20,35),(row['x_standardized'],row['y_standardized']));self.assertEqual((30,40),new.standardized_to_original(row['x_standardized'],row['y_standardized']))
  from app.editor_ready_v9 import ReadyEditorV9
  editor=ReadyEditorV9.__new__(ReadyEditorV9);editor.record={'points':{'P1':{}}};editor.current=lambda:{'source_path':str(self.source/'fish.jpg'),'source_relpath':'fish.jpg','image_id':self.image_id};editor.post_crop_apply_refresh=lambda:None
  with patch('app.editor_ready_v9.active_project',return_value=self.project),patch('app.editor_ready_v9.AsyncCropEditorV2') as opened:editor.correct_normalization()
  opened.assert_called_once()
 def test_rotation_keeps_original_position(self):
  self.put(1,20,30,provenance='manual');new=Transform(100,100,23,50,50,0,0,100,100);self.remap(new);row=self.project.load_landmarks(self.image_id)[1]
  x,y=new.standardized_to_original(row['x_standardized'],row['y_standardized']);self.assertAlmostEqual(x,20,places=7);self.assertAlmostEqual(y,30,places=7)
 def test_outside_point_becomes_unresolved_only(self):
  self.put(1,20,20,provenance='manual');self.put(2,90,90,provenance='manual');new=Transform(100,100,0,50,50,10,10,50,50);result=self.remap(new);rows=self.project.load_landmarks(self.image_id)
  self.assertEqual(1,result['outside_count']);self.assertEqual((10,10),(rows[1]['x_standardized'],rows[1]['y_standardized']));self.assertEqual('unresolved',rows[2]['state']);self.assertIsNone(rows[2]['x_standardized'])
 def test_explicit_missing_remains_missing(self):
  self.put(1,None,None,state='missing',provenance='manual');self.remap(Transform(100,100,0,50,50,10,10,80,80));row=self.project.load_landmarks(self.image_id)[1]
  self.assertEqual('missing',row['state']);self.assertIsNone(row['x_standardized'])
 def test_checked_is_cleared(self):
  for ident in (1,2,3):self.put(ident,10*ident,10*ident,provenance='manual')
  self.project.mark_checked(self.image_id);self.assertTrue(self.project.annotation_status(self.image_id)['verified']);self.remap(Transform(100,100,0,50,50,1,1,99,99));self.assertFalse(self.project.annotation_status(self.image_id)['verified'])
 def test_no_landmark_remap_is_safe(self):
  result=self.project.remap_landmarks_for_transform(self.image_id,None,Transform(100,100,0,50,50,10,10,80,80));self.assertEqual((0,0,0),(result['present_before'],result['present_after'],result['outside_count']))
 def test_recrop_preflight_detects_existing_landmark_frame_change(self):
  self.put(1,30,40,provenance='manual')
  standard=self.project.cache_root/'standardized'/f'{self.image_id}.png'
  same=reviewed_crop_change(self.project,self.image_id,Image.new('RGB',(100,100),'white'),(0,0,100,100),0,standard)
  changed=reviewed_crop_change(self.project,self.image_id,Image.new('RGB',(100,100),'white'),(10,5,90,95),0,standard)
  self.assertTrue(same['had_landmarks']);self.assertFalse(same['frame_changed'])
  self.assertTrue(changed['had_landmarks']);self.assertTrue(changed['frame_changed']);self.assertIsNotNone(changed['old_transform'])

 def test_apply_unchanged_crop_does_not_uncheck_or_remap_landmarks(self):
  standard=self.project.cache_root/'standardized'/f'{self.image_id}.png';standard.parent.mkdir(parents=True,exist_ok=True);Image.new('RGB',(100,100),'white').save(standard)
  for ident in (1,2,3):self.put(ident,10*ident,10*ident,provenance='manual')
  self.project.mark_checked(self.image_id);before=self.project.load_landmarks(self.image_id)
  result=apply_reviewed_crop(self.project,self.image_id,Image.new('RGB',(100,100),'white'),(0,0,100,100),0,standard,self.source/'fish.jpg')
  self.assertFalse(result['landmarks_remapped']);self.assertTrue(self.project.annotation_status(self.image_id)['verified']);self.assertEqual(before,self.project.load_landmarks(self.image_id))

 def test_reviewed_recrop_reprojects_existing_landmarks_and_requires_review(self):
  standard=self.project.cache_root/'standardized'/f'{self.image_id}.png';standard.parent.mkdir(parents=True,exist_ok=True);Image.new('RGB',(100,100),'white').save(standard)
  self.put(1,30,40,provenance='manual');self.put(2,60,70,provenance='manual');self.put(3,50,50,provenance='manual');self.project.mark_checked(self.image_id)
  base=Image.new('RGB',(100,100),'white')
  result=apply_reviewed_crop(self.project,self.image_id,base,(10,5,90,95),0,standard,self.source/'fish.jpg')
  row=self.project.load_landmarks(self.image_id)[1];new=Transform(**self.project.crop_record(self.image_id)['transform_json'])
  self.assertTrue(result['landmarks_remapped']);self.assertTrue(result['review_required']);self.assertFalse(self.project.annotation_status(self.image_id)['verified'])
  self.assertEqual((20,35),(row['x_standardized'],row['y_standardized']))
  original=new.standardized_to_original(row['x_standardized'],row['y_standardized'])
  self.assertAlmostEqual(30,original[0]);self.assertAlmostEqual(40,original[1])

 def test_ai_metadata_and_prediction_coordinates_are_preserved(self):
  self.put(1,30,40,state='auto',provenance='machine',model_id='m1',predicted_x=20,predicted_y=30,confidence=.7,prediction_run_id='run1');new=Transform(100,100,0,50,50,10,5,80,90);self.remap(new);row=self.project.load_landmarks(self.image_id)[1]
  self.assertEqual(('m1',.7,'run1'),(row['model_id'],row['confidence'],row['prediction_run_id']));self.assertEqual((10,25),(row['predicted_x'],row['predicted_y']));self.assertEqual((20,35),(row['x_standardized'],row['y_standardized']))
  with self.project.transaction() as c:self.assertEqual('landmark_transform_remap',c.execute('SELECT kind FROM corrections WHERE image_id=? ORDER BY correction_id DESC LIMIT 1',(self.image_id,)).fetchone()[0])

if __name__=='__main__':unittest.main()