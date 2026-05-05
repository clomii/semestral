FROM mambaorg/micromamba:2.3.3

# Need root just for some system prep and directory creation
USER root
RUN apt-get update && apt-get install -y --no-install-recommends git curl ca-certificates && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 1. Install complex C++ GIS libraries (PDAL, GDAL) and basic science stack via conda-forge.
# This prevents pip from trying to compile pdal from C++ source headers.
RUN micromamba install -y -n base -c conda-forge \
    python=3.10 \
    pip \
    numpy \
    scipy \
    laspy \
    scikit-learn \
    geopandas \
    shapely \
    pdal \
    python-pdal \
    gdal=3.4.0 \
    afwizard \
    jupyter \
    notebook \
    && micromamba clean --all --yes

# 2. Copy components
COPY requirements.txt .

# 3. Pip install remaining Python-only packages (like afwizard). 
# Pip will detect conda's pre-compiled pdal and skip the CMake build step automatically.
RUN /opt/conda/bin/pip install --no-cache-dir -r requirements.txt

# 4. Copy app code
COPY . .

# 5. Make sure volumes can be mounted properly
RUN mkdir -p /app/data /app/output /app/filters && chown -R $MAMBA_USER:$MAMBA_USER /app

# AFwizard 1.0.1 expects LASTools on Linux/macOS to be launched through a
# `wine` command and looks for *.exe names. The current rapidlasso Linux build
# provides native Linux binaries, so this shim executes the native binary. The
# downloaded LASTools build is unlicensed, so demo mode is appended unless the
# command already contains it.
RUN printf '#!/bin/sh\nfor arg in "$@"; do\n  if [ "$arg" = "-demo" ]; then\n    exec "$@"\n  fi\ndone\nexec "$@" -demo\n' > /usr/local/bin/wine && chmod +x /usr/local/bin/wine

USER $MAMBA_USER

# Use Micromamba entrypoint to activate the conda environment automatically
# and run python main.py as the base command
ENTRYPOINT ["/usr/local/bin/_entrypoint.sh", "python", "main.py"]

# By default, we run without arguments if none are passed
CMD []
