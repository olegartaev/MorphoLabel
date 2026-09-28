import shutil
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from app.active_learning import select_ai_worst_first, _verified_error_calibration, _empirical_point_risk, _diverse_take
from app.landmark_ai_review import (activate_review_session, complete_or_advance_review,
                                    create_review_session, create_review_session_for_ids, pending_review_session,
                                    review_summary, successful_prediction_ids, remove_image_from_reviews)
from app.landmark_dataset import v2_human_final_eligible_image_ids
from app.landmark_frames import restore_standardized_frame
from app.project_storage import Project
from app.transforms import Transform


class LandmarkAIReviewTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        source = self.root / "source"; source.mkdir()
        for number in range(3):
            Image.new("RGB", (80, 50), (number * 30, 40, 90)).save(source / f"fish_{number}.png")
        schema = self.root / "schema.csv"
        schema.write_text("id,abbr,name,role\n1,A,Alpha,BOTH\n2,B,Beta,BOTH\n", encoding="utf-8")
        self.project = Project.create("project", source, self.root, schema, source_types=["png"], source_layout="direct")
        self.ids = [row["image_id"] for row in self.project.catalog_rows()]
        for image_id in self.ids:
            source_path = self.project.image_path(image_id)
            developed = self.project.cache_root / "developed" / f"{image_id}.png"
            developed.parent.mkdir(parents=True, exist_ok=True)
            Image.open(source_path).convert("RGB").save(developed)
            transform = Transform(80, 50, 0.0, 40.0, 25.0, 5, 4, 60, 36)
            self.project.save_reviewed_crop(image_id, {
                "developed_full_relpath": f"cache/developed/{image_id}.png",
                "standardized_relpath": f"cache/standardized/{image_id}.png",
                "crop_bounds": [5, 4, 65, 40], "rotation_degrees": 0.0,
                "transform": transform.__dict__, "normalization_status": "PASS",
            })
            restore_standardized_frame(self.project, image_id)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _machine(self, image_id, run="run-1"):
        for landmark_id, point in ((1, (10, 11)), (2, (20, 21))):
            self.project.save_landmark(
                image_id, landmark_id, *point, "auto", provenance="machine", model_id="rtmpose_v1",
                predicted_x=point[0], predicted_y=point[1], confidence=.8,
                prediction_run_id=run, reviewed=False,
            )

    def test_checked_is_explicit_ai_confirmation_and_preserves_machine_data(self):
        image_id = self.ids[0]; self._machine(image_id)
        before = self.project.load_landmarks(image_id)
        self.assertNotIn(image_id, v2_human_final_eligible_image_ids(self.project))
        result = self.project.mark_checked(image_id)
        after = self.project.load_landmarks(image_id)
        self.assertEqual(result["image_id"], image_id)
        self.assertIn(image_id, v2_human_final_eligible_image_ids(self.project))
        for landmark_id in (1, 2):
            self.assertEqual(after[landmark_id]["provenance"], "machine")
            self.assertEqual(after[landmark_id]["prediction_run_id"], before[landmark_id]["prediction_run_id"])
            self.assertEqual(after[landmark_id]["model_id"], before[landmark_id]["model_id"])
            self.assertEqual(after[landmark_id]["x_standardized"], before[landmark_id]["x_standardized"])
            self.assertEqual(after[landmark_id]["reviewed"], 1)
        self.assertTrue(self.project.landmark_ai_review_ready(image_id))

    def test_edit_and_reprediction_invalidate_confirmation(self):
        image_id = self.ids[0]; self._machine(image_id); self.project.confirm_landmark_ai_review(image_id)
        self.project.save_landmark(image_id, 1, 13, 14, "corrected", provenance="corrected_by_human")
        rows = self.project.load_landmarks(image_id)
        self.assertEqual(rows[1]["provenance"], "corrected_by_human")
        self.assertEqual(rows[1]["model_id"], "rtmpose_v1")
        self.assertEqual(rows[1]["reviewed"], 0)
        self.assertNotIn(image_id, v2_human_final_eligible_image_ids(self.project))
        self.project.confirm_landmark_ai_review(image_id)
        self.assertIn(image_id, v2_human_final_eligible_image_ids(self.project))
        self._machine(image_id, "run-2")
        self.assertNotIn(image_id, v2_human_final_eligible_image_ids(self.project))

    def test_excluding_current_ai_review_image_advances_without_confirming_it(self):
        first,second=self.ids[:2]
        for image_id in (first,second):self._machine(image_id)
        create_review_session_for_ids(self.project,"exclude-review",(first,second),kind="review_worst")
        active_session=activate_review_session(self.project,"exclude-review")
        self.assertEqual(first,active_session["current_image_id"])
        target=remove_image_from_reviews(self.project,first)
        self.assertEqual(second,target)
        active_session=activate_review_session(self.project,"exclude-review")
        self.assertEqual([second],active_session["image_ids"])
        self.assertEqual(second,active_session["current_image_id"])
        self.assertFalse(self.project.landmark_ai_review_ready(first))

    def test_review_navigation_skips_members_verified_after_queue_creation(self):
        first,second,third=self.ids
        for image_id in self.ids:self._machine(image_id)
        create_review_session_for_ids(self.project,"skip-verified",(first,second,third),kind="review_worst_v2")
        session=activate_review_session(self.project,"skip-verified")
        self.assertEqual(first,session["current_image_id"])
        self.project.confirm_landmark_ai_review(first)
        self.project.confirm_landmark_ai_review(second)
        session,complete=complete_or_advance_review(self.project,"skip-verified",first)
        self.assertFalse(complete)
        self.assertEqual(third,session["current_image_id"])
        self.assertFalse(self.project.landmark_ai_review_ready(third))

    def test_review_previous_does_not_enter_verified_member(self):
        first,second,third=self.ids
        for image_id in self.ids:self._machine(image_id)
        create_review_session_for_ids(self.project,"skip-back",(first,second,third),kind="review_worst_v2")
        self.project.confirm_landmark_ai_review(second)
        from app.landmark_ai_review import move_review_position
        session=activate_review_session(self.project,"skip-back")
        self.assertEqual(first,session["current_image_id"])
        session=move_review_position(self.project,"skip-back",first,-1)
        self.assertEqual(first,session["current_image_id"])
        self.project.confirm_landmark_ai_review(first)
        session=activate_review_session(self.project,"skip-back")
        self.assertEqual(third,session["current_image_id"])

    def test_review_worst_learns_error_magnitude_from_verified_predictions(self):
        class Snapshot:
            schema = ({'id': 1, 'abbr': 'A', 'name': 'Alpha', 'role': 'BOTH'},)
            dimensions_by_id = {f'v{i}': (100, 100) for i in range(6)}
            def catalog_rows(self): return [{'image_id': f'v{i}'} for i in range(6)]
            def annotation_status(self, image_id): return {'verified': True}
            def load_landmarks(self, image_id):
                i = int(image_id[1:])
                # Low-confidence verified predictions needed larger human corrections.
                confidence = .2 if i < 3 else .9
                delta = 8.0 if i < 3 else 1.0
                return {1: {
                    'state': 'present', 'x_standardized': 10.0 + delta, 'y_standardized': 10.0,
                    'predicted_x': 10.0, 'predicted_y': 10.0, 'confidence': confidence,
                    'model_id': 'm',
                }}
        calibration = _verified_error_calibration(Snapshot())
        low, low_n = _empirical_point_risk(calibration, 1, {'model_id': 'm', 'confidence': .2})
        high, high_n = _empirical_point_risk(calibration, 1, {'model_id': 'm', 'confidence': .9})
        self.assertEqual(calibration['sample_count'], 6)
        self.assertGreater(low, high)
        # With six verified examples the risk estimator deliberately uses the
        # three nearest-confidence examples rather than mixing both confidence groups.
        self.assertEqual(low_n, 3)
        self.assertEqual(high_n, 3)

    def test_review_worst_diversity_is_only_a_tie_break_inside_high_risk_window(self):
        ranked = [
            {'image_id':'a','risk_score':1.00,'_priority_class':0,'_descriptor':{1:(.1,.1),2:(.2,.2),3:(.3,.3)}},
            {'image_id':'b','risk_score':.99,'_priority_class':0,'_descriptor':{1:(.1,.1),2:(.2,.2),3:(.3,.3)}},
            {'image_id':'c','risk_score':.98,'_priority_class':0,'_descriptor':{1:(.7,.7),2:(.8,.8),3:(.9,.9)}},
            {'image_id':'d','risk_score':.40,'_priority_class':0,'_descriptor':{1:(0.,0.),2:(1.,1.),3:(.5,.5)}},
        ]
        selected = _diverse_take(ranked, 2)
        self.assertEqual('a', selected[0]['image_id'])
        self.assertEqual('c', selected[1]['image_id'])
        self.assertNotIn('d', [item['image_id'] for item in selected])

    def test_review_worst_session_persists_reason_and_landmark_highlights(self):
        first, second = self.ids[:2]
        metadata = {
            first: {'reason':'Correction history: LM1 risk high','landmark_ids':[1],'risk_score':1.2},
            second: {'reason':'Low AI confidence: LM2','landmark_ids':[2],'risk_score':.5},
        }
        session = create_review_session_for_ids(self.project,'worst-v2-test',(first,second),kind='review_worst_v2',metadata=metadata)
        self.assertEqual('review_worst_v2',session['kind'])
        self.assertEqual([1],session['review_meta'][first]['landmark_ids'])
        reopened=Project.open(self.project.root)
        active=activate_review_session(reopened,'worst-v2-test')
        self.assertEqual('Correction history: LM1 risk high',active['review_meta'][first]['reason'])

    def test_review_worst_excludes_fully_unresolved_ai_placeholders(self):
        first = self.ids[0]
        self._machine(first)
        with self.project.transaction() as connection:
            connection.execute("UPDATE landmarks SET x_standardized=NULL,y_standardized=NULL,state='unresolved' WHERE image_id=?",(first,))
        queue = select_ai_worst_first(self.project, None)
        self.assertNotIn(first,[item["image_id"] for item in queue])

    def test_review_worst_leaves_partial_unresolved_ai_for_reapply(self):
        first = self.ids[0]
        self._machine(first)
        # A partial prediction is not a review task. Reapply unverified completes it first.
        with self.project.transaction() as connection:
            row = connection.execute("SELECT landmark_abbr FROM landmarks WHERE image_id=? AND landmark_id=?",(first,2)).fetchone()
            connection.execute("UPDATE landmarks SET x_standardized=NULL,y_standardized=NULL,state='unresolved' WHERE image_id=? AND landmark_abbr=?",(first,row["landmark_abbr"]))
        queue = select_ai_worst_first(self.project, None)
        self.assertNotIn(first,[item["image_id"] for item in queue])

    def test_review_worst_excludes_complete_ai_when_crop_is_not_canonical(self):
        first = self.ids[0]
        self._machine(first)
        with self.project.transaction() as connection:
            connection.execute("UPDATE crops SET human_verified=0 WHERE image_id=?",(first,))
        queue = select_ai_worst_first(self.project, None)
        self.assertNotIn(first,[item["image_id"] for item in queue])

    def test_review_worst_size_is_bounded(self):
        for image_id in self.ids:self._machine(image_id)
        queue=select_ai_worst_first(self.project,2)
        self.assertEqual(2,len(queue))
        self.assertTrue(all(item.get('reason') for item in queue))

    def test_review_worst_contains_all_pending_including_corrected_ai(self):
        first, second, third = self.ids
        for image_id in self.ids: self._machine(image_id)
        self.project.save_landmark(second, 1, 14, 15, "corrected", provenance="corrected_by_human")
        self.project.confirm_landmark_ai_review(third)
        queue = select_ai_worst_first(self.project, None)
        self.assertEqual({first, second}, {item["image_id"] for item in queue})
        self.assertNotIn(third, [item["image_id"] for item in queue])
    def test_pending_ai_query_and_reapply_preserve_human_corrections(self):
        image_id = self.ids[0]
        self._machine(image_id, "run-old")
        self.assertIn(image_id, self.project.pending_ai_landmark_image_ids())

        self.project.save_landmark(image_id, 1, 13, 14, "corrected", provenance="corrected_by_human")
        corrected_before = self.project.load_landmarks(image_id)[1].copy()
        saved, skipped = self.project.save_machine_landmarks(
            image_id,
            [
                {"landmark_id": 1, "x": 31, "y": 32, "confidence": .95},
                {"landmark_id": 2, "x": 41, "y": 42, "confidence": .96},
            ],
            model_id="rtmpose_v2",
            prediction_run_id="run-new",
        )
        self.assertEqual((saved, skipped), (1, 1))

        rows = self.project.load_landmarks(image_id)
        self.assertEqual(rows[1]["provenance"], "corrected_by_human")
        self.assertEqual((rows[1]["x_standardized"], rows[1]["y_standardized"]),
                         (corrected_before["x_standardized"], corrected_before["y_standardized"]))
        self.assertEqual(rows[2]["provenance"], "machine")
        self.assertEqual(rows[2]["model_id"], "rtmpose_v2")
        self.assertEqual(rows[2]["prediction_run_id"], "run-new")
        self.assertEqual((rows[2]["x_standardized"], rows[2]["y_standardized"]), (41.0, 42.0))
        self.assertEqual(rows[2]["reviewed"], 0)
        self.assertIn(image_id, self.project.pending_ai_landmark_image_ids())

        self.project.confirm_landmark_ai_review(image_id, "reapply-batch")
        self.assertNotIn(image_id, self.project.pending_ai_landmark_image_ids())

    def test_successful_ids_only_persistent_session_and_exact_counters(self):
        first, second, failed = self.ids
        for image_id in (first, second): self._machine(image_id)
        batch = {
            "batch_id": "batch-42",
            "selected_images": [{"image_id": first}, {"image_id": failed}, {"image_id": second}],
            "prediction_runs": {first: {"run_id": "one"}, second: {"run_id": "two"}},
            "failures": {failed: "backend failure"},
        }
        self.assertEqual(successful_prediction_ids(batch), (first, second))
        session = create_review_session(self.project, batch)
        self.assertFalse(session["active"], "No path leaves predictions persisted but does not enter review")
        self.assertEqual(pending_review_session(self.project)["batch_id"], "batch-42")
        self.assertEqual(tuple(session["image_ids"]), (first, second))
        session = activate_review_session(self.project, "batch-42")
        self.assertEqual(review_summary(self.project, session, first)["remaining"], 2)
        # Previous only changes the current review position; it never confirms a point set.
        self.assertEqual(complete_or_advance_review(self.project, "batch-42", first)[0]["current_image_id"], second)
        self.assertFalse(self.project.landmark_ai_review_ready(first))
        self.project.confirm_landmark_ai_review(first, "batch-42")
        reopened = Project.open(self.project.root)
        self.assertEqual(pending_review_session(reopened)["batch_id"], "batch-42")
        self.assertEqual(review_summary(reopened, current_id=first)["remaining"], 1)
        self.assertIn(first, v2_human_final_eligible_image_ids(reopened))
        self.assertNotIn(second, v2_human_final_eligible_image_ids(reopened))


if __name__ == "__main__":
    unittest.main()