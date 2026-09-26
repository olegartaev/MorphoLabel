"""Canonical, provenance-checked entry point for executable MorphoLabel commands."""
from __future__ import annotations

import argparse
import importlib
import importlib.util
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _inside_repo(path: str | Path) -> bool:
    try:
        Path(path).resolve().relative_to(REPO_ROOT)
    except ValueError:
        return False
    return True


def _module_source(module_name: str) -> str:
    """Resolve a module source without executing that module's dependency tree."""
    spec = importlib.util.find_spec(module_name)
    origin = getattr(spec, "origin", None)
    if spec is None or not origin:
        raise RuntimeError(f"MorphoLabel canonical-source verification failed; cannot resolve {module_name}")
    source = Path(origin).resolve()
    if not _inside_repo(source):
        raise RuntimeError(
            f"MorphoLabel canonical-source verification failed; {module_name} resolves outside this checkout: {source}"
        )
    return str(source)


def verify_provenance() -> dict[str, str]:
    """Pin this checkout first while leaving normal third-party site-packages available."""
    root = str(REPO_ROOT)
    sys.path[:] = [entry for entry in sys.path if Path(entry or ".").resolve() != REPO_ROOT]
    sys.path.insert(0, root)

    existing_app = sys.modules.get("app")
    existing_source = getattr(existing_app, "__file__", None) if existing_app is not None else None
    if existing_source and not _inside_repo(existing_source):
        raise RuntimeError(
            f"MorphoLabel canonical-source verification failed; app was already loaded outside this checkout: {existing_source}"
        )

    app = importlib.import_module("app")
    sources = {
        "CANONICAL_REPO": root,
        "APP_SOURCE": str(Path(app.__file__).resolve()),
        "SHELL_SOURCE": _module_source("app.ui.shell"),
        "TRAINING_WORKFLOW_SOURCE": _module_source("app.landmark_training_workflow"),
        "BOOTSTRAP_SOURCE": _module_source("app.landmark_bootstrap"),
        "HOST_PYTHON": str(Path(sys.executable).resolve()),
    }
    if not all(_inside_repo(value) for key, value in sources.items() if key.endswith("_SOURCE")):
        raise RuntimeError("MorphoLabel canonical-source verification failed; app modules are not from this checkout")
    return sources


def print_provenance() -> None:
    for key, value in verify_provenance().items():
        print(f"{key}={value}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run only provenance-checked MorphoLabel commands.")
    parser.add_argument("command", choices=("shell", "shell-landmarks", "first-model-smoke", "provenance"))
    command = parser.parse_args(argv).command
    print_provenance()
    if command == "provenance":
        return 0
    if command in {"shell", "shell-landmarks"}:
        if command == "shell":
            from app.ui.shell import run
            run()
        else:
            from app.ui.shell import ProductionShell
            from app.ui.preferences import last_project
            from app.project_storage import Project
            project_path = last_project()
            shell = ProductionShell(Project.open(project_path) if project_path is not None else None)
            shell.select("landmarks")
            shell.mainloop()
        return 0
    from tools.gate4a_smoke import main as smoke
    return int(smoke())


if __name__ == "__main__":
    raise SystemExit(main())
