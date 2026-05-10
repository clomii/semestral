# FINAL - obsah odovzdania

Tento priecinok obsahuje iba subory potrebne na kontrolu a prezentovanie riesenia.

Hlavny subor:
- `ML_GroundFiltering_Workflow.ipynb` - vysvetleny Jupyter notebook s workflowom.

Dokumentacia a prezentacia:
- `README.md` - strucny navod na spustenie.
- `KOMPLETNA_DOKUMENTACIA.md` - opis suborov a celeho procesu.
- `SEMINARNE_VYPRACOVANIE.md` - text pre odovzdanie/obhajobu.
- `ML_GroundFiltering_AFwizard_prezentacia.pptx` - prezentacia.

Implementacia:
- `main.py`, `feature_extraction.py`, `ml_optimizer.py`
- `afwizard_fixed_cli.py`, `rasterize_dtm.py`, `benchmark_filters.py`, `filter_scoring.py`
- `run_pk_with_lastools.ps1`

Spustenie:
- `Dockerfile`, `.dockerignore`, `requirements.txt`

Data:
- `data/PK_last.laz`, `data/PK_segments.geojson`, `data/PK_segments_assigned.geojson`
- `data/StA_last.laz`, `data/StA_segment.geojson`, `data/StA_last_dtm.tiff`
- `data/output/*.json` - AFwizard filtre
- `data/output/PK_last_filtered.*` - referencny PK vystup

Vysledky:
- `output/*_ML_assigned.geojson`
- `output/*_filtered.las`, `output/*_filtered.tiff`, `output/*_filtered_dtm.tiff`
- `output/visualizations/*.png`
- `output/benchmarks/sta/candidate_metrics.*`

Neobsahuje:
- `trail-groundfiltering` - povodne workshop materialy nie su potrebne na odovzdanie.
- `tools` - LASTools binarky nie su zahrnute; pre nove spustenie AFwizard filtracie ich treba dodat samostatne.
- `__pycache__`, docasne subory, duplicitne benchmark medzivystupy.
