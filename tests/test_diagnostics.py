import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app import diagnostics


class _Project:
    def __init__(self, root):
        self.root = Path(root) / "secret-project"
        self.source_root = Path(root) / "secret-source"
        self.config = {"format_version": 1, "schema_sha256": "a" * 64}
        self._rows = [
            {"image_id": "secret-fish-001", "excluded": False},
            {"image_id": "secret-fish-002", "excluded": True},
        ]

    def catalog_rows(self):
        return list(self._rows)

    def crop_section_counts(self):
        return {"Total": 1, "Remaining": 1}

    def landmark_counts(self):
        return {"Total": 1, "Train ready": 0}

    def active_model_readonly(self, kind):
        return {"model_id": f"secret-{kind}-model", "dataset_id": "secret-dataset"}

    def get_ui_state(self, key, default=None):
        if key == "crop_active_batch":
            return {"batch_type": "prediction_review", "ids": ["secret-fish-001", "secret-fish-002"], "current_image_id": "secret-fish-001"}
        return default or {}


class DiagnosticBundleTests(unittest.TestCase):
    def test_bundle_is_local_and_excludes_raw_project_identifiers(self):
        with tempfile.TemporaryDirectory() as td, patch.dict("os.environ", {"LOCALAPPDATA": td}, clear=False):
            project = _Project(td)
            context = SimpleNamespace(project=project, section="landmarks", current=lambda: project._rows[0])
            shell = SimpleNamespace(context=context, module_key="landmarks", module_registry=SimpleNamespace(diagnostics=[]))
            with patch("app.gui_crop_debug.LOG", Path(td) / "events.log"):
                Path(td, "events.log").write_text(
                    "2026-01-01T00:00:00.000 thread=Main/1 image_id=secret-fish-001 op=NAV_CLICK state=START elapsed_s=0.000 path=C:\\secret\\fish.jpg locality=SecretPlace\n",
                    encoding="utf-8",
                )
                try:
                    raise RuntimeError(f"failed below {project.root}")
                except RuntimeError as exc:
                    diagnostics.record_exception(type(exc), exc, exc.__traceback__, shell=shell)
                bundle = diagnostics.create_diagnostic_bundle(shell=shell)

            self.assertTrue(bundle.is_file())
            self.assertEqual(Path(td) / "MorphoLabel" / "diagnostics", bundle.parent)
            with zipfile.ZipFile(bundle) as archive:
                names = set(archive.namelist())
                self.assertIn("summary.json", names)
                self.assertIn("latest_exception.txt", names)
                self.assertIn("recent_events.log", names)
                self.assertNotIn("project.sqlite", names)
                content = "\n".join(
                    archive.read(name).decode("utf-8", errors="replace")
                    for name in names
                    if name.endswith((".json", ".txt", ".log"))
                )
            self.assertNotIn("secret-fish-001", content)
            self.assertNotIn("secret-fish-002", content)
            self.assertNotIn("secret-project", content)
            self.assertNotIn("SecretPlace", content)
            self.assertIn("<PROJECT_ROOT>", content)

    def test_shell_exposes_manual_and_automatic_diagnostic_paths(self):
        source=(Path(__file__).resolve().parents[1]/"app"/"ui"/"shell.py").read_text(encoding="utf-8")
        self.assertIn('label="Create diagnostic report..."', source)
        self.assertIn("def report_callback_exception", source)
        self.assertIn("create_diagnostic_bundle(shell=self)", source)
        self.assertIn("record_exception(type(exc),exc,exc.__traceback__)", source)
        self.assertIn('"Open report folder"', source)
        self.assertIn('"Copy path"', source)
        self.assertIn("lambda:self._open_report_location(bundle)", source)
        self.assertIn('subprocess.Popen(["explorer","/select,",str(bundle)])', source)
        self.assertIn('if not bundle.is_file():', source)
        self.assertNotIn("path_var=tk.StringVar", source)
        self.assertIn("self._show_diagnostic_report_dialog(bundle,title=\"MorphoLabel error\",intro=error_text)", source)

    def test_global_log_is_stored_in_local_app_state(self):
        source=(Path(__file__).resolve().parents[1]/"app"/"gui_crop_debug.py").read_text(encoding="utf-8")
        self.assertIn('LOG = app_state_dir() / "logs" / "app.log"', source)
        self.assertNotIn('ROOT / "app.log"', source)


if __name__ == "__main__":
    unittest.main()
