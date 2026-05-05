import argparse
import json
import os
import re
import shlex
import subprocess
from typing import Iterable, List, Optional

from feature_extraction import extract_tiled_feature_records, get_feature_identifier
from ml_optimizer import MLFilterOptimizer


def _infer_epsg_from_geojson(geojson_file: str) -> Optional[str]:
    try:
        with open(geojson_file, "r", encoding="utf-8") as file:
            data = json.load(file)
    except Exception:
        return None

    crs_name = (
        data.get("crs", {})
        .get("properties", {})
        .get("name", "")
    )
    match = re.search(r"EPSG(?::|::)(\d+)", crs_name)
    return match.group(1) if match else None


def _build_afwizard_command(
    las_file: str,
    assigned_geojson_path: str,
    output_dir: str,
    epsg: str,
    filter_libraries: Iterable[str],
    lastools_dir: Optional[str],
) -> List[str]:
    command = [
        "afwizard",
        f"--dataset={las_file}",
        f"--dataset-crs=EPSG:{epsg}",
        f"--segmentation={assigned_geojson_path}",
        f"--segmentation-crs=EPSG:{epsg}",
        f"--output-dir={output_dir}",
    ]

    for library in filter_libraries:
        command.append(f"--library={library}")

    if lastools_dir:
        command.append(f"--lastools-dir={lastools_dir}")

    return command


