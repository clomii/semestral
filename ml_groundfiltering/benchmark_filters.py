import argparse
import csv
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import numpy as np
from osgeo import gdal

from rasterize_dtm import rasterize_ground_points


@dataclass(frozen=True)
class FilterCandidate:
    key: str
    title: str
    pipeline_hash: str
    path: Path


def metadata_hash(filter_config: Dict) -> str:
    metadata = filter_config.get("metadata", {})
    metadata_repr = repr({key: metadata[key] for key in sorted(metadata.keys())})
    return hashlib.sha1(metadata_repr.encode()).hexdigest()


def sanitize_key(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return value.strip("_") or "filter"


def discover_filter_candidates(libraries: Iterable[str]) -> List[FilterCandidate]:
    candidates: List[FilterCandidate] = []

    for library in libraries:
        for path in sorted(Path(library).glob("*.json")):
            if path.name == "library.json":
                continue

            try:
                with path.open("r", encoding="utf-8") as file:
                    config = json.load(file)
            except json.JSONDecodeError:
                continue

            if config.get("_backend") != "pipeline" or "metadata" not in config:
                continue

            pipeline_hash = metadata_hash(config)
            title = str(config.get("metadata", {}).get("title") or path.stem)
            key = f"{sanitize_key(title)}_{pipeline_hash[:8]}"
            candidates.append(
                FilterCandidate(
                    key=key,
                    title=title,
                    pipeline_hash=pipeline_hash,
                    path=path,
                )
            )

    unique: Dict[str, FilterCandidate] = {}
    for candidate in candidates:
        unique[candidate.pipeline_hash] = candidate
    return list(unique.values())


def assign_filter_to_segmentation(
    geojson_path: str,
    candidate: FilterCandidate,
    output_path: Path,
) -> Path:
    with open(geojson_path, "r", encoding="utf-8") as file:
        data = json.load(file)

    for feature in data.get("features", []):
        properties = feature.setdefault("properties", {})
        properties["pipeline"] = candidate.pipeline_hash
        properties["pipeline_title"] = candidate.title
        properties["pipeline_key"] = "candidate_benchmark"
        properties["benchmark_filter_path"] = str(candidate.path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2)

    return output_path


def build_afwizard_command(
    las_path: str,
    segmentation_path: Path,
    output_dir: Path,
    epsg: str,
    libraries: Iterable[str],
    lastools_dir: Optional[str],
    resolution: float,
) -> List[str]:
    command = [
        sys.executable,
        "afwizard_fixed_cli.py",
        f"--dataset={las_path}",
        f"--dataset-crs=EPSG:{epsg}",
        f"--segmentation={segmentation_path}",
        f"--segmentation-crs=EPSG:{epsg}",
        f"--output-dir={output_dir}",
        f"--resolution={resolution}",
    ]

    for library in libraries:
        command.append(f"--library={library}")

    if lastools_dir:
        command.append(f"--lastools-dir={lastools_dir}")

    return command


def raster_bounds(dataset) -> List[float]:
    transform = dataset.GetGeoTransform()
    min_x = transform[0]
    max_y = transform[3]
    max_x = min_x + transform[1] * dataset.RasterXSize
    min_y = max_y + transform[5] * dataset.RasterYSize
    return [min(min_x, max_x), min(min_y, max_y), max(min_x, max_x), max(min_y, max_y)]


def raster_array_and_mask(dataset):
    band = dataset.GetRasterBand(1)
    array = band.ReadAsArray().astype(float)
    nodata = band.GetNoDataValue()

    mask = np.isfinite(array)
    if nodata is not None:
        mask &= array != nodata
    return array, mask


def compare_dtms(reference_tiff: str, candidate_tiff: str) -> Dict[str, float]:
    gdal.UseExceptions()

    reference = gdal.Open(reference_tiff)
    if reference is None:
        raise FileNotFoundError(reference_tiff)

    candidate = gdal.Open(candidate_tiff)
    if candidate is None:
        raise FileNotFoundError(candidate_tiff)

    ref_transform = reference.GetGeoTransform()
    pixel_width = abs(ref_transform[1])
    pixel_height = abs(ref_transform[5])
    ref_bounds = raster_bounds(reference)
    cand_nodata = candidate.GetRasterBand(1).GetNoDataValue()

    warped_candidate = gdal.Warp(
        "",
        candidate,
        format="MEM",
        outputBounds=ref_bounds,
        xRes=pixel_width,
        yRes=pixel_height,
        dstSRS=reference.GetProjection() or None,
        resampleAlg="bilinear",
        srcNodata=cand_nodata,
        dstNodata=-9999,
    )

    reference_array, reference_mask = raster_array_and_mask(reference)
    candidate_array, candidate_mask = raster_array_and_mask(warped_candidate)

    mask = reference_mask & candidate_mask
    valid_pixels = int(np.count_nonzero(mask))
    if valid_pixels == 0:
        raise ValueError("No overlapping valid raster pixels were found.")

    diff = candidate_array[mask] - reference_array[mask]
    abs_diff = np.abs(diff)

    return {
        "rmse": float(math.sqrt(np.mean(diff ** 2))),
        "mae": float(np.mean(abs_diff)),
        "bias": float(np.mean(diff)),
        "median_abs": float(np.median(abs_diff)),
        "p95_abs": float(np.percentile(abs_diff, 95)),
        "valid_pixels": valid_pixels,
        "coverage_ratio": float(valid_pixels / reference_array.size),
    }


def write_metrics_csv(rows: List[Dict], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "rank",
        "candidate_key",
        "pipeline_title",
        "pipeline_hash",
        "rmse",
        "mae",
        "bias",
        "median_abs",
        "p95_abs",
        "valid_pixels",
        "coverage_ratio",
        "filtered_las",
        "dtm_tiff",
        "assigned_geojson",
    ]

    with output_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})


