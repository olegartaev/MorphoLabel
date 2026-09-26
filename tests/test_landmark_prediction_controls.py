import unittest
from unittest.mock import patch
from app.editor_ready_v15 import ReadyEditorV15

class W:
 all=[]
 def __init__(self,parent=None,**kw): self.parent=parent;self.kw=kw;self.manager='';W.all.append(self)
 def pack(self,*a,**k): self.manager='pack'
 def grid(self,*a,**k): self.manager='grid'
 def grid_remove(self): self.manager=''
 def pack_forget(self): self.manager=''
 def bind(self,*a,**k): pass
 def configure(self,*a,**k): pass
 config=configure
 def columnconfigure(self,*a,**k): pass
 def rowconfigure(self,*a,**k): pass
 def set(self,*a,**k): pass
 def yview(self,*a,**k): pass
 def yview_scroll(self,*a,**k): pass
 def create_window(self,*a,**k): return 1
 def itemconfigure(self,*a,**k): pass
 def bbox(self,*a,**k): return (0,0,1,1)
 def winfo_children(self): return []
class P:
 def catalog_rows(self): return []
class T(unittest.TestCase):
 def test_visible_prediction_buttons_in_landmark_ai(self):
  e=object.__new__(ReadyEditorV15);e.landmark_pane=W();e.crop_train_status=type("S",(),{"master":W()})();e.project=P();e.continue_landmark_ai=lambda:None;e.show_review_landmark_sets=lambda:None;e.manage_control_set=lambda:None;e._show_landmark_ai_more=lambda:None;e.new_improvement_batch=lambda:None;e.start_landmark_training=lambda:None;e.start_ai_predict_batch=lambda *a:None;e.start_ai_predict_all_remaining=lambda:None;e.missing=e.remove=e.clear_all=e.check_landmarks=e.previous_review_warning=e.next_review_warning=e.start_review_swap=e.undo_review_swap=e.apply_suggested_reassignment=e.accept_review_warning=e.finish_review=e.toggle_review=e.correct_normalization=e.toggle_source=e.exclude_or_restore=e.start_auto_crop_remaining=e.start_crop_qc_review=e.train_crop_model=e._show_crop_ai_more=e.start_crop_training_batch=e.start_rerun_unreviewed_crops=e.previous_ai_batch=e.next_ai_batch=lambda:None;e.refresh_measurements_status=lambda:None;e._refresh_landmark_ai_panel=lambda:None;e._set_review_controls=lambda:None;e.refresh_crop_training_status=lambda:None;e._load_last_ai_batch=lambda:None
  W.all=[]
  with patch('app.editor_ready_v15.ttk.Frame',W),patch('app.editor_ready_v15.ttk.LabelFrame',W),patch('app.editor_ready_v15.ttk.Button',W),patch('app.editor_ready_v15.ttk.Label',W),patch('app.editor_ready_v15.ttk.Scrollbar',W),patch('app.editor_ready_v15.tk.Canvas',W): ReadyEditorV15._build_compact_controls(e)
  buttons=[w for w in W.all if w.kw.get('text') in ('Predict Batch...','Predict All Remaining')]
  self.assertEqual(2,len(buttons));self.assertTrue(all(w.manager=='grid' and callable(w.kw['command']) and w.parent is e.landmark_ai_context for w in buttons))
if __name__=='__main__': unittest.main()