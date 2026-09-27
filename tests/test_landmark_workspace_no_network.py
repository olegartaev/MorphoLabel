import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from app.landmark_training_workflow import available_training_parents
from app.project_storage import Project, schema_hash


class LandmarkWorkspaceNoNetworkTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(tempfile.mkdtemp())
        source=self.root/"source";source.mkdir()
        Image.new("RGB",(20,20)).save(source/"fish.jpg")
        schema=self.root/"schema.csv"
        schema.write_text("id,abbr,name,role\n1,A,Alpha,BOTH\n",encoding="utf-8")
        self.project=Project.create("project",source,self.root,schema,source_layout="direct")
        self.project.register_model(
            "rtmpose_v001",
            "landmark",
            path="models/rtmpose_v001",
            schema_digest=schema_hash(self.project.schema_path),
        )

    def tearDown(self):
        shutil.rmtree(self.root,ignore_errors=True)

    def test_listing_training_parents_never_resolves_backend_or_ai_runtime(self):
        with patch(
            "app.landmark_training_workflow.backend_for_model",
            side_effect=AssertionError("Landmarks render must not resolve an AI backend"),
        ) as resolve:
            parents=available_training_parents(self.project)
        resolve.assert_not_called()
        self.assertEqual(("rtmpose_v001",),tuple(model["model_id"] for model in parents))


if __name__=="__main__":
    unittest.main()
