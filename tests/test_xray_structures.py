import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from app.xray_crop import crop_from_geometry
from app.xray_project import XRayProject
from app.xray_schema import blank_scheme, bundled_scheme, calculate_trait_values, compatible_reference_roles
from app.xray_structure_display import DEFAULT_OTHER, DEFAULT_SELECTED, DEFAULT_SIZE, ROLE_PALETTE, load_xray_structure_display, save_xray_structure_display
from app.xray_structures_ui import _first_structure_id, _structure_button_order


class XRayStructurePersistenceTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(tempfile.mkdtemp())
        self.source=self.root/"source";self.source.mkdir()
        image=np.tile(np.linspace(15,240,900,dtype=np.uint8),(480,1))
        Image.fromarray(image).save(self.source/"plate_1.png")
        Image.fromarray(image).save(self.source/"plate_2.png")
        destination=self.root/"projects";destination.mkdir()
        self.project=XRayProject.create("xray",self.source,destination,bundled_scheme("phoxinus_vertebral_counts"))
        self.image_ids=[row["image_id"] for row in self.project.source_images()]
        crop=crop_from_geometry(450,240,700,260,0,(900,480),algorithm="manual")
        self.specimen_id=self.project.add_manual_specimen(self.image_ids[0],crop)
        self.project.confirm_plate(self.image_ids[0])

    def tearDown(self):
        shutil.rmtree(self.root,ignore_errors=True)

    def _complete_pass_one(self):
        self.project.add_annotation(self.specimen_id,"vertebra",0.2,0.5,1)
        self.project.add_annotation(self.specimen_id,"vertebra",0.4,0.5,1)
        self.project.add_annotation(self.specimen_id,"first_caudal",0.55,0.5,1,replace_single=True)
        self.project.add_annotation(self.specimen_id,"preanal_pterygiophore",0.6,0.62,1)
        self.project.add_annotation(self.specimen_id,"last_predorsal",0.35,0.5,1,replace_single=True)
        return self.project.verify_annotations(self.specimen_id,1)

    def test_only_human_confirmed_crops_are_structure_eligible(self):
        crop=crop_from_geometry(450,240,700,260,0,(900,480),algorithm="manual")
        unconfirmed=self.project.add_manual_specimen(self.image_ids[1],crop)
        ids=[row["specimen_id"] for row in self.project.structure_specimens(1)]
        self.assertIn(self.specimen_id,ids)
        self.assertNotIn(unconfirmed,ids)

    def test_point_edits_are_normalized_persisted_and_logged(self):
        annotation_id=self.project.add_annotation(self.specimen_id,"vertebra",-2,4,1)
        row=self.project.annotations(self.specimen_id,1)[0]
        self.assertEqual(annotation_id,row["annotation_id"])
        self.assertEqual(0.0,row["x"]);self.assertEqual(1.0,row["y"])
        self.project.move_annotation(annotation_id,0.25,0.35)
        moved=self.project.annotations(self.specimen_id,1)[0]
        self.assertAlmostEqual(0.25,moved["x"]);self.assertAlmostEqual(0.35,moved["y"])
        self.assertTrue(self.project.delete_annotation(annotation_id))
        self.assertEqual([],self.project.annotations(self.specimen_id,1))
        self.assertEqual(["add","move","delete"],[event["action"] for event in self.project.annotation_events(self.specimen_id,1)])

    def test_reference_roles_reuse_existing_series_point_without_duplicate_marker(self):
        one=self.project.add_annotation(self.specimen_id,"vertebra",0.2,0.5,1)
        two=self.project.add_annotation(self.specimen_id,"vertebra",0.4,0.5,1)
        compatible=[item["id"] for item in compatible_reference_roles(self.project.scheme,"vertebra")]
        self.assertEqual(["first_caudal","last_predorsal"],compatible)
        self.assertTrue(self.project.assign_annotation_role(two,"first_caudal"))
        self.assertEqual(2,len(self.project.annotations(self.specimen_id,1)))
        roles=self.project.annotation_roles(self.specimen_id,1)
        self.assertEqual(1,len(roles));self.assertEqual(two,roles[0]["annotation_id"])
        ref=next(row for row in self.project.effective_annotations(self.specimen_id,1) if row["structure_id"]=="first_caudal")
        self.assertAlmostEqual(0.4,ref["x"])
        self.project.move_annotation(two,0.47,0.52)
        ref=next(row for row in self.project.effective_annotations(self.specimen_id,1) if row["structure_id"]=="first_caudal")
        self.assertAlmostEqual(0.47,ref["x"]);self.assertAlmostEqual(0.52,ref["y"])
        self.project.delete_annotation(two)
        self.assertEqual([],self.project.annotation_roles(self.specimen_id,1))

    def test_assigning_shared_reference_replaces_old_standalone_reference(self):
        standalone=self.project.add_annotation(self.specimen_id,"first_caudal",0.55,0.5,1,replace_single=True)
        vertebra=self.project.add_annotation(self.specimen_id,"vertebra",0.4,0.5,1)
        self.project.assign_annotation_role(vertebra,"first_caudal")
        ids=[row["annotation_id"] for row in self.project.annotations(self.specimen_id,1)]
        self.assertNotIn(standalone,ids)
        refs=[row for row in self.project.effective_annotations(self.specimen_id,1) if row["structure_id"]=="first_caudal"]
        self.assertEqual(1,len(refs));self.assertEqual(vertebra,refs[0]["annotation_id"])

    def test_clear_one_marker_category_keeps_other_categories_and_removes_attached_roles(self):
        v1=self.project.add_annotation(self.specimen_id,"vertebra",0.2,0.5,1)
        v2=self.project.add_annotation(self.specimen_id,"vertebra",0.4,0.5,1)
        p=self.project.add_annotation(self.specimen_id,"preanal_pterygiophore",0.5,0.7,1)
        self.project.assign_annotation_role(v2,"first_caudal")
        result=self.project.clear_annotations(self.specimen_id,1,structure_id="vertebra")
        self.assertEqual(2,result["annotations"]);self.assertEqual(1,result["roles"])
        remaining=self.project.annotations(self.specimen_id,1)
        self.assertEqual([p],[row["annotation_id"] for row in remaining])
        self.assertEqual([],self.project.annotation_roles(self.specimen_id,1))
        self.assertEqual("clear_structure",self.project.annotation_events(self.specimen_id,1)[-1]["action"])

    def test_clear_reference_category_removes_role_without_deleting_base_marker(self):
        v=self.project.add_annotation(self.specimen_id,"vertebra",0.3,0.5,1)
        self.project.assign_annotation_role(v,"first_caudal")
        result=self.project.clear_annotations(self.specimen_id,1,structure_id="first_caudal")
        self.assertEqual(0,result["annotations"]);self.assertEqual(1,result["roles"])
        self.assertEqual([v],[row["annotation_id"] for row in self.project.annotations(self.specimen_id,1)])
        self.assertEqual([],self.project.annotation_roles(self.specimen_id,1))

    def test_clear_all_markers_keeps_annotation_run_but_empties_current_specimen(self):
        v=self.project.add_annotation(self.specimen_id,"vertebra",0.2,0.5,1)
        self.project.add_annotation(self.specimen_id,"preanal_pterygiophore",0.5,0.7,1)
        self.project.assign_annotation_role(v,"last_predorsal")
        result=self.project.clear_annotations(self.specimen_id,1)
        self.assertEqual(2,result["annotations"]);self.assertEqual(1,result["roles"])
        self.assertEqual([],self.project.annotations(self.specimen_id,1))
        self.assertEqual([],self.project.annotation_roles(self.specimen_id,1))
        self.assertEqual("draft",self.project.annotation_run(self.specimen_id,1)["status"])
        self.assertEqual("clear_all",self.project.annotation_events(self.specimen_id,1)[-1]["action"])

    def test_verify_warns_with_missing_category_names_and_accepts_shared_roles(self):
        v1=self.project.add_annotation(self.specimen_id,"vertebra",0.2,0.5,1)
        v2=self.project.add_annotation(self.specimen_id,"vertebra",0.4,0.5,1)
        self.project.assign_annotation_role(v2,"first_caudal")
        self.project.assign_annotation_role(v1,"last_predorsal")
        with self.assertRaisesRegex(ValueError,"Pre-anal pterygiophores"):
            self.project.verify_annotations(self.specimen_id,1)
        self.project.add_annotation(self.specimen_id,"preanal_pterygiophore",0.5,0.7,1)
        result=self.project.verify_annotations(self.specimen_id,1)
        self.assertEqual(1,result["counts"]["first_caudal"]);self.assertEqual(1,result["counts"]["last_predorsal"])

    def test_single_reference_is_replaced_instead_of_duplicated(self):
        first=self.project.add_annotation(self.specimen_id,"first_caudal",0.4,0.5,1,replace_single=True)
        second=self.project.add_annotation(self.specimen_id,"first_caudal",0.6,0.5,1,replace_single=True)
        self.assertEqual(first,second)
        rows=[row for row in self.project.annotations(self.specimen_id,1) if row["structure_id"]=="first_caudal"]
        self.assertEqual(1,len(rows));self.assertAlmostEqual(0.6,rows[0]["x"])
        self.assertEqual(["add","move"],[event["action"] for event in self.project.annotation_events(self.specimen_id,1)])

    def test_verify_requires_all_required_structure_roles(self):
        self.project.add_annotation(self.specimen_id,"vertebra",0.2,0.5,1)
        with self.assertRaisesRegex(ValueError,"Before continuing, mark every required category"):
            self.project.verify_annotations(self.specimen_id,1)
        result=self._complete_pass_one()
        self.assertEqual("verified",self.project.annotation_run(self.specimen_id,1)["status"])
        self.assertGreaterEqual(result["counts"]["vertebra"],2)
        self.assertEqual("verify",self.project.annotation_events(self.specimen_id,1)[-1]["action"])

    def test_repeatability_pass_two_requires_verified_primary_pass(self):
        with self.assertRaisesRegex(ValueError,"Verify manual pass 1"):
            self.project.add_annotation(self.specimen_id,"vertebra",0.2,0.5,2)
        self._complete_pass_one()
        annotation_id=self.project.add_annotation(self.specimen_id,"vertebra",0.22,0.5,2)
        self.assertIsInstance(annotation_id,int)
        ids=[row["specimen_id"] for row in self.project.structure_specimens(2)]
        self.assertEqual([self.specimen_id],ids)

    def test_new_schema_version_does_not_overwrite_old_annotation_run(self):
        self._complete_pass_one()
        first=self.project.annotation_run(self.specimen_id,1);first_id=first["run_id"]
        edited=self.project.scheme;edited["description"]="new annotation semantics"
        self.project.save_scheme(edited,"schema edit")
        self.assertIsNone(self.project.annotation_run(self.specimen_id,1))
        new_id=self.project.ensure_annotation_run(self.specimen_id,1)
        self.assertNotEqual(first_id,new_id)
        with self.project.db_path.open("rb") as handle:
            self.assertTrue(handle.read(16).startswith(b"SQLite format 3"))


    def test_untouched_blank_project_gets_bundled_starter_as_new_version(self):
        other=self.root/"blank_projects";other.mkdir()
        blank=XRayProject.create("blank",self.source,other,blank_scheme())
        old_id=blank.active_scheme_record()["version_id"]
        self.assertTrue(blank.ensure_initial_bundled_scheme())
        active=blank.active_scheme_record()
        self.assertNotEqual(old_id,active["version_id"])
        self.assertEqual(4,len(active["scheme"]["structures"]))
        self.assertEqual(7,len(active["scheme"]["traits"]))
        self.assertEqual(2,len(blank.schema_history()))

    def test_shared_selection_persists_across_reopen(self):
        value=self.project.set_current_selection(self.image_ids[0],self.specimen_id)
        self.assertEqual(self.specimen_id,value["specimen_id"])
        reopened=XRayProject(self.project.root)
        self.assertEqual({"image_id":self.image_ids[0],"specimen_id":self.specimen_id},reopened.current_selection())

    def test_bundled_traits_recalculate_from_current_markers(self):
        rows=[
            {"annotation_id":i+1,"structure_id":"vertebra","x":x,"y":0.5,"sort_order":i}
            for i,x in enumerate((0.1,0.2,0.3,0.4,0.5))
        ]
        rows += [
            {"annotation_id":20,"structure_id":"first_caudal","x":0.3,"y":0.5,"sort_order":0},
            {"annotation_id":21,"structure_id":"last_predorsal","x":0.4,"y":0.5,"sort_order":0},
            {"annotation_id":22,"structure_id":"preanal_pterygiophore","x":0.25,"y":0.7,"sort_order":0},
            {"annotation_id":23,"structure_id":"preanal_pterygiophore","x":0.35,"y":0.7,"sort_order":1},
        ]
        values=calculate_trait_values(bundled_scheme("phoxinus_vertebral_counts"),rows)
        self.assertEqual(9,values["tv"])
        self.assertEqual(6,values["abdv"])
        self.assertEqual(3,values["caudv"])
        self.assertEqual(8,values["predv"])
        self.assertEqual(2,values["preap"])
        self.assertEqual(3,values["dac"])
        self.assertEqual("6+3",values["formv"])

    def test_repeated_markers_keep_click_order_when_added_or_moved(self):
        one=self.project.add_annotation(self.specimen_id,"vertebra",0.20,0.5,1)
        two=self.project.add_annotation(self.specimen_id,"vertebra",0.40,0.5,1)
        three=self.project.add_annotation(self.specimen_id,"vertebra",0.30,0.5,1)
        rows=[row for row in self.project.annotations(self.specimen_id,1) if row["structure_id"]=="vertebra"]
        self.assertEqual([one,two,three],[row["annotation_id"] for row in rows])
        self.assertEqual([0,1,2],[row["sort_order"] for row in rows])
        self.project.move_annotation(one,0.80,0.5)
        rows=[row for row in self.project.annotations(self.specimen_id,1) if row["structure_id"]=="vertebra"]
        self.assertEqual([one,two,three],[row["annotation_id"] for row in rows])
        self.project.delete_annotation(two)
        rows=[row for row in self.project.annotations(self.specimen_id,1) if row["structure_id"]=="vertebra"]
        self.assertEqual([one,three],[row["annotation_id"] for row in rows])

    def test_structure_batch_is_persisted_and_advances(self):
        crop=crop_from_geometry(450,240,700,260,0,(900,480),algorithm="manual")
        second=self.project.add_manual_specimen(self.image_ids[1],crop)
        self.project.confirm_plate(self.image_ids[1])
        state=self.project.start_structure_batch(2,1,self.specimen_id)
        self.assertEqual(2,len(state["ids"]))
        reopened=XRayProject(self.project.root)
        self.assertEqual(state["ids"],reopened.structure_batch(1)["ids"])
        moved=reopened.move_structure_batch(state["ids"][0],1,1)
        self.assertEqual(state["ids"][1],moved["specimen_id"])

    def test_marker_tools_follow_numeric_hotkeys_and_new_specimen_starts_with_marker_one(self):
        structures=[
            {"id":"a","hotkey":"1"},{"id":"c","hotkey":"3"},{"id":"b","hotkey":"2"},{"id":"d","hotkey":"4"},
        ]
        self.assertEqual(["a","b","c","d"],[item["id"] for item in _structure_button_order(structures)])
        self.assertEqual("a",_first_structure_id(structures))

    def test_marker_display_matches_landmarks_selected_other_language_and_keeps_role_colors(self):
        structures=self.project.scheme["structures"]
        settings=load_xray_structure_display(self.project,structures)
        self.assertEqual(DEFAULT_SIZE,settings["size"])
        self.assertEqual(DEFAULT_SELECTED,settings["selected_color"])
        self.assertEqual(DEFAULT_OTHER,settings["other_color"])
        self.assertEqual(tuple(settings["role_colors"][item["id"]] for item in structures),ROLE_PALETTE[:len(structures)])
        self.assertEqual(3,settings["design_version"])
        settings["size"]=12;settings["selected_color"]="#12ff34";settings["other_color"]="#334455"
        save_xray_structure_display(self.project,settings,structures)
        reopened=load_xray_structure_display(XRayProject(self.project.root),structures)
        self.assertEqual(12,reopened["size"]);self.assertEqual("#12ff34",reopened["selected_color"]);self.assertEqual("#334455",reopened["other_color"])

    def test_legacy_structure_colors_survive_only_as_semantic_role_colors(self):
        structures=self.project.scheme["structures"]
        self.project.set_ui_state("xray_structure_display",{"colors":{structures[0]["id"]:"#123456"}})
        migrated=load_xray_structure_display(self.project,structures)
        self.assertEqual(DEFAULT_SELECTED,migrated["selected_color"]);self.assertEqual(DEFAULT_OTHER,migrated["other_color"])
        self.assertEqual("#123456",migrated["role_colors"][structures[0]["id"]])

    def test_crop_archive_preserves_shared_role_provenance(self):
        vertebra=self.project.add_annotation(self.specimen_id,"vertebra",0.3,0.5,1)
        self.project.assign_annotation_role(vertebra,"first_caudal")
        crop=dict(self.project.specimen(self.specimen_id)["crop"]);crop["center_x"]+=2
        from app.xray_crop import crop_corners
        crop["corners"]=[list(point) for point in crop_corners(crop["center_x"],crop["center_y"],crop["length"],crop["width"],crop["angle_degrees"])]
        self.project.update_specimen_crop(self.specimen_id,crop)
        archived=self.project.annotation_archives(self.specimen_id)[-1]["annotations"]
        row=next(item for item in archived if item["annotation_id"]==vertebra)
        self.assertEqual(["first_caudal"],row["role_structure_ids"])
    def test_crop_change_archives_and_hides_coordinate_dependent_markers(self):
        self._complete_pass_one()
        before=self.project.annotations(self.specimen_id,1);self.assertTrue(before)
        crop=dict(self.project.specimen(self.specimen_id)["crop"]);crop["center_x"]+=4
        from app.xray_crop import crop_corners
        crop["corners"]=[list(point) for point in crop_corners(crop["center_x"],crop["center_y"],crop["length"],crop["width"],crop["angle_degrees"])]
        self.project.update_specimen_crop(self.specimen_id,crop)
        self.assertEqual([],self.project.annotations(self.specimen_id,1))
        run=self.project.annotation_run(self.specimen_id,1);self.assertEqual("stale_crop",run["status"])
        archives=self.project.annotation_archives(self.specimen_id)
        self.assertEqual(len(before),len(archives[-1]["annotations"]))
        row=next(item for item in self.project.trait_rows() if item["specimen_id"]==self.specimen_id)
        self.assertTrue(all(value is None for value in row["trait_values"].values()))

    def test_marker_change_updates_live_result_and_crop_edit_invalidates_verification(self):
        self._complete_pass_one()
        before=self.project.recalculate_trait_results(self.specimen_id)
        self.assertEqual("verified",before["status"])
        extra=self.project.add_annotation(self.specimen_id,"vertebra",0.8,0.5,1)
        after=self.project.recalculate_trait_results(self.specimen_id)
        self.assertEqual("draft",after["status"])
        self.assertEqual(before["values"]["tv"]+1,after["values"]["tv"])
        self.project.delete_annotation(extra)
        self.project.verify_annotations(self.specimen_id,1)
        crop=dict(self.project.specimen(self.specimen_id)["crop"]);crop["center_x"]+=3
        self.project.update_specimen_crop(self.specimen_id,crop)
        self.assertEqual("stale_crop",self.project.annotation_run(self.specimen_id,1)["status"])

