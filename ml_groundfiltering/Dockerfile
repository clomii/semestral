FROM mambaorg/micromamba:1.5.3

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

USER $MAMBA_USER

ENTRYPOINT ["/usr/local/bin/_entrypoint.sh", "python", "main.py"]
