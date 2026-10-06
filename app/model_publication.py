"""Publish complete new model directories without modifying older artifacts."""
from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import tempfile


@contextmanager
def staged_model_directory(target):
    """Keep staging on the target volume; clean only this attempt's artifacts.

    The caller validates all artifacts before publish, then registers while
    still inside the context. A registration failure removes the new child.
    """
    target=Path(target)
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists():raise FileExistsError(target)
    staging=Path(tempfile.mkdtemp(prefix=f".{target.name}.training-",dir=target.parent))
    published=False
    def publish():
        nonlocal published
        if published:raise RuntimeError("Model artifacts already published")
        if target.exists():raise FileExistsError(target)
        os.rename(staging,target)
        published=True
    try:
        yield staging,publish
    except BaseException:
        if published:shutil.rmtree(target)
        raise
    finally:
        if staging.exists():shutil.rmtree(staging)
