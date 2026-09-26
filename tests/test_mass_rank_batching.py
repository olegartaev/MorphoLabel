import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.ai import ImagePrediction, InferenceRequest, LandmarkPrediction
from app.ai_hardware import HardwareProfile
from app.landmark_ai_service import LandmarkAIService
from app.rtmpose_backend import RTMPoseBackend, RTMPoseModelSpec, RTMPoseRuntimeError


class BackendPayloadTests(unittest.TestCase):
    def test_batch_size_reaches_rank_payload_and_effective_value_returns(self):
        spec = RTMPoseModelSpec('m', 'schema', Path('config.py'), Path('weights.pth'), (640, 320), 'cuda:0', 4)
        backend = RTMPoseBackend(spec, runtime_python='python', runner_path='runner.py')
        request = InferenceRequest('image', Path('image.png'), ({'id': 1},), 'schema', 10, 10)
        raw = {'model_id': 'm', 'schema_sha256': 'schema', 'effective_batch_size': 2, 'results': [{'image_id': 'image', 'landmarks': [{'landmark_id': 1, 'x': 1, 'y': 2, 'confidence': .5}]}]}
        with patch.object(backend, '_invoke', return_value=raw) as invoke:
            prediction = backend.predict_readonly_many((request,))[0]
        self.assertEqual(4, invoke.call_args.args[1]['batch_size'])
        self.assertEqual(2, backend.last_rank_batch_size)
        self.assertEqual('image', prediction.image_id)

    def test_persistent_benchmark_payload_returns_selected_batch(self):
        spec = RTMPoseModelSpec('m', 'schema', Path('config.py'), Path('weights.pth'), (640, 320), 'cuda:0', 4)
        backend = RTMPoseBackend(spec, runtime_python='python', runner_path='runner.py')
        request = InferenceRequest('image', Path('image.png'), ({'id': 1},), 'schema', 10, 10)
        raw = {'model_id': 'm', 'schema_sha256': 'schema', 'selected_batch_size': 8, 'benchmarks': [{'batch_size': 8, 'images_per_second': 20.0}]}
        with patch.object(backend, '_invoke', return_value=raw) as invoke:
            result = backend.benchmark_readonly_many((request,))
        self.assertEqual(8, result['selected_batch_size'])
        self.assertEqual('rank_benchmark', invoke.call_args.args[0])
        self.assertEqual([1, 2, 4, 8, 16, 32, 64], invoke.call_args.args[1]['batch_sizes'])

class ServiceFallbackTests(unittest.TestCase):
    class Project:
        def __init__(self, root):
            self.data_root = Path(root)
        def model_metadata(self, _):
            return {'kind': 'landmark', 'schema_sha256': 'schema'}

    class Backend:
        model_id = 'm'
        schema_sha256 = 'schema'
        last_rank_batch_size = 4
        def __init__(self): self.calls = []
        def predict_readonly_many(self, requests, *, batch_size=None):
            self.calls.append(batch_size)
            if len(self.calls) == 1:
                raise RTMPoseRuntimeError('RTMPose rank failed (return code 3221226505)')
            return tuple(ImagePrediction(r.image_id, 'm', 'schema', (LandmarkPrediction(1, 1, 2, .5),)) for r in requests)

    def test_native_rank_crash_retries_smaller_batch_and_records_safe_value(self):
        with tempfile.TemporaryDirectory() as root:
            service = LandmarkAIService(self.Project(root), self.Backend())
            requests = [InferenceRequest(x, Path(x + '.png'), ({'id': 1},), 'schema', 10, 10) for x in ('a', 'b')]
            saved = []
            service._request = lambda image_id: next(r for r in requests if r.image_id == image_id)
            service._persist_prediction = lambda request, prediction: type('Result', (), {'saved_landmarks': 1})()
            with patch('app.landmark_ai_service.auto_performance_config', return_value={'batch_size': 8}), patch('app.landmark_ai_service.record_inference_batch') as record:
                summary = service.predict_many(('a', 'b'), progress=lambda image_id, result, error: saved.append((image_id, result is not None, error)))
            self.assertEqual([8, 4], service.backend.calls)
            self.assertEqual(2, summary.succeeded)
            self.assertEqual(['a', 'b'], [item[0] for item in saved])
            self.assertEqual(4, record.call_args.kwargs['batch_size'])

