import shutil
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from app.landmark_dataset import create_dataset, v2_human_final_eligible_image_ids
from app.landmark_review import root_v1_eligible_image_ids
from app.project_storage import Project


class V2DatasetSemanticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp())
        source = self.temp / 'source'
        source.mkdir()
        Image.new('RGB', (100, 80)).save(source / 'fish.jpg')
        schema = self.temp / 'schema.csv'
        schema.write_text('id,abbr,name,role\n1,A,One,BOTH\n2,B,Two,BOTH\n', encoding='utf-8')
        self.project = Project.create('p', source, self.temp, schema, source_layout='direct')
        self.image_id = self.project.catalog_rows()[0]['image_id']
        cache = self.project.cache_root / 'standardized' / f'{self.image_id}.png'
        cache.parent.mkdir(parents=True, exist_ok=True)
        Image.new('RGB', (100, 80)).save(cache)

    def tearDown(self):
        shutil.rmtree(self.temp, ignore_errors=True)

    def _machine_complete(self, checked=True):
        for landmark_id, x in ((1, 10), (2, 20)):
            self.project.save_landmark(self.image_id, landmark_id, x, 30, 'auto', provenance='machine', model_id='v1', predicted_x=x, predicted_y=30, confidence=.8, prediction_run_id='run-1')
        if checked:
            self.project.mark_checked(self.image_id)

    def test_v1_rejects_checked_ai_but_v2_accepts_current_final(self):
        self._machine_complete()
        self.assertNotIn(self.image_id, root_v1_eligible_image_ids(self.project))
        self.assertIn(self.image_id, v2_human_final_eligible_image_ids(self.project))

    def test_v2_snapshot_uses_unchanged_checked_ai_final_without_rewriting_history(self):
        self._machine_complete()
        before = self.project.load_landmarks(self.image_id)[1].copy()
        manifest = create_dataset(self.project, dataset_id='v2', splits={'train': [self.image_id]}, eligibility_mode='v2_human_final')
        label = manifest['images'][0]['landmarks'][0]
        self.assertEqual((label['x'], label['y']), (10, 30))
        self.assertEqual(manifest['images'][0]['training_label_origins']['1'], 'human_accepted_unchanged_ai_final')
        after = self.project.load_landmarks(self.image_id)[1]
        self.assertEqual((after['provenance'], after['predicted_x'], after['predicted_y'], after['model_id'], after['confidence'], after['prediction_run_id']), (before['provenance'], before['predicted_x'], before['predicted_y'], before['model_id'], before['confidence'], before['prediction_run_id']))

    def test_v2_snapshot_uses_current_human_corrected_ai_final(self):
        self._machine_complete()
        self.project.save_landmark(self.image_id, 1, 44, 55, 'corrected', provenance='corrected_by_human', model_id='v1', predicted_x=10, predicted_y=30, confidence=.8, prediction_run_id='run-1')
        self.project.mark_checked(self.image_id)
        manifest = create_dataset(self.project, dataset_id='v2corrected', splits={'train': [self.image_id]}, eligibility_mode='v2_human_final')
        first = manifest['images'][0]['landmarks'][0]
        self.assertEqual((first['x'], first['y'], first['provenance']), (44, 55, 'corrected_by_human'))
        self.assertEqual(manifest['images'][0]['training_label_origins']['1'], 'human_corrected_ai_final')

    def test_unchecked_ai_is_rejected_by_v2_mode(self):
        self._machine_complete(checked=False)
        self.assertNotIn(self.image_id, v2_human_final_eligible_image_ids(self.project))
        with self.assertRaises(Exception):
            create_dataset(self.project, dataset_id='unchecked', splits={'train': [self.image_id]}, eligibility_mode='v2_human_final')


if __name__ == '__main__':
    unittest.main()