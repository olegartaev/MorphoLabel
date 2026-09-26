import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.landmark_qc import control_landmark_quality_profile, stable_weak_landmark_profile
from app.smart_selection import select_improvement_ranked, select_improvement_weak_aware


def ranked(count=20):
 return [{'image_id':f'{index:016x}','median_confidence':.2+index*.01,'predictions':[{'landmark_id':18,'confidence':.01+index*.01},{'landmark_id':1,'confidence':.8}], 'descriptor':((float(index),0.0),(0.0,1.0)),'locality':str(index%5)} for index in range(count)]
def profile(model_id, weak_id):
 values={str(index):{'landmark_id':index,'median_error_percent':1,'p90_error_percent':1} for index in range(1,5)}
 values[str(weak_id)]={'landmark_id':weak_id,'median_error_percent':9,'p90_error_percent':9}
 return {'model_id':model_id,'control_image_ids':(),'per_landmark':values}


class WeakLandmarkSelectionTests(unittest.TestCase):
 def setUp(self): self.root=Path(tempfile.mkdtemp()); self.project=type('P',(),{'data_root':self.root})()
 def tearDown(self): shutil.rmtree(self.root,ignore_errors=True)
 def add_profile(self, value):
  with patch('app.landmark_qc.evaluate_control_set',return_value=value): return control_landmark_quality_profile(self.project,value['model_id'],recalculate=True)
 def test_one_model_profile_keeps_one_hundred_percent_existing_general_selection(self):
  self.add_profile(profile('v1',18)); self.assertIsNone(stable_weak_landmark_profile(self.project,'v1'))
  with patch('app.smart_selection._human_descriptors',return_value=()):
   self.assertEqual(select_improvement_ranked(None,ranked(),17,10),select_improvement_ranked(None,ranked(),17,10))
 def test_same_weak_landmark_in_two_profiles_is_eligible_for_thirty_percent_focus(self):
  self.add_profile(profile('v1',18)); self.add_profile(profile('v2',18)); stable=stable_weak_landmark_profile(self.project,'v2')
  self.assertEqual((18,),stable['weak_landmark_ids'])
  with patch('app.smart_selection._human_descriptors',return_value=()): selected,focused,general=select_improvement_weak_aware(None,ranked(),17,10,stable['weak_landmark_ids'])
  self.assertEqual((focused,general),(3,7)); self.assertEqual(10,len(selected))
 def test_unstable_weak_landmarks_receive_no_focus(self):
  self.add_profile(profile('v1',18)); self.add_profile(profile('v2',23)); self.assertIsNone(stable_weak_landmark_profile(self.project,'v2'))
 def test_batch_is_approximately_thirty_seventy_and_preserves_diversity_and_exclusions(self):
  allowed=[item for item in ranked() if item['image_id'] not in {'0000000000000000','0000000000000001'}]
  with patch('app.smart_selection._human_descriptors',return_value=()): selected,focused,general=select_improvement_weak_aware(None,allowed,17,10,[18])
  self.assertEqual((focused,general),(3,7)); self.assertEqual(10,len({item['image_id'] for item in selected})); self.assertTrue(all(item['image_id'] not in {'0000000000000000','0000000000000001'} for item in selected)); self.assertTrue(all(sum(item['locality']==locality for item in selected)<=2 for locality in {item['locality'] for item in selected}))


if __name__=='__main__': unittest.main()