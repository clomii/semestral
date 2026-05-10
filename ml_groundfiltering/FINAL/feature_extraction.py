import json
import math
from typing import Dict, Iterable, List, Tuple

import laspy
import numpy as np
from shapely.geometry import Point, box, shape
from shapely.prepared import prep


FEATURE_NAMES = [
    "log_point_count",
    "density",
    "z_std",
    "z_range",
    "z_p95_p05",
    "z_iqr",
    "plane_slope",
    "plane_rmse",
    "above_p10_1m_fraction",
    "above_p10_3m_fraction",
]


def get_feature_identifier(feature: dict, index: int = 0) -> str:
    """Return a stable id for GeoJSON features with common AFwizard/workshop keys."""
    properties = feature.get("properties") or {}

    candidates = [
        feature.get("id"),
        properties.get("id"),
        properties.get("segment"),
        properties.get("name"),
        properties.get("class"),
        properties.get("label"),
    ]

    for value in candidates:
        if value is not None and str(value).strip():
            return str(value)

    return f"segment_{index}"


def _load_las_xyz(laz_path: str) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    las = laspy.read(laz_path)
    return np.asarray(las.x), np.asarray(las.y), np.asarray(las.z)


def _normalize_geometry(geojson_geometry: dict):
    geometry = shape(geojson_geometry)
    if not geometry.is_valid:
        geometry = geometry.buffer(0)
    return geometry


