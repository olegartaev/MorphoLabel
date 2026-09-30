"""Lightweight, deterministic X-ray specimen detection and oriented crop proposals."""
from __future__ import annotations

from dataclasses import dataclass, asdict
import math

import cv2
import numpy as np
from PIL import Image

ALGORITHM_VERSION = "xray-otsu-pca-v1"


@dataclass(frozen=True)
class CropProposal:
    center_x: float
    center_y: float
    length: float
    width: float
    angle_degrees: float
    corners: tuple[tuple[float, float], ...]
    bounds: tuple[float, float, float, float]
    confidence: str
    qc: tuple[str, ...]
    algorithm: str = ALGORITHM_VERSION

    def to_dict(self):
        data = asdict(self)
        data["corners"] = [list(p) for p in self.corners]
        data["bounds"] = list(self.bounds)
        data["qc"] = list(self.qc)
        return data


def _read_gray(path, max_dim=1200):
    with Image.open(path) as image:
        arr = np.asarray(image)
    if arr.ndim == 3:
        if arr.shape[2] == 4:
            arr = cv2.cvtColor(arr, cv2.COLOR_RGBA2GRAY)
        else:
            arr = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    if arr.ndim != 2:
        raise ValueError("Unsupported X-ray image shape")
    original_h, original_w = arr.shape
    scale = min(1.0, float(max_dim) / max(original_h, original_w))
    if scale < 1.0:
        arr = cv2.resize(arr, (round(original_w * scale), round(original_h * scale)), interpolation=cv2.INTER_AREA)
    work = arr.astype(np.float32)
    lo, hi = np.percentile(work, (0.5, 99.5))
    if hi <= lo:
        raise ValueError("X-ray image has no usable intensity range")
    preview = np.clip((work - lo) / (hi - lo) * 255.0, 0, 255).astype(np.uint8)
    return preview, scale, (original_w, original_h)


def _smooth_1d(values, sigma):
    values = np.asarray(values, dtype=np.float32).reshape(1, -1)
    kernel = max(3, int(round(float(sigma) * 6)) | 1)
    return cv2.GaussianBlur(values, (kernel, 1), sigmaX=max(0.1, float(sigma)), borderType=cv2.BORDER_REPLICATE).ravel()


def _peaks(values, min_distance, min_height):
    values = np.asarray(values, dtype=float)
    if len(values) < 3:
        return []
    candidates = np.where((values[1:-1] >= values[:-2]) & (values[1:-1] >= values[2:]))[0] + 1
    candidates = sorted(candidates, key=lambda i: values[i], reverse=True)
    chosen = []
    for index in candidates:
        if values[index] < min_height:
            continue
        if all(abs(int(index) - old) >= int(min_distance) for old in chosen):
            chosen.append(int(index))
    return sorted(chosen)


def _pca(points):
    mean = points.mean(axis=0)
    values, vectors = np.linalg.eigh(np.cov((points - mean).T))
    major = vectors[:, int(np.argmax(values))]
    if abs(major[0]) >= abs(major[1]):
        if major[0] < 0:
            major = -major
    elif major[1] < 0:
        major = -major
    minor = np.array([-major[1], major[0]], dtype=float)
    projected = np.column_stack(((points - mean) @ major, (points - mean) @ minor))
    return mean, major, minor, projected


def _component_geometry(points):
    mean, major, minor, projected = _pca(points)
    quantiles = np.percentile(projected, (1.0, 99.0), axis=0)
    length, width = quantiles[1] - quantiles[0]
    return mean, major, minor, projected, quantiles, float(length / (width + 1e-6))


def _split_component(points, image_area):
    _, _, _, projected, _, ratio = _component_geometry(points)
    area_fraction = len(points) / float(image_area)
    if ratio >= 2.8 or area_fraction <= 0.04:
        return [(points, None)]
    cross = projected[:, 1]
    low, high = int(np.floor(cross.min())), int(np.ceil(cross.max()))
    if high - low < 20:
        return [(points, None)]
    hist = np.histogram(cross, bins=np.arange(low, high + 2))[0].astype(float)
    smoothed = _smooth_1d(hist, sigma=max(4.0, len(hist) * 0.013))
    peaks = _peaks(smoothed, max(20, int(len(smoothed) * 0.25)), smoothed.max() * 0.10)
    if len(peaks) < 2:
        return [(points, None)]
    first, second = sorted(sorted(peaks, key=lambda i: smoothed[i], reverse=True)[:2])
    valley_index = first + int(np.argmin(smoothed[first:second + 1]))
    valley_ratio = float(smoothed[valley_index] / max(1e-6, min(smoothed[first], smoothed[second])))
    if valley_ratio >= 0.72:
        return [(points, None)]
    cut = low + valley_index
    groups = []
    for side in (cross <= cut, cross > cut):
        child = points[side]
        if len(child) > 0.005 * image_area:
            groups.append((child, valley_ratio))
    return groups if len(groups) == 2 else [(points, None)]


