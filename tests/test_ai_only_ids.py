import unittest
from unittest.mock import patch
from app.editor_ready_v15 import ReadyEditorV15
class P:
 def catalog_rows(self): return [{'image_id':'machine','excluded':False},{'image_id':'verified','excluded':False},{'image_id':'corrected','excluded':False},{'image_id':'manual','excluded':False},{'image_id':'excluded','excluded':True},{'image_id':'other','excluded':False}]
 def annotation_status(self,i): return {'verified':i=='verified'}
 def load_landmarks(self,i): return {'1':{'provenance':'machine'}} if i in ('machine','other','verified','excluded') else {'1':{'provenance':'corrected_by_human' if i=='corrected' else 'manual'}}
 def active_model_readonly(self,k): return {'model_id':'m'}
class T(unittest.TestCase):
 def test_exact_ai_only_ids(self):
  e=object.__new__(ReadyEditorV15);e.project=P();seen=[];e.start_ai_predict_batch=lambda **k:seen.append(k)
  with patch('app.editor_ready_v15.messagebox.askyesno',return_value=True):ReadyEditorV15.start_ai_repredict_machine_only(e)
  self.assertEqual(['machine','other'],seen[0]['image_ids'])
if __name__=='__main__':unittest.main()