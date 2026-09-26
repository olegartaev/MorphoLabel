import queue, threading, unittest
from pathlib import Path
from unittest.mock import patch
from app.editor_ready_v13 import ReadyEditorV13


class PrepareRaceTests(unittest.TestCase):
 def test_second_selection_waits_for_same_image_preparation(self):
  source=Path("orig_photos/ob-altay_Katun_Nizh-Ujmon_RU_25/img_008662.nef")
  row={"source_relpath":str(source),"sample_id":source.parent.name}
  started=threading.Event();release=threading.Event();ready={"value":False}
  def status(_):
   return {"ready":ready["value"],"png_exists":True,"source_hash_match":True,"settings_hash_match":True,"standardized_exists":True,"png_integrity":True,"standardized_integrity":True,"reason":"ready" if ready["value"] else "standardized_png_missing","png_path":"work/x.png","standardized_path":"work/y.png"}
  def normalize(*_,**__): started.set();release.wait(3);ready["value"]=True
  a=ReadyEditorV13.__new__(ReadyEditorV13);b=ReadyEditorV13.__new__(ReadyEditorV13);a._pending=queue.Queue();b._pending=queue.Queue()
  with patch("app.editor_ready_v13.navigation_cache_status",side_effect=status),patch("app.editor_ready_v13.normalize",side_effect=normalize),patch("app.editor_ready_v13.ensure"):
   first=threading.Thread(target=a._load_selected_v12,args=(1,row,source,0));second=threading.Thread(target=b._load_selected_v12,args=(2,row,source,0));first.start();self.assertTrue(started.wait(2));second.start();release.set();first.join(5);second.join(5)
  self.assertEqual(a._pending.get_nowait()[1],"ok");self.assertEqual(b._pending.get_nowait()[1],"ok")


if __name__=="__main__":unittest.main()
