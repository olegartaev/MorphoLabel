import unittest
from pathlib import Path

from app.extensions.builtins import module_registry
from app.modules.xray_counts import STAGES, _clean_reference, _replace_trait_definition, _scheme_display_model
from app.xray_icons import XRAY_ICON_NAMES, render_xray_icon

class XRayModuleContractTests(unittest.TestCase):
    def test_xray_module_is_available_and_taxon_neutral(self):
        spec=module_registry().get("xray_counts")
        self.assertEqual("available",spec.status);self.assertEqual("X-ray traits",spec.display_name);self.assertIsNotNone(spec.factory)
        self.assertNotIn("fish",spec.description.lower())

    def test_workflow_matches_landmark_shape(self):
        self.assertEqual(("project","crops","structures","results","export"),tuple(item[0] for item in STAGES))

    def test_project_ui_keeps_scheme_actions_biologist_facing_and_compact(self):
        source=(Path(__file__).resolve().parents[1]/"app/modules/xray_counts.py").read_text(encoding="utf-8")
        for text in (
            "Project setup","Source X-rays","Trait scheme","Traits",
            "Choose traits...","Edit traits...","More...","Save scheme copy...",
            "Existing annotations and earlier scheme versions will be kept.",
            "Active structure","Structure keys","Manual repeatability",
        ):self.assertIn(text,source)
        self.assertIn("bundled_scheme_catalog()",source)
        self.assertIn("load_scheme_file(path)",source)
        self.assertIn("save_scheme_file(self.project.scheme,path)",source)
        for technical in ("Open JSON...","Save as JSON...","Built-in schemes...","New blank...","Choose / open scheme...","Apply preset"):
            self.assertNotIn(technical,source)

    def test_choose_traits_dialog_is_one_clear_choice_screen(self):
        source=(Path(__file__).resolve().parents[1]/"app/modules/xray_counts.py").read_text(encoding="utf-8")
        start=source.index("class SchemeLibraryDialog")
        end=source.index("class SchemeReferenceDialog",start)
        block=source[start:end]
        for text in ("Choose traits","Ready-made sets","What it contains","Open saved scheme...","Create my own...","Use selected"):
            self.assertIn(text,block)
        for text in ("Open JSON...","New scheme...","Edit selected...","Source:","Available schemes"):
            self.assertNotIn(text,block)
        self.assertLess(block.index("self.apply=ttk.Button"),block.index("if self._entries:"))

    def test_new_project_starts_blank_without_nested_scheme_chooser(self):
        source=(Path(__file__).resolve().parents[1]/"app/modules/xray_counts.py").read_text(encoding="utf-8")
        self.assertIn('blank_scheme(),scheme_note="Blank scheme created with project"',source)
        self.assertNotIn("def _initial_scheme",source)

    def test_trait_rows_are_editable_and_navigation_reuses_landmarks_stage_style(self):
        source=(Path(__file__).resolve().parents[1]/"app/modules/xray_counts.py").read_text(encoding="utf-8")
        self.assertIn('self.tree.bind("<Double-1>",self._edit_selected',source)
        self.assertIn('"Edit"',source)
        self.assertIn('text=("● "+label) if active else label',source)
        self.assertIn('style="StageActive.TButton" if active else "Stage.TButton"',source)
        self.assertNotIn("XrayStageActive.TButton",source)

    def test_scheme_display_is_identical_for_bundled_and_saved_content(self):
        from app.xray_schema import bundled_scheme
        scheme=bundled_scheme("phoxinus_vertebral_counts")
        bundled=_scheme_display_model(scheme,"Built-in · phoxinus_vertebral_counts.json")
        saved=_scheme_display_model(scheme,"File · my_scheme.json")
        for key in ("name","description","trait_count","structure_count","trait_abbrs","reference_text","reference_doi","reference_note"):
            self.assertEqual(bundled[key],saved[key])
        self.assertNotEqual(bundled["source"],saved["source"])

    def test_reference_is_optional_and_empty_reference_has_no_display_text(self):
        from app.xray_schema import blank_scheme
        self.assertEqual({},_clean_reference("","",""))
        model=_scheme_display_model(blank_scheme("Blank"))
        self.assertEqual("",model["reference_text"])
        self.assertEqual("",model["reference_doi"])

    def test_trait_edit_replaces_definition_and_prunes_only_unused_unannotated_structures(self):
        from app.xray_schema import bundled_scheme
        scheme=bundled_scheme("phoxinus_vertebral_counts")
        replacement={"id":"preap","name":"Pre-anal supports","abbr":"preAp","method":"count","structures":["vertebra"],"rule":{}}
        pruned=_replace_trait_definition(scheme,"preap",replacement,(),{})
        self.assertEqual("Pre-anal supports",next(t for t in pruned["traits"] if t["id"]=="preap")["name"])
        self.assertNotIn("preanal_pterygiophore",{s["id"] for s in pruned["structures"]})
        preserved=_replace_trait_definition(scheme,"preap",replacement,(),{"preanal_pterygiophore":4})
        self.assertIn("preanal_pterygiophore",{s["id"] for s in preserved["structures"]})

    def test_xray_and_trait_icons_render_at_production_sizes(self):
        required={"xray","xray_project","xray_crops","xray_structures","xray_results","xray_export","count","count_to","count_between","position","presence","distance","angle","derived"}
        self.assertTrue(required.issubset(XRAY_ICON_NAMES))
        for name in required:
            image=render_xray_icon(name,38);self.assertEqual((38,38),image.size);self.assertIsNotNone(image.getbbox(),name)
        source=(Path(__file__).resolve().parents[1]/"app/xray_icons.py").read_text(encoding="utf-8")
        self.assertIn("XRAY_ICON_SIZE=38",source)
        self.assertIn("def _vertebra",source)
        self.assertIn("One large lateral-view fish vertebra",source)
        self.assertIn("deliberately not a row of dots",source)
        for name in ("xray_project","xray_crops","xray_structures","xray_results","xray_export"):
            self.assertIn(f'elif name=="{name}"',source)
        self.assertNotIn('return render_icon("project",size)',source)
        self.assertNotIn('return render_icon("crop",size)',source)
        self.assertNotIn('return render_icon("landmarks",size)',source)
        self.assertNotIn('return render_icon("export",size)',source)
        self.assertNotIn('CYAN=',source)
        self.assertNotIn('PURPLE=',source)

if __name__=="__main__":unittest.main()