class ServiceAutoBenchmarkTests(unittest.TestCase):
    class Project(ServiceFallbackTests.Project):
        pass

    class Backend(ServiceFallbackTests.Backend):
        def __init__(self):
            super().__init__(); self.benchmarks=[]
        def benchmark_readonly_many(self, requests, *, batch_sizes):
            self.benchmarks.append((tuple(request.image_id for request in requests), tuple(batch_sizes)))
            return {'selected_batch_size': 4, 'benchmarks': [{'batch_size': 4, 'images_per_second': 20.0}]}
        def predict_readonly_many(self, requests, *, batch_size=None):
            self.calls.append(batch_size)
            return tuple(ImagePrediction(r.image_id, 'm', 'schema', (LandmarkPrediction(1, 1, 2, .5),)) for r in requests)

    def test_new_hardware_tuple_benchmarks_once_before_bulk_rank(self):
        with tempfile.TemporaryDirectory() as root:
            service = LandmarkAIService(self.Project(root), self.Backend())
            requests = [InferenceRequest(x, Path(x + '.png'), ({'id': 1},), 'schema', 10, 10) for x in ('a', 'b')]
            service._request = lambda image_id: next(r for r in requests if r.image_id == image_id)
            service._persist_prediction = lambda request, prediction: type('Result', (), {'saved_landmarks': 1})()
            hardware=HardwareProfile("CPU",8,16,32*1024**3,"GPU",24576,None,True,"12.0","CUDA",24000)
            statuses=[]
            with patch('app.landmark_ai_service.auto_performance_config', return_value={'batch_size': 8, 'tuning_source': 'heuristic'}), patch('app.landmark_ai_service.get_hardware_profile', return_value=hardware), patch('app.landmark_ai_service.record_inference_batch', return_value={'batch_size':4}) as record:
                summary = service.predict_many(('a', 'b'),status=statuses.append)
            self.assertEqual(32, len(service.backend.benchmarks[0][0]))
            self.assertEqual(('a', 'b', 'a', 'b'), service.backend.benchmarks[0][0][:4])
            self.assertEqual((1, 2, 4, 8, 16, 32), service.backend.benchmarks[0][1])
            self.assertEqual([4], service.backend.calls)
            self.assertEqual(2, summary.succeeded)
            self.assertEqual(4, record.call_args.kwargs['batch_size'])
            self.assertTrue(any('Calibrating inference' in message for message in statuses))
            self.assertTrue(any('Selected inference batch 4' in message for message in statuses))

    def test_inference_cache_uses_model_input_size_not_first_photo_size(self):
        with tempfile.TemporaryDirectory() as root:
            backend=self.Backend()
            backend.spec=SimpleNamespace(input_size=(512,256),config_path=Path('missing-config.py'))
            service=LandmarkAIService(self.Project(root),backend)
            request=InferenceRequest('a',Path('a.png'),({'id':1},),'schema',3452,1414)
            service._request=lambda _image_id:request
            service._persist_prediction=lambda request,prediction:type('Result',(),{'saved_landmarks':1})()
            statuses=[]
            with patch('app.landmark_ai_service.auto_performance_config',return_value={'batch_size':1,'tuning_source':'cache'}) as tuned, patch('app.landmark_ai_service.record_inference_batch') as recorded:
                summary=service.predict_many(('a',),status=statuses.append)
            self.assertEqual(1,summary.succeeded)
            self.assertEqual((512,256),tuned.call_args.kwargs['input_size'])
            self.assertEqual((512,256),recorded.call_args.kwargs['input_size'])
            self.assertTrue(any('Using cached inference settings' in message for message in statuses))

if __name__ == '__main__':
    unittest.main()