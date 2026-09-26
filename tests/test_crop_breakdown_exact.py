import unittest
class T(unittest.TestCase):
 def test_partition_example(self):
  counts={'ADDED_TO_TRAINING':16,'ALREADY_SEEN':12,'HOLDOUT':3,'INVALID_CACHE':0,'INVALID_CROP':0,'DUPLICATE':0,'OTHER':0};self.assertEqual(sum(counts.values()),31)