class XRayStructureUIContractTests(unittest.TestCase):
    def test_structures_workspace_is_interactive_and_not_placeholder(self):
        root=Path(__file__).resolve().parents[1]
        ui=(root/"app/xray_structures_ui.py").read_text(encoding="utf-8")
        module=(root/"app/modules/xray_counts.py").read_text(encoding="utf-8")
        for text in (
            "Apply","Sample","Specimen","Locality:","Plate:","Fish №",
            "PhotoListCanvas","status_shape=\"square\"","Annotation batch","Repeatability","Training data","Open Results",
            "delete_selected","clear_marker_category","clear_all_markers","clear_type_button",
            "move_annotation","replace_single","_wheel","_pan_motion","_key_pressed","_structure_button_order",
        ):
            self.assertIn(text,ui)
        self.assertNotIn("Manual pass",ui)
        self.assertNotIn("Verify & Next",ui)
        self.assertNotIn("Marker actions:",ui)
        self.assertIn("XRayStructureWorkspace(",module)
        self.assertIn("initial_specimen_id=selection.get(\"specimen_id\")",module)
        self.assertIn("on_selection=self._set_selection",module)
        self.assertIn('on_open_results=lambda:self._select("results")',module)
        self.assertNotIn("Specimen image / annotation canvas",module)
        self.assertNotIn("Structures to mark",ui)
        self.assertIn("trait_rows()",module)

    def test_structure_navigation_is_batch_only_and_apply_is_always_separate(self):
        root=Path(__file__).resolve().parents[1]
        ui=(root/"app/xray_structures_ui.py").read_text(encoding="utf-8")
        self.assertIn("self.batch_nav.grid_remove()",ui)
        self.assertIn("self.apply_separator=ttk.Separator",ui)
        self.assertNotIn("self.batch_separator",ui)
        self.assertIn("command=self.verify_current",ui)
        self.assertIn("command=self.verify_next",ui)
        self.assertIn("if not batch or self.selected_specimen_id not in batch.get(\"ids\",()):return",ui)
        self.assertNotIn("self.pass_box",ui)

    def test_structure_toolbar_matches_landmarks_layout_and_resets_first_marker_on_load(self):
        root=Path(__file__).resolve().parents[1]
        ui=(root/"app/xray_structures_ui.py").read_text(encoding="utf-8")
        display=(root/"app/xray_structure_display.py").read_text(encoding="utf-8")
        for text in ('text="Clear type…"', 'text="Clear all markers"', 'text="Display…"', 'text="Apply"', 'text="Markers:"'):
            self.assertIn(text,ui)
        self.assertIn("self.apply_separator=ttk.Separator",ui)
        self.assertIn('self.active_structure_id=_first_structure_id(self.project.scheme.get("structures",()))',ui)
        self.assertIn("DEFAULT_SELECTED",display);self.assertIn("DEFAULT_OTHER",display)
        self.assertIn("draw_marker",display);self.assertIn("draw_label",display)
        self.assertNotIn("Marker icons and colors",ui)

    def test_structures_use_project_orientation_and_one_plate_source_cache(self):
        root=Path(__file__).resolve().parents[1]
        ui=(root/"app/xray_structures_ui.py").read_text(encoding="utf-8")
        self.assertIn("self._source_cache_id",ui)
        self.assertIn("source=self._source_for(item[\"image_id\"])",ui)
        self.assertIn("self.project.orientation_policy",ui)
        self.assertIn("align_top=True",ui)

    def test_shared_role_ui_uses_context_menu_badges_and_preserves_right_drag_pan(self):
        root=Path(__file__).resolve().parents[1]
        ui=(root/"app/xray_structures_ui.py").read_text(encoding="utf-8")
        display=(root/"app/xray_structure_display.py").read_text(encoding="utf-8")
        for text in ("Use this point as…","compatible_reference_roles","assign_annotation_role","remove_annotation_role","_right_start","_right_motion","_right_end"):
            self.assertIn(text,ui)
        self.assertIn("draw_xray_role_badges",ui);self.assertIn("draw_xray_role_badges",display)
        self.assertNotIn('("<Button-3>",self._pan_start)',ui)
        self.assertIn('("<Button-2>",self._pan_start)',ui)
    def test_structures_ui_renders_oriented_crop_without_project_image_copy(self):
        root=Path(__file__).resolve().parents[1]
        ui=(root/"app/xray_structures_ui.py").read_text(encoding="utf-8")
        self.assertIn("oriented_crop",ui)
        self.assertIn("crop_normalized_v1",(root/"app/xray_project.py").read_text(encoding="utf-8"))
        self.assertNotIn(".save(",ui)
        self.assertIn("draw_xray_marker",ui)
        self.assertIn('self.canvas.move(f"annotation:{self._drag_annotation}"',ui)
        self.assertIn("| №{int(row.get('ordinal') or 0)}",ui)
        self.assertNotIn('text="Delete"',ui)
        self.assertNotIn("Wheel = zoom · right-drag = pan",ui)


if __name__=="__main__":
    unittest.main()
