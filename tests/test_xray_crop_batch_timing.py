"""Crop batch timing is additive instrumentation, not an inference change."""
from pathlib import Path
from unittest import TestCase,main,mock
from app import xray_detector


class _Project:
    root=Path(".")
    def active_crop_model(self):return {"model_id":"test","config_path":"config.py","path":"model.pth"}
    def compact_disposable_ai_artifacts(self):return None


class CropTimingTests(TestCase):
    def test_batch_predictions_preserved_and_timed(self):
        project=_Project()
        settings={"inference":{"device":"cpu","batch_size":2,"mixed_precision":False}}
        def prepare(_project,image_id,_path):
            return Path(f"{image_id}.png"),1.0,(100,100)
        def runner(*args):
            payload=args[2]
            return {"results":[{"detections":[]} for _ in payload["images"]]}
        def saved(_project,model,image_id,proposals):
            return {"image_id":image_id}
        with mock.patch.object(xray_detector,"ensure_ai_runtime",return_value=("python",None)),\
             mock.patch.object(xray_detector,"detector_performance_settings",return_value=settings),\
             mock.patch.object(xray_detector,"_prediction_input",side_effect=prepare),\
             mock.patch.object(xray_detector,"_run",side_effect=runner) as called,\
             mock.patch.object(xray_detector,"_prediction_proposals",return_value=[]),\
             mock.patch.object(xray_detector,"predict_orientation_batch",side_effect=lambda p,m,i,r,s,c:i),\
             mock.patch.object(xray_detector,"_save_prediction",side_effect=saved):
            value=xray_detector.predict_plates(project,["A","B","C"])
        self.assertEqual(value["success"],3)
        self.assertEqual(value["successful_ids"],["A","B","C"])
        self.assertEqual(called.call_count,2)
        self.assertEqual(value["inference_batch_size"],2)
        self.assertTrue(all(n>=0 for n in value["timings_seconds"].values()))
        self.assertIn("runtime_setup",value["timings_seconds"])


if __name__=="__main__":
    main()
