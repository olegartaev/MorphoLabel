import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from app.landmark_ai_workflow import STATE_KEY, begin_improvement, training_eligible_ids
from app.project_storage import Project


class ImprovementCycleTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(tempfile.mkdtemp()); source=self.root/"source";source.mkdir()
        for index in range(18): Image.new("RGB",(20,20)).save(source/f"fish_{index}.jpg")
        schema=self.root/"schema.csv";schema.write_text("id,abbr,name\n1,A,Alpha\n",encoding="utf-8")
        self.project=Project.create("project",source,self.root,schema,source_layout="direct")
        self.ids=[row["image_id"] for row in self.project.catalog_rows()]
        self.control=self.ids[:2];self.initial=self.ids[2:4];self.old=self.ids[4:9]
        for image_id in self.old:
            self.project.save_landmark(image_id,1,5,5,"present",provenance="manual");self.project.mark_checked(image_id)
        self.state={"stage":"READY_FOR_FULL_PREDICTION","seed":17,"control_image_ids":self.control,"initial_image_ids":self.initial,"improvement_image_ids":self.old,"improvement_history_ids":[],"improvement_target":5,"current_image_id":self.old[0],"current_position":0,"unfinished_image_id":self.old[0]}
        self.project.set_ui_state(STATE_KEY,self.state)

    def tearDown(self): shutil.rmtree(self.root,ignore_errors=True)

    def new_cycle(self):
        with patch("app.landmark_ai_workflow.refresh_stage", return_value=dict(self.state)):
            return begin_improvement(self.project,target=5)

    def test_completed_old_improvement_ready_creates_fresh_ids(self):
        state=self.new_cycle()
        self.assertEqual("MODEL_IMPROVEMENT",state["stage"]);self.assertEqual(5,len(state["improvement_image_ids"]));self.assertFalse(set(state["improvement_image_ids"]) & set(self.old))

    def test_control_initial_and_prior_improvement_ids_are_never_reused(self):
        state=self.new_cycle()
        blocked=set(self.control)|set(self.initial)|set(self.old)
        self.assertFalse(set(state["improvement_image_ids"]) & blocked);self.assertEqual(self.old,state["improvement_history_ids"])

    def test_old_improvement_annotations_remain_training_eligible(self):
        self.new_cycle()
        self.assertTrue(set(self.old).issubset(set(training_eligible_ids(self.project))))


if __name__ == "__main__": unittest.main()