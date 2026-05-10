# Automaticka optimalizacia ground filteringu pomocou ML a AFwizard

Projekt riesi zadanie: automatizovat vyber filtrov pre LiDAR point cloud tak,
aby vysledna klasifikacia ground bodov bola co najblizsia referencnemu vystupu
z AFwizard workshopu / manualneho operatora.

## Hlavna myslienka

AFwizard uz vie:

- nacitat LAS/LAZ dataset,
- pouzit existujuce filtre z kniznice `.json` suborov,
- zapisat do segmentacneho GeoJSON-u hodnotu `properties.pipeline`,
- aplikovat priestorovo adaptivny filter cez CLI.

Problem je manualne rozhodnutie, ktory filter patri do ktoreho segmentu.
Tento projekt nahradza operatora modelom:

1. Z referencnej segmentacie `data/PK_segments_assigned.geojson` nacita
   manualne priradene AFwizard pipeline hashe.
2. Kazdy polygon rozdeli na mensie dlazdice.
3. Z bodov v kazdej dlazdici extrahuje geometricke priznaky: hustota,
   variabilita vysky, relativny vyskovy rozsah, sklon roviny, roughness a
   podiel vyssich bodov.
4. Natrenuje `RandomForestClassifier`, ktory mapuje priznaky segmentu na
   najlepsi AFwizard `pipeline` hash.
5. Pre novy GeoJSON zapise predikovany `properties.pipeline`,
   `pipeline_title`, `ml_confidence` a priznak `ml_requires_review`, ak je
   istota nizsia ako nastavena hranica.
6. Vygeneruje prikaz na spustenie AFwizard batch filtracie.

## Dolezite subory

- `feature_extraction.py` - realna extrakcia priznakov z LAS/LAZ bodov v
  GeoJSON polygonoch. Povoluje aj vytvorenie trenovacich dlazdic.
- `ml_optimizer.py` - trenovanie a ulozenie modelu. Cielova trieda je AFwizard
  pipeline hash, nie nazov suboru.
- `main.py` - hlavny CLI workflow: trenovanie/nacitanie modelu, predikcia,
  zapis ML segmentacie a priprava AFwizard prikazu.
- `filter_scoring.py` - pomocny skript na objektivne porovnanie kandidatskych
  filtrov oproti referencnemu LAS/LAZ vystupu, kde ground body maju
  `Classification == 2`.
- `benchmark_filters.py` - spusti viac AFwizard filtrov, vytvori DTM pre kazdy
  kandidat a porovna ho s referencnym DTM rasterom pomocou RMSE/MAE.
- `SEMINARNE_VYPRACOVANIE.md` - textove vypracovanie metodiky do semestralnej
  prace.
- `ML_GroundFiltering_Workflow.ipynb` - vysvetlovaci Jupyter notebook, ktory
  ukazuje proces od dat cez trening a predikciu az po overenie metrikami.

## Spustenie pre PK data

Projekt je pripraveny na Docker, pretoze AFwizard/PDAL/GDAL zavislosti su na
Windows tazkopadne.

### Build image

```powershell
docker build -t ml-groundfiltering-app .
```

### Trenovanie + predikcia ML segmentacie

Predvolene sa trenuje z:

- `data/PK_last.laz`
- `data/PK_segments_assigned.geojson`

a predikuje sa pre:

- `data/PK_segments.geojson`

```powershell
docker run --rm -v "${PWD}:/app" -w /app ml-groundfiltering-app --retrain
```

Vystup:

- model `optimizer_model.pkl`,
- ML segmentacia `output/PK_segments_ML_assigned.geojson`,
- pripraveny `afwizard ...` prikaz.

### Skutocne spustenie AFwizard

Filtre z workshopu pouzivaju backend `lastools`. V projekte je pripraveny
launcher, ktory namapuje Linux LASTools balik do Docker kontajnera:

```powershell
.\run_pk_with_lastools.ps1 -LastoolsDir tools
```

Ak priecinok `tools` este neexistuje, stiahni a rozbal Linux LASTools balik:

```powershell
New-Item -ItemType Directory -Force tools
curl.exe -L -o tools\LAStools.tar.gz https://downloads.rapidlasso.de/LAStools.tar.gz
tar -xzf tools\LAStools.tar.gz -C tools
.\run_pk_with_lastools.ps1 -LastoolsDir tools
```

Launcher:

- skontroluje `tools/bin/lasground_new64`,
- vytvori kompatibilny nazov `lasground_new64.exe`, ktory AFwizard ocakava,
- namapuje LASTools do kontajnera ako `/lastools`,
- spusti ML vyber filtrov a AFwizard batch filtering.

Vystupy po uspesnom PK behu:

