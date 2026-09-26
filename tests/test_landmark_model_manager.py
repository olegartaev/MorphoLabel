import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app.editor_ready_v15 import ReadyEditorV15

class W:
 def __init__(self,*a,**k): self.children=[]
 def title(self,*a): pass
 def transient(self,*a): pass
 def resizable(self,*a): pass
 def pack(self,*a,**k): pass
 def grid(self,*a,**k): pass
 def rowconfigure(self,*a,**k): pass
 def columnconfigure(self,*a,**k): pass
 def configure(self,*a,**k): pass
 def yview(self,*a,**k): pass
 def set(self,*a,**k): pass
 def bind(self,*a,**k): pass
 def config(self,*a,**k): pass
 def destroy(self): pass
class Table(W):
 last=None
 def __init__(self,*a,**k): super().__init__();self.rows=[];Table.last=self
 def heading(self,*a,**k): pass
 def column(self,*a,**k): pass
 def insert(self,*a,**k): self.rows.append(k['values']);return str(len(self.rows))
 def get_children(self): return ()
 def delete(self,*a): pass
 def focus(self): return ''
 def item(self,*a): return {'values':()}
class P:
 def __init__(self,root,schema): self.data_root=root;self.schema_path=schema
 def active_model_readonly(self,k): return {'model_id':'rtmpose_v027'}
 def model_metadata(self,mid): return {'schema_sha256': __import__('app.project_storage',fromlist=['schema_hash']).schema_hash(self.schema_path), 'dataset_manifest_path':'manifest.json'}
class E:
 def __init__(self,p): self.project=p
 def _refresh_landmark_ai_panel(self): pass
 def _set_landmark_workflow_controls(self): pass
class TestManager(unittest.TestCase):
 def test_enumerates_mixed_metadata(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);schema=root/'schema.json';schema.write_text('{}');models=root/'ai/models';models.mkdir(parents=True)
   (models/'rtmpose_v027').mkdir();(root/'manifest.json').write_text(json.dumps({'images':[{'split':'train'},{'split':'validation'},{'split':'train'}]}))
   (models/'rtmpose_v027'/'model.json').write_text(json.dumps({'model_id':'rtmpose_v027','training_settings':{'batch_size':8,'max_epochs':210},'result':{'best_epoch':60,'engineering_validation':{'p90_error_percent':0.39}},'input_size':[640,320]}))
   (models/'rtmpose_v028').mkdir();(models/'rtmpose_v028'/'model.json').write_text(json.dumps({'model_id':'rtmpose_v028'}))
   (models/'rtmpose_v029').mkdir()
   e=E(P(root,schema))
   with patch('app.editor_ready_v15.tk.Toplevel',W),patch('app.editor_ready_v15.ttk.Frame',W),patch('app.editor_ready_v15.ttk.Treeview',Table),patch('app.editor_ready_v15.ttk.Scrollbar',W),patch('app.editor_ready_v15.ttk.Label',W),patch('app.editor_ready_v15.ttk.Button',W),patch('app.editor_ready_v15.center_child_window',lambda x:x): ReadyEditorV15.show_landmark_models(e)
   self.assertEqual(3,len(Table.last.rows));active=next(r for r in Table.last.rows if r[0]=='rtmpose_v027');self.assertEqual('Active',active[1]);self.assertEqual('8',active[5]);self.assertEqual('210',active[6]);self.assertEqual('60',active[8]);self.assertEqual('640 x 320',active[3]);self.assertEqual('Compatible',active[-1]);self.assertEqual('3',active[4]);self.assertIn('rtmpose_v029',[r[0] for r in Table.last.rows])
if __name__=='__main__': unittest.main()