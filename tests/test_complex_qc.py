import shutil
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from app.complex_qc import scan_complex_qc
from app.measurements import save_measurements
from app.project_storage import Project


class ComplexQCTests(unittest.TestCase):
    def setUp(self):
        self.roots=[]

    def tearDown(self):
        for root in self.roots:
            shutil.rmtree(root,ignore_errors=True)

    def _project(self,variant):
        root=Path(tempfile.mkdtemp());self.roots.append(root)
        source=root/"source";source.mkdir()
        for index in range(12):
            Image.new("RGB",(200,160),"white").save(source/f"fish_{index:02d}.jpg")
        schema=root/"schema.csv"
        schema.write_text(
            "id,abbr,name,role\n"
            "1,A,One,BOTH\n2,B,Two,BOTH\n3,C,Three,BOTH\n4,D,Four,BOTH\n5,E,Five,BOTH\n",
            encoding="utf8",
        )
        project=Project.create("p",source,root,schema,source_layout="direct")
        ids=[row["image_id"] for row in project.catalog_rows()]
        base={1:(20.0,25.0),2:(55.0,20.0),3:(90.0,30.0),4:(30.0,70.0),5:(80.0,75.0)}
        for index,image_id in enumerate(ids):
            Image.new("RGB",(200,160),"white").save(project.cache_root/"standardized"/f"{image_id}.png")
            coords=dict(base)
            if index==0 and variant=="point":
                coords[5]=(145.0,25.0)
            elif index==0 and variant=="scale":
                coords={ident:(x*1.6+10.0,y*1.6+5.0) for ident,(x,y) in coords.items()}
            for ident,(x,y) in coords.items():
                project.save_landmark(image_id,ident,x,y,"manual",provenance="manual")
            project.mark_checked(image_id)
        save_measurements(project,[
            {"use":True,"abbr":"AB","name":"AB","point1":1,"point2":2},
            {"use":True,"abbr":"AC","name":"AC","point1":1,"point2":3},
            {"use":True,"abbr":"CE","name":"CE","point1":3,"point2":5},
            {"use":True,"abbr":"DE","name":"DE","point1":4,"point2":5},
        ])
        return project,ids

    def test_ensemble_localizes_one_displaced_landmark(self):
        project,ids=self._project("point");target=ids[0]
        before=project.load_landmarks(target)
        result=scan_complex_qc(project)
        issue=next(item for item in result["queue"] if item["image_id"]==target)
        families={item["family"] for item in issue["signals"]}
        self.assertEqual("High",issue["priority"])
        self.assertIn(5,issue["landmark_ids"])
        self.assertIn("distance",families)
        self.assertIn("measurements",families)
        try:
            import numpy  # noqa: F401
        except ImportError:
            pass
        else:
            self.assertTrue(result["methods"]["gm"]["used"])
            self.assertIn("gm",families)
        self.assertEqual(before,project.load_landmarks(target))

    def test_scan_excludes_unverified_manual_and_machine_annotations(self):
        project,ids=self._project("clean")
        manual_id,machine_id=ids[1],ids[2]
        project.save_landmark(manual_id,5,145.0,25.0,"corrected",provenance="corrected_by_human");project.clear_checked(manual_id)
        with project.transaction() as db:
            db.execute("UPDATE landmarks SET x_standardized=145.0,y_standardized=25.0,provenance='machine',reviewed=0,model_id='m',prediction_run_id='r' WHERE image_id=? AND landmark_abbr='E'",(machine_id,))
            db.execute("UPDATE image_review SET human_verified=0 WHERE image_id=?",(machine_id,))
        result=scan_complex_qc(project)
        self.assertEqual(len(ids)-2,result["scanned"])
        queued={item["image_id"]:item for item in result["queue"]}
        self.assertNotIn(manual_id,queued);self.assertNotIn(machine_id,queued)

    def test_incomplete_annotation_stays_out_of_complex_qc(self):
        project,ids=self._project("clean");target=ids[0]
        project.delete_landmark(target,5)
        result=scan_complex_qc(project)
        self.assertEqual(len(ids)-1,result["scanned"])
        self.assertNotIn(target,{item["image_id"] for item in result["queue"]})

    def test_missing_frame_dimensions_are_not_qc_errors(self):
        project,ids=self._project("clean")
        result=scan_complex_qc(project)
        self.assertEqual(len(ids),result["scanned"])
        self.assertEqual(len(ids),result["methods"]["basic"]["dimensions_missing"])
        self.assertEqual(0,result["methods"]["basic"]["issues"])
        self.assertEqual(set(),{item["image_id"] for item in result["queue"]})

    def test_uniform_scale_and_translation_are_not_annotation_outliers(self):
        project,ids=self._project("scale");target=ids[0]
        result=scan_complex_qc(project)
        self.assertNotIn(target,{item["image_id"] for item in result["queue"]})

    def test_human_acceptance_suppresses_same_unchanged_complex_qc_issue(self):
        project,ids=self._project("point");target=ids[0]
        first=scan_complex_qc(project)
        issue=next(item for item in first["queue"] if item["image_id"]==target)
        project.accept_review_warning(target,issue)
        second=scan_complex_qc(project)
        self.assertNotIn(target,{item["image_id"] for item in second["queue"]})

    def test_complex_qc_acceptance_survives_cosmetic_schema_rename(self):
        project,ids=self._project("point");target=ids[0]
        issue=next(item for item in scan_complex_qc(project)["queue"] if item["image_id"]==target)
        project.accept_review_warning(target,issue)
        project.schema_path.write_text(
            "id,abbr,name,role\n"
            "1,A,Renamed one,CLASSICAL\n2,B,Renamed two,BOTH\n3,C,Renamed three,BOTH\n4,D,Renamed four,BOTH\n5,E,Renamed five,BOTH\n",
            encoding="utf8",
        )
        second=scan_complex_qc(project)
        self.assertNotIn(target,{item["image_id"] for item in second["queue"]})

    def test_flagged_queue_is_worst_first(self):
        project,ids=self._project("clean")
        project.save_landmark(ids[0],5,145.0,25.0,"corrected",provenance="corrected_by_human")
        project.save_landmark(ids[1],5,130.0,30.0,"corrected",provenance="corrected_by_human")
        project.mark_checked(ids[0]);project.mark_checked(ids[1])
        result=scan_complex_qc(project)
        risks=[float(item["risk_score"]) for item in result["queue"] if item.get("priority")=="High"]
        self.assertEqual(risks,sorted(risks,reverse=True))

    def test_workflow_has_prominent_complex_qc_and_no_review_pending_button(self):
        root=Path(__file__).parents[1]
        landmarks=(root/"app"/"ui"/"landmarks_section.py").read_text(encoding="utf8")
        shell=(root/"app"/"ui"/"shell.py").read_text(encoding="utf8")
        dialog=(root/"app"/"ui"/"complex_qc_dialog.py").read_text(encoding="utf8")
        self.assertIn("'Final data QC'",landmarks)
        self.assertIn("'Unverified AI review'",landmarks)
        self.assertNotIn("'Review pending'",landmarks)
        self.assertIn("ReviewAction.TButton",shell)
        self.assertIn('"Review flagged — worst first"',dialog)
        self.assertIn("human-verified",dialog)
        self.assertNotIn('"Review selected"',dialog)
        self.assertNotIn('"Scan again"',dialog)
        self.assertIn("Outlier ≠ error",dialog)


if __name__=="__main__":
    unittest.main()
