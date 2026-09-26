import shutil
import tempfile
import unittest
from pathlib import Path

from app.landmark_ai_workflow import CONTROL_TARGET, diverse_selection, stage_summary, start_or_continue
from app.landmark_dataset import eligible_image_ids
from app.project_storage import Project, schema_hash


class LandmarkAIWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        source = self.root / "source"; source.mkdir()
        for locality in ("a", "b", "c"):
            folder = source / locality; folder.mkdir()
            for n in range(3): (folder / f"fish_{n}.jpg").write_bytes(b"x")
        schema = self.root / "schema.csv"; schema.write_text("id,abbr,name,role\n1,A,Alpha,BOTH\n", encoding="utf-8")
        self.project = Project.create("project", source, self.root, schema, source_layout="direct")

    def tearDown(self): shutil.rmtree(self.root, ignore_errors=True)

    def test_control_set_is_persistent_and_excluded_from_training_pool(self):
        info = stage_summary(self.project)
        controls = set(info["state"]["control_image_ids"])
        self.assertEqual(9, len(controls))
        for image_id in controls:
            self.project.save_landmark(image_id, 1, 10, 10, "present", "manual")
        self.assertFalse(controls.intersection(eligible_image_ids(self.project, require_verified=True)))
        reopened = Project.open(self.project.root)
        self.assertEqual(controls, set(stage_summary(reopened)["state"]["control_image_ids"]))

    def test_same_seed_diverse_selection_is_deterministic(self):
        rows = self.project.catalog_rows()
        self.assertEqual(diverse_selection(self.project, rows, 6, 99), diverse_selection(self.project, rows, 6, 99))
        chosen = diverse_selection(self.project, rows, 3, 99)
        localities = {next(row for row in rows if row["image_id"] == image_id)["locality"] for image_id in chosen}
        self.assertEqual(3, len(localities))

    def test_no_model_and_imported_model_both_start_at_control_set(self):
        self.assertEqual("CONTROL_SET", start_or_continue(self.project)["stage"])
        artifact = self.project.models_root / "imported"; artifact.mkdir(parents=True)
        self.project.register_model("imported_model", "landmark", path=artifact.relative_to(self.project.data_root).as_posix(), active=True, schema_digest=schema_hash(self.project.schema_path))
        self.assertEqual("CONTROL_SET", start_or_continue(self.project)["stage"])
        self.assertEqual("imported_model", stage_summary(self.project)["active_model_id"])

    def test_state_is_project_local_and_survives_reopen(self):
        state = start_or_continue(self.project)
        state["full_prediction_done"] = True
        self.project.set_ui_state("landmark_ai_workflow", state)
        reopened = Project.open(self.project.root)
        self.assertTrue(reopened.get_ui_state("landmark_ai_workflow")["full_prediction_done"])

if __name__ == "__main__": unittest.main()
class LandmarkAIWorkflowEditingSafetyTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        source = self.root / "source"; source.mkdir()
        for n in range(3): (source / f"fish_{n}.jpg").write_bytes(b"x")
        schema = self.root / "schema.csv"; schema.write_text("id,abbr,name,role\n1,A,Alpha,BOTH\n", encoding="utf-8")
        self.project = Project.create("project", source, self.root, schema, source_layout="direct")

    def tearDown(self): shutil.rmtree(self.root, ignore_errors=True)

    def test_clearing_current_landmarks_does_not_remove_control_membership(self):
        info = stage_summary(self.project); image_id = info["state"]["control_image_ids"][0]
        self.project.save_landmark(image_id, 1, 8, 9, "present", "manual")
        self.project.replace_landmarks(image_id, {})
        self.assertIn(image_id, self.project.permanent_test_image_ids())
        self.assertFalse(self.project.annotation_status(image_id)["verified"])

if __name__ == "__main__": unittest.main()

class LandmarkAIWorkflowResumeTests(unittest.TestCase):
 def setUp(self):
  self.root=Path(tempfile.mkdtemp());src=self.root/'source';src.mkdir()
  for n in range(40):(src/f'fish_{n:02d}.jpg').write_bytes(b'x')
  schema=self.root/'schema.csv';schema.write_text('id,abbr,name,role\n1,A,Alpha,BOTH\n',encoding='utf-8');self.p=Project.create('p',src,self.root,schema,source_layout='direct')
 def tearDown(self):shutil.rmtree(self.root,ignore_errors=True)
 def test_explicit_control_order_progress_and_resume_are_persistent(self):
  from app.landmark_ai_workflow import create_stage,load_state,workflow_current
  state=create_stage(self.p,'CONTROL_SET',25);ordered=list(state['control_image_ids']);self.assertEqual(25,len(ordered))
  for image_id in ordered[:3]:self.p.save_landmark(image_id,1,1,1,'manual',provenance='manual');self.p.mark_checked(image_id)
  reopened=Project.open(self.p.root);state=load_state(reopened);_,current,position,restored=workflow_current(reopened,state)
  self.assertEqual(ordered,state['control_image_ids']);self.assertEqual((ordered[3],3,False),(current,position,restored));self.assertEqual(3,stage_summary(reopened,create_missing=False)['verified'])
 def test_draft_has_priority_over_first_untouched(self):
  from app.landmark_ai_workflow import create_stage,workflow_current
  state=create_stage(self.p,'CONTROL_SET',25);ordered=state['control_image_ids'];self.p.save_annotation_draft(ordered[7],'CONTROL_SET',7)
  _,current,position,restored=workflow_current(self.p)
  self.assertEqual((ordered[7],7,True),(current,position,restored))
 def test_stage_defaults_and_chosen_targets_are_persisted(self):
  from app.landmark_ai_workflow import create_stage,load_state,CONTROL_TARGET,INITIAL_TARGET,IMPROVEMENT_TARGET
  self.assertEqual((25,30,20),(CONTROL_TARGET,INITIAL_TARGET,IMPROVEMENT_TARGET))
  control=create_stage(self.p,'CONTROL_SET',25);self.assertEqual(25,control['control_target']);self.assertIn('CONTROL_SET',control['stage_created_at'])
  for image_id in control['control_image_ids']:self.p.save_landmark(image_id,1,1,1,'manual',provenance='manual');self.p.mark_checked(image_id)
  initial=create_stage(self.p,'INITIAL_TRAINING',5);self.assertEqual(5,initial['initial_target']);self.assertIn('INITIAL_TRAINING',initial['stage_created_at'])
  improvement=create_stage(self.p,'MODEL_IMPROVEMENT',5);self.assertEqual(5,improvement['improvement_target']);self.assertIn('MODEL_IMPROVEMENT',improvement['stage_created_at'])
  reopened=load_state(Project.open(self.p.root));self.assertEqual((25,5,5),(reopened['control_target'],reopened['initial_target'],reopened['improvement_target']))