def _geometry_point_mask(geometry, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    minx, miny, maxx, maxy = geometry.bounds
    bbox_mask = (x >= minx) & (x <= maxx) & (y >= miny) & (y <= maxy)
    candidate_indices = np.flatnonzero(bbox_mask)

    mask = np.zeros(x.shape, dtype=bool)
    if candidate_indices.size == 0:
        return mask

    try:
        from shapely import contains_xy

        selected = contains_xy(geometry, x[candidate_indices], y[candidate_indices])
    except Exception:
        prepared = prep(geometry)
        selected = np.fromiter(
            (
                prepared.contains(Point(float(px), float(py)))
                for px, py in zip(x[candidate_indices], y[candidate_indices])
            ),
            dtype=bool,
            count=candidate_indices.size,
        )

    mask[candidate_indices] = selected
    return mask


def _fit_plane_features(x: np.ndarray, y: np.ndarray, z: np.ndarray) -> Tuple[float, float]:
    if z.size < 3 or np.ptp(x) == 0 or np.ptp(y) == 0:
        return 0.0, 0.0

    sample_count = min(z.size, 5000)
    sample_idx = np.linspace(0, z.size - 1, sample_count, dtype=int)

    xs = x[sample_idx] - np.mean(x[sample_idx])
    ys = y[sample_idx] - np.mean(y[sample_idx])
    zs = z[sample_idx]

    design = np.column_stack([xs, ys, np.ones(sample_count)])
    coefficients, *_ = np.linalg.lstsq(design, zs, rcond=None)
    predicted = design @ coefficients
    residuals = zs - predicted

    slope = float(math.sqrt(coefficients[0] ** 2 + coefficients[1] ** 2))
    rmse = float(math.sqrt(np.mean(residuals**2)))
    return slope, rmse


def compute_point_features(
    x: np.ndarray, y: np.ndarray, z: np.ndarray, area: float
) -> Tuple[List[float], int]:
    """Compute geometry-only features used by the ML pipeline."""
    point_count = int(z.size)
    if point_count == 0:
        return [0.0 for _ in FEATURE_NAMES], 0

    safe_area = max(float(area), 1e-9)
    percentiles = np.percentile(z, [10, 25, 75, 95, 5])
    p10, p25, p75, p95, p05 = [float(value) for value in percentiles]
    slope, plane_rmse = _fit_plane_features(x, y, z)

    features = [
        float(math.log1p(point_count)),
        float(point_count / safe_area),
        float(np.std(z)),
        float(np.max(z) - np.min(z)),
        float(p95 - p05),
        float(p75 - p25),
        slope,
        plane_rmse,
        float(np.mean(z > p10 + 1.0)),
        float(np.mean(z > p10 + 3.0)),
    ]
    return features, point_count


def _features_for_geometry(
    x: np.ndarray, y: np.ndarray, z: np.ndarray, geometry
) -> Tuple[List[float], int]:
    mask = _geometry_point_mask(geometry, x, y)
    return compute_point_features(x[mask], y[mask], z[mask], geometry.area)


def _iter_tiles(geometry, cell_size: float) -> Iterable:
    minx, miny, maxx, maxy = geometry.bounds
    x0 = minx
    while x0 < maxx:
        y0 = miny
        while y0 < maxy:
            tile = box(x0, y0, min(x0 + cell_size, maxx), min(y0 + cell_size, maxy))
            if geometry.intersects(tile):
                clipped = geometry.intersection(tile)
                if not clipped.is_empty and clipped.area > 0:
                    yield clipped
            y0 += cell_size
        x0 += cell_size


def extract_feature_records(laz_path: str, segment_geojson_path: str) -> List[dict]:
    """Extract one feature vector for each GeoJSON feature."""
    x, y, z = _load_las_xyz(laz_path)

    with open(segment_geojson_path, "r", encoding="utf-8") as file:
        segmentation = json.load(file)

    records = []
    for index, feature in enumerate(segmentation.get("features", [])):
        geometry = _normalize_geometry(feature["geometry"])
        features, point_count = _features_for_geometry(x, y, z, geometry)
        records.append(
            {
                "segment_id": get_feature_identifier(feature, index),
                "features": features,
                "point_count": point_count,
                "area": float(geometry.area),
                "properties": dict(feature.get("properties") or {}),
            }
        )

    return records


def extract_tiled_feature_records(
    laz_path: str,
    segment_geojson_path: str,
    cell_size: float = 40.0,
    min_points: int = 30,
) -> List[dict]:
    """
    Extract tile-level feature vectors grouped by segment.

    Prediction should use the same spatial scale as training. A single feature
    vector for a large segment can wash out local water/vegetation differences,
    while tile voting keeps the model close to the AFwizard tuning workflow.
    """
    x, y, z = _load_las_xyz(laz_path)

    with open(segment_geojson_path, "r", encoding="utf-8") as file:
        segmentation = json.load(file)

    grouped_records = []
    for index, feature in enumerate(segmentation.get("features", [])):
        geometry = _normalize_geometry(feature["geometry"])
        tile_records = []

        for tile_index, tile in enumerate(_iter_tiles(geometry, cell_size)):
            features, point_count = _features_for_geometry(x, y, z, tile)
            if point_count < min_points:
                continue

            tile_records.append(
                {
                    "tile_index": tile_index,
                    "features": features,
                    "point_count": point_count,
                    "area": float(tile.area),
                }
            )

        if not tile_records:
            features, point_count = _features_for_geometry(x, y, z, geometry)
            tile_records.append(
                {
                    "tile_index": None,
                    "features": features,
                    "point_count": point_count,
                    "area": float(geometry.area),
                }
            )

        grouped_records.append(
            {
                "segment_id": get_feature_identifier(feature, index),
                "tile_records": tile_records,
                "tile_features": [record["features"] for record in tile_records],
                "properties": dict(feature.get("properties") or {}),
            }
        )

    return grouped_records


def extract_segment_features(laz_path: str, segment_geojson_path: str) -> Dict[str, List[float]]:
    """Return a mapping segment_id -> feature vector for prediction."""
    return {
        record["segment_id"]: record["features"]
        for record in extract_feature_records(laz_path, segment_geojson_path)
    }


def extract_training_samples(
    laz_path: str,
    assigned_geojson_path: str,
    cell_size: float = 40.0,
    min_points: int = 30,
) -> Tuple[List[List[float]], List[str], Dict[str, str], List[dict]]:
    """
    Build training samples from an AFwizard-assigned segmentation.

    Each tile inside a labelled polygon becomes one training sample. This turns a
    small number of manually labelled AFwizard regions into many local examples.
    """
    x, y, z = _load_las_xyz(laz_path)

    with open(assigned_geojson_path, "r", encoding="utf-8") as file:
        segmentation = json.load(file)

    X: List[List[float]] = []
    y_labels: List[str] = []
    pipeline_titles: Dict[str, str] = {}
    sample_records: List[dict] = []

    for feature_index, feature in enumerate(segmentation.get("features", [])):
        properties = feature.get("properties") or {}
        pipeline = properties.get("pipeline")
        if not pipeline:
            continue

        pipeline = str(pipeline)
        pipeline_titles[pipeline] = str(properties.get("pipeline_title") or pipeline)
        segment_id = get_feature_identifier(feature, feature_index)
        geometry = _normalize_geometry(feature["geometry"])

        samples_added_for_segment = 0
        for tile_index, tile in enumerate(_iter_tiles(geometry, cell_size)):
            features, point_count = _features_for_geometry(x, y, z, tile)
            if point_count < min_points:
                continue

            X.append(features)
            y_labels.append(pipeline)
            sample_records.append(
                {
                    "segment_id": segment_id,
                    "tile_index": tile_index,
                    "pipeline": pipeline,
                    "pipeline_title": pipeline_titles[pipeline],
                    "point_count": point_count,
                    "area": float(tile.area),
                }
            )
            samples_added_for_segment += 1

        if samples_added_for_segment == 0:
            features, point_count = _features_for_geometry(x, y, z, geometry)
            if point_count >= min_points:
                X.append(features)
                y_labels.append(pipeline)
                sample_records.append(
                    {
                        "segment_id": segment_id,
                        "tile_index": None,
                        "pipeline": pipeline,
                        "pipeline_title": pipeline_titles[pipeline],
                        "point_count": point_count,
                        "area": float(geometry.area),
                    }
                )

    return X, y_labels, pipeline_titles, sample_records
