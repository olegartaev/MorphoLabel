import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.ui import preferences
from app.ui.module_credits import module_credit_rows

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
        self.assertIn('def build_queue_navigation(self,parent):',shell)
        self.assertIn('text="Queues",image=self.ui_icon("queues"',shell)
        self.assertNotIn('queue_text=f"Queues (',shell)
        self.assertIn("self.shell.build_queue_navigation(header)",crop)
        self.assertIn("self.shell.build_queue_navigation(header)",landmarks)
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
        self.assertIn('text="Specimen №:",style="ContextKey.TLabel"',crop)
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
        self.assertIn('crop_models=self.context.project.models("crop")',crop)
        self.assertIn("Bootstrap / first model",crop)
        self.assertNotIn("Verified Crop data",crop)
        self.assertIn("RTMDet pretrained",xcrop)
        self.assertIn("ImageNet ResNet18",structures)

    def test_core_crop_from_selector_uses_registered_model_lineage(self):
        crop=source("app/ui/crop_section.py")
        training=source("app/crop_training.py")
        storage=source("app/project_storage.py")
        self.assertIn('crop_models=self.context.project.models("crop")',crop)
        self.assertIn('parent_default=active_crop.get("model_id")',crop)
        self.assertIn("parent_model_id=parent_model_id",crop)
        self.assertIn("def train_project(project,seed=42,ridge=1.0,parent_model_id=None):",training)
        self.assertIn("lineage_parent=previous if parent_model_id is None",training)
        self.assertIn("def models(self,kind):",storage)

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

    def test_queue_center_close_removes_queue_navigation_state(self):
        shell=source("app/ui/shell.py")
        review=source("app/landmark_ai_review.py")
        self.assertIn("close_review_session(project,batch_id)",shell)
        self.assertIn('project.set_ui_state("crop_active_batch",{})',shell)
        self.assertIn('project.set_ui_state("landmark_training_queue_closed"',shell)
        self.assertIn('workflow_nav_closed=workflow_nav_key in self.__dict__.get("_closed_queue_navigation",set())',shell)
        self.assertIn("def close_review_session(project,batch_id=None):",review)
        self.assertIn('"closed":True',review)
        self.assertIn('not item.get("closed")',review)

    def test_xray_queue_buttons_are_grouped_right_and_close_reveals_any_remaining_queue(self):
        structures=source("app/xray_structures_ui.py")
        self.assertIn('review_actions=ttk.Frame(self.review_queue_banner',structures)
        self.assertIn('review_actions.pack(side="right")',structures)
        self.assertIn('annotation_actions=ttk.Frame(self.annotation_queue_banner',structures)
        self.assertIn('annotation_actions.pack(side="right")',structures)
        self.assertIn('clear_result_review_queue(self.project);self._refresh_workflow()',structures)

    def test_xray_queue_navigation_uses_shared_nav_button_styles(self):
        structures=source("app/xray_structures_ui.py")
        self.assertGreaterEqual(structures.count('style="Nav.TButton"'),2)
        self.assertIn('style="NavPrimary.TButton"',structures)

    def test_workflow_uses_real_icon_tabs_without_vertical_divider_bars(self):
        workflow=source("app/ui/workflow.py")
        self.assertIn("ttk.Notebook(self,style='Workflow.TNotebook')",workflow)
        self.assertIn("self.notebook.add(card,**options)",workflow)
        self.assertIn("options['image']=image",workflow)
        separator=workflow[workflow.index("def add_command_separator"):workflow.index("def build_help_button")]
        self.assertNotIn("ttk.Separator",separator)

    def test_verify_apply_and_predict_current_button_contracts(self):
        landmarks=source("app/ui/landmarks_section.py")
        crop=source("app/xray_crop_ui.py")
        structures=source("app/xray_structures_ui.py")
        self.assertIn("self.predict_current_button=self.button(",landmarks)
        self.assertIn("def predict_current(self):",landmarks)
        self.assertIn("state='normal' if active and eligible else 'disabled'",landmarks)
        self.assertIn("def _current_apply_needed(self):",crop)
        self.assertIn('button.configure(state="normal" if needed else "disabled")',crop)
        self.assertIn('self.apply_button.configure(text="Verified ✓" if verified else "Verify specimen",state=state)',structures)
        self.assertNotIn('"Next unfinished"',structures)

    def test_xray_last_project_preference_is_separate_and_runtime_restores_it(self):
        with tempfile.TemporaryDirectory() as root:
            state=Path(root)/"state";core=Path(root)/"core";xray=Path(root)/"xray";core.mkdir();xray.mkdir()
            with patch.object(preferences,"app_state_dir",return_value=state):
                self.assertTrue(preferences.remember_project(core))
                self.assertTrue(preferences.remember_xray_project(xray))
                self.assertEqual(core.resolve(),preferences.last_project())
                self.assertEqual(xray.resolve(),preferences.last_xray_project())
        module=source("app/modules/xray_counts.py")
        self.assertIn("self._restore_last_project()",module)
        self.assertIn("remember_xray_project(self.project.root)",module)

    def test_about_ai_rows_follow_the_active_xray_model(self):
        class Registry:
            def available(self):
                return (
                    SimpleNamespace(module_id="landmarks",display_name="Landmarks",source="builtin",description=""),
                    SimpleNamespace(module_id="xray_counts",display_name="X-ray Traits",source="builtin",description=""),
                )
        class Project:
            def __init__(self):self.crop_id="crop-v1";self.structure_id="structures-v1"
            def active_crop_model(self):
                return {"model_id":self.crop_id,"metrics":{"backend":"rtmdet_tiny_mmdet_3_2","orientation/backend":"mobilenet_v3_small_imagenet_transfer_v1"}}
            def active_structure_model(self):
                return {"model_id":self.structure_id,"backend":"resnet18_heatmap_v1","metrics":{}}
        project=Project()
        shell=SimpleNamespace(
            module_key="xray_counts",_active_module_runtime=SimpleNamespace(project=project),
            context=SimpleNamespace(project=None),
        )
        first={name:ai for name,_author,_scope,ai in module_credit_rows(Registry(),shell)}
        self.assertIn("RTMDet-tiny",first["X-ray Traits"])
        self.assertIn("MobileNetV3-Small",first["X-ray Traits"])
        self.assertIn("ResNet-18 heatmap",first["X-ray Traits"])
        self.assertIn("crop-v1",first["X-ray Traits"]);self.assertIn("structures-v1",first["X-ray Traits"])
        project.crop_id="crop-v2";project.structure_id="structures-v2"
        second={name:ai for name,_author,_scope,ai in module_credit_rows(Registry(),shell)}
        self.assertIn("crop-v2",second["X-ray Traits"]);self.assertNotIn("crop-v1",second["X-ray Traits"])
        self.assertIn("structures-v2",second["X-ray Traits"]);self.assertNotIn("structures-v1",second["X-ray Traits"])

    def test_about_design_keeps_author_subdued_and_each_module_self_contained(self):
        about=source("app/ui/shell.py")
        credits=source("app/ui/module_credits.py")
        self.assertIn("module_box=ttk.LabelFrame(credits,text=name",about)
        self.assertIn('text=f"Author: {author}",style="Muted.TLabel"',about)
        for text in ("RTMPose-M","RTMDet-tiny","MobileNetV3-Small","ResNet-18 heatmap","NumPy ridge image regression"):
            self.assertIn(text,credits)

    def test_xray_specimen_number_means_ordinal_on_current_plate(self):
        structures=source("app/xray_structures_ui.py")
        module=source("app/modules/xray_counts.py")
        context=structures[structures.index("def _set_context"):structures.index("def _refresh_plate_context") if "def _refresh_plate_context" in structures else structures.index("def refresh(",structures.index("def _set_context"))]
        self.assertIn('int(item.get("ordinal") or 0)',context)
        self.assertNotIn("structure_workflow_number",context)
        self.assertIn('tree.heading("row_no",text="#")',module)
        self.assertIn('tree.heading("locality",text="Sample")',module)
        self.assertIn('tree.heading("fish",text="Specimen №")',module)
        self.assertIn("self._refresh_selection_context()",module)

    def test_structure_list_preserves_scroll_when_workspace_refreshes(self):
        structures=source("app/xray_structures_ui.py")
        self.assertIn("self.specimen_list.refresh(preserve_scroll=True,reveal=True)",structures)
        self.assertIn("self.canvas.see(visible,align_top=False)",structures)
        self.assertIn("self.specimen_list.select(specimen_id,reveal=False)",structures)
        self.assertIn("self.pass_no.set(1);self.specimen_list.pass_no=1;self.refresh()",structures)

    def test_active_models_are_initial_training_parent_choices(self):
        landmarks=source("app/ui/landmarks_section.py")
        xcrop=source("app/xray_crop_ui.py")
        structures=source("app/xray_structures_ui.py")
        self.assertIn("chosen=active.get('model_id') if active.get('model_id') in valid",landmarks)
        self.assertIn('if not getattr(self,"_training_parent_touched",False) or current_parent not in parent_values:',xcrop)
        self.assertIn('if not getattr(self,"_training_parent_touched",False) or current_parent not in parent_values:',structures)
        self.assertIn("self._training_parent_touched=False;refresh();self._refresh_controls()",xcrop)
        self.assertIn("self._training_parent_touched=False;reload(model_id);self._refresh_workflow()",structures)

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

    def test_queue_strip_is_mounted_after_toolbar_and_before_image(self):
        crop=source("app/ui/crop_section.py")
        landmarks=source("app/ui/landmarks_section.py")
        self.assertLess(crop.index('self.shell.build_queue_navigation(header)'),crop.index('self.canvas_frame=ttk.Frame(panel)'))
        self.assertLess(landmarks.index('controls.relayout()'),landmarks.index('self.shell.build_queue_navigation(header)'))
        self.assertLess(landmarks.index('self.shell.build_queue_navigation(header)'),landmarks.index("batch=tk.IntVar"))
        shell=source("app/ui/shell.py")
        self.assertIn('actions=ttk.Frame(navigation,style="Attention.TFrame");actions.pack(side="right")',shell)

    def test_xray_queue_close_returns_repeatability_list_to_main_pass(self):
        structures=source("app/xray_structures_ui.py")
        close_block=structures[structures.index("def _close_annotation_batch"):structures.index("def _refresh_prediction_info")]
        self.assertIn('self.project.set_ui_state("xray_structure_active_batch",{})',close_block)
        self.assertIn("self.pass_no.set(1);self.specimen_list.pass_no=1",close_block)
        self.assertIn("self.refresh()",close_block)
        module=source("app/modules/xray_counts.py")
        self.assertNotIn('Queues (',module)
        self.assertIn('title="Human Repeatability" if pass_no>1 else "Structure annotation batch"',module)

    def test_xray_selection_is_one_project_state_across_crop_structure_and_export(self):
        module=source("app/modules/xray_counts.py")
        self.assertIn("return self.project.current_selection()",module)
        self.assertIn("self.project.set_current_selection(image_id=image_id,specimen_id=specimen_id)",module)
        self.assertIn('initial_image_id=selection.get("image_id"),initial_specimen_id=selection.get("specimen_id")',module)
        self.assertGreaterEqual(module.count('initial_image_id=selection.get("image_id"),initial_specimen_id=selection.get("specimen_id")'),2)
        self.assertIn('self._set_selection(specimen["image_id"],chosen[0]);self._refresh_selection_context()',module)

    def test_export_uses_plate_ordinal_for_specimen_number_and_keeps_row_index_separate(self):
        module=source("app/modules/xray_counts.py")
        self.assertIn('tree.heading("row_no",text="#")',module)
        self.assertIn('tree.heading("fish",text="Specimen №")',module)
        self.assertIn('int(row.get("ordinal") or 0)',module)
        self.assertIn("workflow_no=int(row.get(\"workflow_no\") or index)",module)

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
