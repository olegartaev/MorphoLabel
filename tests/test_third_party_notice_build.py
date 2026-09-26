import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

class ThirdPartyNoticeBuildTests(unittest.TestCase):
    def test_distribution_build_generates_and_bundles_notices(self):
        workflow=(ROOT/".github"/"workflows"/"windows-release.yml").read_text(encoding="utf-8")
        spec=(ROOT/"packaging"/"morpholabel.spec").read_text(encoding="utf-8")
        generator=(ROOT/"tools"/"build_third_party_notices.py").read_text(encoding="utf-8")
        self.assertIn("build_third_party_notices.py build/third_party",workflow)
        self.assertIn("THIRD_PARTY_NOTICES.txt",spec)
        self.assertIn('DISTRIBUTIONS = ("Pillow", "numpy", "opencv-python", "rawpy")',generator)
        self.assertIn("Python redistribution license file was not found",generator)

if __name__=="__main__":
    unittest.main()
