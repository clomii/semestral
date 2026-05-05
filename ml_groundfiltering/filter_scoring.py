import argparse
import json
from typing import Dict, Iterable, List, Tuple

import laspy
import numpy as np

from feature_extraction import (
    _geometry_point_mask,
    _normalize_geometry,
    get_feature_identifier,
)


GROUND_CLASSIFICATION = 2


def _ground_mask(las_path: str) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    las = laspy.read(las_path)
    return (
        np.asarray(las.x),
        np.asarray(las.y),
        np.asarray(las.classification) == GROUND_CLASSIFICATION,
    )


def score_ground_masks(reference_ground: np.ndarray, candidate_ground: np.ndarray) -> dict:
    if reference_ground.shape != candidate_ground.shape:
        raise ValueError("Reference and candidate masks have different shapes.")

    true_positive = int(np.sum(reference_ground & candidate_ground))
    false_positive = int(np.sum(~reference_ground & candidate_ground))
    false_negative = int(np.sum(reference_ground & ~candidate_ground))
    true_negative = int(np.sum(~reference_ground & ~candidate_ground))

    precision = true_positive / max(true_positive + false_positive, 1)
    recall = true_positive / max(true_positive + false_negative, 1)
    f1 = 2 * precision * recall / max(precision + recall, 1e-12)
    iou = true_positive / max(true_positive + false_positive + false_negative, 1)
    accuracy = (true_positive + true_negative) / max(reference_ground.size, 1)

    return {
        "precision": float(precision),
        "recall": float(recall),
        "f1": float(f1),
        "iou": float(iou),
        "accuracy": float(accuracy),
        "tp": true_positive,
        "fp": false_positive,
        "fn": false_negative,
        "tn": true_negative,
    }


def score_candidate_las(reference_las: str, candidate_las: str) -> dict:
    _, _, reference_ground = _ground_mask(reference_las)
    _, _, candidate_ground = _ground_mask(candidate_las)
    return score_ground_masks(reference_ground, candidate_ground)


def score_candidates_by_segment(
    reference_las: str,
    candidate_las_by_pipeline: Dict[str, str],
    segmentation_geojson: str,
) -> List[dict]:
    """
    Score candidate filtered LAS files against reference ground points per segment.

    All LAS files must represent the same original point order. This is true for
    many AFwizard/LASTools classification outputs, but should be checked if a
    backend drops or reorders points.
    """
    x, y, reference_ground = _ground_mask(reference_las)
    candidate_ground_by_pipeline = {
        pipeline: _ground_mask(path)[2] for pipeline, path in candidate_las_by_pipeline.items()
    }

    with open(segmentation_geojson, "r", encoding="utf-8") as file:
        segmentation = json.load(file)

    rows = []
    for index, feature in enumerate(segmentation.get("features", [])):
        segment_id = get_feature_identifier(feature, index)
        geometry = _normalize_geometry(feature["geometry"])
        segment_mask = _geometry_point_mask(geometry, x, y)
        if not np.any(segment_mask):
            continue

        best_pipeline = None
        best_metrics = None
        for pipeline, candidate_ground in candidate_ground_by_pipeline.items():
            metrics = score_ground_masks(
                reference_ground[segment_mask], candidate_ground[segment_mask]
            )
            if best_metrics is None or metrics["f1"] > best_metrics["f1"]:
                best_pipeline = pipeline
                best_metrics = metrics

        row = {
            "segment_id": segment_id,
            "pipeline": best_pipeline,
            "point_count": int(np.sum(segment_mask)),
        }
        row.update(best_metrics or {})
        rows.append(row)

    return rows


def write_scored_assignment_geojson(
    segmentation_geojson: str,
    score_rows: List[dict],
    output_geojson: str,
    pipeline_titles: Dict[str, str],
) -> None:
    score_by_segment = {row["segment_id"]: row for row in score_rows}

    with open(segmentation_geojson, "r", encoding="utf-8") as file:
        segmentation = json.load(file)

    for index, feature in enumerate(segmentation.get("features", [])):
        segment_id = get_feature_identifier(feature, index)
        score = score_by_segment.get(segment_id)
        if not score:
            continue

        pipeline = score["pipeline"]
        properties = feature.setdefault("properties", {})
        properties["pipeline"] = pipeline
        properties["pipeline_title"] = pipeline_titles.get(pipeline, pipeline)
        properties["pipeline_key"] = "ground_truth_score"
        properties["score_f1"] = round(score["f1"], 6)
        properties["score_iou"] = round(score["iou"], 6)
        properties["score_precision"] = round(score["precision"], 6)
        properties["score_recall"] = round(score["recall"], 6)

    with open(output_geojson, "w", encoding="utf-8") as file:
        json.dump(segmentation, file, indent=2)


def _parse_candidate(values: Iterable[str]) -> Dict[str, str]:
    parsed = {}
    for value in values:
        if "=" not in value:
            raise ValueError("Candidate must use pipeline_hash=path syntax.")
        pipeline, path = value.split("=", 1)
        parsed[pipeline] = path
    return parsed


def _parse_titles(values: Iterable[str] | None) -> Dict[str, str]:
    parsed = {}
    for value in values or []:
        if "=" not in value:
            raise ValueError("Title must use pipeline_hash=Title syntax.")
        pipeline, title = value.split("=", 1)
        parsed[pipeline] = title
    return parsed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Score candidate ground-filtered LAS files against reference ground points."
    )
    parser.add_argument("--reference", required=True, help="Reference LAS/LAZ with ground class 2")
    parser.add_argument("--segmentation", help="Optional segmentation GeoJSON for per-segment scores")
    parser.add_argument(
        "--candidate",
        action="append",
        required=True,
        help="Candidate in pipeline_hash=filtered.las syntax. Can be repeated.",
    )
    parser.add_argument("--out", help="Optional JSON output path")
    parser.add_argument(
        "--assigned-out",
        help="Optional GeoJSON output with the best scored pipeline assigned per segment",
    )
    parser.add_argument(
        "--title",
        action="append",
        help="Optional pipeline_hash=Human readable title. Can be repeated.",
    )
    args = parser.parse_args()

    candidates = _parse_candidate(args.candidate)
    titles = _parse_titles(args.title)
    if args.segmentation:
        result = score_candidates_by_segment(args.reference, candidates, args.segmentation)
        if args.assigned_out:
            write_scored_assignment_geojson(
                args.segmentation,
                result,
                args.assigned_out,
                titles,
            )
    else:
        if args.assigned_out:
            raise ValueError("--assigned-out requires --segmentation.")
        result = {
            pipeline: score_candidate_las(args.reference, path)
            for pipeline, path in candidates.items()
        }

    if args.out:
        with open(args.out, "w", encoding="utf-8") as file:
            json.dump(result, file, indent=2)
    else:
        print(json.dumps(result, indent=2))
