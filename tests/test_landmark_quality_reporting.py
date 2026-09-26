import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.editor_ready_v15 import format_landmark_quality_summary, format_landmark_quality_table
from app.landmark_qc import stored_control_landmark_quality_profile


PROFILE={'model_id':'v2','weak_landmark_ids':[23,18,25],'weak_landmarks':[{'landmark_id':23,'p90_error_percent':2.8,'median_error_percent':.9},{'landmark_id':18,'p90_error_percent':2.3,'median_error_percent':.75},{'landmark_id':25,'p90_error_percent':2.1,'median_error_percent':.7}], 'per_landmark':{'18':{'landmark_id':18,'p90_error_percent':2.3,'median_error_percent':.75},'23':{'landmark_id':23,'p90_error_percent':2.8,'median_error_percent':.9},'25':{'landmark_id':25,'p90_error_percent':2.1,'median_error_percent':.7},'1':{'landmark_id':1,'p90_error_percent':.5,'median_error_percent':.2}}}


class LandmarkQualityReportingTests(unittest.TestCase):
 def test_training_complete_shows_top_weak_and_persistent_landmarks(self):
  text=format_landmark_quality_summary(PROFILE,[23,25])
  self.assertIn('LM23  P90: 2.80%  Median: 0.90%',text); self.assertIn('LM18  P90: 2.30%  Median: 0.75%',text); self.assertIn('Persistent weak landmarks: LM23, LM25',text); self.assertIn('focus ~30%',text)
 def test_landmark_quality_lists_all_landmarks_sorted_by_p90(self):
  schema=[{'id':1,'abbr':'SnT'},{'id':18,'abbr':'LM18'},{'id':23,'abbr':'LM23'},{'id':25,'abbr':'LM25'}]
  text=format_landmark_quality_table(PROFILE,schema,[23,25]); lines=text.splitlines()
  self.assertEqual('LM | Abbr | P90 | Median | Status',lines[0]); self.assertTrue(lines[1].startswith('LM23 | LM23 | 2.80%')); self.assertTrue(lines[2].startswith('LM18 | LM18 | 2.30%')); self.assertTrue(lines[3].startswith('LM25 | LM25 | 2.10%')); self.assertIn('Persistent weak',lines[1]); self.assertIn('Currently weak',lines[2]); self.assertTrue(lines[4].startswith('LM01 | SnT | 0.50%'))
 def test_opening_report_reads_only_and_never_runs_inference_or_writes(self):
  root=Path(tempfile.mkdtemp()); project=type('P',(),{'data_root':root})(); path=root/'ai'/'qc'/'control'/'v2.json'; path.parent.mkdir(parents=True); path.write_text(json.dumps(PROFILE),encoding='utf8'); before=path.read_bytes()
  try:
   with patch('app.landmark_qc.evaluate_control_set') as evaluate: loaded=stored_control_landmark_quality_profile(project,'v2')
   self.assertEqual(PROFILE,loaded); self.assertEqual(before,path.read_bytes()); evaluate.assert_not_called()
  finally: shutil.rmtree(root,ignore_errors=True)


if __name__=='__main__': unittest.main()