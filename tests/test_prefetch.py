import unittest
from pathlib import Path
from app.prefetch import PrefetchManager

class PrefetchTests(unittest.TestCase):
 def test_queue_deduplicates_and_user_claim_wins(self):
  manager=PrefetchManager.__new__(PrefetchManager);manager._cv=__import__('threading').Condition();manager._heap=[];manager._pending={};manager._seq=0;manager._stop=False
  a=Path("orig_photos/a/image_a.nef");b=Path("orig_photos/b/image_b.nef")
  manager.schedule([a,b,a]);self.assertEqual(len(manager._heap),2);manager.claim_user(b);manager.schedule([b]);self.assertEqual(manager._pending[__import__('app.standardize',fromlist=['image_id']).image_id(b)],"user")
 def test_prefetch_manager_has_single_worker_entrypoint(self):
  self.assertEqual(PrefetchManager._run.__name__,"_run")

if __name__=="__main__":unittest.main()