class LandmarkAIExcludedStageRepairTests(unittest.TestCase):
 def setUp(self):
  self.root=Path(tempfile.mkdtemp());src=self.root/'source';src.mkdir()
  for n in range(40):(src/f'fish_{n:02d}.jpg').write_bytes(b'x')
  schema=self.root/'schema.csv';schema.write_text('id,abbr,name,role\n1,A,Alpha,BOTH\n',encoding='utf-8')
  self.p=Project.create('p',src,self.root,schema,source_layout='direct')
 def tearDown(self):shutil.rmtree(self.root,ignore_errors=True)
 def _verify(self,image_id):
  self.p.save_landmark(image_id,1,1,1,'present','manual');self.p.mark_checked(image_id)
 def test_control_repair_replaces_only_excluded_position_and_prevents_loop(self):
  from app.landmark_ai_workflow import create_stage,repair_excluded_stage_members,workflow_current
  original=list(create_stage(self.p,'CONTROL_SET',25)['control_image_ids']);old=original[16]
  for image_id in original:
   if image_id!=old:self._verify(image_id)
  self.p.exclude_image(old,'Bent specimen')
  repaired=repair_excluded_stage_members(self.p,stage='CONTROL_SET');ids=repaired['control_image_ids'];new=ids[16]
  self.assertEqual(25,len(ids));self.assertNotEqual(old,new);self.assertEqual(original[:16],ids[:16]);self.assertEqual(original[17:],ids[17:])
  catalog={row['image_id']:row for row in self.p.catalog_rows()};self.assertFalse(catalog[new]['excluded'])
  self.assertIn(old,self.p.permanent_test_image_ids());self.assertIn(new,self.p.permanent_test_image_ids())
  self.assertEqual(24,stage_summary(self.p,create_missing=False)['verified'])
  _,current,position,_=workflow_current(self.p);self.assertEqual((new,16),(current,position))
  self.assertFalse(self.p.annotation_status(old)['verified'])
  self._verify(new);self.assertTrue(all(self.p.annotation_status(image_id)['verified'] for image_id in ids))
  self.assertEqual(ids,repair_excluded_stage_members(self.p,stage='CONTROL_SET')['control_image_ids'])
 def test_initial_replacement_never_uses_control_member(self):
  from app.landmark_ai_workflow import create_stage,repair_excluded_stage_members
  controls=create_stage(self.p,'CONTROL_SET',25)['control_image_ids'];initial=list(create_stage(self.p,'INITIAL_TRAINING',5)['initial_image_ids']);old=initial[2]
  self.p.exclude_image(old,'Bent specimen');repaired=repair_excluded_stage_members(self.p,stage='INITIAL_TRAINING');ids=repaired['initial_image_ids']
  self.assertEqual(initial[:2],ids[:2]);self.assertEqual(initial[3:],ids[3:]);self.assertNotEqual(old,ids[2]);self.assertNotIn(ids[2],controls)
  self.assertFalse(next(row for row in self.p.catalog_rows() if row['image_id']==ids[2])['excluded'])
class ManageControlSetTests(unittest.TestCase):
 def setUp(self):
  self.root=Path(tempfile.mkdtemp());src=self.root/'source';src.mkdir()
  for n in range(32):(src/f'fish_{n:02d}.jpg').write_bytes(b'x')
  schema=self.root/'schema.csv';schema.write_text('id,abbr,name,role\n1,A,Alpha,BOTH\n',encoding='utf-8')
  self.p=Project.create('p',src,self.root,schema,source_layout='direct')
 def tearDown(self):shutil.rmtree(self.root,ignore_errors=True)
 def test_add_current_control_member_is_permanent_and_idempotent(self):
  from app.landmark_ai_workflow import add_control_image,control_set_summary,create_stage
  before=list(create_stage(self.p,'CONTROL_SET',25)['control_image_ids']);candidate=next(row['image_id'] for row in self.p.catalog_rows() if row['image_id'] not in before)
  info,added=add_control_image(self.p,candidate);self.assertTrue(added);self.assertEqual(before+[candidate],list(info['current_ids']));self.assertEqual(26,info['state']['control_target']);self.assertIn(candidate,self.p.permanent_test_image_ids())
  again,added_again=add_control_image(self.p,candidate);self.assertFalse(added_again);self.assertEqual(tuple(before+[candidate]),again['current_ids']);self.assertEqual((0,26),(control_set_summary(self.p)['verified'],control_set_summary(self.p)['total']))
