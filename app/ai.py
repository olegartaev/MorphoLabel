"""Small GUI-independent landmark inference contract.

Backends consume standardized-pixel requests and return no GUI/canvas state.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

@dataclass(frozen=True)
class InferenceRequest:
    image_id: str
    standardized_image_path: Path
    schema: tuple[Mapping[str, object], ...]
    schema_sha256: str
    width: int | None = None
    height: int | None = None

@dataclass(frozen=True)
class LandmarkPrediction:
    landmark_id: int
    x: float
    y: float
    confidence: float | None = None

@dataclass(frozen=True)
class ImagePrediction:
    image_id: str
    model_id: str
    schema_sha256: str
    landmarks: tuple[LandmarkPrediction, ...]

class LandmarkBackend(ABC):
    """Stable adapter boundary. Backends never replace human final records."""
    model_id: str
    schema_sha256: str
    @abstractmethod
    def predict(self, request: InferenceRequest) -> ImagePrediction: ...
    @abstractmethod
    def train(self, dataset_manifest: str, output_dir: str) -> dict: ...
    @abstractmethod
    def evaluate(self, dataset_manifest: str) -> dict: ...
    @abstractmethod
    def export(self, output_dir: str) -> dict: ...
    @abstractmethod
    def model_info(self) -> dict: ...

class UnconfiguredBackend(LandmarkBackend):
    model_id = "unconfigured"
    schema_sha256 = ""
    def _unconfigured(self):
        raise RuntimeError("No trained AI backend is configured. Manual landmarks remain available.")
    def predict(self, request: InferenceRequest) -> ImagePrediction:
        self._unconfigured()
    train = lambda self, *args: self._unconfigured()
    evaluate = lambda self, *args: self._unconfigured()
    export = lambda self, *args: self._unconfigured()
    def model_info(self):
        return {"status": "unconfigured", "candidates": ["RTMPose", "HRNet", "ViTPose"]}

class MockBackend(LandmarkBackend):
    """Deterministic test-only backend; it has no ML dependencies."""
    def __init__(self, schema_sha256: str, *, model_id: str = "mock-landmark-v1",
                 missing_ids=frozenset(), confidences=None, coordinate_overrides=None,
                 extra_predictions=(), fail_image_ids=frozenset()):
        self.schema_sha256 = schema_sha256
        self.model_id = model_id
        self.missing_ids = frozenset(int(value) for value in missing_ids)
        self.confidences = dict(confidences or {})
        self.coordinate_overrides = dict(coordinate_overrides or {})
        self.extra_predictions = tuple(extra_predictions)
        self.fail_image_ids = frozenset(str(value) for value in fail_image_ids)
    def predict(self, request: InferenceRequest) -> ImagePrediction:
        if request.image_id in self.fail_image_ids:
            raise RuntimeError("mock backend configured failure")
        if request.schema_sha256 != self.schema_sha256:
            raise ValueError("mock backend schema hash does not match request schema")
        width, height = request.width or 1, request.height or 1
        landmarks = []
        for row in request.schema:
            landmark_id = int(row["id"])
            if landmark_id in self.missing_ids:
                continue
            x, y = self.coordinate_overrides.get(landmark_id, ((landmark_id * 37) % width, (landmark_id * 53) % height))
            landmarks.append(LandmarkPrediction(landmark_id, x, y, self.confidences.get(landmark_id, 0.9)))
        return ImagePrediction(request.image_id, self.model_id, self.schema_sha256, tuple(landmarks) + self.extra_predictions)
    train = lambda self, *args: {"status": "mock-no-training"}
    evaluate = lambda self, *args: {"status": "mock-no-evaluation"}
    export = lambda self, *args: {"status": "mock-no-export"}
    def model_info(self):
        return {"model_id": self.model_id, "schema_sha256": self.schema_sha256, "backend": "MockBackend", "status": "test_only"}