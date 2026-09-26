import unittest
from pathlib import Path
from app.paths import ROOT, ORIGINALS, require_relative
from app.workflow import stable_image_id

class PortabilityTests(unittest.TestCase):
    def test_root_is_discovered_from_code_location(self):
        self.assertEqual(ROOT.name,"MorphoLabel")
        self.assertEqual(require_relative(ORIGINALS),"orig_photos")
    def test_ids_depend_on_relative_not_drive_path(self):
        rel="orig_photos/sample/image.nef"
        self.assertEqual(stable_image_id(rel),stable_image_id(rel))
        self.assertNotIn(":",stable_image_id(rel))

if __name__ == "__main__": unittest.main()
