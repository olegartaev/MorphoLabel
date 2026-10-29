"""Release-facing UI contracts for the four user-reported defects.

These are fast source-level tests, supplementing the Windows GUI smoke, not a
substitute for testing actual user interaction and model checkpoints.
"""
import ast
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]


class UserFacingControlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.structures=(ROOT/"app/xray_structures_ui.py").read_text(encoding="utf-8")
        cls.workflow=(ROOT/"app/ui/workflow.py").read_text(encoding="utf-8")
        cls.evaluation=(ROOT/"app/xray_structure_ai.py").read_text(encoding="utf-8")
        cls.runner=(ROOT/"ai_runtime/xray_structure_runner.py").read_text(encoding="utf-8")

    def test_single_train_button_and_no_auxiliary_marker_counter(self):
        self.assertIn('train_actions,"Train",self.train_structure_ai',self.structures)
        self.assertNotIn('self.highres_train_button=',self.structures)
        self.assertNotIn('self.new_training_label=',self.structures)
        self.assertNotIn('self.training_parent_box.pack(',self.structures)
        self.assertIn('self.training_parent_choice.set(active_id if compatible_active',self.structures)
        self.assertIn('return self.train_highres_structure_ai()',self.structures)

    def test_comparison_runs_on_verified_and_not_only_val_membership(self):
        self.assertIn('split="all",progress=progress',self.structures)
        self.assertIn('if not rows:',self.evaluation)
        self.assertIn('human-verified specimens',self.structures)

    def test_no_wrong_kwarg_is_passed_to_legacy_decoder(self):
        module=ast.parse(self.runner)
        calls=[n for n in ast.walk(module)
               if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=="_decode_one"]
        self.assertTrue(calls)
        self.assertTrue(all(not any(k.arg in ("preprocessing","preprocessing_report") for k in call.keywords)
                            for call in calls))

    def test_empty_scrollbars_auto_hide(self):
        self.assertIn('autohide_scroll_command(scroll)',self.workflow)
        self.assertIn('autohide_scroll_command(marker_scroll)',self.structures)
        self.assertIn('autohide_scroll_command(scroll,geometry="pack")',self.structures)


if __name__=="__main__":
    unittest.main()