def automate_filtration_process(
    las_file: str,
    geojson_file: str,
    output_dir: str,
    epsg: Optional[str],
    lastools_dir: Optional[str],
    model_path: str,
    train_las: Optional[str],
    train_geojson: Optional[str],
    filter_libraries: Iterable[str],
    retrain: bool,
    cell_size: float,
    min_points: int,
    run_afwizard: bool,
) -> None:
    print("==================================================")
    print("Automated ML Point Cloud Ground Filtering")
    print("==================================================")

    epsg = epsg or _infer_epsg_from_geojson(geojson_file) or "31256"
    filter_libraries = list(filter_libraries)

    print(f"Dataset:      {las_file}")
    print(f"Segmentation: {geojson_file}")
    print(f"CRS:          EPSG:{epsg}")
    print(f"Model:        {model_path}")

    print("\n1. Training/loading the ML optimizer...")
    optimizer = MLFilterOptimizer(model_path=model_path)
    training_summary = optimizer.load_or_train(
        train_las=train_las,
        train_geojson=train_geojson,
        retrain=retrain,
        cell_size=cell_size,
        min_points=min_points,
    )

    if training_summary is None:
        print("Loaded existing model.")
    else:
        print(
            "Trained model from assigned AFwizard segmentation "
            f"({training_summary['samples']} tiled samples, "
            f"{training_summary['classes']} classes, "
            f"training accuracy={training_summary['training_accuracy']:.3f})."
        )

    print("\n2. Extracting tiled geometric features from target segments...")
    segment_records = extract_tiled_feature_records(
        las_file,
        geojson_file,
        cell_size=cell_size,
        min_points=min_points,
    )
    if not segment_records:
        raise RuntimeError("No target segments were found in the GeoJSON file.")

    tile_count = sum(len(record["tile_records"]) for record in segment_records)
    print(f"Extracted {tile_count} tile feature vectors in {len(segment_records)} segments.")

    print("\n3. Predicting best AFwizard pipeline per segment...")
    assigned_predictions = {}
    for record in segment_records:
        prediction = optimizer.predict_from_samples(record["tile_features"])
        assigned_predictions[record["segment_id"]] = prediction
        print(
            f"   {record['segment_id']}: {prediction.title} "
            f"({prediction.pipeline}, confidence={prediction.confidence:.2f}, "
            f"tiles={len(record['tile_features'])})"
        )

    print("\n4. Writing ML-assigned AFwizard segmentation...")
    with open(geojson_file, "r", encoding="utf-8") as file:
        segment_data = json.load(file)

    for index, feature in enumerate(segment_data.get("features", [])):
        segment_id = get_feature_identifier(feature, index)
        prediction = assigned_predictions.get(segment_id)
        if prediction is None:
            continue

        properties = feature.setdefault("properties", {})
        properties["pipeline"] = prediction.pipeline
        properties["pipeline_title"] = prediction.title
        properties["pipeline_key"] = "ml_optimizer"
        properties["ml_confidence"] = round(prediction.confidence, 4)

    input_basename = os.path.basename(geojson_file)
    name_part, ext_part = os.path.splitext(input_basename)
    assigned_geojson_path = os.path.join(output_dir, f"{name_part}_ML_assigned{ext_part}")
    os.makedirs(output_dir, exist_ok=True)

    with open(assigned_geojson_path, "w", encoding="utf-8") as file:
        json.dump(segment_data, file, indent=2)

    print(f"Saved: {assigned_geojson_path}")

    print("\n5. AFwizard execution command...")
    afwizard_command = _build_afwizard_command(
        las_file=las_file,
        assigned_geojson_path=assigned_geojson_path,
        output_dir=output_dir,
        epsg=epsg,
        filter_libraries=filter_libraries,
        lastools_dir=lastools_dir,
    )
    print(" ".join(shlex.quote(part) for part in afwizard_command))

    if run_afwizard:
        print("\n6. Running AFwizard...")
        subprocess.run(afwizard_command, check=True)
    else:
        print("\n6. Dry run only. Add --run-afwizard to execute the command.")

    print("\nProcess completed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Train/predict ML assignment of AFwizard ground filtering pipelines."
    )
    parser.add_argument("--las", default="data/PK_last.laz", help="Input LAZ/LAS point cloud")
    parser.add_argument(
        "--geojson",
        default="data/PK_segments.geojson",
        help="Target segmentation GeoJSON without ML pipeline assignments",
    )
    parser.add_argument("--outdir", default="output", help="Output directory")
    parser.add_argument(
        "--epsg",
        default=None,
        help="EPSG code. If omitted, the code is inferred from the GeoJSON CRS when possible.",
    )
    parser.add_argument(
        "--lastools",
        default=None,
        help="LASTools directory used by AFwizard for LASTools-backed filters",
    )
    parser.add_argument(
        "--library",
        action="append",
        default=None,
        help="AFwizard filter library directory. Can be specified multiple times.",
    )
    parser.add_argument("--model", default="optimizer_model.pkl", help="Model pickle path")
    parser.add_argument(
        "--train-las",
        default="data/PK_last.laz",
        help="Training point cloud used with the assigned GeoJSON",
    )
    parser.add_argument(
        "--train-geojson",
        default="data/PK_segments_assigned.geojson",
        help="AFwizard-assigned GeoJSON containing reference pipeline labels",
    )
    parser.add_argument(
        "--retrain",
        action="store_true",
        help="Retrain even when the model file already exists",
    )
    parser.add_argument(
        "--cell-size",
        type=float,
        default=40.0,
        help="Training tile size in CRS units/metres",
    )
    parser.add_argument(
        "--min-points",
        type=int,
        default=30,
        help="Minimum points required for a training tile",
    )
    parser.add_argument(
        "--run-afwizard",
        action="store_true",
        help="Actually execute AFwizard after writing the ML-assigned segmentation",
    )

    args = parser.parse_args()

    automate_filtration_process(
        las_file=args.las,
        geojson_file=args.geojson,
        output_dir=args.outdir,
        epsg=args.epsg,
        lastools_dir=args.lastools,
        model_path=args.model,
        train_las=args.train_las,
        train_geojson=args.train_geojson,
        filter_libraries=args.library or ["data/output"],
        retrain=args.retrain,
        cell_size=args.cell_size,
        min_points=args.min_points,
        run_afwizard=args.run_afwizard,
    )
