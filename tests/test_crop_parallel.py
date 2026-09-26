import threading,time,unittest
from app.crop_parallel import bounded_map
class T(unittest.TestCase):
 def test_jobs_overlap_and_results_serialize(self):
  running=[];lock=threading.Lock();peak=[0]
  def work(x):
   with lock:running.append(x);peak[0]=max(peak[0],len(running))
   time.sleep(.03)
   with lock:running.remove(x)
   return x
  got=[r for _,r,e in bounded_map(range(6),work,config={'workers':3,'max_in_flight':3}) if not e]
  self.assertEqual(sorted(got), list(range(6)));self.assertGreaterEqual(peak[0],2)
 def test_cancel_stops_new_submission(self):
  stop=threading.Event();seen=[]
  def work(x):seen.append(x);stop.set();return x
  list(bounded_map(range(10),work,cancel=stop,config={'workers':1,'max_in_flight':1}));self.assertEqual(seen,[0])

