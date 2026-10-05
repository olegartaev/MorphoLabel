"""Missing biological observations stay blank in live tables and CSV exports."""
import csv
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from app.xray_crop import crop_from_geometry
from app.xray_project import XRayProject, _db_connection
from app.xray_schema import blank_scheme, bundled_scheme, calculate_trait_values
from app.xray_structure_ai import summarize_structure_ai_human_comparison
from app.xray_trait_export import export_trait_rows


def count_scheme():
    scheme=blank_scheme("Missing counts")
    scheme["structures"]=[{"id":sid,"name":sid,"repeated":True} for sid in ("a","b")]
    scheme["traits"]=[{"id":sid,"name":sid,"method":"count","structures":[sid],"rule":{}} for sid in ("a","b")]
    for ident,expression in (("sum","a+b"),("difference","a-b"),("product","a*b"),("ratio","a/b"),("formula","a+'+'+b")):
        scheme["traits"].append({"id":ident,"name":ident,"method":"derived","structures":[],"rule":{"expression":expression,"depends_on":["a","b"]}})
    scheme["traits"].append({"id":"presence","name":"Presence","method":"presence","structures":["b"],"rule":{}})
    return scheme


class MissingTraitCalculationTests(unittest.TestCase):
    def test_no_marks_produce_no_values_including_count_offsets(self):
        values=calculate_trait_values(bundled_scheme("phoxinus_vertebral_counts"),[])
        self.assertTrue(values);self.assertTrue(all(value is None for value in values.values()))

    def test_missing_either_component_leaves_every_composite_blank(self):
        scheme=count_scheme()
        for present,missing in (("a","b"),("b","a")):
            with self.subTest(present=present):
                values=calculate_trait_values(scheme,[{"structure_id":present,"x":.2,"y":.5}])
                self.assertEqual(1,values[present]);self.assertIsNone(values[missing])
                for ident in ("sum","difference","product","ratio","formula"):
                    self.assertIsNone(values[ident])

    def test_explicit_absence_and_calculated_zero_are_real_values(self):
        values=calculate_trait_values(count_scheme(),[{"structure_id":"a","x":.2,"y":.5}],absent_structures={"b"})
        self.assertEqual(0,values["b"]);self.assertEqual(0,values["presence"])
        self.assertEqual(0,values["product"]);self.assertEqual(1,values["sum"])
        self.assertEqual("1+0",values["formula"]);self.assertIsNone(values["ratio"])
        unknown=calculate_trait_values(count_scheme(),[],absent_structures={"b"},unknown_structures={"b"})
        self.assertTrue(all(value is None for value in unknown.values()))

    def test_declared_missing_dependency_prevents_partial_formula(self):
        scheme=count_scheme();scheme["traits"][-2]["rule"]["expression"]="a+'+'"
        values=calculate_trait_values(scheme,[{"structure_id":"a","x":.2,"y":.5}])
        self.assertIsNone(values["formula"])

    def test_two_and_three_reference_traits_require_every_mark(self):
        scheme=blank_scheme("References")
        scheme["structures"]=[{"id":sid,"name":sid,"repeated":sid=="series"} for sid in ("series","one","two")]
        for method,ids in (("count_to",["series","one"]),("position",["series","one"]),("count_between",["series","one","two"]),("distance",["one","two"]),("angle",["series","one","two"])):
            scheme["traits"]=[{"id":"value","name":"Value","method":method,"structures":ids,"rule":{}}]
            for missing in ids:
                with self.subTest(method=method,missing=missing):
                    marks=[{"structure_id":sid,"x":index*.2,"y":.5} for index,sid in enumerate(ids) if sid!=missing]
                    self.assertIsNone(calculate_trait_values(scheme,marks)["value"])

    def test_ai_comparison_keeps_known_absence_and_missing_detections_distinct(self):
        scheme=count_scheme();human=[{"structure_id":"a","x":.2,"y":.5}]
        report=summarize_structure_ai_human_comparison(scheme,[{"human":human,"predicted":[],"visibility":{"b":"absent"}}])
        traits={row["trait_id"]:row for row in report["traits"]}
        self.assertEqual(0,traits["a"]["accuracy"])
        self.assertEqual(1,traits["b"]["accuracy"])


class MissingTraitExportTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        root=Path(temporary.name);source=root/"source";source.mkdir()
        Image.new("L",(800,400),100).save(source/"plate.png")
        self.project=XRayProject.create("missing",source,root,bundled_scheme("phoxinus_vertebral_counts"))
        plate=self.project.source_images()[0]["image_id"]
        self.ident=self.project.add_manual_specimen(plate,crop_from_geometry(400,200,700,150,0,(800,400),algorithm="manual"))
        self.project.confirm_plate(plate)
        self.target=root/"traits.csv"

    def csv_row(self):
        export_trait_rows(self.project,self.target)
        with self.target.open(encoding="utf-8-sig",newline="") as stream:return next(csv.DictReader(stream))

    def assert_traits_empty(self,row):
        for trait in self.project.scheme["traits"]:
            self.assertEqual("",row[trait.get("abbr") or trait["id"]],trait["id"])

    def test_unstarted_and_cleared_specimens_have_blank_cells_and_null_storage(self):
        self.assert_traits_empty(self.csv_row())
        self.project.add_annotation(self.ident,"vertebra",.2,.5)
        self.project.clear_annotations(self.ident)
        self.assert_traits_empty(self.csv_row())
        self.assertTrue(all(value is None for value in self.project.trait_rows()[0]["trait_values"].values()))
        self.project.recalculate_trait_results(self.ident)
        with _db_connection(self.project.db_path) as db:
            self.assertTrue(all(row[0] is None for row in db.execute("SELECT value_text FROM trait_results WHERE specimen_id=?",(self.ident,))))

    def test_partial_annotation_only_exports_values_with_all_required_inputs(self):
        self.project.add_annotation(self.ident,"vertebra",.2,.5)
        row=self.csv_row();self.assertEqual("5",row["tv"])
        for key in ("abdv","caudv","preDv","preAp","dac","formv"):self.assertEqual("",row[key],key)
        self.project.add_annotation(self.ident,"first_caudal",.2,.5)
        row=self.csv_row();self.assertEqual("4+1",row["formv"])
        self.assertEqual("",row["preAp"]);self.assertEqual("",row["preDv"])

    def test_explicit_absence_exports_zero_and_unknown_exports_empty(self):
        self.project.set_structure_visibility(self.ident,"preanal_pterygiophore","absent")
        self.assertEqual("0",self.csv_row()["preAp"])
        self.project.set_structure_visibility(self.ident,"preanal_pterygiophore","not_visible")
        self.assertEqual("",self.csv_row()["preAp"])

    def test_verified_only_export_keeps_unknown_and_dependent_traits_blank(self):
        for structure in self.project.scheme["structures"]:
            self.project.set_structure_visibility(self.ident,structure["id"],"not_visible")
        self.project.verify_annotations(self.ident)
        export_trait_rows(self.project,self.target,verified_only=True)
        with self.target.open(encoding="utf-8-sig",newline="") as stream:row=next(csv.DictReader(stream))
        self.assert_traits_empty(row);self.assertEqual("verified",row["result_status"])
