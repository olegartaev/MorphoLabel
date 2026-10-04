import unittest
from pathlib import Path

from app.extensions.builtins import module_registry
from app.modules.xray_counts import (
    EDITOR_METHOD_IDS, STAGES, _clean_reference, _default_structure, _derived_builder_from_rule,
    _derived_rule_from_builder, _derived_trait_choices, _reference_relation_text,
    _renumber_default_structure_hotkeys, _scheme_display_model, _sort_export_tree,
)
from app.xray_icons import VISIBILITY_ICON_SIZE, VISIBILITY_STATES, XRAY_ICON_NAMES, _count_to_indices, render_rule_preview, render_visibility_icon, render_xray_icon


class XRayOrientationAndStorageContractTests(unittest.TestCase):
    def test_project_creation_exposes_orientation_and_portable_source(self):
        source=(Path(__file__).resolve().parents[1]/"app/modules/xray_counts.py").read_text(encoding="utf-8")
        self.assertIn("class OrientationSetupDialog",source)
        self.assertIn("Head faces",source)
        self.assertIn("Ventral side faces",source)
        self.assertIn("Confirmed crops teach orientation.",source)
        self.assertIn("Original X-rays stay unchanged.",source)
        self.assertIn("Don't standardize",source)
        self.assertIn("Make self-contained",source)
        self.assertIn("Clear reproducible cache",source)


