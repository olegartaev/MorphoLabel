import unittest
from app.developed_cache import cached_meta,ensure
class DevelopedCacheTests(unittest.TestCase):
 def test_cache_api_exists(self):self.assertTrue(callable(cached_meta));self.assertTrue(callable(ensure))
if __name__=="__main__":unittest.main()
