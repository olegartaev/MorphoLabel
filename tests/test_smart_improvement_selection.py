import unittest
from unittest.mock import patch
from app.smart_selection import select_improvement_ranked
from app.landmark_ai_workflow import begin_improvement

class SmartImprovementSelectionTests(unittest.TestCase):
 def test_requested_count_is_uncertain_diverse_and_deterministic(self):
  ranked=[{'image_id':f'{i:016x}','median_confidence':.1+i*.01,'descriptor':((float(i),0.0),(0.0,1.0)),'locality':str(i%3)} for i in range(20)]
  with patch('app.smart_selection._human_descriptors',return_value=()):
   first=select_improvement_ranked(None,ranked,17,10);second=select_improvement_ranked(None,ranked,17,10)
  self.assertEqual(10,len(first));self.assertEqual([x['image_id'] for x in first],[x['image_id'] for x in second])
 def test_bad_selected_ids_leave_state_unchanged(self):
  state={'stage':'READY_FOR_FULL_PREDICTION','seed':1,'control_image_ids':['c'],'initial_image_ids':['i'],'improvement_image_ids':[],'improvement_history_ids':[],'improvement_target':5}
  class P:
   def catalog_rows(self):return [{'image_id':x,'excluded':False} for x in ('c','i','a','b','d','e','f')]
  with patch('app.landmark_ai_workflow.refresh_stage',return_value=dict(state)):
   with self.assertRaises(ValueError):begin_improvement(P(),target=5,selected_ids=['c']*5)
  self.assertEqual([],state['improvement_image_ids'])
if __name__=='__main__':unittest.main()