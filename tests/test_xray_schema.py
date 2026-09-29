import shutil
import tempfile
import unittest
from pathlib import Path

from app.xray_project import XRayProject
from app.xray_schema import METHOD_BY_ID, phoxinus_vertebral_preset, scheme_change_impact, scheme_hash

class XRaySchemaTests(unittest.TestCase):
    def test_phoxinus_preset_matches_legacy_trait_contract(self):
        scheme=phoxinus_vertebral_preset()
        self.assertEqual("phoxinus_vertebral_counts",scheme["scheme_id"])
        self.assertEqual({"tv","abdv","caudv","predv","preap","dac","formv"},{item["id"] for item in scheme["traits"]})
        structures={item["id"]:item for item in scheme["structures"]}
        self.assertEqual({"vertebra","first_caudal","preanal_pterygiophore","last_predorsal"},set(structures))
        self.assertTrue(structures["vertebra"]["repeated"]);self.assertFalse(structures["first_caudal"]["repeated"])
        self.assertEqual("10.1111/jfb.14210",scheme["reference"]["doi"]);self.assertIn("Naseka (1996)",scheme["reference"]["note"])

    def test_each_trait_method_has_user_facing_icon_and_help(self):
        for method in METHOD_BY_ID.values():
            self.assertTrue(method["label"]);self.assertTrue(method["icon"]);self.assertTrue(method["help"])

    def test_scheme_change_reports_semantic_reannotation_without_deleting_data(self):
        old=phoxinus_vertebral_preset();new=phoxinus_vertebral_preset()
        for item in new["structures"]:
            if item["id"]=="vertebra":item["repeated"]=False
        impact=scheme_change_impact(old,new,{"vertebra":123})
        self.assertEqual(["vertebra"],impact["changed_structure_semantics"]);self.assertEqual(123,impact["affected_annotations"]);self.assertFalse(impact["safe_without_reannotation"])

    def test_scheme_versioning_preserves_previous_versions(self):
        root=Path(tempfile.mkdtemp())
        try:
            source=root/"source";source.mkdir();(source/"plate.tif").write_bytes(b"x")
            destination=root/"projects";destination.mkdir()
            project=XRayProject.create("xr",source,destination,phoxinus_vertebral_preset())
            first=project.active_scheme_record();edited=project.scheme;edited["description"]="edited"
            second_id=project.save_scheme(edited,"edit")
            self.assertNotEqual(first["version_id"],second_id);self.assertEqual(2,len(project.schema_history()))
            self.assertEqual("edited",project.scheme["description"]);self.assertEqual(1,len(project.source_images()))
            self.assertNotEqual(scheme_hash(first["scheme"]),scheme_hash(project.scheme))
        finally:shutil.rmtree(root,ignore_errors=True)

if __name__=="__main__":unittest.main()
