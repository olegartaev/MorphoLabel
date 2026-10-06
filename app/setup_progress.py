"""Component overview and monotonic first-run progress, independent of Tk."""
from dataclasses import dataclass
import re


@dataclass(frozen=True)
class Component:
    stage: str
    name: str
    used_by: str
    purpose: str
    weight: int


COMPONENTS = (
    Component("CORE", "MorphoLabel Core", "Application", "Program and project tools", 5),
    Component("AI ENGINE", "Shared AI engine", "Landmarks + X-ray Traits", "Python / PyTorch / OpenMMLab libraries", 48),
    Component("PRETRAINED MODEL", "Landmark AI starter", "Landmarks", "RTMPose-M AP-10K starting model", 12),
    Component("XRAY CROP", "X-ray Crop detector starter", "X-ray Traits", "RTMDet-Tiny initial detector weights", 8),
    Component("XRAY ORIENTATION", "X-ray orientation starter", "X-ray Traits", "MobileNetV3 initial orientation weights", 4),
    Component("XRAY STRUCTURE", "X-ray Structure AI starter", "X-ray Traits", "ResNet18 initial Structure-AI weights", 8),
    Component("HARDWARE", "Hardware profile", "All AI", "CPU / GPU / CUDA qualification", 5),
    Component("AI TEST", "AI qualification", "AI", "Disposable prediction and training checks", 10),
)


class SetupProgress:
    def __init__(self):
        self.status = {item.stage: "○ Waiting" for item in COMPONENTS}
        self.fractions = {item.stage: 0.0 for item in COMPONENTS}
        self.status["CORE"] = "✓ Ready"
        self.fractions["CORE"] = 1.0
        self.current = None
        self.overall = 5.0
        self.component_percent = 0
        self.started = False

    def start(self):
        self.started = True

    def retry(self):
        for stage, value in self.status.items():
            if value == "⚠ Failed":
                self.status[stage] = "○ Waiting"

    def update(self, stage, detail):
        self.started = True
        if stage == "READY":
            for item in COMPONENTS:
                self.status[item.stage] = "✓ Ready"
                self.fractions[item.stage] = 1.0
            self.overall = 100.0
            self.component_percent = 100
            return
        if stage not in self.status:
            return
        self.current = stage
        text = str(detail).lower()
        match = re.search(r"(\d{1,3})%", text)
        self.component_percent = min(100, int(match[1])) if match else 0
        if detail == "✓ Ready":
            value = 1.0
            status = "✓ Ready"
            self.component_percent = 100
        elif "downloading" in text or "resuming" in text:
            value = self.component_percent / 100 * .95
            status = f"↓ Downloading {self.component_percent}%" if match else "↓ Downloading"
        elif "installing" in text:
            value = .96
            status = "⚙ Installing"
        else:
            value = 0.0
            status = "… Checking"
        # Retry never hides components that have already succeeded.
        if self.status[stage] != "✓ Ready":
            self.status[stage] = status
        self.fractions[stage] = max(self.fractions[stage], value)
        self.overall = max(self.overall, sum(item.weight * self.fractions[item.stage] for item in COMPONENTS))

    def fail(self):
        if self.current:
            self.status[self.current] = "⚠ Failed"

    @property
    def ready_count(self):
        return sum(value == "✓ Ready" for value in self.status.values())