class XRayModuleContractTests(unittest.TestCase):
    def test_xray_module_is_available_and_taxon_neutral(self):
        spec=module_registry().get("xray_counts")
        self.assertEqual("available",spec.status)
        self.assertEqual("X-ray traits",spec.display_name)
        self.assertIsNotNone(spec.factory)
        self.assertNotIn("fish",spec.description.lower())

    def test_visibility_icons_are_large_readable_and_semantically_distinct(self):
        self.assertEqual(32,VISIBILITY_ICON_SIZE)
        images={state:render_visibility_icon(state) for state in VISIBILITY_STATES}
        for state,image in images.items():
            self.assertEqual((VISIBILITY_ICON_SIZE,VISIBILITY_ICON_SIZE),image.size)
            self.assertIsNotNone(image.getbbox(),state)
        self.assertEqual(len(images),len({image.tobytes() for image in images.values()}))
        self.assertNotEqual(images["not_visible"].tobytes(),images["absent"].tobytes())

    def test_workflow_matches_landmarks_shape(self):
        self.assertEqual(("project","crops","structures","export"),tuple(item[0] for item in STAGES))

    def test_top_navigation_uses_landmarks_sizes_and_styles(self):
        source=(Path(__file__).resolve().parents[1]/"app/modules/xray_counts.py").read_text(encoding="utf-8")
        self.assertIn("TOPBAR_ICON_SIZE",source)
        self.assertIn('self._core_icon(nav,"modules")',source)
        self.assertIn('style="StageActive.TButton" if active else "Stage.TButton"',source)
        self.assertNotIn('self._icon(row,"xray",42)',source)

    def test_traits_workspace_has_explicit_visible_project_apply_action(self):
        source=(Path(__file__).resolve().parents[1]/"app/modules/xray_counts.py").read_text(encoding="utf-8")
        self.assertIn('"Use these traits for project"',source)
        self.assertIn("Changes are not saved until you choose this button.",source)
        self.assertIn("self.apply_button.pack(side=\"right\"",source)

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
        self.assertIn('self._build();self._load_scheme(self.scheme,self.note);self.after(60,self._maximize_window);self.grab_set()',source)
        self.assertIn('if sys.platform.startswith("win"):',source)
        self.assertIn('self.geometry("1320x900")',source)

    def test_main_trait_window_is_two_ordered_biological_steps(self):
        source=(Path(__file__).resolve().parents[1]/"app/modules/xray_counts.py").read_text(encoding="utf-8")
        for text in (
            "First define the anatomical marks. Then define the biological traits calculated from them.",
            "Define the anatomical marks",
            "Elements to count","Reference marks",
            "Define biological traits",
            "Anatomical landmarks used as counting boundaries",
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

    def test_reference_creation_asks_for_biological_relationship_in_plain_language(self):
        source=(Path(__file__).resolve().parents[1]/"app/modules/xray_counts.py").read_text(encoding="utf-8")
        for text in (
            "How is this reference related?",
            "It is one of the elements in an existing series",
            "It is a separate anatomical mark",
            "Choose the biological relationship.",
            "Relationship…",
        ):
            self.assertIn(text,source)
        from app.xray_schema import blank_scheme
        scheme=blank_scheme("relationships")
        series=_default_structure(scheme,"Serial elements",True);scheme["structures"].append(series)
        role=_default_structure(scheme,"Special element",False);role.update({"learning_relation":"role_on_structure","reuse_from":[series["id"]]});scheme["structures"].append(role)
        independent=_default_structure(scheme,"Boundary",False);independent.update({"learning_relation":"independent","reuse_from":[]});scheme["structures"].append(independent)
        self.assertEqual("one of Serial elements",_reference_relation_text(scheme,role))
        self.assertEqual("separate anatomical mark",_reference_relation_text(scheme,independent))

    def test_counting_rule_menu_exposes_only_requested_rules(self):
        self.assertEqual(("count","count_to","count_between","derived"),EDITOR_METHOD_IDS)
        source=(Path(__file__).resolve().parents[1]/"app/modules/xray_counts.py").read_text(encoding="utf-8")
        for label in ("Count all","Count to a stop mark","Count between two reference marks","Calculate from other traits"):
            self.assertIn(label,source)
        self.assertIn("tuple(METHOD_ID_TO_LABEL[item] for item in EDITOR_METHOD_IDS)",source)

    def test_derived_traits_use_visual_builder_without_formula_typing(self):
        rule=_derived_rule_from_builder("abdv","subtract","caudv")
        self.assertEqual({"expression":"abdv-caudv","depends_on":["abdv","caudv"]},rule)
        parsed=_derived_builder_from_rule(rule)
        self.assertEqual("subtract",parsed["operation"])
        joined=_derived_rule_from_builder("abdv","join","caudv","+")
        self.assertEqual("abdv+'+'+caudv",joined["expression"])
        self.assertEqual("join",_derived_builder_from_rule(joined)["operation"])
        scheme={
            "traits":[
                {"id":"a","abbr":"A","name":"First"},
                {"id":"b","abbr":"B","name":"Second"},
            ]
        }
        self.assertEqual([("B — Second","b")],_derived_trait_choices(scheme,"a"))
        source=(Path(__file__).resolve().parents[1]/"app/modules/xray_counts.py").read_text(encoding="utf-8")
        editor=source[source.index("    def _build_trait_editor"):source.index("    def _capture_scheme_fields")]
        self.assertIn('text="A · First trait"',editor)
        self.assertIn('text="Combine as"',editor)
        self.assertIn('text="B · Second trait"',editor)
        self.assertIn('text="Preview"',editor)
        self.assertIn('state="readonly"',editor)
        self.assertNotIn('text="Formula"',editor)
        self.assertNotIn('text="Uses traits"',editor)

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
        toolbar=source[source.index("class TraitSchemeDialog"):source.index('scheme=ttk.LabelFrame(outer,text="Trait set"')]
        self.assertNotIn('"Colors & keys..."',toolbar)

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

    def test_default_marker_numbers_put_counted_elements_before_reference_marks(self):
        from app.xray_schema import blank_scheme,bundled_scheme
        scheme=blank_scheme("roles")
        ref=_default_structure(scheme,"Boundary",False);scheme["structures"].append(ref)
        series=_default_structure(scheme,"Series",True);scheme["structures"].append(series)
        _renumber_default_structure_hotkeys(scheme)
        self.assertEqual("1",series["hotkey"]);self.assertEqual("2",ref["hotkey"])
        preset=bundled_scheme("phoxinus_vertebral_counts")
        ordered=[item["id"] for item in sorted(preset["structures"],key=lambda item:int(item["hotkey"]))]
        self.assertEqual(["vertebra","preanal_pterygiophore","first_caudal","last_predorsal"],ordered)

    def test_bundled_phoxinus_file_remains_portable_and_reference_is_compact(self):
        from app.xray_schema import bundled_scheme
        scheme=bundled_scheme("phoxinus_vertebral_counts")
        model=_scheme_display_model(scheme,"file")
        self.assertEqual("Bogutskaya et al. (2020)",model["reference_text"])
        self.assertEqual("10.1111/jfb.14210",model["reference_doi"])
        self.assertEqual(7,model["trait_count"])

    def test_xray_user_facing_context_uses_specimen_not_fish(self):
        root=Path(__file__).resolve().parents[1]
        source=(root/"app/modules/xray_counts.py").read_text(encoding="utf-8")
        self.assertIn("structure_workflow_number",source)
        self.assertIn('tree.heading("fish",text="On plate #")',source)
        self.assertIn('workflow_no=int(row.get("workflow_no") or index)',source)
        self.assertNotIn("Fish №",source)

    def test_xray_icons_include_role_step_and_fish_crop_icons(self):
        required={
            "xray","xray_project","xray_crops","xray_structures","xray_results","xray_export",
            "count","count_to","count_between","derived","counted_element","reference_mark",
            "annotation_setup","trait_setup","flip_horizontal","flip_vertical","delete_crop","clear_crops",
            "structure_apply","structure_previous","structure_next","clear_marker_set","clear_all_markers",
        }
        self.assertTrue(required.issubset(XRAY_ICON_NAMES))
        for name in required:
            image=render_xray_icon(name,26)
            self.assertEqual((26,26),image.size)
            self.assertIsNotNone(image.getbbox(),name)
        source=(Path(__file__).resolve().parents[1]/"app/xray_icons.py").read_text(encoding="utf-8")
        self.assertIn("Large lateral fish skeleton silhouette for the Crops stage.",source)
        self.assertIn("_fish_skeleton_icon(d,p);_crop_brackets",source)
        self.assertIn('if name=="xray":',source);self.assertIn("_fish_skeleton_icon(d,p)",source)
        self.assertIn('elif name=="counted_element"',source)
        self.assertIn('elif name=="reference_mark"',source)
        self.assertIn('elif name=="annotation_setup"',source)
        self.assertIn('elif name=="trait_setup"',source)
        self.assertIn('elif name=="flip_vertical"',source)
        self.assertIn('fill=ACCENT_ORANGE',source)
        self.assertIn('ACCENT_ORANGE="#ffb000"',source)
        self.assertNotIn('"flip_vertical":"flip_vertical"',source)

    def test_count_to_through_includes_the_reference_element(self):
        self.assertEqual({0,1,2},_count_to_indices("before",3,5))
        self.assertEqual({0,1,2,3},_count_to_indices("through",3,5))
        self.assertEqual({3,4},_count_to_indices("from",3,5))

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


    def test_xray_runtime_exposes_module_owned_top_menu_model_transfer(self):
        root=Path(__file__).resolve().parents[1]
        module=(root/"app/modules/xray_counts.py").read_text(encoding="utf-8")
        self.assertIn("def standard_menu_entries",module)
        self.assertIn("Import X-ray Structure AI…",module)
        self.assertIn("Export active X-ray Structure AI…",module)
        self.assertIn("on_check_results=self._show_result_checks",module)

    def test_xray_export_has_one_action_scope_sorting_row_number_and_clean_headers(self):
        root=Path(__file__).resolve().parents[1]
        module=(root/"app/modules/xray_counts.py").read_text(encoding="utf-8")
        exporter=(root/"app/xray_trait_export.py").read_text(encoding="utf-8")
        self.assertEqual(1,sum(key=="export" for key,_,_ in STAGES))
        self.assertNotIn('("results","Results","xray_results")',module)
        export_section=module[module.index("    def _render_results"):module.index("    def _show_result_checks")]
        self.assertIn('ttk.Radiobutton(actions,text="All"',export_section)
        self.assertIn('ttk.Radiobutton(actions,text="Verified only"',export_section)
        self.assertIn('actions,"Export",lambda:self._export_traits(self._trait_export_scope.get()=="verified")',export_section)
        self.assertNotIn("Check results…",export_section)
        self.assertIn('cols=("row_no","locality","plate","fish"',export_section)
        self.assertIn('tree.heading("row_no",text="Specimen #")',export_section)
        self.assertIn("_sort_export_tree(tree,value,False)",export_section)
        self.assertIn("def _trait_columns",exporter)
        self.assertNotIn('f"trait:',exporter)

    def test_export_sort_helper_orders_numbers_and_keeps_blanks_last(self):
        class Tree:
            def __init__(self):
                self.order=["a","b","c"];self.values={"a":{"x":"10","row_no":"7"},"b":{"x":"2","row_no":"3"},"c":{"x":"","row_no":"9"}}
            def get_children(self,_parent=""):return tuple(self.order)
            def set(self,item,column,value=None):
                if value is None:return self.values[item].get(column,"")
                self.values[item][column]=value
            def move(self,item,_parent,index):
                self.order.remove(item);self.order.insert(index,item)
            def item(self,item,tags=()):pass
            def heading(self,column,command=None):pass
        tree=Tree()
        self.assertEqual(["b","a","c"],_sort_export_tree(tree,"x",False))
        self.assertEqual(["3","7","9"],[tree.values[item]["row_no"] for item in tree.order])
        self.assertEqual(["a","b","c"],_sort_export_tree(tree,"x",True))
        self.assertEqual(["7","3","9"],[tree.values[item]["row_no"] for item in tree.order])

    def test_result_checks_start_a_ranked_navigable_review_queue(self):
        root=Path(__file__).resolve().parents[1]
        module=(root/"app/modules/xray_counts.py").read_text(encoding="utf-8")
        ui=(root/"app/xray_structures_ui.py").read_text(encoding="utf-8")
        qc=(root/"app/xray_result_qc.py").read_text(encoding="utf-8")
        self.assertIn("start_result_review_queue(self.project",module)
        workflow=ui[ui.index('workflow=WorkflowDock(main'):ui.index('    def _show_help',ui.index('workflow=WorkflowDock(main'))]
        self.assertNotIn('"4. Export"',workflow)
        self.assertNotIn('"Open Export"',workflow)
        self.assertIn('"Check results…",self.on_check_results',ui)
        self.assertIn('self.review_queue_banner=ttk.Frame(self.queue_host,style="Attention.TFrame"',ui)
        self.assertIn('"Previous",lambda:self._move_result_review(-1)',ui)
        self.assertIn('"Next",lambda:self._move_result_review(1)',ui);self.assertIn("_close_result_review",ui)
        self.assertIn('key=lambda row:(-row["score"]',qc)
        self.assertIn("evidence_bonus",qc)

if __name__=="__main__":
    unittest.main()
