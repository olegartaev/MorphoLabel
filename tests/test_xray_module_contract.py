import unittest
from pathlib import Path

from app.extensions.builtins import module_registry
from app.modules.xray_counts import (
    EDITOR_METHOD_IDS, STAGES, _clean_reference, _default_structure, _scheme_display_model,
)
from app.xray_icons import XRAY_ICON_NAMES, render_rule_preview, render_xray_icon


class XRayOrientationAndStorageContractTests(unittest.TestCase):
    def test_project_creation_exposes_orientation_and_portable_source(self):
        source=(Path(__file__).resolve().parents[1]/"app/modules/xray_counts.py").read_text(encoding="utf-8")
        self.assertIn("class OrientationSetupDialog",source)
        self.assertIn("Head direction",source)
        self.assertIn("Anatomical bottom / ventral side",source)
        self.assertIn("Make self-contained",source)
        self.assertIn("Clear reproducible cache",source)


class XRayModuleContractTests(unittest.TestCase):
    def test_xray_module_is_available_and_taxon_neutral(self):
        spec=module_registry().get("xray_counts")
        self.assertEqual("available",spec.status)
        self.assertEqual("X-ray traits",spec.display_name)
        self.assertIsNotNone(spec.factory)
        self.assertNotIn("fish",spec.description.lower())

    def test_workflow_matches_landmarks_shape(self):
        self.assertEqual(("project","crops","structures","results","export"),tuple(item[0] for item in STAGES))

    def test_top_navigation_uses_landmarks_sizes_and_styles(self):
        source=(Path(__file__).resolve().parents[1]/"app/modules/xray_counts.py").read_text(encoding="utf-8")
        self.assertIn("TOPBAR_ICON_SIZE",source)
        self.assertIn('self._core_icon(nav,"modules")',source)
        self.assertIn('style="StageActive.TButton" if active else "Stage.TButton"',source)
        self.assertNotIn('self._icon(row,"xray",42)',source)

    def test_project_has_one_primary_entry_to_trait_configuration(self):
        source=(Path(__file__).resolve().parents[1]/"app/modules/xray_counts.py").read_text(encoding="utf-8")
        self.assertIn('"Traits..."',source)
        self.assertIn("Choose what to measure, how to count it, and which marks are used on the X-ray.",source)
        for obsolete in ("Choose traits...","Edit traits...","Open JSON...","Built-in schemes...","New blank...","Apply preset"):
            self.assertNotIn(obsolete,source)

    def test_traits_workspace_opens_maximized_with_portable_fallback(self):
        source=(Path(__file__).resolve().parents[1]/"app/modules/xray_counts.py").read_text(encoding="utf-8")
        self.assertIn("def _maximize_window",source)
        self.assertIn('self.state("zoomed")',source)
        self.assertIn('self.attributes("-zoomed",True)',source)
        self.assertIn('self._build();self._load_scheme(self.scheme,self.note);self._maximize_window();self.grab_set()',source)

    def test_main_trait_window_is_two_ordered_biological_steps(self):
        source=(Path(__file__).resolve().parents[1]/"app/modules/xray_counts.py").read_text(encoding="utf-8")
        for text in (
            "First define what you mark on the X-ray. Then build biological traits from those annotations.",
            "Define what you will mark on the X-ray",
            "Elements to count","Start / stop marks",
            "Build biological traits from those annotations",
            "Element to count","Stop at","What this rule means",
        ):
            self.assertIn(text,source)
        self.assertIn('step1,1,"annotation_setup"',source)
        self.assertIn('step2,2,"trait_setup"',source)
        self.assertIn("def _add_structure",source)
        self.assertIn("def _rename_structure",source)
        self.assertIn("def _remove_structure",source)
        self.assertNotIn("+ Add structure",source)
        self.assertNotIn("Selected structure",source)

    def test_counting_rule_menu_exposes_only_requested_rules(self):
        self.assertEqual(("count","count_to","count_between","derived"),EDITOR_METHOD_IDS)
        source=(Path(__file__).resolve().parents[1]/"app/modules/xray_counts.py").read_text(encoding="utf-8")
        for label in ("Count all","Count to a stop mark","Count between two reference marks","Calculate from other traits"):
            self.assertIn(label,source)
        self.assertIn("tuple(METHOD_ID_TO_LABEL[item] for item in EDITOR_METHOD_IDS)",source)

    def test_ready_made_menu_is_removed_but_portable_file_open_remains(self):
        source=(Path(__file__).resolve().parents[1]/"app/modules/xray_counts.py").read_text(encoding="utf-8")
        self.assertNotIn("Ready-made",source)
        self.assertNotIn("ready-made",source)
        self.assertNotIn("bundled_scheme_catalog",source)
        self.assertIn('menu.add_command(label="Open..."',source)
        self.assertIn("initialdir=str(SCHEME_RESOURCE_DIR)",source)

    def test_literature_is_visible_compact_and_editable(self):
        from app.xray_schema import blank_scheme
        self.assertEqual({},_clean_reference("","",""))
        model=_scheme_display_model(blank_scheme("Blank"))
        self.assertEqual("",model["reference_text"])
        source=(Path(__file__).resolve().parents[1]/"app/modules/xray_counts.py").read_text(encoding="utf-8")
        self.assertIn('text="Reference"',source)
        self.assertIn('text="DOI"',source)
        self.assertIn("Bogutskaya et al. (2020)",source)

    def test_annotation_appearance_is_optional_second_depth_only(self):
        source=(Path(__file__).resolve().parents[1]/"app/modules/xray_counts.py").read_text(encoding="utf-8")
        marker_start=source.index("class MarkerSettingsDialog")
        trait_start=source.index("class TraitSchemeDialog",marker_start)
        marker=source[marker_start:trait_start]
        for text in ("Colors & keys","Shortcut key","Marker shape","Color","Done"):
            self.assertIn(text,marker)
        for forbidden in ("+ Add structure","Add counted element","Add reference mark","Use for project"):
            self.assertNotIn(forbidden,marker)

    def test_trait_uses_explicit_lists_instead_of_implicitly_creating_structures(self):
        source=(Path(__file__).resolve().parents[1]/"app/modules/xray_counts.py").read_text(encoding="utf-8")
        self.assertNotIn("def _resolve_structure",source)
        self.assertIn("def _structure_id_by_name",source)
        self.assertIn("Choose an Element to count from step 1.",source)
        self.assertIn("Choose a Stop at mark from step 1.",source)
        self.assertIn("reference_end",source)

    def test_fields_have_contextual_tooltips(self):
        source=(Path(__file__).resolve().parents[1]/"app/modules/xray_counts.py").read_text(encoding="utf-8")
        self.assertIn("def _help",source)
        for help_text in (
            "Choose one of the Elements to count defined in step 1.",
            "Choose one of the Start / stop marks defined in step 1.",
            "Optional correction added after counting",
            "Choose whether the stop mark itself belongs to the count",
        ):
            self.assertIn(help_text,source)

    def test_default_structure_uses_distinct_repeated_and_reference_roles(self):
        from app.xray_schema import blank_scheme
        scheme=blank_scheme("test")
        one=_default_structure(scheme,"Vertebrae",True);scheme["structures"].append(one)
        two=_default_structure(scheme,"First caudal vertebra",False)
        self.assertEqual("1",one["hotkey"])
        self.assertEqual("2",two["hotkey"])
        self.assertTrue(one["repeated"])
        self.assertFalse(two["repeated"])

    def test_bundled_phoxinus_file_remains_portable_and_reference_is_compact(self):
        from app.xray_schema import bundled_scheme
        scheme=bundled_scheme("phoxinus_vertebral_counts")
        model=_scheme_display_model(scheme,"file")
        self.assertEqual("Bogutskaya et al. (2020)",model["reference_text"])
        self.assertEqual("10.1111/jfb.14210",model["reference_doi"])
        self.assertEqual(7,model["trait_count"])

    def test_xray_icons_include_role_step_and_fish_crop_icons(self):
        required={
            "xray","xray_project","xray_crops","xray_structures","xray_results","xray_export",
            "count","count_to","count_between","derived","counted_element","reference_mark",
            "annotation_setup","trait_setup",
        }
        self.assertTrue(required.issubset(XRAY_ICON_NAMES))
        for name in required:
            image=render_xray_icon(name,26)
            self.assertEqual((26,26),image.size)
            self.assertIsNotNone(image.getbbox(),name)
        source=(Path(__file__).resolve().parents[1]/"app/xray_icons.py").read_text(encoding="utf-8")
        self.assertIn("Large lateral fish skeleton silhouette for the Crops stage.",source)
        self.assertIn("_fish_skeleton_icon(d,p);_crop_brackets",source)
        self.assertIn('elif name=="counted_element"',source)
        self.assertIn('elif name=="reference_mark"',source)
        self.assertIn('elif name=="annotation_setup"',source)
        self.assertIn('elif name=="trait_setup"',source)

    def test_counting_rule_preview_supports_two_reference_marks(self):
        for method in ("count","count_to","count_between","derived"):
            image=render_rule_preview(
                method,"before","Vertebrae","First caudal vertebra","Last predorsal vertebra",(430,150)
            )
            self.assertEqual((430,150),image.size)
            self.assertIsNotNone(image.getbbox(),method)
        source=(Path(__file__).resolve().parents[1]/"app/xray_icons.py").read_text(encoding="utf-8")
        self.assertIn("reference_label2",source)
        self.assertIn("from {reference_label} to {reference_label2}",source)


if __name__=="__main__":
    unittest.main()
