import unittest
from pathlib import Path
from app.paths import ORIGINALS
from app.standardize import provisional_standardize
from app.workflow import assert_no_split_leakage, make_sample_split, select_seed_queue

class IntegrationTests(unittest.TestCase):
    def test_real_source_can_be_decoded_to_review_master(self):
        source = next(ORIGINALS.rglob("*.nef"))
        before = source.stat().st_mtime_ns
        result = provisional_standardize(source)
        self.assertEqual(result["normalization_status"], "REVIEW")
        self.assertFalse(result["mirrored"])
        self.assertTrue(Path(result["standardized_relpath"]).exists())
        self.assertEqual(before, source.stat().st_mtime_ns)
    def test_seed_queue_and_split(self):
        queue = select_seed_queue(target=100, seed=17)
        split = make_sample_split(seed=17)
        self.assertEqual(len(queue["images"]), 100)
        self.assertLessEqual(max(sum(item["sample_id"] == s for item in queue["images"]) for s in {x["sample_id"] for x in queue["images"]}), 7)
        assert_no_split_leakage(split)

if __name__ == "__main__": unittest.main()
