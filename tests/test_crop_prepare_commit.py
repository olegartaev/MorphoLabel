import unittest
from app.normalization_pipeline import prepare_crop_result,commit_crop_result
class T(unittest.TestCase):
 def test_commit_requires_explicit_project(self):
  with self.assertRaises(ValueError):commit_crop_result(None,{})
 def test_prepare_api_has_no_project_commit(self):
  self.assertNotIn("save_crop",prepare_crop_result.__code__.co_names)