def _bounds_from_corners(corners, original_size):
    width, height = original_size
    xs = np.asarray(corners)[:, 0]
    ys = np.asarray(corners)[:, 1]
    return (
        float(max(0.0, xs.min())),
        float(max(0.0, ys.min())),
        float(min(width, xs.max())),
        float(min(height, ys.max())),
    )


def detect_specimens(path, max_preview_dim=1200):
    """Return conservative oriented crop proposals in original-image coordinates."""
    preview, scale, original_size = _read_gray(path, max_preview_dim)
    height, width = preview.shape
    image_area = height * width
    border_width = max(5, min(height, width) // 30)
    border = np.concatenate((
        preview[:border_width, :].ravel(), preview[-border_width:, :].ravel(),
        preview[:, :border_width].ravel(), preview[:, -border_width:].ravel(),
    ))
    threshold, _ = cv2.threshold(preview, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    bright_foreground = float(np.median(border)) <= float(threshold)
    mask = ((preview > threshold) if bright_foreground else (preview <= threshold)).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)

    components = []
    min_area = max(120, int(image_area * 0.008))
    for label in range(1, count):
        area = int(stats[label, cv2.CC_STAT_AREA])
        if area < min_area:
            continue
        ys, xs = np.nonzero(labels == label)
        points = np.column_stack((xs, ys)).astype(np.float32)
        _, _, _, _, quantiles, ratio = _component_geometry(points)
        length = float(quantiles[1, 0] - quantiles[0, 0])
        if length < 0.12 * max(width, height):
            continue
        if ratio < 1.35 and area < 0.04 * image_area:
            continue
        components.extend(_split_component(points, image_area))

    geometries = []
    for points, split_ratio in components:
        mean, major, minor, projected = _pca(points)
        quantiles = np.percentile(projected, (0.5, 99.5), axis=0)
        geometries.append({
            "points": points, "mean": mean, "major": major, "minor": minor,
            "q": quantiles, "split_ratio": split_ratio,
        })

    proposals = []
    for index, geom in enumerate(geometries):
        q = geom["q"]
        core_length, core_width = q[1] - q[0]
        u0, u1 = q[0, 0] - 0.18 * core_length, q[1, 0] + 0.18 * core_length
        v0, v1 = q[0, 1] - 0.35 * core_width, q[1, 1] + 0.35 * core_width
        min_u0, min_u1 = q[0, 0] - 0.10 * core_length, q[1, 0] + 0.10 * core_length
        min_v0, min_v1 = q[0, 1] - 0.12 * core_width, q[1, 1] + 0.12 * core_width
        neighbor_limited = False
        others = [item["points"] for j, item in enumerate(geometries) if j != index]
        if others:
            other_points = np.vstack(others)
            uv = np.column_stack((
                (other_points - geom["mean"]) @ geom["major"],
                (other_points - geom["mean"]) @ geom["minor"],
            ))
            gap_v = 0.05 * core_width
            gap_u = 0.04 * core_length
            in_u = (uv[:, 0] >= u0) & (uv[:, 0] <= u1)
            positive = uv[in_u & (uv[:, 1] > q[1, 1]), 1]
            negative = uv[in_u & (uv[:, 1] < q[0, 1]), 1]
            if len(positive):
                new = max(min_v1, min(v1, float(positive.min() - gap_v)))
                neighbor_limited |= new < v1
                v1 = new
            if len(negative):
                new = min(min_v0, max(v0, float(negative.max() + gap_v)))
                neighbor_limited |= new > v0
                v0 = new
            in_v = (uv[:, 1] >= v0) & (uv[:, 1] <= v1)
            positive_u = uv[in_v & (uv[:, 0] > q[1, 0]), 0]
            negative_u = uv[in_v & (uv[:, 0] < q[0, 0]), 0]
            if len(positive_u):
                new = max(min_u1, min(u1, float(positive_u.min() - gap_u)))
                neighbor_limited |= new < u1
                u1 = new
            if len(negative_u):
                new = min(min_u0, max(u0, float(negative_u.max() + gap_u)))
                neighbor_limited |= new > u0
                u0 = new

        preview_corners = np.asarray([
            geom["mean"] + u0 * geom["major"] + v0 * geom["minor"],
            geom["mean"] + u1 * geom["major"] + v0 * geom["minor"],
            geom["mean"] + u1 * geom["major"] + v1 * geom["minor"],
            geom["mean"] + u0 * geom["major"] + v1 * geom["minor"],
        ], dtype=float)
        corners = preview_corners / scale
        center = geom["mean"] / scale
        angle = math.degrees(math.atan2(float(geom["major"][1]), float(geom["major"][0])))
        if angle > 90:
            angle -= 180
        if angle <= -90:
            angle += 180

        qc = []
        points = geom["points"]
        edge_pad = max(3, int(min(height, width) * 0.004))
        source_incomplete = bool(
            (points[:, 0] <= edge_pad).any() or (points[:, 0] >= width - 1 - edge_pad).any() or
            (points[:, 1] <= edge_pad).any() or (points[:, 1] >= height - 1 - edge_pad).any()
        )
        if source_incomplete:
            qc.append("source_incomplete")
        if geom["split_ratio"] is not None and geom["split_ratio"] > 0.55:
            qc.append("ambiguous_split")
        if neighbor_limited and (
            u0 > min_u0 + 1e-6 or u1 < min_u1 - 1e-6 or
            v0 > min_v0 + 1e-6 or v1 < min_v1 - 1e-6
        ):
            qc.append("neighbor_too_close")
        bounds = _bounds_from_corners(corners, original_size)
        confidence = "review" if qc else "high"
        proposals.append(CropProposal(
            center_x=float(center[0]), center_y=float(center[1]),
            length=float((u1 - u0) / scale), width=float((v1 - v0) / scale),
            angle_degrees=float(angle),
            corners=tuple((float(x), float(y)) for x, y in corners),
            bounds=bounds, confidence=confidence, qc=tuple(qc),
        ))

    if proposals:
        vertical = np.median([abs(math.sin(math.radians(p.angle_degrees))) for p in proposals]) > 0.7
        proposals.sort(key=(lambda p: (p.center_x, p.center_y)) if vertical else (lambda p: (p.center_y, p.center_x)))
    return proposals


def display_preview(path, max_dim=1200):
    """Return an 8-bit display-only preview plus scale and original size."""
    preview, scale, original_size = _read_gray(path, max_dim)
    return Image.fromarray(preview), scale, original_size


def crop_corners(center_x, center_y, length, width, angle_degrees):
    angle = math.radians(float(angle_degrees))
    major = np.array([math.cos(angle), math.sin(angle)], dtype=float)
    minor = np.array([-major[1], major[0]], dtype=float)
    center = np.array([float(center_x), float(center_y)], dtype=float)
    half_l, half_w = float(length) / 2.0, float(width) / 2.0
    points = (
        center - half_l * major - half_w * minor,
        center + half_l * major - half_w * minor,
        center + half_l * major + half_w * minor,
        center - half_l * major + half_w * minor,
    )
    return tuple((float(point[0]), float(point[1])) for point in points)


def crop_from_geometry(center_x, center_y, length, width, angle_degrees, image_size, confidence="high", qc=(), algorithm="manual"):
    corners = crop_corners(center_x, center_y, length, width, angle_degrees)
    return {
        "center_x": float(center_x), "center_y": float(center_y),
        "length": float(length), "width": float(width), "angle_degrees": float(angle_degrees),
        "corners": [list(point) for point in corners],
        "bounds": list(_bounds_from_corners(corners, image_size)),
        "confidence": str(confidence), "qc": list(qc), "algorithm": str(algorithm),
    }


def oriented_crop(image, proposal):
    """Extract an upright crop from an in-memory PIL image without modifying the source."""
    p = proposal.to_dict() if isinstance(proposal, CropProposal) else dict(proposal)
    center = (float(p["center_x"]), float(p["center_y"]))
    length, width = float(p["length"]), float(p["width"])
    angle = float(p["angle_degrees"])
    arr = np.asarray(image)
    matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    if arr.ndim == 2:
        border_value = int(np.median(arr))
    else:
        med = np.median(arr.reshape(-1, arr.shape[-1]), axis=0)
        border_value = tuple(float(x) for x in med)
    rotated = cv2.warpAffine(arr, matrix, (arr.shape[1], arr.shape[0]), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=border_value)
    x0 = max(0, int(round(center[0] - length / 2)))
    x1 = min(rotated.shape[1], int(round(center[0] + length / 2)))
    y0 = max(0, int(round(center[1] - width / 2)))
    y1 = min(rotated.shape[0], int(round(center[1] + width / 2)))
    return Image.fromarray(rotated[y0:y1, x0:x1])
