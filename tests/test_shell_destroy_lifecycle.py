import gc
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image


class ShellDestroyLifecycleTests(unittest.TestCase):
    def test_destroy_releases_real_landmark_workspace_before_tcl_teardown(self):
        from app.project_storage import Project
        from app.ui.shell import ProductionShell
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            source=root/"source";source.mkdir()
            Image.new("RGB",(64,40)).save(source/"fish.png")
            schema=root/"schema.csv"
            schema.write_text("id,abbr,name,role\n1,A,Alpha,BOTH\n",encoding="utf-8")
            project=Project.create("shutdown",source,root,schema,source_types=["png"],source_layout="direct")
            with patch("app.modules.landmarks.last_project",return_value=None), \
                 patch.object(ProductionShell,"_warm_ai_hardware",return_value=None):
                shell=ProductionShell()
            shell.withdraw()
            shell.open_module("landmarks")
            shell._active_module_runtime.context.project=project
            shell._active_module_runtime.context.invalidate_catalog()
            for section in ("project","crop","landmarks","measurements","export"):
                shell._active_module_runtime.select(section)
                shell.update_idletasks()
            shell.destroy()
            gc.collect()
            self.assertTrue(shell._morpholabel_destroying)
            self.assertIsNone(shell._active_module_runtime)
            self.assertIsNone(shell.current_view)

    def test_module_hub_logo_is_owned_by_durable_shell(self):
        source=(Path(__file__).resolve().parents[1]/"app"/"ui"/"module_hub.py").read_text(encoding="utf-8")
        self.assertIn("self.shell._morpholabel_hub_icon=self.logo",source)


if __name__=="__main__":
    unittest.main()
