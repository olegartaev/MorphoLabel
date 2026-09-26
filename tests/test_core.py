import tempfile
import unittest
from pathlib import Path
from app.profile import load_profile
from app.transforms import Transform
from app.io import atomic_json_write, read_json

class CoreTests(unittest.TestCase):
    def test_profile_has_25_and_gm_first_twenty(self):
        profile = load_profile(Path(__file__).resolve().parent / "fixtures" / "phoxinus" / "Phoxinus_lateral_v1.json")
        self.assertEqual(len(profile.landmarks), 25)
        self.assertTrue(all(p.gm_included for p in profile.landmarks[:20]))
        self.assertTrue(all(p.measurement_only for p in profile.landmarks[20:]))
    def test_transform_round_trip(self):
        transform = Transform(4000, 3000, 17.5, 2000, 1500, 120, 80, 3600, 2600)
        original = (1234.5, 987.25)
        standardized = transform.original_to_standardized(*original)
        result = transform.standardized_to_original(*standardized)
        self.assertAlmostEqual(original[0], result[0], places=9)
        self.assertAlmostEqual(original[1], result[1], places=9)
    def test_atomic_record_preserves_missing(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "record.json"
            atomic_json_write(path, {"points":{"1":{"state":"missing","x_standardized":None,"y_standardized":None}}})
            data = read_json(path, {})
            self.assertEqual(data["points"]["1"]["state"], "missing")
            self.assertIsNone(data["points"]["1"]["x_standardized"])

if __name__ == "__main__": unittest.main()
