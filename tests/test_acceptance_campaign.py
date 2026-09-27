import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from tools.acceptance_campaign import (
    _validate_destructive_target,
    build_support_report,
    run_process,
    source_metadata_fingerprint,
)


class AcceptanceCampaignTests(unittest.TestCase):
    def _project(self, root, name="project-copy"):
        project=Path(root)/name
        project.mkdir()
        (project/"project.yaml").write_text(json.dumps({"source_root":str(Path(root)/"source")}),encoding="utf-8")
        (project/"landmark_schema.csv").write_text("id,abbr,name,role\n1,A,Alpha,BOTH\n",encoding="utf-8")
        data=project/"project_data"
        data.mkdir()
        (data/"project.sqlite").write_bytes(b"sqlite")
        source=Path(root)/"source"
        source.mkdir()
        return project,source

    def test_source_fingerprint_uses_metadata_and_ignores_non_images(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            (root/"a.jpg").write_bytes(b"abc")
            (root/"note.txt").write_text("ignored",encoding="utf-8")
            first=source_metadata_fingerprint(root)
            self.assertEqual(1,first["count"])
            self.assertEqual(3,first["bytes"])
            (root/"note.txt").write_text("changed",encoding="utf-8")
            self.assertEqual(first,source_metadata_fingerprint(root))
            (root/"a.jpg").write_bytes(b"abcd")
            self.assertNotEqual(first["digest"],source_metadata_fingerprint(root)["digest"])

    def test_destructive_target_requires_visible_copy_and_external_output(self):
        with tempfile.TemporaryDirectory() as td:
            project,source=self._project(td)
            output=Path(td)/"campaign-output"
            db,resolved_source=_validate_destructive_target(project,output)
            self.assertTrue(db.name=="project.sqlite")
            self.assertEqual(source.resolve(),resolved_source)
            original=Path(td)/"original-project"
            original.mkdir()
            (original/"project.yaml").write_text(json.dumps({"source_root":str(source)}),encoding="utf-8")
            (original/"landmark_schema.csv").write_text("x",encoding="utf-8")
            (original/"project_data").mkdir()
            (original/"project_data"/"project.sqlite").write_bytes(b"x")
            with self.assertRaises(RuntimeError):
                _validate_destructive_target(original,output)
            with self.assertRaises(RuntimeError):
                _validate_destructive_target(project,project/"output")

    def test_support_report_sanitizes_known_paths_and_keeps_status_counts(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            project=root/"project-copy";source=root/"source";output=root/"out"
            output.mkdir()
            stderr=output/"stderr.txt"
            stderr.write_text(f"failed at {project} while reading {source}\n",encoding="utf-8")
            results=[
                {"name":"one","status":"PASS","returncode":0,"elapsed_seconds":1.0,"stdout":None,"stderr":None},
                {"name":"two","status":"FAIL","returncode":1,"elapsed_seconds":2.0,"stdout":None,"stderr":str(stderr)},
                {"name":"three","status":"HANG","returncode":None,"elapsed_seconds":3.0,"stdout":None,"stderr":None},
            ]
            fp={"count":1,"bytes":2,"digest":"abc","exists":True}
            report=build_support_report(
                results,project_root=project,source_root=source,output_root=output,
                source_before=fp,source_after=dict(fp),expected_version="0.5-test",
            )
            self.assertEqual((1,1,1),(report["pass"],report["fail"],report["hang"]))
            self.assertTrue(report["source_images"]["metadata_unchanged"])
            failure=report["scenarios"][1]["failure_tail"]
            self.assertIn("<PROJECT_COPY>",failure)
            self.assertIn("<SOURCE_ROOT>",failure)
            self.assertNotIn(str(project),failure)
            self.assertNotIn(str(source),failure)

    def test_process_timeout_is_reported_as_hang_without_raising(self):
        with tempfile.TemporaryDirectory() as td:
            result=run_process(
                "sleep",
                [sys.executable,"-c","import time; time.sleep(5)"],
                timeout=0.2,
                env=os.environ.copy(),
                scenario_dir=Path(td)/"sleep",
            )
            self.assertEqual("HANG",result["status"])


if __name__=="__main__":
    unittest.main()