- `output/PK_segments_ML_assigned.geojson`,
- `output/PK_last_filtered.las`,
- AFwizard GeoTIFF raster: `output/PK_last_filtered.tiff`,
- DTM raster iba z ground bodov: `output/PK_last_filtered_dtm.tiff`.

Projekt pouziva `afwizard_fixed_cli.py`, co je kompatibilny wrapper okolo
AFwizard 1.0.1 CLI. Opravuje zmenu v novsom `python-pdal`, kde sa metadata
vracaju ako JSON text namiesto objektu. Vdaka tomu prebehne aj povodna AFwizard
GeoTIFF rasterizacia bez chyby.

Pri PK datach sa EPSG kod nacita z GeoJSON-u ako `25833`. Pri StA datach je to
`31256`.

Poznamka: stiahnuty LASTools balik je nelicencovany, preto Docker image obsahuje
kompatibilny `wine` shim, ktory spusta natívny Linux LASTools v demo rezime.
Na produkcne alebo komercne pouzitie treba riesit licenciu rapidlasso.

## Objektivne trenovanie podla zhody s ground points

Ak mas pre jeden segment viac kandidatskych filtrov a pre kazdy vies vyrobit
samostatny filtrovany LAS/LAZ, cielovy label sa nema volit rucne. Vyberie sa
filter s najvyssim F1/IoU oproti referencii:

```powershell
docker run --rm --entrypoint /usr/local/bin/_entrypoint.sh -v "${PWD}:/app" -w /app ml-groundfiltering-app python filter_scoring.py `
  --reference data/output/PK_last_filtered.las `
  --segmentation data/PK_segments.geojson `
  --candidate da3ef59d40b2853b00710542a0dc72c7d2ddc9da=path/to/candidate_land.las `
  --candidate 0f94f36544761b2337ee37a7b41d160290486ed2=path/to/candidate_water.las `
  --title da3ef59d40b2853b00710542a0dc72c7d2ddc9da="Ground points over land" `
  --title 0f94f36544761b2337ee37a7b41d160290486ed2="Ground points in the water" `
  --out output/pk_candidate_scores.json `
  --assigned-out output/PK_segments_scored_assigned.geojson
```

Tento skript porovnava masku `Classification == 2` medzi referenciou a
kandidatom. Najlepsi filter pre segment je ten, ktory maximalizuje najma F1
alebo IoU. Takto sa z problemu "operator vizualne vybera filter" stane
supervizovana ML uloha. Vystup `PK_segments_scored_assigned.geojson` sa potom
da pouzit ako `--train-geojson` pre `main.py`.

## Lepsi level: benchmark filtrov voci referencnemu DTM

Ak existuje referencny DTM raster, napr. `data/StA_last_dtm.tiff`, da sa overit
aj dataset bez rucne priradeneho GeoJSON-u. Skript `benchmark_filters.py`
spravi pre kazdy dostupny AFwizard filter vlastnu segmentaciu, spusti AFwizard,
vyrasterizuje ground body do DTM a porovna ich s referencnym DTM.

Priklad pre StA:

```powershell
docker run --rm --entrypoint /usr/local/bin/_entrypoint.sh `
  -v "${PWD}:/app" `
  -v "${PWD}\tools:/lastools:ro" `
  -e LASTOOLS_DIR=/lastools `
  -e LD_LIBRARY_PATH=/lastools/bin/lib:/lastools/lib:/opt/conda/lib `
  -w /app `
  ml-groundfiltering-app `
  python benchmark_filters.py `
  --las data/StA_last.laz `
  --geojson data/StA_segment.geojson `
  --reference-dtm data/StA_last_dtm.tiff `
  --epsg 31256 `
  --library data/output `
  --outdir output/benchmarks/sta `
  --lastools-dir /lastools `
  --resolution 1.0 `
  --run-afwizard
```

V aktualnom behu benchmark potvrdil rovnaky filter, ktory navrhol model:

```text
Ground points over land     RMSE 0.322 m, MAE 0.040 m
Ground points in the water  RMSE 0.332 m, MAE 0.037 m
```

Pre StA ma model nizsiu istotu okolo 54 %, preto je tento segment oznaceny na
kontrolu. Benchmark vsak ukazuje, ze z dostupnych filtrov je stale najlepsi
`Ground points over land`.

## Co treba obhajit

Model nie je priamo nahrada za samotny ground-filter algoritmus. Je to
meta-optimalizator: na zaklade vlastnosti terenu vybera konfiguraciu filtra,
ktoru potom vykona AFwizard/PDAL/LASTools/OPALS.

Pri malom mnozstve manualnych segmentov je generalizacia obmedzena. Preto kod
robi dlazdicovanie polygonov, aby z jednej referencnej oblasti vzniklo viac
lokalnych trenovacich vzoriek. Pre realne nasadenie treba pridat viac lokalit,
viac typov terenu a viac kandidatskych filtrov.
