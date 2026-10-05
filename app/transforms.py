from dataclasses import dataclass
import math

@dataclass(frozen=True)
class Transform:
    """Original-to-standardized affine transform and crop provenance."""
    original_width: int
    original_height: int
    rotation_degrees: float
    center_x: float
    center_y: float
    crop_left: float
    crop_top: float
    output_width: int
    output_height: int
    version: str = "affine_crop_v1"

    def original_to_standardized(self, x: float, y: float) -> tuple[float, float]:
        # PIL rotates counter-clockwise in image coordinates (y increases down).
        theta = math.radians(-self.rotation_degrees)
        dx, dy = x - self.center_x, y - self.center_y
        rx = dx * math.cos(theta) - dy * math.sin(theta) + self.center_x
        ry = dx * math.sin(theta) + dy * math.cos(theta) + self.center_y
        return rx - self.crop_left, ry - self.crop_top

    def standardized_to_original(self, x: float, y: float) -> tuple[float, float]:
        theta = math.radians(self.rotation_degrees)
        dx, dy = x + self.crop_left - self.center_x, y + self.crop_top - self.center_y
        return (dx * math.cos(theta) - dy * math.sin(theta) + self.center_x,
                dx * math.sin(theta) + dy * math.cos(theta) + self.center_y)
