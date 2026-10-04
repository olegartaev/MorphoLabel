import unittest
from pathlib import Path

from app.ui.icons import TOPBAR_ICON_SIZE, render_icon


ROOT=Path(__file__).resolve().parents[1]


def source(relative):
    return (ROOT/relative).read_text(encoding="utf-8")


class ReleaseUIUnificationTests(unittest.TestCase):
    def test_one_shared_queue_presentation_replaces_duplicate_section_banners(self):
        crop=source("app/ui/crop_section.py")
        landmarks=source("app/ui/landmarks_section.py")
        shell=source("app/ui/shell.py")
        queue_center=source("app/ui/queue_center.py")
        self.assertNotIn("self.attention_banner(",crop)
        self.assertNotIn("self.attention_banner(",landmarks)
        self.assertIn('style="Attention.TFrame"',shell)
        self.assertIn('text=queue_text,image=self.ui_icon("queues"',shell)
        self.assertIn('"Open"',queue_center)
        self.assertIn('"Close queue"',queue_center)

    def test_queue_button_has_a_distinct_pictorial_icon(self):
        image=render_icon("queues",TOPBAR_ICON_SIZE)
        self.assertEqual((TOPBAR_ICON_SIZE,TOPBAR_ICON_SIZE),image.size)
        self.assertIsNotNone(image.getbbox())

    def test_context_rows_use_bold_keys_and_readable_values(self):
        shell=source("app/ui/shell.py")
        crop=source("app/xray_crop_ui.py")
        structures=source("app/xray_structures_ui.py")
        module=source("app/modules/xray_counts.py")
        self.assertIn('text="Sample:",style="ContextKey.TLabel"',shell)
        self.assertIn('status_locality=ElidedLabel',shell)
        self.assertIn('columnconfigure(1,weight=1,minsize=180)',shell)
        self.assertIn('text="Sample:",style="ContextKey.TLabel"',crop)
        self.assertIn('text="Plate:",style="ContextKey.TLabel"',crop)
        self.assertIn('text="Crop:",style="ContextKey.TLabel"',crop)
        self.assertIn('text="Sample:",style="ContextKey.TLabel"',structures)
        self.assertIn('text="Specimen №:",style="ContextKey.TLabel"',structures)
        self.assertIn('style="ContextKey.TLabel"',module)
        self.assertIn('style="ContextValue.TLabel"',module)

    def test_human_repeatability_is_named_explicitly_in_both_annotation_workflows(self):
        landmarks=source("app/ui/landmarks_section.py")
        structures=source("app/xray_structures_ui.py")
        self.assertIn("1. Human Repeatability",landmarks)
        self.assertIn("Human Repeatability…",landmarks)
        self.assertIn("1. Human Repeatability",structures)
        self.assertIn("Human Repeatability…",structures)
        self.assertNotIn("add_card('1. Repeatability'",landmarks)
        self.assertNotIn('add_card("1. Repeatability"',structures)

    def test_training_cards_share_active_from_train_models_pattern(self):
        crop=source("app/ui/crop_section.py")
        landmarks=source("app/ui/landmarks_section.py")
        xcrop=source("app/xray_crop_ui.py")
        structures=source("app/xray_structures_ui.py")
        for value in (crop,landmarks,xcrop,structures):
            self.assertIn("Train model",value)
            self.assertIn("Active:",value)
            self.assertIn('text="From"',value)
            self.assertIn("Models…",value)
        self.assertIn("Verified Crop data",crop)
        self.assertIn("RTMDet pretrained",xcrop)
        self.assertIn("ImageNet ResNet18",structures)

    def test_xray_training_parent_choices_are_real_saved_models_not_decorative_fields(self):
        crop=source("app/xray_crop_ui.py")
        structures=source("app/xray_structures_ui.py")
        detector=source("app/xray_detector.py")
        structure_ai=source("app/xray_structure_ai.py")
        self.assertIn('parent_values=("RTMDet pretrained",)+tuple(item["model_id"] for item in self.project.crop_models())',crop)
        self.assertIn('parent_values=("ImageNet ResNet18",)+tuple(item["model_id"] for item in self.project.structure_models())',structures)
        self.assertIn("parent_model_id=parent_model_id",crop)
        self.assertIn("parent_model_id=parent_model_id",structures)
        self.assertIn("def train_detector(project,seed=42,epochs=80,progress=None,parent_model_id=None):",detector)
        self.assertIn("def train_structure_model(project, seed=42, epochs=60, progress=None, parent_model_id=None):",structure_ai)

    def test_structures_never_stacks_two_yellow_queue_banners(self):
        structures=source("app/xray_structures_ui.py")
        self.assertIn("if ids and current in ids and result_queue is None:",structures)
        self.assertIn("detail=item.get(\"top_reason\")",structures)
        banner=structures[structures.index("def _refresh_result_review_banner"):structures.index("def _move_result_review")]
        self.assertNotIn("\\n{item.get('top_reason')",banner)

    def test_traits_editor_scrolls_and_has_no_dead_appearance_button_reference(self):
        module=source("app/modules/xray_counts.py")
        self.assertIn("_trait_scroll_canvas",module)
        self.assertIn('ttk.Scrollbar(shell,orient="vertical"',module)
        self.assertIn('self.bind("<MouseWheel>"',module)
        self.assertNotIn("appearance_button",module)

    def test_xray_predict_current_refreshes_for_the_selected_nonexcluded_plate(self):
        crop=source("app/xray_crop_ui.py")
        self.assertIn("def _refresh_predict_current_state",crop)
        self.assertIn('current_ok=not bool(image.get("excluded"))',crop)
        self.assertNotIn('current_ok=not bool(image.get("excluded")) and not bool(image.get("crop_reviewed"))',crop)
        self.assertIn("self._refresh_plate_context();self._refresh_predict_current_state()",crop)

    def test_modules_are_visually_separated_and_queues_sit_left_of_menu(self):
        shell=source("app/ui/shell.py")
        xray=source("app/modules/xray_counts.py")
        self.assertIn('ttk.Separator(row,orient="vertical")',shell)
        self.assertIn('ttk.Separator(nav,orient="vertical")',xray)
        menu_pack=shell.index('button.configure(menu=menu);button.pack(side="right"')
        queue_pack=shell.index('queues.pack(side="right"',menu_pack)
        self.assertGreater(queue_pack,menu_pack)


if __name__=="__main__":
    unittest.main()
