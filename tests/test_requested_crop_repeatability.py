import math
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from app.crop_training import circular_error_degrees, predict, train_project
from app.human_baseline import available_control_image_ids, start_or_continue_run, pass_session_ids
from app.project_storage import Project


class RequestedCropAndRepeatabilityTests(unittest.TestCase):
 def setUp(self):
  self.root=Path(tempfile.mkdtemp());self.source=self.root/'source';self.source.mkdir();self.schema=self.root/'schema.csv';self.schema.write_text('id,abbr,name,role\n1,A,A,BOTH\n',encoding='utf8')
  for index in range(30):Image.new('RGB',(64,48),(index,30,80)).save(self.source/f'{index}.jpg')
  self.project=Project.create('p',self.source,self.root,self.schema,source_types=['jpg'])
  for index,row in enumerate(self.project.catalog_rows()):
   image_id=row['image_id'];developed=self.project.cache_root/'developed'/f'{image_id}.png';Image.open(self.project.image_path(image_id)).save(developed)
   self.project.save_reviewed_crop(image_id,{'developed_full_relpath':f'cache/developed/{image_id}.png','standardized_relpath':f'cache/standardized/{image_id}.png','crop_bounds':[4,4,58,44],'rotation_degrees':30.0,'transform':{'original_width':64,'original_height':48,'rotation_degrees':30.0,'center_x':32,'center_y':24,'crop_left':4,'crop_top':4,'output_width':54,'output_height':40}})
 def tearDown(self):
  import shutil;shutil.rmtree(self.root,ignore_errors=True)
 def test_second_crop_model_uses_all_current_eligible_examples_and_has_rotation_schema(self):
  # v001 sees the first 20; exclusion/pending status remain outside the canonical query.
  ids=[row['image_id'] for row in self.project.catalog_rows()];self.project.exclude_image(ids[20],'User excluded')
  expected=len(self.project.crop_training_rows());result=train_project(self.project);self.assertEqual(expected,result['training_examples'])
  manifest=__import__('json').loads((self.project.models_root/result['model_id']/'model_manifest.json').read_text())
  self.assertEqual(['x1','y1','x2','y2','sin_rotation','cos_rotation'],manifest['output_schema']['fields'])
  with self.project.transaction() as c:membership=c.execute('SELECT COUNT(*) FROM crop_training_membership WHERE model_id=?',(result['model_id'],)).fetchone()[0]
  self.assertEqual(expected,membership)
  self.assertIn('rotation_mae_degrees',result['metrics'])
 def test_four_output_model_is_neutral_and_six_output_model_decodes_angle(self):
  path=self.project.models_root/'old';path.mkdir();np.savez_compressed(path/'model.npz',weights=np.zeros((769,4)))
  self.project.register_model('old','crop',path='models/old',metrics={},active=True)
  output,_=predict(Image.new('RGB',(64,48)),project=self.project);self.assertEqual(0.0,output['rotation_degrees'])
  path=self.project.models_root/'new';path.mkdir();weights=np.zeros((769,6));weights[0]=[.1,.1,.9,.9,math.sin(math.radians(-45)),math.cos(math.radians(-45))];np.savez_compressed(path/'model.npz',weights=weights)
  self.project.register_model('new','crop',path='models/new',metrics={},active=True)
  output,_=predict(Image.new('RGB',(64,48)),project=self.project);self.assertAlmostEqual(-45.0,output['rotation_degrees'],places=4);self.assertEqual(0.0,circular_error_degrees(179,-181))
 def test_repeatability_new_run_uses_selected_count_and_exact_pass_membership(self):
  ids=[row['image_id'] for row in self.project.catalog_rows()]
  for image_id in ids:
   Image.new('RGB',(20,20)).save(self.project.cache_root/'standardized'/f'{image_id}.png')
   self.project.save_landmark(image_id,1,5,5,'manual','manual')
  from unittest.mock import patch
  with patch('app.landmark_ai_workflow.control_set_summary',return_value={'current_ids':ids}),patch('app.operator_qc.operator_eligible_image_ids',return_value=tuple(ids)):
   self.assertEqual(30,len(available_control_image_ids(self.project)));run,created=start_or_continue_run(self.project,count=6)
  self.assertTrue(created);self.assertEqual(6,run['requested_count']);self.assertEqual(6,run['actual_count']);self.assertEqual(6,len(run['image_ids']));self.assertEqual(tuple(run['image_ids']),tuple(run['image_ids']))

if __name__=='__main__':unittest.main()
