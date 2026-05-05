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
   `pipeline_title` a `ml_confidence`.
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
- `SEMINARNE_VYPRACOVANIE.md` - textove vypracovanie metodiky do semestralnej
  prace.

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
- volitelne DTM raster z ground bodov: `output/PK_last_filtered_dtm.tiff`.

AFwizard 1.0.1 vie po vytvoreni LAS suboru zahlasit internu chybu pri vlastnej
GeoTIFF rasterizacii (`TypeError: string indices must be integers`). Launcher
preto po AFwizard behu automaticky vytvori DTM cez `rasterize_dtm.py`, ktory
berie iba ground body `Classification == 2`.

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

## Co treba obhajit

Model nie je priamo nahrada za samotny ground-filter algoritmus. Je to
meta-optimalizator: na zaklade vlastnosti terenu vybera konfiguraciu filtra,
ktoru potom vykona AFwizard/PDAL/LASTools/OPALS.

Pri malom mnozstve manualnych segmentov je generalizacia obmedzena. Preto kod
robi dlazdicovanie polygonov, aby z jednej referencnej oblasti vzniklo viac
lokalnych trenovacich vzoriek. Pre realne nasadenie treba pridat viac lokalit,
viac typov terenu a viac kandidatskych filtrov.
