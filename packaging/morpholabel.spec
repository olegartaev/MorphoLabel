# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules
ROOT = Path(SPEC).resolve().parents[1]
a = Analysis(
    [str(ROOT / "packaging" / "entrypoint.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / "ai_runtime" / "rtmpose_runner.py"), "ai_runtime"),
        (str(ROOT / "ai_runtime" / "xray_detector_runner.py"), "ai_runtime"),
        (str(ROOT / "ai_runtime" / "xray_orientation_runner.py"), "ai_runtime"),
        (str(ROOT / "ai_runtime" / "xray_structure_runner.py"), "ai_runtime"),
        (str(ROOT / "app" / "resources" / "xray_trait_schemes"), "app/resources/xray_trait_schemes"),
        (str(ROOT / "app" / "resources" / "module_covers"), "app/resources/module_covers"),
        (str(ROOT / "LICENSE"), "."),
        (str(ROOT / "NOTICE"), "."),
        (str(ROOT / "build" / "third_party" / "THIRD_PARTY_NOTICES.txt"), "."),
        (str(ROOT / "build" / "third_party" / "licenses"), "licenses"),
    ],
    hiddenimports=collect_submodules("app"),
    hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=["tests", "tools"], noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="MorphoLabel", debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=False,
          icon=str(ROOT / "build" / "brand" / "MorphoLabel.ico"))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="MorphoLabel")
