"""High-resolution training sends real progress before GPU subprocess exits."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from app.xray_multires_training import run_high_resolution_training


class TrainingStreamingTests(unittest.TestCase):
    def test_progress_reaches_gui_before_candidate_written(self):
        with tempfile.TemporaryDirectory(prefix="morpholabel_stream_test_") as dirname:
            root=Path(dirname)
            project_root=root/"original"
            project_root.mkdir()
            # Model a frozen GUI bundle whose top-level extension has another
            # Python ABI. It must never shadow the AI interpreter's _ctypes.
            (root/"_ctypes.py").write_text("raise ImportError('GUI Python ABI leaked into AI worker')\n",encoding="utf-8")
            (root/"app").mkdir()
            (root/"app/__init__.py").write_text("",encoding="utf-8")
            (root/"app/worker_marker.py").write_text("TOKEN=42\n",encoding="utf-8")
            (root/"tools").mkdir()
            script=root/"tools"/"fake_training.py"
            script.write_text(
                "import json,sys,time,zipfile\n"
                "import ctypes\n"
                "from app.worker_marker import TOKEN\n"
                "assert TOKEN==42 and ctypes.sizeof(ctypes.c_int)>0\n"
                "from pathlib import Path\n"
                "out=Path(sys.argv[sys.argv.index('--output')+1])\n"
                "print(json.dumps({'stage':'PREPARED','training_specimens':7}),flush=True)\n"
                "time.sleep(0.8)\n"
                "with zipfile.ZipFile(out,'w') as z:\n"
                "    z.writestr('manifest.json',json.dumps({'model_id':'new_candidate'}))\n"
                "print(json.dumps({'membership':[{'specimen_id':'local-id','split':'train'}]}),flush=True)\n",
                encoding="utf-8",
            )
            project=type("Project",(),{"root":project_root})()
            output=root/"output"/"new.zip"
            delivered=[]
            def progress(line):
                delivered.append((json.loads(line).get("stage"),output.exists()))
            def create_copy(_project,_model,destination):
                destination.mkdir(parents=True)
                return destination
            with patch("app.xray_multires_training.is_universal_multires_model",return_value=True), \
                 patch("app.xray_multires_training.resource_path",return_value=script), \
                 patch("app.xray_multires_training.create_read_only_source_project_copy",side_effect=create_copy):
                result=run_high_resolution_training(
                    project,"parent",output,python_executable=Path(sys.executable),
                    progress=progress,cancelled=threading.Event())
            self.assertEqual(result["model_id"],"new_candidate")
            self.assertIn(("PREPARED",False),delivered)
            self.assertTrue(output.is_file())
            self.assertEqual(result["membership"],[{"specimen_id":"local-id","split":"train"}])
            self.assertEqual(len(result["log"]),2)


if __name__=="__main__":
    unittest.main()
