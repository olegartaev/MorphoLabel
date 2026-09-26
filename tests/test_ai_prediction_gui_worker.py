import threading,time,unittest
from pathlib import Path
from unittest.mock import patch
from app.editor_ready_v15 import ReadyEditorV15
class W:
 def __init__(self):self.text=[];self.states=[]
 def config(self,**k):self.text.append((threading.current_thread().name,k))
 def winfo_exists(self):return True
class P:
 def active_model_readonly(self,k):return {'model_id':'m'}
 def set_ui_state(self,*a):pass
class E:
 def __init__(self):self.project=P();self._ai_batch_worker=False;self.ai_predict_button=W();self.ai_batch_status=W();self.review_status=W();self.q=[];self._ai_batch=None
 def current(self):return {'image_id':'start'}
 def _show_nonmodal_progress(self,*a):self.progress=W();self.label=W();return self.progress,self.label
 def _close_nonmodal_progress(self,*a):pass
 def after(self,*a):self.q.append(a[-1])
 def _open_ai_batch_item(self,*a):self.finished=True
class T(unittest.TestCase):
 def test_actual_editor_callback_worker_and_progress(self):
  e=E();calls=[];data={'batch_id':'b','prediction_runs':{'a':'r1','b':'r2'},'failures':{},'selected_images':[{'image_id':'a'},{'image_id':'b'}]};path=Path('batch.json')
  def run(project,p,service,progress):
   calls.append('run_batch');progress(1,2,'fish-a.png');progress(2,2,'fish-b.png');return data,path
  with patch('app.editor_ready_v15.active_backend',side_effect=lambda p: (calls.append('active_backend') or ({'model_id':'m'},object()))),patch('app.editor_ready_v15.prospective_candidates',side_effect=lambda *a: (('a','b'),set())),patch('app.editor_ready_v15.preflight_backend'),patch('app.editor_ready_v15.create_batch',side_effect=lambda *a: (calls.append('create_batch') or (data,path))),patch('app.editor_ready_v15.LandmarkAIService',side_effect=lambda *a: calls.append('service') or object()),patch('app.editor_ready_v15.run_batch',side_effect=run),patch('app.editor_ready_v15.set_progress_dialog_progress') as setbar:
   ReadyEditorV15.start_ai_predict_batch(e,2)
   for _ in range(100):
    while e.q:e.q.pop(0)()
    if getattr(e,'finished',False):break
    time.sleep(.01)
  self.assertEqual(['active_backend','create_batch','service','run_batch'],calls);self.assertTrue(e.finished);self.assertTrue(setbar.call_args_list[-1].args[2]==2);self.assertIn('2 / 2',e.label.text[-1][1]['text']);self.assertIn('fish-b.png',e.label.text[-1][1]['text']);self.assertTrue(all(n=='MainThread' for n,_ in e.label.text))
if __name__=='__main__':unittest.main()