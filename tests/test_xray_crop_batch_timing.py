"""Crop batch timing is additive instrumentation, not an inference change."""
from pathlib import Path
import subprocess
import sys
from unittest import TestCase,main,mock
from app import xray_detector


class _Project:
    root=Path(".")
    def active_crop_model(self):return {"model_id":"test","config_path":"config.py","path":"model.pth"}
    def compact_disposable_ai_artifacts(self):return None


class CropTimingTests(TestCase):
    def test_stream_reader_reuses_single_stdout_reader_across_batches(self):
        code=(
            "import json,sys; print('runner log',flush=True); "
            "print(json.dumps({'event':'ready'}),flush=True); "
            "sys.stdin.readline(); print(json.dumps({'event':'batch'}),flush=True); "
            "sys.stdin.readline(); print(json.dumps({'event':'closed'}),flush=True)"
        )
        process=subprocess.Popen([sys.executable,"-u","-c",code],stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding="utf-8",bufsize=1)
        try:
            self.assertEqual("ready",xray_detector._stream_event(process,timeout=5)["event"])
            reader=process._morpholabel_stdout_thread;events=process._morpholabel_stdout_queue
            process.stdin.write("{}\n");process.stdin.flush()
            self.assertEqual("batch",xray_detector._stream_event(process,timeout=5)["event"])
            self.assertIs(reader,process._morpholabel_stdout_thread)
            self.assertIs(events,process._morpholabel_stdout_queue)
            process.stdin.write("{}\n");process.stdin.flush()
            self.assertEqual("closed",xray_detector._stream_event(process,timeout=5)["event"])
            self.assertEqual(0,process.wait(timeout=5))
        finally:
            if process.poll() is None:process.kill();process.wait(timeout=5)
            for handle in (process.stdin,process.stdout,process.stderr):
                handle.close()

    def test_batch_predictions_preserved_and_timed(self):
        project=_Project()
        settings={"inference":{"device":"cpu","batch_size":2,"mixed_precision":False}}
        def prepare(_project,image_id,_path):
            return Path(f"{image_id}.png"),1.0,(100,100)
        def batch_runner(_process,images,_timeout):
            return {"results":[{"detections":[]} for _ in images],
                    "timings_seconds":{"detection":0.25}}
        def saved(_project,model,image_id,proposals):
            return {"image_id":image_id}
        with mock.patch.object(xray_detector,"ensure_ai_runtime",return_value=("python",None)),\
             mock.patch.object(xray_detector,"detector_performance_settings",return_value=settings),\
             mock.patch.object(xray_detector,"_prediction_input",side_effect=prepare),\
             mock.patch.object(xray_detector,"_start_prediction_stream",return_value=(object(),0.5,0.2)) as started,\
             mock.patch.object(xray_detector,"_predict_stream_batch",side_effect=batch_runner) as called,\
             mock.patch.object(xray_detector,"_close_prediction_stream") as closed,\
             mock.patch.object(xray_detector,"_prediction_proposals",return_value=[]),\
             mock.patch.object(xray_detector,"predict_orientation_batch",side_effect=lambda p,m,i,r,s,c,**kwargs:i),\
             mock.patch.object(xray_detector,"_save_prediction",side_effect=saved):
            value=xray_detector.predict_plates(project,["A","B","C"])
        self.assertEqual(value["success"],3)
        self.assertEqual(value["successful_ids"],["A","B","C"])
        self.assertEqual(started.call_count,1)
        header=started.call_args.args[1]
        self.assertTrue(Path(header["config"]).is_absolute())
        self.assertTrue(Path(header["checkpoint"]).is_absolute())
        self.assertEqual(called.call_count,2)
        closed.assert_called_once()
        self.assertEqual(value["inference_batch_size"],2)
        self.assertTrue(all(n>=0 for n in value["timings_seconds"].values()))
        self.assertIn("runtime_setup",value["timings_seconds"])
        self.assertAlmostEqual(0.5,value["timings_seconds"]["model_load"])
        self.assertAlmostEqual(0.5,value["timings_seconds"]["detection"])
        self.assertAlmostEqual(0.2,value["timings_seconds"]["ai_launch"])
        self.assertIn("ai_launch",value["timings_seconds"])
        self.assertIn("persistence",value["timings_seconds"])


if __name__=="__main__":
    main()
