import hashlib
import shutil
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from app.landmark_dataset import create_dataset
from app.rtmpose_dataset import generate_smoke_config
from app.project_storage import Project


class V2TrainingContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.temp, ignore_errors=True)

    def test_parent_checkpoint_is_full_config_load_from(self):
        manifest = self.temp / 'manifest.json'
        manifest.write_text('{"format_version":1,"dataset_id":"d","schema_sha256":"test","schema_landmarks":[{"landmark_id":1,"abbr":"A"}],"images":[]}', encoding='utf-8')
        base = self.temp / 'base.py'; base.write_text('', encoding='utf-8')
        ap = self.temp / 'ap.pth'; ap.write_bytes(b'ap')
        parent = self.temp / 'parent.pth'; parent.write_bytes(b'parent')
        config = generate_smoke_config(manifest, data_root=self.temp, train_coco=self.temp/'train.json', val_coco=self.temp/'val.json', output_path=self.temp/'config.py', base_config=base, base_checkpoint=ap, parent_checkpoint=parent, batch_size=1, max_epochs=2)
        self.assertIn(f'load_from = {str(parent.resolve())!r}', config.read_text(encoding='utf-8'))

    def test_dataset_snapshot_does_not_modify_standardized_png(self):
        source = self.temp / 'source'; source.mkdir(); Image.new('RGB',(20,20)).save(source/'fish.jpg')
        schema = self.temp / 'schema.csv'; schema.write_text('id,abbr,name\n1,A,One\n', encoding='utf-8')
        project = Project.create('p',source,self.temp,schema,source_layout='direct'); image_id=project.catalog_rows()[0]['image_id']
        cache=project.cache_root/'standardized'/f'{image_id}.png'; cache.parent.mkdir(parents=True,exist_ok=True); Image.new('RGB',(20,20)).save(cache)
        project.save_landmark(image_id,1,4,5,'manual',provenance='manual'); project.mark_checked(image_id)
        before=hashlib.sha256(cache.read_bytes()).hexdigest()
        create_dataset(project,dataset_id='d',splits={'train':[image_id]},eligibility_mode='v2_human_final')
        self.assertEqual(hashlib.sha256(cache.read_bytes()).hexdigest(),before)


if __name__ == '__main__':
    unittest.main()