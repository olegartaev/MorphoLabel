import json
import shutil
import tempfile
import unittest
from pathlib import Path

from app.xray_project import XRayProject
from app.xray_schema import (
    METHOD_BY_ID, SCHEME_RESOURCE_DIR, bundled_scheme, bundled_scheme_catalog,
    load_scheme_file, phoxinus_vertebral_preset, save_scheme_file,
    scheme_change_impact, scheme_hash,
)

class XRaySchemaTests(unittest.TestCase):
    def test_bundled_phoxinus_scheme_is_file_backed(self):
        catalog=bundled_scheme_catalog()
        self.assertGreaterEqual(len(catalog),1)
        item=next(item for item in catalog if item["id"]=="phoxinus_vertebral_counts")
        self.assertEqual(SCHEME_RESOURCE_DIR/"phoxinus_vertebral_counts.json",item["path"])
        self.assertTrue(item["path"].is_file())
        scheme=bundled_scheme(item["id"])
        self.assertEqual(scheme,load_scheme_file(item["path"]))
        self.assertEqual(scheme,phoxinus_vertebral_preset())
        self.assertEqual({"tv","abdv","caudv","predv","preap","dac","formv"},{trait["id"] for trait in scheme["traits"]})
        self.assertEqual(4,len(scheme["structures"]))
        self.assertEqual("10.1111/jfb.14210",scheme["reference"]["doi"])

    def test_scientific_scheme_content_is_not_duplicated_in_python(self):
        source=(Path(__file__).resolve().parents[1]/"app/xray_schema.py").read_text(encoding="utf-8")
        self.assertNotIn("_legacy_phoxinus_vertebral_preset",source)
        self.assertNotIn('"Total vertebrae"',source)
        self.assertIn('glob("*.json")',source)

    def test_portable_scheme_roundtrip(self):
        source=bundled_scheme("phoxinus_vertebral_counts")
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"scheme.json"
            save_scheme_file(source,path)
            self.assertEqual(source,load_scheme_file(path))
            parsed=json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual("phoxinus_vertebral_counts",parsed["scheme_id"])

    def test_each_trait_method_has_user_facing_icon_and_help(self):
        for method in METHOD_BY_ID.values():
            self.assertTrue(method["label"]);self.assertTrue(method["icon"]);self.assertTrue(method["help"])

    def test_scheme_change_reports_semantic_reannotation_without_deleting_data(self):
        old=bundled_scheme("phoxinus_vertebral_counts");new=bundled_scheme("phoxinus_vertebral_counts")
        for item in new["structures"]:
            if item["id"]=="vertebra":item["repeated"]=False
        impact=scheme_change_impact(old,new,{"vertebra":123})
        self.assertEqual(["vertebra"],impact["changed_structure_semantics"]);self.assertEqual(123,impact["affected_annotations"]);self.assertFalse(impact["safe_without_reannotation"])

    def test_project_creation_preserves_initial_scheme_source_note(self):
        root=Path(tempfile.mkdtemp())
        try:
            source=root/"source";source.mkdir();(source/"plate.tif").write_bytes(b"x")
            destination=root/"projects";destination.mkdir()
            note="File · custom_counts.json"
            project=XRayProject.create("xr",source,destination,bundled_scheme("phoxinus_vertebral_counts"),scheme_note=note)
            self.assertEqual(note,project.active_scheme_record()["note"])
        finally:shutil.rmtree(root,ignore_errors=True)

    def test_scheme_versioning_preserves_previous_versions(self):
        root=Path(tempfile.mkdtemp())
        try:
            source=root/"source";source.mkdir();(source/"plate.tif").write_bytes(b"x")
            destination=root/"projects";destination.mkdir()
            project=XRayProject.create("xr",source,destination,bundled_scheme("phoxinus_vertebral_counts"))
            first=project.active_scheme_record();edited=project.scheme;edited["description"]="edited"
            second_id=project.save_scheme(edited,"edit")
            self.assertNotEqual(first["version_id"],second_id);self.assertEqual(2,len(project.schema_history()))
            self.assertEqual("edited",project.scheme["description"]);self.assertEqual(1,len(project.source_images()))
            self.assertNotEqual(scheme_hash(first["scheme"]),scheme_hash(project.scheme))
        finally:shutil.rmtree(root,ignore_errors=True)

    def test_release_spec_packages_scheme_files(self):
        spec=(Path(__file__).resolve().parents[1]/"packaging/morpholabel.spec").read_text(encoding="utf-8")
        self.assertIn('app" / "resources" / "xray_trait_schemes',spec)

if __name__=="__main__":unittest.main()
