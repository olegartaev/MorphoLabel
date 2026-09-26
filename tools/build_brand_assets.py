"""Generate Windows branding assets from the single embedded MorphoLabel PNG source."""
from __future__ import annotations
import base64
from io import BytesIO
from pathlib import Path
from PIL import Image
from app.identity import ICON_PNG_BASE64, ICON_SOURCE_SHA256
import hashlib

def generate(output_root: Path):
    output_root=Path(output_root)
    output_root.mkdir(parents=True,exist_ok=True)
    raw=base64.b64decode(ICON_PNG_BASE64)
    if hashlib.sha256(raw).hexdigest()!=ICON_SOURCE_SHA256:
        raise RuntimeError("embedded MorphoLabel icon checksum mismatch")
    image=Image.open(BytesIO(raw)).convert("RGBA")
    target=output_root/"MorphoLabel.ico"
    image.save(target,format="ICO",sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
    return target

if __name__=="__main__":
    import sys
    print(generate(Path(sys.argv[1] if len(sys.argv)>1 else "build/brand")))
