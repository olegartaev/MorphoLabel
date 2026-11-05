"""Display labels reflect saved X-ray routes without changing model identity."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from app.xray_structures_ui import _structure_model_labels, _structure_method_details
from tests.test_universal_multires import meta

class StructureModelLabelsTests(unittest.TestCase):
    def test_saved_methods_and_imported_identifiers(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            standard={"structures":[{"id":"plant_vein"},{"id":"cell_nucleus"}]}
            mixed=meta("tiled_native")
            entries=[]
            for i,(ident,data) in enumerate((("xray_structure_model_v008",standard),("multires_retrained_abc",mixed),("imported_multires_retrained_abc_2",mixed))):
                name=f"{i}.json"; (root/name).write_text(json.dumps(data),encoding="utf-8")
                entries.append({"model_id":ident,"metadata_path":name,"created_at":f"2026-01-0{i+1}"})
            labels,descriptions=_structure_model_labels(SimpleNamespace(root=root),entries)
            self.assertEqual("X-ray 008 · Standard",labels["xray_structure_model_v008"])
            self.assertEqual(3,len(set(labels.values())))
            self.assertEqual("X-ray 009 · Mixed: Native + ROI",labels["multires_retrained_abc"])
            self.assertEqual("X-ray 010 · Mixed: Native + ROI",labels["imported_multires_retrained_abc_2"])
            self.assertIn("Mixed: Native + ROI",labels["multires_retrained_abc"])
            self.assertEqual({"plant_vein":"ROI Detail","cell_nucleus":"Native Full"},descriptions["multires_retrained_abc"][1])
            self.assertEqual(labels,_structure_model_labels(SimpleNamespace(root=root),list(reversed(entries)))[0])
            scheme={"format_version":1,"structures":[{"id":"plant_vein","name":"Leaf vein","repeated":True},{"id":"cell_nucleus","name":"Nucleus","repeated":False}]}
            detail=_structure_method_details(scheme,descriptions["multires_retrained_abc"][1])
            self.assertIn("Leaf vein: ROI Detail",detail)
            self.assertIn("Nucleus: Native Full",detail)

    def test_unknown_or_invalid_metadata_is_not_mislabeled(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); data=meta("tiled_native");data["inference_pipeline"]["retain_detail_structures"]=["unknown"]
            (root/"bad.json").write_text(json.dumps(data),encoding="utf-8")
            labels,descriptions=_structure_model_labels(SimpleNamespace(root=root),[{"model_id":"bad","metadata_path":"bad.json"}])
            self.assertIn("Method unavailable",labels["bad"])
            self.assertEqual({},descriptions["bad"][1])


    def test_saved_numbers_survive_deleting_an_unrelated_model(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            entries=[]
            for i,(ident,number) in enumerate((("xray_structure_model_v008",None),("first",9),("second",10))):
                data={"structures":[{"id":"plant_vein"}]}
                if number:data["display_number"]=number
                name=ident+".json";(root/name).write_text(json.dumps(data),encoding="utf-8")
                entries.append({"model_id":ident,"metadata_path":name,"created_at":f"2026-01-0{i+1}"})
            project=SimpleNamespace(root=root)
            labels,_=_structure_model_labels(project,entries)
            after,_=_structure_model_labels(project,[entries[0],entries[2]])
            self.assertEqual(labels["second"],after["second"])
            self.assertEqual("X-ray 010 · Standard",after["second"])


