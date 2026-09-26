"""Sequential, non-GUI diagnosis of one cached developed_full PNG."""
from __future__ import annotations
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PIL import Image
from app.developed_cache_v2 import cached_png_ready
from app.gui_crop_debug import log, error
from app.normalization_pipeline import paths
from app.standardize import image_id


def timed(ident, op, path, work):
 started = time.monotonic(); log(ident, op, "START", path=path)
 try:
  result = work()
  log(ident, op, "END", time.monotonic() - started, path)
  return result
 except Exception as exc:
  error(ident, op, path, exc)
  raise


def main():
 parser = argparse.ArgumentParser()
 parser.add_argument("source", nargs="?", help="relative NEF path")
 args = parser.parse_args()
 if args.source:
  source = ROOT / args.source
 else:
  source = ROOT / json.loads((ROOT / "reports" / "visual_crop_acceptance_5.json").read_text(encoding="utf-8"))[0]["source"]
 ident = image_id(source)
 developed = paths(source)[2]
 log(ident, "diagnostic", "START", path=str(source))
 ready = timed(ident, "cache_validation_no_raw", str(developed), lambda: cached_png_ready(source))
 stat = timed(ident, "developed_full_stat", str(developed), developed.stat)
 log(ident, "developed_full_stat", "END", path=str(developed), detail=f"bytes={stat.st_size} cache_ready={ready} rawpy_nef_calls=0")
 image = timed(ident, "png_open", str(developed), lambda: Image.open(developed))
 timed(ident, "png_force_decode", str(developed), image.load)
 log(ident, "decoded_image", "END", path=str(developed), detail=f"width={image.width} height={image.height} mode={image.mode}")
 rgb = timed(ident, "convert_rgb", str(developed), lambda: image.convert("RGB"))
 proxy = timed(ident, "display_proxy", str(developed), lambda: rgb.copy())
 timed(ident, "display_proxy_thumbnail", str(developed), lambda: proxy.thumbnail((1800, 1800)))
 log(ident, "display_proxy", "END", path=str(developed), detail=f"width={proxy.width} height={proxy.height} mode={proxy.mode}")
 log(ident, "diagnostic", "END", path=str(source), detail="rawpy_nef_calls=0")
 print(json.dumps({"image_id": ident, "cache_ready": ready, "developed_full": str(developed), "bytes": stat.st_size, "full": [rgb.width, rgb.height, rgb.mode], "proxy": [proxy.width, proxy.height, proxy.mode], "rawpy_nef_calls": 0}))


if __name__ == "__main__":
 main()
