import argparse
import json

import pdal


def rasterize_ground_points(
    las_path: str,
    output_tiff: str,
    epsg: str,
    resolution: float = 0.5,
    output_type: str = "min",
) -> int:
    pipeline = [
        {
            "type": "readers.las",
            "filename": las_path,
            "override_srs": f"EPSG:{epsg}",
        },
        {
            "type": "filters.range",
            "limits": "Classification[2:2]",
        },
        {
            "type": "writers.gdal",
            "filename": output_tiff,
            "gdaldriver": "GTiff",
            "output_type": output_type,
            "resolution": resolution,
            "data_type": "float32",
            "nodata": -9999,
        },
    ]

    return pdal.Pipeline(json.dumps(pipeline)).execute()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Rasterize LAS ground points into a DTM GeoTIFF.")
    parser.add_argument("--las", required=True, help="Filtered LAS/LAZ with ground class 2")
    parser.add_argument("--out", required=True, help="Output GeoTIFF")
    parser.add_argument("--epsg", default="25833", help="EPSG code")
    parser.add_argument("--resolution", type=float, default=0.5, help="Raster resolution")
    parser.add_argument(
        "--output-type",
        default="min",
        choices=["min", "max", "mean", "idw", "count", "stdev"],
        help="PDAL writers.gdal output_type",
    )
    args = parser.parse_args()

    count = rasterize_ground_points(
        las_path=args.las,
        output_tiff=args.out,
        epsg=args.epsg,
        resolution=args.resolution,
        output_type=args.output_type,
    )
    print(f"Rasterized {count} ground points to {args.out}")
