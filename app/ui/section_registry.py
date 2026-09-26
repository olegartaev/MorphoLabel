"""Section visibility metadata for the production shell."""
from dataclasses import dataclass
@dataclass(frozen=True)
class Section: key:str; label:str; requires_crop:bool=False
SECTIONS=(Section("project","Project"),Section("crop","Crop",True),Section("landmarks","Landmarks"),Section("measurements","Measurements"),Section("export","Export"))
def visible_sections(crop_enabled:bool): return tuple(s for s in SECTIONS if crop_enabled or not s.requires_crop)