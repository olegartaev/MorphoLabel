"""Pinned official X-ray starter assets in MorphoLabel-owned user state."""
from dataclasses import dataclass
from .runtime_paths import app_state_dir, is_frozen
from .verified_download import download_verified, sha256_file

SETUP_HELP = "Open Menu → AI support → Set up AI support… to repair the missing or damaged AI starter."


@dataclass(frozen=True)
class Starter:
    role: str
    stage: str
    name: str
    url: str
    sha256: str
    size: int

    @property
    def path(self):
        return app_state_dir() / "starters" / self.url.rsplit("/", 1)[1]

    def record(self):
        return dict(path=str(self.path), url=self.url, sha256=self.sha256, bytes=self.size)


# Independently streamed and hashed from these upstream URLs on 2026-10-06.
STARTERS = (
    Starter("detector", "XRAY CROP", "RTMDet-Tiny starter",
            "https://download.openmmlab.com/mmdetection/v3.0/rtmdet/rtmdet_tiny_8xb32-300e_coco/rtmdet_tiny_8xb32-300e_coco_20220902_112414-78e30dcc.pth",
            "78e30dcce0c6f594eaff0d6977b84b4103688b4aff0ad1aa16008a8cc854a7fb", 57532893),
    Starter("orientation", "XRAY ORIENTATION", "MobileNetV3 starter",
            "https://download.pytorch.org/models/mobilenet_v3_small-047dcff4.pth",
            "047dcff4addef86ea5bc2eff13c9614dc11f47ab1160d0a71a25e7db994f4e1f", 10306551),
    Starter("structure", "XRAY STRUCTURE", "ResNet18 starter",
            "https://download.pytorch.org/models/resnet18-f37072fd.pth",
            "f37072fd47e89c5e827621c5baffa7500819f7896bbacec160b1a16c560e07ec", 46830571),
)


def starter_valid(spec):
    return spec.path.is_file() and spec.path.stat().st_size == spec.size and sha256_file(spec.path) == spec.sha256


def install_starter(spec, progress=None):
    from .first_run_setup import ai_setup_download_active
    if is_frozen() and not ai_setup_download_active():
        raise RuntimeError(SETUP_HELP)
    return download_verified(spec.url, spec.path, spec.sha256, expected_bytes=spec.size, name=spec.name,
                             progress=(lambda detail: progress(spec.stage, detail)) if progress else None)


def local_starter(role):
    """Never performs network IO. None opts source checkouts into legacy behavior."""
    spec = next(item for item in STARTERS if item.role == role)
    if starter_valid(spec):
        return str(spec.path)
    if is_frozen():
        raise RuntimeError(SETUP_HELP)
    return None
