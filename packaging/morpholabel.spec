# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules
ROOT = Path(SPEC).resolve().parents[1]
# High-resolution Structure AI fine-tuning is deliberately launched by the
# separately managed CUDA Python runtime, not by the frozen Tk executable.
# That process must be able to import the same local application modules.
# PyInstaller's PYZ is not importable from a separate Python interpreter, so
# package source modules as files too. This ships no models or user data.
required_xray_runners = (
    "xray_detector_runner.py",
    "xray_orientation_runner.py",
    "xray_structure_runner.py",
)
required_xray_runner_paths = {
    (ROOT / "ai_runtime" / name).resolve() for name in required_xray_runners
}
training_worker_sources = [
    (str(module), str(module.parent.relative_to(ROOT)))
    for package in ("app", "ai_runtime")
    for module in sorted((ROOT / package).rglob("*.py"))
    if module.resolve() not in required_xray_runner_paths
]
training_worker_sources.extend(
    (str(ROOT / "ai_runtime" / name), "ai_runtime")
    for name in required_xray_runners
)
training_worker_sources.append(
    (str(ROOT / "tools" / "train_universal_multires.py"), "tools")
)
a = Analysis(
    [str(ROOT / "packaging" / "entrypoint.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        *training_worker_sources,
        (str(ROOT / "app" / "resources" / "xray_trait_schemes"), "app/resources/xray_trait_schemes"),
        (str(ROOT / "app" / "resources" / "module_covers"), "app/resources/module_covers"),
        (str(ROOT / "app" / "resources" / "orientation"), "app/resources/orientation"),
        (str(ROOT / "LICENSE"), "."),
        (str(ROOT / "NOTICE"), "."),
        (str(ROOT / "build" / "third_party" / "THIRD_PARTY_NOTICES.txt"), "."),
        (str(ROOT / "build" / "third_party" / "licenses"), "licenses"),
    ],
    hiddenimports=collect_submodules("app") + ["ai_runtime.universal_multires"],
    hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=["tests", "tools"], noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="MorphoLabel", debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=False,
          icon=str(ROOT / "build" / "brand" / "MorphoLabel.ico"))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="MorphoLabel")
