import json
import logging
import os
import re

import click

from afwizard.dataset import DataSet
from afwizard.execute import apply_adaptive_pipeline
from afwizard.lastools import set_lastools_directory
from afwizard.library import add_filter_library
from afwizard.opals import set_opals_directory
from afwizard.paths import get_temporary_filename, locate_file
from afwizard.segmentation import Segmentation
from afwizard.utils import check_spatial_reference

import afwizard.pdal as af_pdal


logger = logging.getLogger("afwizard")


def patch_pdal_metadata_string_handling() -> None:
    """Support newer python-pdal versions returning metadata as JSON text."""

    def fixed_convert(cls, dataset):
        if isinstance(dataset, af_pdal.PDALInMemoryDataSet):
            return dataset

        spatial_reference = dataset.spatial_reference
        dataset = dataset.save(get_temporary_filename("las"))

        assert dataset.filename is not None
        filename = locate_file(dataset.filename)

        config = {"type": "readers.las", "filename": filename}
        if spatial_reference is not None:
            config["override_srs"] = spatial_reference
            config["nosrs"] = True

        pipeline = af_pdal.execute_pdal_pipeline(config=[config])

        if spatial_reference is None:
            metadata = pipeline.metadata
            if isinstance(metadata, str):
                metadata = json.loads(metadata)

            spatial_reference = metadata["metadata"]["readers.las"][
                "comp_spatialreference"
            ]

        spatial_reference = check_spatial_reference(spatial_reference)
        return af_pdal.PDALInMemoryDataSet(
            pipeline=pipeline,
            spatial_reference=spatial_reference,
        )

    af_pdal.PDALInMemoryDataSet.convert = classmethod(fixed_convert)


def locate_lidar_dataset(ctx, param, path):
    _, ext = os.path.splitext(path)
    if ext.lower() in (".las", ".laz"):
        return DataSet(os.path.abspath(path))
    raise click.BadParameter(f"Lidar datasets must be .las or .laz (not: {path})")


def validate_segmentation(ctx, param, filename):
    _, ext = os.path.splitext(filename)
    if ext.lower() != ".geojson":
        raise click.BadParameter(
            f"Segmentation files must be .geojson (not: {filename})"
        )

    try:
        return Segmentation.load(filename)
    except Exception as exc:
        raise click.BadParameter(
            f"Segmentation file was not {filename} readable"
        ) from exc


def validate_suffix(ctx, param, suffix):
    if not re.fullmatch("[a-z0-9_]*", suffix):
        raise click.BadParameter(
            "Suffix should consist of lowercase letters, numbers and underscores only"
        )
    return suffix


def validate_spatial_reference(ctx, param, crs):
    try:
        return check_spatial_reference(crs)
    except Exception as exc:
        raise click.BadParameter(
            f"Cannot validate spatial reference system '{crs}'. "
            "Use either WKT or 'EPSG:xxxx'"
        ) from exc


@click.command()
@click.option(
    "--dataset",
    type=click.Path(exists=True, dir_okay=False),
    required=True,
    callback=locate_lidar_dataset,
    help="The LAS/LAZ data file to work on.",
)
@click.option(
    "--dataset-crs",
    type=str,
    required=True,
    callback=validate_spatial_reference,
    help="The CRS of the data",
)
@click.option(
    "--segmentation",
    type=click.Path(exists=True, dir_okay=False),
    required=True,
    callback=validate_segmentation,
    help="The GeoJSON file that describes the segmentation of the dataset.",
)
@click.option(
    "--segmentation-crs",
    type=str,
    required=True,
    callback=validate_spatial_reference,
    help="The CRS used in the segmentation",
)
@click.option(
    "--library",
    type=click.Path(exists=True, file_okay=False),
    multiple=True,
    help="A filter library location that AFwizard should take into account.",
)
@click.option(
    "--output-dir",
    type=click.Path(file_okay=False),
    default="output",
    show_default=True,
    help="The directory to place output files.",
)
@click.option(
    "--resolution",
    type=click.FloatRange(min=0.0, min_open=True),
    default=0.5,
    show_default=True,
    help="The meshing resolution to use for generating GeoTiff files",
)
@click.option(
    "--compress",
    type=bool,
    is_flag=True,
    help="Whether LAZ files should be written instead of LAS.",
)
@click.option(
    "--suffix",
    type=str,
    default="filtered",
    callback=validate_suffix,
    show_default=True,
    help="The suffix to add to filtered datasets.",
)
@click.option(
    "--opals-dir",
    type=click.Path(file_okay=False, exists=True),
    help="The directory where to find an OPALS installation",
)
@click.option(
    "--lastools-dir",
    type=click.Path(file_okay=False, exists=True),
    help="The directory where to find a LASTools installation",
)
def main(**args):
    patch_pdal_metadata_string_handling()

    for library in args.pop("library"):
        add_filter_library(path=library)

    set_opals_directory(args.pop("opals_dir"))
    set_lastools_directory(args.pop("lastools_dir"))

    args["dataset"].spatial_reference = args.pop("dataset_crs")
    args["segmentation"].spatial_reference = args.pop("segmentation_crs")

    apply_adaptive_pipeline(**args)


if __name__ == "__main__":
    main()