def benchmark_candidates(args) -> List[Dict]:
    candidates = discover_filter_candidates(args.library)
    if not candidates:
        raise RuntimeError("No AFwizard pipeline filters were found in the libraries.")

    output_dir = Path(args.outdir)
    output_dir.mkdir(parents=True, exist_ok=True)

    rows: List[Dict] = []
    las_base = Path(args.las).stem

    for candidate in candidates:
        candidate_dir = output_dir / candidate.key
        assigned_geojson = candidate_dir / f"{Path(args.geojson).stem}_{candidate.key}.geojson"
        assign_filter_to_segmentation(args.geojson, candidate, assigned_geojson)

        filtered_las = candidate_dir / f"{las_base}_filtered.las"
        dtm_tiff = candidate_dir / f"{las_base}_filtered_dtm.tiff"

        if args.run_afwizard and (args.force or not filtered_las.exists()):
            command = build_afwizard_command(
                las_path=args.las,
                segmentation_path=assigned_geojson,
                output_dir=candidate_dir,
                epsg=args.epsg,
                libraries=args.library,
                lastools_dir=args.lastools_dir,
                resolution=args.resolution,
            )
            print(f"Running AFwizard candidate {candidate.title}:")
            print(" ".join(str(part) for part in command))
            subprocess.run(command, check=True)

        if not filtered_las.exists():
            raise FileNotFoundError(
                f"{filtered_las} does not exist. Re-run with --run-afwizard."
            )

        if args.force or not dtm_tiff.exists():
            count = rasterize_ground_points(
                las_path=str(filtered_las),
                output_tiff=str(dtm_tiff),
                epsg=args.epsg,
                resolution=args.resolution,
                output_type=args.output_type,
            )
            print(f"Rasterized {count} ground points for {candidate.title}.")

        metrics = compare_dtms(args.reference_dtm, str(dtm_tiff))
        rows.append(
            {
                "candidate_key": candidate.key,
                "pipeline_title": candidate.title,
                "pipeline_hash": candidate.pipeline_hash,
                "filtered_las": str(filtered_las),
                "dtm_tiff": str(dtm_tiff),
                "assigned_geojson": str(assigned_geojson),
                **metrics,
            }
        )

    rows.sort(key=lambda row: row["rmse"])
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank

    write_metrics_csv(rows, output_dir / "candidate_metrics.csv")
    with (output_dir / "candidate_metrics.json").open("w", encoding="utf-8") as file:
        json.dump(rows, file, indent=2)

    best = rows[0]
    best_source = Path(best["assigned_geojson"])
    shutil.copyfile(best_source, output_dir / "best_filter_assigned.geojson")

    print("\nCandidate filter ranking by DTM RMSE:")
    for row in rows:
        print(
            f"#{row['rank']} {row['pipeline_title']}: "
            f"RMSE={row['rmse']:.3f}, MAE={row['mae']:.3f}, "
            f"coverage={row['coverage_ratio']:.1%}"
        )

    print(f"\nBest filter: {best['pipeline_title']} ({best['pipeline_hash']})")
    return rows


def parse_args():
    parser = argparse.ArgumentParser(
        description="Benchmark AFwizard filter candidates against a reference DTM."
    )
    parser.add_argument("--las", required=True, help="Input LAS/LAZ point cloud")
    parser.add_argument("--geojson", required=True, help="Target segmentation GeoJSON")
    parser.add_argument("--reference-dtm", required=True, help="Reference DTM GeoTIFF")
    parser.add_argument("--epsg", required=True, help="EPSG code without the EPSG: prefix")
    parser.add_argument(
        "--library",
        action="append",
        required=True,
        help="AFwizard filter library directory. Can be repeated.",
    )
    parser.add_argument("--outdir", required=True, help="Benchmark output directory")
    parser.add_argument("--lastools-dir", default=None, help="LASTools directory inside the runtime")
    parser.add_argument("--resolution", type=float, default=1.0, help="DTM raster resolution")
    parser.add_argument(
        "--output-type",
        default="min",
        choices=["min", "max", "mean", "idw", "count", "stdev"],
        help="PDAL writers.gdal output_type for DTM candidate rasters",
    )
    parser.add_argument(
        "--run-afwizard",
        action="store_true",
        help="Run AFwizard for candidates whose filtered LAS is missing.",
    )
    parser.add_argument("--force", action="store_true", help="Rebuild candidate outputs")
    return parser.parse_args()


if __name__ == "__main__":
    benchmark_candidates(parse_args())
