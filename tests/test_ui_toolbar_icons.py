import unittest

from app.ui.icons import (
    CONTROL_ICON_SIZE,
    ICON_NAMES,
    TOPBAR_ICON_SIZE,
    render_icon,
)
from app.ui.section_registry import SECTIONS


class ToolbarIconContractTests(unittest.TestCase):
    def test_every_production_section_has_a_generic_topbar_icon(self):
        self.assertEqual({"project","crop","landmarks","measurements","export"},{section.key for section in SECTIONS})
        self.assertTrue({section.key for section in SECTIONS}.issubset(ICON_NAMES))
        self.assertIn("modules",ICON_NAMES)

    def test_icons_render_at_compact_toolbar_sizes(self):
        self.assertEqual(24,TOPBAR_ICON_SIZE)
        self.assertEqual(18,CONTROL_ICON_SIZE)
        for name in ICON_NAMES:
            for size in (CONTROL_ICON_SIZE,TOPBAR_ICON_SIZE):
                image=render_icon(name,size)
                self.assertEqual((size,size),image.size)
                self.assertEqual("RGBA",image.mode)
                self.assertIsNotNone(image.getbbox(),name)

    def test_landmark_toolbar_uses_only_existing_actions_with_variant_b_icons(self):
        text=open("app/ui/landmarks_section.py",encoding="utf-8").read()
        for label,icon in (
            ("Mark missing","missing"),
            ("Delete","delete"),
            ("Clear all…","clear"),
            ("Verify image","verify"),
            ("Display…","display"),
        ):
            self.assertIn(repr(label),text)
            self.assertIn("icon="+repr(icon),text)
        self.assertNotIn("'Undo'",text)
        self.assertNotIn("'Redo'",text)

    def test_exclude_button_changes_icon_without_changing_exclusion_semantics(self):
        text=open("app/ui/photo_list_panel.py",encoding="utf-8").read()
        self.assertIn("image=self._action_icon('exclude')",text)
        self.assertIn("self._action_icon('restore' if excluded else 'exclude')",text)
        self.assertIn("project.exclude_image(image_id,'User excluded',None)",text)
        self.assertIn("project.restore_image(image_id)",text)


if __name__=="__main__":
    unittest.main()
