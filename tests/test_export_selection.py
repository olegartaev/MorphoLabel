import unittest
from pathlib import Path

from app.export_formats import selected_groups


class ExportSelectionTests(unittest.TestCase):
    def test_all_mode_is_represented_by_empty_group_filter(self):
        self.assertEqual((), selected_groups(("GM", "Meristics"), {}))

    def test_manual_selection_keeps_only_checked_groups_in_display_order(self):
        groups = ("GM", "Meristics", "Shape")
        self.assertEqual(("GM", "Shape"), selected_groups(groups, {"GM": True, "Meristics": False, "Shape": True}))

    def test_export_ui_uses_individual_group_checkboxes(self):
        source = (Path(__file__).parents[1] / "app/ui/export_section.py").read_text(encoding="utf-8")
        self.assertIn("ttk.Checkbutton", source)
        self.assertIn("selected_groups", source)
        self.assertIn("text='Choose groups'", source)


if __name__ == "__main__":
    unittest.main()
