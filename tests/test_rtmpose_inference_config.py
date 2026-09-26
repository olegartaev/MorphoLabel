import importlib.util
import unittest
from pathlib import Path


def runner_module():
    path = Path(__file__).resolve().parents[1] / "ai_runtime" / "rtmpose_runner.py"
    spec = importlib.util.spec_from_file_location("rtmpose_runner_inference_test", path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


class Config(dict):
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__


class Loader:
    @staticmethod
    def fromfile(_path):
        return Config(test_dataloader=None, train_dataloader=Config(dataset=Config(type="CocoDataset", pipeline=["train"])), val_pipeline=["val"])


class RTMPoseInferenceConfigTests(unittest.TestCase):
    def test_none_test_dataloader_is_repaired_before_model_initialization(self):
        config = runner_module().prepare_inference_config("generated.py", config_loader=Loader)
        self.assertEqual(["val"], config.test_dataloader["dataset"]["pipeline"])
        self.assertEqual("CocoDataset", config.test_dataloader["dataset"]["type"])

    def test_training_probe_matches_real_amp_cuda_mode(self):
        text=(Path(__file__).resolve().parents[1]/"ai_runtime"/"rtmpose_runner.py").read_text(encoding="utf-8")
        self.assertIn('amp=bool(request.get("mixed_precision",False))',text)
        self.assertIn('torch.cuda.amp.GradScaler(enabled=amp)',text)
        self.assertIn('with torch.autocast(device_type="cuda",dtype=torch.float16,enabled=amp):',text)
        self.assertIn('torch.backends.cudnn.benchmark=True',text)

    def test_runner_autotune_warms_cudnn_and_scales_batch_prefetch(self):
        text=(Path(__file__).resolve().parents[1]/"ai_runtime"/"rtmpose_runner.py").read_text(encoding="utf-8")
        self.assertIn("torch.backends.cudnn.benchmark=True",text)
        self.assertIn("(1,2,4,8,16,32,64)",text)
        self.assertIn("warm each candidate's own batch",text)
        self.assertIn("preprocess_wait_seconds",text)
        self.assertIn("if not supplied and best is not None:",text)

    def test_predict_and_rank_share_the_same_inference_helper(self):
        text = (Path(__file__).resolve().parents[1] / "ai_runtime" / "rtmpose_runner.py").read_text(encoding="utf-8")
        self.assertEqual(3, text.count("model=inference_model(request)"))


if __name__ == "__main__":
    unittest.main()