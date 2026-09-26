"""Resolve the official AP-10K RTMPose bootstrap beside the selected AI runtime."""
from dataclasses import dataclass
from pathlib import Path
import hashlib
from .ai_delivery import ensure_ai_runtime
from .ai_component import component_root_for_runtime
@dataclass(frozen=True)
class BootstrapSpec:
 config_path: Path; checkpoint_path: Path; input_size: tuple; provenance: str; checksum: str; runtime_python: Path
def resolve_landmark_bootstrap(project, progress_callback=None):
 runtime,_=ensure_ai_runtime(project=project,progress=progress_callback); root=component_root_for_runtime(runtime) or runtime.parents[1]
 config=next(iter((root/'vendor'/'mmpose'/'configs'/'animal_2d_keypoint'/'rtmpose'/'ap10k').glob('rtmpose-m_8xb64-210e_ap10k-256x256.py')),None)
 checkpoint=next(iter((root/'assets').glob('rtmpose-m_ap10k_*.pth')),None)
 if not config or not checkpoint or not config.is_file() or not checkpoint.is_file():
  raise RuntimeError('Official RTMPose AP-10K bootstrap is unavailable beside the resolved AI runtime; install/cache the compatible runtime assets.')
 return BootstrapSpec(config,checkpoint,(512,256),'official MMPose AP-10K RTMPose-M local runtime asset',hashlib.sha256(checkpoint.read_bytes()).hexdigest(),runtime)
