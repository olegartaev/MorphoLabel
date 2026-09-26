import tempfile
import unittest
from pathlib import Path
import app.dataset_v2 as dataset
from app.io import atomic_json_write

class StrictExportFilterTests(unittest.TestCase):
    def test_partial_record_is_excluded(self):
        original=dataset.WORK
        try:
            with tempfile.TemporaryDirectory() as folder:
                dataset.WORK=Path(folder)
                path=dataset.WORK/"sample"/"landmarks"/"image.json"
                atomic_json_write(path,{"profile_id":"Phoxinus_lateral_v1","image_id":"image","sample_id":"sample","source_relpath":"orig_photos/sample/a.nef","points":{"1":{"state":"manual"}}})
                result=dataset.export_training_dataset("Phoxinus_lateral_v1")
                self.assertEqual(result["images"],[]); self.assertEqual(len(result["excluded"]),1)
        finally: dataset.WORK=original

if __name__ == "__main__": unittest.main()
