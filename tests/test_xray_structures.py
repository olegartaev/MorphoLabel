import ast
import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from app.xray_crop import crop_from_geometry
from app.xray_project import XRayProject
from app.xray_schema import blank_scheme, bundled_scheme, calculate_trait_values, compatible_reference_roles
from app.xray_result_qc import (
    build_result_qc, clear_result_review_queue, complete_result_review_item,
    move_result_review_queue, remove_result_review_image, remove_result_review_specimen, result_review_queue, start_result_review_queue,
)
from app.xray_trait_export import export_trait_rows
from app.xray_structure_display import DEFAULT_PALETTE, DEFAULT_SIZE, load_xray_structure_display, save_xray_structure_display
from app.xray_structures_ui import _first_structure_id, _structure_button_order, _structure_shortcuts


class XRayStructuresExcludeControlContractTests(unittest.TestCase):
    def test_structures_exclusion_matches_landmarks_but_targets_one_specimen(self):
        source=(Path(__file__).resolve().parents[1]/"app/xray_structures_ui.py").read_text(encoding="utf-8")
        self.assertIn('text="Show excluded"',source)
        self.assertIn('text="Restore" if excluded else "Exclude"',source)
        self.assertIn('self._action_icon("restore" if excluded else "exclude")',source)
        self.assertIn('style="Icon.TButton"',source)
        self.assertIn("def exclude_or_restore",source)
        self.assertIn("self.project.set_specimen_excluded(specimen_id,False)",source)
        self.assertIn("self.project.set_specimen_excluded(specimen_id,True)",source)
        self.assertIn("remove_result_review_specimen(self.project,specimen_id)",source)
        panel=source[source.index("class XRaySpecimenListPanel"):source.index("class XRayStructureWorkspace")]
        self.assertNotIn("set_source_excluded(",panel)
        self.assertIn('row.get("workflow_no")',panel)


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

    def test_excluding_one_specimen_keeps_plate_mates_and_stable_workflow_numbers(self):
        self._complete_pass_one()
        crop=crop_from_geometry(250,170,220,110,0,(900,480),algorithm="manual")
        other=self.project.add_manual_specimen(self.image_ids[0],crop)
        self.project.confirm_specimen(other)
        before=[dict(row) for row in self.project.effective_annotations(self.specimen_id,1,"human")]
        catalog={row["specimen_id"]:int(row["workflow_no"]) for row in self.project.structure_specimens(1,include_excluded=True)}
        self.assertIn(self.specimen_id,catalog);self.assertIn(other,catalog)
        self.project.set_specimen_excluded(self.specimen_id,True)
        active={row["specimen_id"]:row for row in self.project.structure_specimens(1)}
        self.assertNotIn(self.specimen_id,active);self.assertIn(other,active)
        self.assertEqual(catalog[other],int(active[other]["workflow_no"]))
        restore_rows={row["specimen_id"]:row for row in self.project.structure_specimens(1,include_excluded=True)}
        self.assertEqual(1,int(restore_rows[self.specimen_id]["excluded"]))
        self.assertEqual(catalog[self.specimen_id],int(restore_rows[self.specimen_id]["workflow_no"]))
        export_ids={row["specimen_id"]:int(row["workflow_no"]) for row in self.project.trait_rows()}
        self.assertNotIn(self.specimen_id,export_ids);self.assertEqual(catalog[other],export_ids[other])
        self.assertEqual(before,self.project.effective_annotations(self.specimen_id,1,"human"))
        self.project.set_specimen_excluded(self.specimen_id,False)
        active={row["specimen_id"]:row for row in self.project.structure_specimens(1)}
        self.assertEqual(catalog[self.specimen_id],int(active[self.specimen_id]["workflow_no"]))
        self.assertEqual(before,self.project.effective_annotations(self.specimen_id,1,"human"))

    def test_legacy_phoxinus_offsets_are_corrected_without_losing_annotations(self):
        root=Path(tempfile.mkdtemp())
        try:
            source=root/"source";source.mkdir()
            Image.fromarray(np.full((300,600),80,np.uint8)).save(source/"plate.png")
            destination=root/"projects";destination.mkdir()
            legacy=bundled_scheme("phoxinus_vertebral_counts")
            by_id={item["id"]:item for item in legacy["traits"]}
            for trait_id in ("tv","abdv","predv"):by_id[trait_id].setdefault("rule",{})["offset"]=4
            project=XRayProject.create("legacy",source,destination,legacy)
            image_id=project.source_images()[0]["image_id"]
            sid=project.add_manual_specimen(image_id,crop_from_geometry(300,150,440,120,0,(600,300),algorithm="manual"))
            project.confirm_plate(image_id)
            a=project.add_annotation(sid,"vertebra",0.10,0.50,1)
            b=project.add_annotation(sid,"vertebra",0.30,0.50,1)
            c=project.add_annotation(sid,"vertebra",0.50,0.50,1)
            project.assign_annotation_role(b,"first_caudal");project.assign_annotation_role(c,"last_predorsal")
            project.add_annotation(sid,"preanal_pterygiophore",0.40,0.70,1)
            project.verify_annotations(sid,1)
            old_version=project.active_scheme_record()["version_id"]
            old_annotations=[dict(row) for row in project.effective_annotations(sid,1,"human")]
            self.assertTrue(project.ensure_phoxinus_count_semantics())
            self.assertNotEqual(old_version,project.active_scheme_record()["version_id"])
            self.assertEqual("verified",project.annotation_run(sid,1,"human",False)["status"])
            self.assertEqual(old_annotations,project.effective_annotations(sid,1,"human"))
            values=project.trait_rows()[0]["trait_values"]
            self.assertEqual(3,values["tv"]);self.assertEqual(1,values["abdv"]);self.assertEqual(2,values["caudv"])
            self.assertEqual(3,values["predv"]);self.assertEqual("1+2",values["formv"])
            self.assertFalse(project.ensure_phoxinus_count_semantics())
        finally:shutil.rmtree(root,ignore_errors=True)


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

    def test_repeatability_uses_two_dedicated_blind_passes_and_allows_new_run(self):
        specimens=[]
        for image_id in self.image_ids:
            for cx in (300,600):
                crop=crop_from_geometry(cx,240,260,140,0,(900,480),algorithm="manual")
                sid=self.project.add_manual_specimen(image_id,crop);specimens.append(sid)
            self.project.confirm_plate(image_id)
        targets=[self.specimen_id]+specimens
        for sid in targets:
            v1=self.project.add_annotation(sid,"vertebra",0.2,0.5,1)
            v2=self.project.add_annotation(sid,"vertebra",0.4,0.5,1)
            self.project.assign_annotation_role(v2,"first_caudal")
            self.project.assign_annotation_role(v1,"last_predorsal")
            self.project.add_annotation(sid,"preanal_pterygiophore",0.6,0.65,1)
            self.project.verify_annotations(sid,1)
        run=self.project.start_structure_repeatability(3,seed=7)
        self.assertEqual(3,run["total"]);self.assertFalse(run["legacy"])
        self.assertGreater(run["annotation1_pass_no"],1)
        self.assertGreater(run["annotation2_pass_no"],run["annotation1_pass_no"])
        self.assertEqual(0,run["annotation1_verified"]);self.assertEqual(0,run["annotation2_verified"])
        for sid in run["ids"]:
            for pass_no in (run["annotation1_pass_no"],run["annotation2_pass_no"]):
                a=self.project.add_annotation(sid,"vertebra",0.2,0.5,pass_no)
                b=self.project.add_annotation(sid,"vertebra",0.4,0.5,pass_no)
                self.project.assign_annotation_role(b,"first_caudal")
                self.project.assign_annotation_role(a,"last_predorsal")
                self.project.add_annotation(sid,"preanal_pterygiophore",0.6,0.65,pass_no)
                self.project.verify_annotations(sid,pass_no)
        finished=self.project.structure_repeatability(run["run_id"])
        self.assertEqual("completed",finished["status"])
        self.assertEqual(3,finished["annotation1_verified"]);self.assertEqual(3,finished["annotation2_verified"])
        metrics=self.project.structure_repeatability_metrics(run["run_id"])
        vertebra=next(row for row in metrics["structures"] if row["structure_id"]=="vertebra")
        self.assertEqual(1.0,vertebra["exact_count_accuracy"])
        self.project.retire_structure_repeatability(run["run_id"])
        newer=self.project.start_structure_repeatability(2,seed=8)
        self.assertNotEqual(run["run_id"],newer["run_id"])
        self.assertGreater(newer["annotation1_pass_no"],run["annotation2_pass_no"])

    def test_result_gap_qc_uses_spatial_sequence_not_click_order(self):
        for x in (0.70,0.10,0.90,0.30,0.20,0.80):
            self.project.add_annotation(self.specimen_id,"vertebra",x,0.50,1)
        self.project.add_annotation(self.specimen_id,"first_caudal",0.70,0.50,1,replace_single=True)
        self.project.add_annotation(self.specimen_id,"last_predorsal",0.30,0.50,1,replace_single=True)
        for x in (0.25,0.35,0.45,0.55,0.65):
            self.project.add_annotation(self.specimen_id,"preanal_pterygiophore",x,0.70,1)
        self.project.verify_annotations(self.specimen_id,1)
        report=build_result_qc(self.project)
        spacing=[item for item in report["issues"] if item["code"]=="series_spacing" and item["target"]=="Vertebrae"]
        self.assertTrue(spacing)
        self.assertTrue(any(float(item["metric"]["ratio"])>=3.0 for item in spacing))

    def test_result_qc_flags_detached_reference_and_conspicuous_serial_gap(self):
        for x in (0.10,0.20,0.30,0.40,0.80,0.90):
            self.project.add_annotation(self.specimen_id,"vertebra",x,0.50,1)
        self.project.add_annotation(self.specimen_id,"first_caudal",0.80,0.50,1,replace_single=True)
        self.project.add_annotation(self.specimen_id,"last_predorsal",0.30,0.50,1,replace_single=True)
        for x in (0.25,0.35,0.45,0.55,0.65):
            self.project.add_annotation(self.specimen_id,"preanal_pterygiophore",x,0.70,1)
        self.project.verify_annotations(self.specimen_id,1)
        report=build_result_qc(self.project)
        codes={item["code"] for item in report["issues"]}
        self.assertIn("detached_reference",codes)
        self.assertIn("series_spacing",codes)

    def test_result_review_queue_drops_every_specimen_from_an_excluded_xray(self):
        issues=[
            {"specimen_id":"a","image_id":"plate_bad","severity":"high","code":"repeat_count","metric":{"difference":2},"sample":"S","plate":"bad","ordinal":1,"reason":"a"},
            {"specimen_id":"b","image_id":"plate_bad","severity":"review","code":"series_spacing","metric":{"ratio":2.0},"sample":"S","plate":"bad","ordinal":2,"reason":"b"},
            {"specimen_id":"c","image_id":"plate_good","severity":"review","code":"series_spacing","metric":{"ratio":1.9},"sample":"S","plate":"good","ordinal":1,"reason":"c"},
        ]
        start_result_review_queue(self.project,issues)
        value=remove_result_review_image(self.project,"plate_bad")
        self.assertIsNotNone(value)
        self.assertEqual(["c"],[row["specimen_id"] for row in value["items"]])
        self.assertEqual(0,value["position"])

    def test_result_review_queue_is_worst_first_stable_and_navigable(self):
        issues=[
            {"specimen_id":"mild","image_id":"i1","severity":"review","code":"series_spacing","metric":{"ratio":1.9},"sample":"S","plate":"p","ordinal":1},
            {"specimen_id":"worst","image_id":"i2","severity":"high","code":"sample_outlier","metric":{"modified_z":8.0},"sample":"S","plate":"p","ordinal":2},
            {"specimen_id":"worst","image_id":"i2","severity":"review","code":"repeat_position","metric":{"ratio":1.0},"sample":"S","plate":"p","ordinal":2},
        ]
        started=start_result_review_queue(self.project,issues)
        self.assertEqual(["worst","mild"],[item["specimen_id"] for item in started["items"]])
        self.assertEqual(2,started["items"][0]["issue_count"])
        current=result_review_queue(self.project);self.assertEqual("worst",current["items"][current["position"]]["specimen_id"])
        moved,finished=move_result_review_queue(self.project,1)
        self.assertFalse(finished);self.assertEqual(1,moved["position"])
        moved,finished=complete_result_review_item(self.project)
        self.assertTrue(finished);self.assertIsNone(result_review_queue(self.project))
        clear_result_review_queue(self.project);self.assertIsNone(result_review_queue(self.project))

    def test_result_review_queue_combines_multiple_warning_signals_after_worst_score(self):
        issues=[
            {"specimen_id":"single","image_id":"i1","severity":"high","code":"repeat_count","metric":{"difference":1},"sample":"S","plate":"p","ordinal":1,"reason":"one"},
            {"specimen_id":"multi","image_id":"i2","severity":"high","code":"repeat_count","metric":{"difference":1},"sample":"S","plate":"p","ordinal":2,"reason":"same worst"},
            {"specimen_id":"multi","image_id":"i2","severity":"review","code":"series_spacing","metric":{"ratio":1.9},"sample":"S","plate":"p","ordinal":2,"reason":"extra"},
        ]
        started=start_result_review_queue(self.project,issues)
        self.assertEqual("multi",started["items"][0]["specimen_id"])
        self.assertGreater(started["items"][0]["score"],started["items"][1]["score"])
        self.assertEqual(2,started["items"][0]["issue_count"])

    def test_export_all_and_verified_only_keep_live_trait_calculation(self):
        self._complete_pass_one()
        pending=self.project.add_manual_specimen(self.image_ids[1],crop_from_geometry(450,240,620,230,0,(900,480),algorithm="manual"))
        self.project.confirm_plate(self.image_ids[1])
        all_path=self.root/"all.csv";verified_path=self.root/"verified.csv"
        all_result=export_trait_rows(self.project,all_path)
        verified_result=export_trait_rows(self.project,verified_path,verified_only=True)
        self.assertEqual(2,all_result["rows"]);self.assertEqual(1,verified_result["rows"])
        all_text=all_path.read_text(encoding="utf-8-sig");verified_text=verified_path.read_text(encoding="utf-8-sig")
        self.assertNotIn("trait:",all_text);self.assertIn("tv",all_text.splitlines()[0]);self.assertIn(self.specimen_id,verified_text)
        self.assertNotIn(pending,verified_text)

    def test_result_qc_uses_robust_within_sample_count_check_without_global_pooling(self):
        crop=crop_from_geometry(450,240,620,230,0,(900,480),algorithm="manual")
        specimen_ids=[self.specimen_id]
        for index in range(5):
            sid=self.project.add_manual_specimen(self.image_ids[index%2],crop,label=f"extra-{index}")
            specimen_ids.append(sid)
        for image_id in self.image_ids:self.project.confirm_plate(image_id)
        for index,sid in enumerate(specimen_ids):
            vertebra_count=10 if index==len(specimen_ids)-1 else 6
            vertebra_ids=[]
            for point_index in range(vertebra_count):
                vertebra_ids.append(self.project.add_annotation(sid,"vertebra",0.08+0.07*point_index,0.45,1))
            self.project.assign_annotation_role(vertebra_ids[min(3,len(vertebra_ids)-1)],"first_caudal")
            self.project.assign_annotation_role(vertebra_ids[min(2,len(vertebra_ids)-1)],"last_predorsal")
            for x in (0.30,0.40,0.50,0.60,0.70):
                self.project.add_annotation(sid,"preanal_pterygiophore",x,0.70,1)
            self.project.verify_annotations(sid,1)
        report=build_result_qc(self.project)
        outliers=[item for item in report["issues"] if item["code"]=="sample_outlier" and item["target"]=="tv"]
        self.assertEqual(1,len(outliers))
        self.assertEqual(specimen_ids[-1],outliers[0]["specimen_id"])

    def test_result_qc_flat_cluster_flags_any_deviation_without_fixed_unit_jump(self):
        crop=crop_from_geometry(450,240,620,230,0,(900,480),algorithm="manual")
        specimen_ids=[self.specimen_id]
        for index in range(5):
            sid=self.project.add_manual_specimen(self.image_ids[index%2],crop,label=f"flat-{index}")
            specimen_ids.append(sid)
        for image_id in self.image_ids:self.project.confirm_plate(image_id)
        for index,sid in enumerate(specimen_ids):
            vertebra_count=7 if index==len(specimen_ids)-1 else 6
            vertebra=[]
            for point_index in range(vertebra_count):
                vertebra.append(self.project.add_annotation(sid,"vertebra",0.08+0.07*point_index,0.45,1))
            self.project.assign_annotation_role(vertebra[min(3,len(vertebra)-1)],"first_caudal")
            self.project.assign_annotation_role(vertebra[min(2,len(vertebra)-1)],"last_predorsal")
            for x in (0.30,0.40,0.50,0.60,0.70):
                self.project.add_annotation(sid,"preanal_pterygiophore",x,0.70,1)
            self.project.verify_annotations(sid,1)
        report=build_result_qc(self.project)
        flagged=[item for item in report["issues"] if item["code"]=="sample_outlier" and item["target"]=="tv"]
        self.assertEqual(1,len(flagged))
        self.assertEqual(specimen_ids[-1],flagged[0]["specimen_id"])
        self.assertIn("dominant cluster",flagged[0]["reason"])

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

    def test_visibility_state_allows_unknown_or_absent_required_structures_without_faking_points(self):
        v1=self.project.add_annotation(self.specimen_id,"vertebra",0.2,0.5,1)
        v2=self.project.add_annotation(self.specimen_id,"vertebra",0.4,0.5,1)
        self.project.assign_annotation_role(v2,"first_caudal")
        self.project.assign_annotation_role(v1,"last_predorsal")
        self.assertEqual("complete",self.project.structure_visibility(self.specimen_id,"preanal_pterygiophore",1))
        self.project.set_structure_visibility(self.specimen_id,"preanal_pterygiophore","not_visible",1)
        result=self.project.verify_annotations(self.specimen_id,1)
        self.assertEqual("verified",self.project.annotation_run(self.specimen_id,1)["status"])
        self.assertNotIn("preanal_pterygiophore",result["counts"])
        reopened=XRayProject(self.project.root)
        self.assertEqual("not_visible",reopened.structure_visibility(self.specimen_id,"preanal_pterygiophore",1))
        verify=reopened.annotation_events(self.specimen_id,1)[-1]
        self.assertEqual("not_visible",verify["payload"]["structure_visibility"]["preanal_pterygiophore"])

    def test_absent_or_not_visible_cannot_coexist_with_saved_markers(self):
        self.project.add_annotation(self.specimen_id,"preanal_pterygiophore",0.55,0.65,1)
        with self.assertRaisesRegex(ValueError,"Clear existing markers"):
            self.project.set_structure_visibility(self.specimen_id,"preanal_pterygiophore","absent",1)
        self.project.clear_annotations(self.specimen_id,1,structure_id="preanal_pterygiophore")
        self.project.set_structure_visibility(self.specimen_id,"preanal_pterygiophore","absent",1)
        self.assertEqual("absent",self.project.structure_visibility(self.specimen_id,"preanal_pterygiophore",1))

    def test_partial_required_structure_still_requires_at_least_one_visible_marker(self):
        v1=self.project.add_annotation(self.specimen_id,"vertebra",0.2,0.5,1)
        v2=self.project.add_annotation(self.specimen_id,"vertebra",0.4,0.5,1)
        self.project.assign_annotation_role(v2,"first_caudal")
        self.project.assign_annotation_role(v1,"last_predorsal")
        self.project.set_structure_visibility(self.specimen_id,"preanal_pterygiophore","partial",1)
        with self.assertRaisesRegex(ValueError,"Pre-anal pterygiophores"):
            self.project.verify_annotations(self.specimen_id,1)
        self.project.add_annotation(self.specimen_id,"preanal_pterygiophore",0.55,0.65,1)
        self.project.verify_annotations(self.specimen_id,1)
        self.assertEqual("partial",self.project.structure_visibility(self.specimen_id,"preanal_pterygiophore",1))

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
        unknown=calculate_trait_values(
            bundled_scheme("phoxinus_vertebral_counts"),rows,unknown_structures={"vertebra"}
        )
        for trait_id in ("tv","abdv","caudv","predv","dac","formv"):
            self.assertIsNone(unknown[trait_id])
        self.assertEqual(2,unknown["preap"])

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

    def test_marker_tools_put_counted_series_before_reference_marks_and_number_consecutively(self):
        structures=[
            {"id":"series_a","hotkey":"1","repeated":True},
            {"id":"ref_a","hotkey":"2","repeated":False},
            {"id":"series_b","hotkey":"3","repeated":True},
            {"id":"ref_b","hotkey":"4","repeated":False},
        ]
        self.assertEqual(["series_a","series_b","ref_a","ref_b"],[item["id"] for item in _structure_button_order(structures)])
        self.assertEqual({"series_a":"1","series_b":"2","ref_a":"3","ref_b":"4"},_structure_shortcuts(structures))
        self.assertEqual("series_a",_first_structure_id(structures))

    def test_xray_marker_display_defaults_are_bright_distinct_and_persistent(self):
        structures=self.project.scheme["structures"]
        settings=load_xray_structure_display(self.project,structures)
        self.assertEqual(DEFAULT_SIZE,settings["size"])
        self.assertEqual(("#56b4e9","#e69f00","#009e73","#cc79a7"),DEFAULT_PALETTE[:4])
        self.assertEqual(len(structures),len(set(settings["colors"].values())))
        self.assertEqual(tuple(settings["colors"][item["id"]] for item in structures),DEFAULT_PALETTE[:len(structures)])
        settings["size"]=12;settings["colors"][structures[0]["id"]]="#12ff34"
        save_xray_structure_display(self.project,settings,structures)
        reopened=load_xray_structure_display(XRayProject(self.project.root),structures)
        self.assertEqual(12,reopened["size"]);self.assertEqual("#12ff34",reopened["colors"][structures[0]["id"]])

    def test_landmarks_style_intermediate_settings_restore_old_role_colors_as_marker_colors(self):
        structures=self.project.scheme["structures"]
        self.project.set_ui_state("xray_structure_display",{"role_colors":{structures[0]["id"]:"#123456"}})
        restored=load_xray_structure_display(self.project,structures)
        self.assertEqual("#123456",restored["colors"][structures[0]["id"]])

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
        self.project.set_structure_visibility(self.specimen_id,"preanal_pterygiophore","partial",1)
        self.project.verify_annotations(self.specimen_id,1)
        before=self.project.annotations(self.specimen_id,1);self.assertTrue(before)
        crop=dict(self.project.specimen(self.specimen_id)["crop"]);crop["center_x"]+=4
        from app.xray_crop import crop_corners
        crop["corners"]=[list(point) for point in crop_corners(crop["center_x"],crop["center_y"],crop["length"],crop["width"],crop["angle_degrees"])]
        self.project.update_specimen_crop(self.specimen_id,crop)
        self.assertEqual([],self.project.annotations(self.specimen_id,1))
        run=self.project.annotation_run(self.specimen_id,1);self.assertEqual("stale_crop",run["status"])
        archives=self.project.annotation_archives(self.specimen_id)
        self.assertEqual(len(before),len(archives[-1]["annotations"]))
        self.assertEqual("partial",archives[-1]["structure_states"]["preanal_pterygiophore"])
        self.assertEqual("complete",self.project.structure_visibility(self.specimen_id,"preanal_pterygiophore",1))
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
            "Apply","Sample","Specimen","Locality:","Plate:","Specimen:",
            "PhotoListCanvas","status_shape=\"square\"","Annotation batch","Repeatability","Training data",
            "delete_selected","clear_marker_category","clear_all_markers","clear_type_button",
            "move_annotation","replace_single","_wheel","_pan_motion","_key_pressed","_structure_button_order",
        ):
            self.assertIn(text,ui)
        self.assertNotIn("Fish №",ui)
        self.assertNotIn("Manual pass",ui)
        self.assertNotIn("Verify & Next",ui)
        self.assertNotIn("Marker actions:",ui)
        self.assertIn("XRayStructureWorkspace(",module)
        self.assertIn("initial_specimen_id=selection.get(\"specimen_id\")",module)
        self.assertIn("on_selection=self._set_selection",module)
        self.assertIn('on_open_results=lambda:self._select("export")',module)
        self.assertNotIn("Specimen image / annotation canvas",module)
        self.assertNotIn("Structures to mark",ui)
        self.assertIn("trait_rows()",module)
        self.assertIn("self.specimen_list.select(specimen_id,reveal=False)",ui)
        self.assertNotIn("self.selected_specimen_id=row[\"specimen_id\"];self.on_select(row[\"specimen_id\"]);self.refresh(preserve_scroll=True)",ui)
        self.assertIn("preferred_plate=next((row[\"specimen_id\"] for row in rows if row[\"image_id\"]==self.preferred_image_id),None)",ui)
        self.assertIn("elif self.preferred_image_id:target=preferred_plate if preferred_plate in ids else None",ui)
        self.assertIn("else:target=preferred_batch if preferred_batch in ids else (ids[0] if ids else None)",ui)
        self.assertIn("No confirmed specimen crop is available on this plate.",ui)

    def test_results_exposes_non_destructive_scientific_qc_review(self):
        root=Path(__file__).resolve().parents[1]
        module=(root/"app/modules/xray_counts.py").read_text(encoding="utf-8")
        ui=(root/"app/xray_structures_ui.py").read_text(encoding="utf-8")
        qc=(root/"app/xray_result_qc.py").read_text(encoding="utf-8")
        export_section=module[module.index("    def _render_results"):module.index("    def _show_result_checks")]
        self.assertNotIn("Check results…",export_section)
        self.assertIn('text="Check results…"',ui)
        self.assertIn("build_result_qc(self.project)",module)
        self.assertIn("start_result_review_queue(self.project",module)
        for text in ("modified_z","series_spacing","sample_outlier","detached_reference","repeat_count","repeat_position"):
            self.assertIn(text,qc)

    def test_structure_toolbar_has_no_previous_next_buttons_and_apply_stays_separate(self):
        root=Path(__file__).resolve().parents[1]
        ui=(root/"app/xray_structures_ui.py").read_text(encoding="utf-8")
        self.assertNotIn("self.previous_button=ttk.Button",ui)
        self.assertNotIn("self.next_button=ttk.Button",ui)
        self.assertNotIn("self.batch_nav=ttk.Frame",ui)
        self.assertIn("self.apply_separator=ttk.Separator",ui)
        self.assertIn("command=self.verify_current",ui)
        self.assertIn("def _navigate(self,step):",ui)
        self.assertIn("def verify_next(self):",ui)
        self.assertIn("if not batch or self.selected_specimen_id not in batch.get(\"ids\",()):return",ui)
        self.assertNotIn("self.pass_box",ui)

    def test_restored_marker_style_signature_is_used_by_every_ui_call(self):
        root=Path(__file__).resolve().parents[1]
        ui=(root/"app/xray_structures_ui.py").read_text(encoding="utf-8")
        tree=ast.parse(ui)
        calls=[
            node for node in ast.walk(tree)
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=="marker_style"
        ]
        self.assertEqual(3,len(calls))
        for call in calls:
            self.assertEqual(3,len(call.args))
            self.assertEqual([],[(keyword.arg or "**") for keyword in call.keywords])

    def test_visibility_controls_are_compact_per_marker_and_top_status_is_preserved(self):
        root=Path(__file__).resolve().parents[1]
        ui=(root/"app/xray_structures_ui.py").read_text(encoding="utf-8")
        for text in ('"Complete"','"Partial"','"Not visible"','"Absent"',"_VISIBILITY_SYMBOLS","_marker_visibility_buttons","StatusChip.TLabel"):
            self.assertIn(text,ui)
        self.assertIn('(("locality","Locality:"),("plate","Plate:"),("specimen","Specimen:"))',ui)
        self.assertIn('style="SectionTitle.TLabel"',ui)
        self.assertIn('width=2,style="P.TButton"',ui)
        self.assertNotIn('text="Visibility:"',ui)
        self.assertNotIn("self.visibility_box",ui)
        self.assertNotIn("self.counts_label",ui)
        self.assertNotIn("self.summary_label=ttk.Label",ui)

    def test_structure_toolbar_keeps_current_layout_and_restores_original_marker_display(self):
        root=Path(__file__).resolve().parents[1]
        ui=(root/"app/xray_structures_ui.py").read_text(encoding="utf-8")
        display=(root/"app/xray_structure_display.py").read_text(encoding="utf-8")
        for text in ('text="Clear type…"', 'text="Clear all markers"', 'text="Display…"', 'text="Apply"', 'text="Markers:"'):
            self.assertIn(text,ui)
        self.assertIn("self.apply_separator=ttk.Separator",ui)
        self.assertIn('self.active_structure_id=_first_structure_id(self.project.scheme.get("structures",()))',ui)
        self.assertIn("DEFAULT_PALETTE",display)
        self.assertIn("Compact high-contrast marker for grayscale radiographs.",display)
        self.assertIn("DISPLAY_DESIGN_VERSION=2",display)
        self.assertIn("Marker icons and colors",ui)
        self.assertNotIn("Same marker language as Landmarks.",ui)

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
    def test_display_dialog_restores_per_structure_colors_and_symbols(self):
        root=Path(__file__).resolve().parents[1]
        ui=(root/"app/xray_structures_ui.py").read_text(encoding="utf-8")
        display=(root/"app/xray_structure_display.py").read_text(encoding="utf-8")
        for text in ("X-ray marker display","High-contrast defaults stay visible on black, white and gray radiographs.","Marker icons and colors","color_vars","symbol_vars"):
            self.assertIn(text,ui)
        self.assertIn("DEFAULT_PALETTE",display)
        self.assertIn('"colors":colors',display);self.assertIn('"symbols":symbols',display)
        self.assertNotIn("Same marker language as Landmarks.",ui)
    def test_structures_ui_has_compact_per_marker_visibility_and_quick_result_check(self):
        root=Path(__file__).resolve().parents[1]
        ui=(root/"app/xray_structures_ui.py").read_text(encoding="utf-8")
        module=(root/"app/modules/xray_counts.py").read_text(encoding="utf-8")
        shell=(root/"app/ui/shell.py").read_text(encoding="utf-8")
        self.assertIn("_VISIBILITY_SYMBOLS",ui)
        self.assertIn("_marker_visibility_buttons",ui)
        self.assertIn("_marker_visibility_vars",ui)
        self.assertIn("add_radiobutton",ui)
        self.assertIn("variable=state_var",ui)
        self.assertIn("Check results…",ui)
        self.assertNotIn('text="Visibility:"',ui)
        self.assertIn("standard_menu_entries",module)
        self.assertIn("Import X-ray Structure AI…",module)
        self.assertIn("Export active X-ray Structure AI…",module)
        self.assertIn("standard_menu_entries",shell)

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