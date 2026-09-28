"""Self-healing source launcher for MorphoLabel development checkouts.

The public Windows build is standalone.  This helper exists only for running a
Git checkout: it uses the current Python when the core packages are available,
otherwise it prepares the repo-local .venv and runs from there.  A poisoned or
redirected Windows user-site therefore cannot make RUN_CANONICAL depend on
machine-local APPDATA history.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import sys
import venv


REPO_ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = REPO_ROOT / "requirements.txt"
VENV_ROOT = REPO_ROOT / ".venv"
STAMP_FILE = VENV_ROOT / ".morpholabel-requirements.sha256"
CANONICAL = REPO_ROOT / "tools" / "canonical_exec.py"
CORE_IMPORTS = ("PIL", "numpy", "cv2", "rawpy")


def _venv_python() -> Path:
    return VENV_ROOT / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _requirements_digest() -> str:
    return hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()


def _clean_environment(source=None) -> dict[str, str]:
    """Drop Python path overrides but deliberately preserve OS profile paths."""
    env = dict(os.environ if source is None else source)
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    return env


def _core_available(python: str | Path) -> bool:
    modules = ",".join(repr(name) for name in CORE_IMPORTS)
    code = (
        "import importlib.util,sys;"
        f"mods=({modules},);"
        "sys.exit(0 if all(importlib.util.find_spec(m) is not None for m in mods) else 2)"
    )
    try:
        result = subprocess.run(
            [str(python), "-E", "-B", "-c", code],
            cwd=REPO_ROOT,
            env=_clean_environment(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return False
    return result.returncode == 0


def _ensure_local_venv() -> Path:
    python = _venv_python()
    digest = _requirements_digest()
    current = ""
    try:
        current = STAMP_FILE.read_text(encoding="ascii").strip()
    except OSError:
        pass

    if not python.is_file():
        print("MorphoLabel source setup: creating local .venv ...", flush=True)
        venv.EnvBuilder(with_pip=True, clear=False, symlinks=False).create(VENV_ROOT)

    if current != digest or not _core_available(python):
        print("MorphoLabel source setup: installing core dependencies (one-time/update) ...", flush=True)
        subprocess.run(
            [
                str(python), "-m", "pip", "install",
                "--disable-pip-version-check",
                "-r", str(REQUIREMENTS),
            ],
            cwd=REPO_ROOT,
            env=_clean_environment(),
            check=True,
        )
        if not _core_available(python):
            raise RuntimeError("MorphoLabel source environment is incomplete after installing requirements.txt")
        STAMP_FILE.write_text(digest, encoding="ascii")

    return python


def resolve_source_python() -> Path:
    """Prefer the host Python only when it can actually import core packages."""
    host = Path(sys.executable)
    if _core_available(host):
        return host
    print(
        "MorphoLabel source setup: host Python cannot see the core packages; "
        "using an isolated repo-local .venv instead.",
        flush=True,
    )
    return _ensure_local_venv()


def main(argv: list[str] | None = None) -> int:
    python = resolve_source_python()
    command = [
        str(python), "-E", "-B", str(CANONICAL),
        *(list(sys.argv[1:]) if argv is None else list(argv)),
    ]
    return int(subprocess.call(command, cwd=REPO_ROOT, env=_clean_environment()))


if __name__ == "__main__":
    raise SystemExit(main())
