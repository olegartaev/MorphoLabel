"""Regression gates for defects reported during installed Windows user testing.

No CUDA, scientific data, real images or model checkpoints are required.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from ai_runtime import xray_structure_runner
from app import xray_structure_ai


class LegacyPredictSignatureRegression(unittest.TestCase):
    def test_current_and_many_do_not_pass_invalid_decode_kwargs(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)
            metadata=folder/"metadata.json"
            metadata.write_text(json.dumps({"structures":[{"id":"elements","repeated":True}]}),encoding="utf-8")
            fake_torch=SimpleNamespace(cuda=SimpleNamespace(is_available=lambda:False),
                                       load=lambda *_a,**_k: {})
            fake_model=Mock()
            with patch.dict(sys.modules, {"torch":fake_torch}),\
                 patch.object(xray_structure_runner,"_model",return_value=fake_model),\
                 patch.object(xray_structure_runner,"_decode_one",return_value=[{"structure_id":"elements","points":[]}]) as decode:
                result=xray_structure_runner.predict_many({
                    "metadata":str(metadata),"checkpoint":str(folder/"model.pth"),
                    "images":["one.png","two.png"],"device":"cpu",
                    "specimen_preprocessing":"standard"
                })
                self.assertEqual(len(result["results"]),2)
                self.assertEqual(decode.call_count,2)
                self.assertEqual(len(decode.call_args_list[0].args),4)
                self.assertEqual(decode.call_args_list[0].kwargs,{})
                with self.assertRaisesRegex(ValueError,"Unsupported legacy"):
                    xray_structure_runner.predict_many({
                        "metadata":str(metadata),"checkpoint":str(folder/"model.pth"),
                        "images":["one.png"],"device":"cpu",
                        "specimen_preprocessing":"unknown"
                    })


class ReadOnlyHumanComparisonRegression(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        (self.root/"checkpoint.pth").touch()
        (self.root/"metadata.json").write_text("{}",encoding="utf-8")
        project=SimpleNamespace()
        project.root=self.root
        project.scheme={"structures":[],"traits":[]}
        project.structure_models=lambda:[{"model_id":"candidate","path":"checkpoint.pth","metadata_path":"metadata.json","backend":"xray"}]
        project.active_structure_model=lambda:project.structure_models()[0]
        project.structure_model_membership=lambda _id:[
            {"specimen_id":"old_training","split":"train"}]
        project.structure_specimens=lambda _pass:[
            {"specimen_id":"old_training","annotation_status":"verified"},
            {"specimen_id":"new_verified","annotation_status":"verified"},
            {"specimen_id":"unfinished","annotation_status":"draft"}]
        project.annotation_run=lambda sid,*_a:{"status":"verified" if sid!="unfinished" else "draft"}
        project.effective_annotations=lambda *_a:[]
        project.structure_visibility_states=lambda *_a:{}
        project.specimen_crop_size=lambda *_a:(120,80)
        self.project=project

    def _context(self, backend):
        from contextlib import ExitStack
        stack=ExitStack()
        stack.enter_context(patch.object(xray_structure_ai,"_scheme_matches_model",return_value=True))
        stack.enter_context(patch.object(xray_structure_ai,"backend_for_structure_model",return_value=backend))
        stack.enter_context(patch.object(xray_structure_ai,"structure_performance_settings",
                                         return_value={"inference":{"device":"cpu","batch_size":2}}))
        stack.enter_context(patch.object(xray_structure_ai,"_prediction_image",
                                         side_effect=lambda _p,_sid,dest:dest))
        stack.enter_context(patch.object(xray_structure_ai,"summarize_structure_ai_human_comparison",
                                         side_effect=lambda _scheme,rows:{"summary":{"specimens_compared":len(rows)},"traits":[],"structures":[]}))
        return stack

    def test_all_verified_scope_includes_specimens_without_training_membership(self):
        backend=Mock()
        backend.predict_many.return_value={"results":[{"structures":[]},{"structures":[]}]}
        with self._context(backend):
            report=xray_structure_ai.compare_structure_model_to_human(self.project,"candidate",split="all")
        summary=report["summary"]
        self.assertEqual(summary["specimens_compared"],2)
        self.assertEqual(summary["registered_training_compared"],1)
        self.assertEqual(summary["registered_validation_compared"],0)
        self.assertEqual(summary["other_verified_compared"],1)
        self.assertEqual(summary["prediction_failures"],0)

    def test_all_predictions_failed_is_error_not_false_zero_accuracy(self):
        backend=Mock()
        backend.predict_many.side_effect=RuntimeError("simulated inference failure")
        with self._context(backend):
            with self.assertRaisesRegex(xray_structure_ai.XRayStructureAIError,"simulated inference failure"):
                xray_structure_ai.compare_structure_model_to_human(self.project,"candidate",split="all")


if __name__=="__main__":
    unittest.main()
