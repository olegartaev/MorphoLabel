import unittest

from app.extensions.builtins import module_registry
from app.modules.xray_counts import STAGES
from app.xray_icons import XRAY_ICON_NAMES, render_xray_icon

class XRayModuleContractTests(unittest.TestCase):
    def test_xray_module_is_available_and_taxon_neutral(self):
        spec=module_registry().get("xray_counts")
        self.assertEqual("available",spec.status);self.assertEqual("X-ray traits",spec.display_name);self.assertIsNotNone(spec.factory)
        self.assertNotIn("fish",spec.description.lower())

    def test_workflow_matches_landmark_shape(self):
        self.assertEqual(("project","crops","structures","results","export"),tuple(item[0] for item in STAGES))

    def test_xray_ui_exposes_reusable_presets_and_clear_empty_states(self):
        source=open("app/modules/xray_counts.py",encoding="utf-8").read()
        for text in ("Apply preset…","Create traits…","New blank…","Import…","No traits yet","No annotation structures","Nothing to export"):
            self.assertIn(text,source)
        self.assertIn("preset_catalog()",source)
        self.assertIn("preset_scheme(dialog.result)",source)
        self.assertIn("Existing project data and earlier scheme versions will be kept.",source)
        self.assertIn("active_marker.configure",source)
        self.assertIn("foreground=s.get(\"color\"",source)
        self.assertIn("press its number key",source)

    def test_xray_and_trait_icons_render_at_production_sizes(self):
        required={"xray","xray_project","xray_crops","xray_structures","xray_results","xray_export","count","count_to","count_between","position","presence","distance","angle","derived"}
        self.assertTrue(required.issubset(XRAY_ICON_NAMES))
        for name in required:
            image=render_xray_icon(name,26);self.assertEqual((26,26),image.size);self.assertIsNotNone(image.getbbox(),name)

if __name__=="__main__":unittest.main()
