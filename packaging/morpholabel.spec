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
        (str(ROOT / "LICENSE"), "."),
        (str(ROOT / "NOTICE"), "."),
    ],
    hiddenimports=collect_submodules("app"),
    hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=["tests", "tools"], noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="MorphoLabel", debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="MorphoLabel")
