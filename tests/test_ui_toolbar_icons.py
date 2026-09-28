import unittest

from app.ui.icons import (
    CONTROL_ICON_SIZE,
    ICON_NAMES,
    TOPBAR_ICON_SIZE,
    WORKFLOW_ICON_SIZE,
    render_icon,
)
from app.ui.section_registry import SECTIONS


class ToolbarIconContractTests(unittest.TestCase):
    def test_every_production_section_has_a_generic_topbar_icon(self):
        self.assertEqual({"project","crop","landmarks","measurements","export"},{section.key for section in SECTIONS})
        self.assertTrue({section.key for section in SECTIONS}.issubset(ICON_NAMES))
        self.assertIn("modules",ICON_NAMES)
        self.assertTrue({"review_worst","complex_qc"}.issubset(ICON_NAMES))

    def test_icons_render_at_compact_toolbar_sizes(self):
        self.assertEqual(26,TOPBAR_ICON_SIZE)
        self.assertEqual(20,CONTROL_ICON_SIZE)
        for name in ICON_NAMES:
            for size in (CONTROL_ICON_SIZE,TOPBAR_ICON_SIZE):
                image=render_icon(name,size)
                self.assertEqual((size,size),image.size)
                self.assertEqual("RGBA",image.mode)
                self.assertIsNotNone(image.getbbox(),name)

    def test_landmark_toolbar_uses_only_existing_actions_with_selected_icons(self):
        text=open("app/ui/landmarks_section.py",encoding="utf-8").read()
        start=text.index("ttk.Label(controls,text='Landmark actions:'")
        end=text.index("batch=tk.IntVar",start)
        toolbar=text[start:end]
        for label,icon in (
            ("Mark missing","missing"),
            ("Delete","delete"),
            ("Clear all…","clear"),
            ("Verify image","verify"),
            ("Display…","display"),
        ):
            self.assertIn(repr(label),toolbar)
            self.assertIn("icon="+repr(icon),toolbar)
        self.assertNotIn("'Undo'",toolbar)
        self.assertNotIn("'Redo'",toolbar)


    def test_review_actions_have_distinct_icons_and_equal_layout(self):
        source=open("app/ui/landmarks_section.py",encoding="utf-8").read()
        self.assertIn("'Unverified AI review'",source)
        self.assertIn("'Final data QC'",source)
        self.assertIn("icon='review_worst'",source)
        self.assertIn("icon='complex_qc'",source)
        self.assertIn("uniform='review_actions'",source)
        self.assertIn("style='ReviewAction.TButton'",source)

    def test_selected_workflow_icons_render_and_sections_use_exact_current_mapping(self):
        selected={
            "crop_training","crop_train","crop_apply",
            "landmark_repeat","landmark_training","landmark_train","landmark_apply",
            "measurement_calibrate","measurement_define","measurement_export",
            "export_landmarks","export_measurements",
        }
        self.assertEqual(24,WORKFLOW_ICON_SIZE)
        self.assertTrue(selected.issubset(ICON_NAMES))
        for name in selected:
            image=render_icon(name,WORKFLOW_ICON_SIZE)
            self.assertEqual((WORKFLOW_ICON_SIZE,WORKFLOW_ICON_SIZE),image.size)
            self.assertIsNotNone(image.getbbox(),name)

        mappings={
            "app/ui/crop_section.py":(
                'icon="crop_training"','icon="crop_train"','icon="crop_apply"',
            ),
            "app/ui/landmarks_section.py":(
                "icon='landmark_repeat'","icon='landmark_training'",
                "icon='landmark_train'","icon='landmark_apply'",
            ),
            "app/ui/measurements_section.py":(
                "icon='measurement_calibrate'","icon='measurement_define'",
                "icon='measurement_export'",
            ),
            "app/ui/export_section.py":(
                "card_header('export_landmarks','Landmark coordinates')",
                "card_header('export_measurements','Measurements')",
            ),
        }
        for path,needles in mappings.items():
            source=open(path,encoding="utf-8").read()
            for needle in needles:self.assertIn(needle,source)

    def test_workflow_dock_uses_compact_drawn_icons_without_changing_card_layout(self):
        source=open("app/ui/workflow.py",encoding="utf-8").read()
        self.assertIn("icon in ICON_NAMES",source)
        self.assertIn("self.shell.ui_icon(icon, WORKFLOW_ICON_SIZE)",source)
        self.assertIn("card.grid(",source)

    def test_exclude_button_changes_icon_without_changing_exclusion_semantics(self):
        text=open("app/ui/photo_list_panel.py",encoding="utf-8").read()
        self.assertIn("image=self._action_icon('exclude')",text)
        self.assertIn("self._action_icon('restore' if excluded else 'exclude')",text)
        self.assertIn("project.exclude_image(image_id,'User excluded',None)",text)
        self.assertIn("project.restore_image(image_id)",text)


if __name__=="__main__":
    unittest.main()
