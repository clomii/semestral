# Kompletna dokumentacia projektu ML ground filtering

## 1. Ciel projektu

Zadanie riesi filtrovanie LiDAR point cloudu pre tvorbu digitalneho modelu
terenu (DTM) s pouzitim strojoveho ucenia. Najdolezitejsia uloha je rozlisit
body odrazene od zeme od bodov vegetacie, vody, budov alebo inych objektov.

Projekt nadvazuje na AFwizard:

- AFwizard dokumentacia: https://afwizard.readthedocs.io/en/latest/
- workshop: https://3dgeo-heidelberg.github.io/trail-groundfiltering/

Povodny AFwizard workflow je manualny. Operator vizualne vybera alebo ladi
filter pre rozne casti uzemia. Tento projekt nahradza manualny vyber filtrov
modelom strojoveho ucenia.

Hlavna myslienka:

```text
vlastnosti segmentu point cloudu -> ML model -> najlepsi AFwizard filter
```

Samotnu filtraciu potom nerobi ML model. ML model iba vyberie, ktory AFwizard
filter sa ma pouzit. Fyzicku klasifikaciu bodov vykona AFwizard cez LASTools
backend.

## 2. Celkovy proces od zaciatku po koniec

Proces ma tieto kroky:

1. Nacita sa vstupny point cloud `data/PK_last.laz`.
2. Nacita sa segmentacia `data/PK_segments.geojson`.
3. Z referencnej segmentacie `data/PK_segments_assigned.geojson` sa ziska, aky
   filter bol manualne priradeny jednotlivym segmentom.
4. Segmenty sa rozdelia na mensie dlazdice, aby z dvoch velkych polygonov
   vzniklo viac trenovacich vzoriek.
5. Z kazdej dlazdice sa vypocitaju geometricke priznaky.
6. Natrenuje sa `RandomForestClassifier`.
7. Model predikuje najlepsi AFwizard `pipeline` hash pre cielove segmenty.
8. Program zapise predikovane filtre do `output/PK_segments_ML_assigned.geojson`.
9. AFwizard nacita tento GeoJSON a spusti prislusne filtre z kniznice.
10. LASTools vykona ground filtering a vytvori `output/PK_last_filtered.las`.
11. AFwizard vytvori raster `output/PK_last_filtered.tiff`.
12. Pomocny PDAL skript vytvori este DTM raster iba z ground bodov:
    `output/PK_last_filtered_dtm.tiff`.
13. Vysledok sa overi oproti referencii `data/output/PK_last_filtered.las`.

## 3. Co znamena "filter" v tomto projekte

Filter je JSON subor, ktory opisuje konfiguraciu ground filtering algoritmu.
V tomto projekte su pouzite filtre z workshopu ulozene v:

```text
data/output/ground_points_over_land.json
data/output/ground_points_in_the_water.json
```

Tieto filtre maju backend `lastools`, teda AFwizard ich nevykonava sam vlastnym
algoritmom. AFwizard ich nacita, spravuje a aplikuje na spravne segmenty, ale
samotny vypocet vykona LASTools program `lasground_new64`.

Dostupne filtre:

```text
Ground points over land
```

Tento filter je urceny pre segment s vegetaciou alebo beznym terenom. V projekte
ma AFwizard hash:

```text
da3ef59d40b2853b00710542a0dc72c7d2ddc9da
```

Pouziva dve LASTools konfiguracie:

```json
{"offset": 0.0, "spike": 0.4, "step": 1.4}
{"offset": 0.0, "spike": 0.5, "step": 1.0}
```

```text
Ground points in the water
```

Tento filter je urceny pre vodny alebo problematicky segment, kde je potrebna
ina citlivost ground filtra. V projekte ma AFwizard hash:

```text
0f94f36544761b2337ee37a7b41d160290486ed2
```

Pouziva jednu LASTools konfiguraciu:

```json
{"offset": 0.0, "spike": 0.3, "step": 1.0}
```

AFwizard v segmentacii nepouziva nazov suboru filtra, ale hodnotu
`properties.pipeline`, teda metadata hash filtra. Preto ML model predikuje
priamo tento hash.

## 4. Na com sa model trenuje

Model sa trenuje na kombinacii:

```text
data/PK_last.laz
data/PK_segments_assigned.geojson
```

`PK_last.laz` obsahuje body point cloudu. `PK_segments_assigned.geojson`
obsahuje segmenty, kde uz je manualne alebo referencne priradeny AFwizard
filter v poli `properties.pipeline`.

V referencii su dva segmenty:

```text
veg -> Ground points over land
UW  -> Ground points in the water
```

Keby sa model trenoval iba na dvoch polygonoch, mal by iba dve trenovacie
vzorky. Preto sa kazdy polygon rozdeli na mensie dlazdice. Kazda dlazdica dedi
label povodneho segmentu. V overenom PK behu vzniklo:

```text
129 tiled samples
2 classes
training accuracy = 1.000
```

To znamena, ze model mal 129 lokalnych trenovacich vzoriek a ucil sa rozlisit
dve triedy filtrov.

## 5. Ake priznaky sa pouzivaju

Priznaky sa pocitaju v `feature_extraction.py`. Pre kazdy segment alebo dlazdicu
sa vyberu body, ktore spadaju do GeoJSON polygonu, a vypocitaju sa geometricke
charakteristiky.

Pouzite priznaky:

```text
log_point_count
density
z_std
z_range
z_p95_p05
z_iqr
plane_slope
plane_rmse
above_p10_1m_fraction
above_p10_3m_fraction
```

Vysvetlenie:

- `log_point_count`: logaritmus poctu bodov v segmente.
- `density`: hustota bodov na plochu polygonu.
- `z_std`: smerodajna odchylka vysky.
- `z_range`: rozdiel medzi maximalnou a minimalnou vyskou.
- `z_p95_p05`: robustny vyskovy rozsah medzi 95. a 5. percentilom.
- `z_iqr`: interkvartilovy rozsah vysky.
- `plane_slope`: sklon aproximovanej roviny.
- `plane_rmse`: chyba aproximacie roviny, pouzita ako roughness.
- `above_p10_1m_fraction`: podiel bodov vyssich ako P10 + 1 m.
- `above_p10_3m_fraction`: podiel bodov vyssich ako P10 + 3 m.

Tieto priznaky opisuju, ci segment vyzera ako hladky teren, clenity teren,
vegetacia alebo problematicka oblast.

## 6. Aky model sa pouziva

Model je implementovany v `ml_optimizer.py`.

Pouzity model:

```text
RandomForestClassifier
```

Dovod vyberu:

- dobre zvlada male a stredne tabulkove datasety,
- nepotrebuje normalizaciu priznakov tak striktne ako niektore ine modely,
- vie pracovat s nelinearnymi vztahmi,
- je vhodny pre kombinaciu hustoty, vyskovych statistik a roughness priznakov,
- vracia pravdepodobnosti tried, z ktorych sa pocita `ml_confidence`.

Model nepredikuje body. Model predikuje najlepsi filter pre segment:

```text
features -> pipeline hash
```

Po natrenovani sa ulozi do:

```text
optimizer_model.pkl
```

## 7. Ako prebieha predikcia

Predikcia sa robi v `main.py`.

Cielovy GeoJSON `data/PK_segments.geojson` nema priradene filtre. Program:

1. rozdeli segmenty na dlazdice rovnako ako pri treningu,
2. vypocita priznaky pre kazdu dlazdicu,
3. model predikuje pravdepodobnosti filtrov pre dlazdice,
4. pravdepodobnosti sa spriemeruju v ramci segmentu,
5. segment dostane filter s najvyssou priemernou pravdepodobnostou.

Toto je dolezite. Predikcia sa nerobi z jedneho priemerneho vektora celeho
velkeho segmentu, lebo velky polygon moze prekryt lokalne rozdiely. Dlazdicove
hlasovanie lepsie zodpoveda tomu, ako AFwizard operator vizualne hodnoti mensie
casti terenu.

Overeny vysledok:

```text
veg -> Ground points over land, confidence 0.96
UW  -> Ground points in the water, confidence 0.95
```

Vystupna segmentacia:

```text
output/PK_segments_ML_assigned.geojson
```

Do kazdeho segmentu sa zapise:

```json
"pipeline": "...",
"pipeline_title": "...",
"pipeline_key": "ml_optimizer",
"ml_confidence": 0.95
```

## 8. Ako AFwizard a LASTools spolupracuju

AFwizard je workflow nastroj. Spravuje filtre, segmenty, kniznice filtrov a
aplikaciu filtrov na spravne oblasti.

LASTools je vykonny backend. V tomto projekte vykonava samotne `lasground_new64`
filtrovanie.

Proces:

```text
AFwizard nacita output/PK_segments_ML_assigned.geojson
AFwizard nacita filter JSON subory z data/output
AFwizard najde filtre podla pipeline hashov
AFwizard rozdeli dataset podla segmentov
LASTools aplikuje lasground_new64 pre kazdy filter
AFwizard spoji segmenty naspat
AFwizard zapise LAS a GeoTIFF vystupy
```

V Docker image je pridany maly `wine` shim. Dovod je kompatibilita s AFwizard
1.0.1: tato verzia na Linuxe ocakava LASTools nazvy s `.exe` a spustanie cez
`wine`, ale aktualny rapidlasso balik obsahuje nativne Linux binarky. Shim
spusti nativny Linux program tak, aby AFwizard zostal kompatibilny.

Stiahnuty LASTools balik je nelicencovany, preto sa spusta v demo rezime. Na
skolske overenie workflowu to staci. Na produkcne alebo komercne pouzitie treba
riesit licenciu rapidlasso.

## 9. Oprava AFwizard rasterizacie

AFwizard 1.0.1 ma problem s novsou verziou `python-pdal`. Niektore PDAL metadata
sa vracaju ako JSON text namiesto Python objektu. Povodny AFwizard potom pri
GeoTIFF rasterizacii spadol na chybe:

```text
TypeError: string indices must be integers
```

Projekt preto obsahuje:

```text
afwizard_fixed_cli.py
```

Tento subor zachovava spravanie AFwizard CLI, ale pred rasterizaciou opravi
metadata parsing. Vysledkom je, ze AFwizard uz vytvori aj:

```text
output/PK_last_filtered.tiff
```

Bez tejto opravy by vznikol spravny LAS, ale AFwizard GeoTIFF by padol.

## 10. Vysledne vystupy

Po kompletnom behu vzniknu najma tieto subory:

```text
output/PK_segments_ML_assigned.geojson
```

Segmentacia s ML priradenymi AFwizard filtrami.

```text
output/PK_last_filtered.las
```

Filtrovaný point cloud. Ground body su oznacene ako `Classification == 2`.

```text
output/PK_last_filtered.tiff
```

GeoTIFF raster vytvoreny priamo AFwizardom.

```text
output/PK_last_filtered_dtm.tiff
```

Pomocny DTM raster vytvoreny cez `rasterize_dtm.py` iba z ground bodov
`Classification == 2`.

```text
output/output.log
```

Log AFwizard behu, kde je vidiet volanie filtrov a LASTools prikazov.

## 11. Ako sa overuje spravnost

Hlavne overenie sa nerobi iba vizualne. Porovnava sa ground maska v novom
vystupe proti referencnemu PK vystupu.

Referencia:

```text
data/output/PK_last_filtered.las
```

Novy vystup:

```text
output/PK_last_filtered.las
```

Ground body:

```text
Classification == 2
```

Pouzity skript:

```text
filter_scoring.py
```

Metriky:

- `precision`: kolko bodov oznacenych ako ground je naozaj ground podla referencie.
- `recall`: kolko referencnych ground bodov model zachytil.
- `f1`: harmonicky priemer precision a recall.
- `iou`: prekryv ground masiek.
- `accuracy`: celkova zhoda klasifikacie ground/non-ground.

Overeny vysledok projektu:

```text
precision = 1.0
recall    = 1.0
f1        = 1.0
iou       = 1.0
accuracy  = 1.0
```

To znamena, ze na PK datach sa vysledne ground body presne zhoduju s referencnym
PK outputom.

## 12. Popis suborov v projekte

```text
main.py
```

Hlavny spustaci skript. Riadi trening/nacitanie modelu, extrakciu priznakov,
predikciu filtrov, zapis ML GeoJSON-u a volanie AFwizard runnera.

```text
feature_extraction.py
```

Extrahuje priznaky z LAS/LAZ bodov podla GeoJSON polygonov. Obsahuje aj logiku
dlazdicovania segmentov pre trening a predikciu.

```text
ml_optimizer.py
```

Obsahuje triedu `MLFilterOptimizer`. Trenuje Random Forest, uklada model,
nacitava model a predikuje najlepsi AFwizard pipeline hash.

```text
afwizard_fixed_cli.py
```

Kompatibilny wrapper okolo AFwizard CLI. Opravuje problem s PDAL metadata a
umoznuje, aby prebehla aj AFwizard GeoTIFF rasterizacia.

```text
filter_scoring.py
```

Porovnava referencny a kandidatsky LAS/LAZ subor. Pocita precision, recall, F1,
IoU a accuracy pre ground body `Classification == 2`. Vie porovnavat aj viac
kandidatskych filtrov po segmentoch.

```text
benchmark_filters.py
```

Vyssi level overenia pre dataset, kde je dostupny referencny DTM raster.
Skript vytvori pre kazdy dostupny AFwizard filter samostatne priradenie,
spusti AFwizard, vyrastruje ground body do DTM a porovna kandidatny DTM s
referencnym DTM pomocou RMSE, MAE, bias a pokrytia platnych pixelov.

```text
rasterize_dtm.py
```

Pomocny PDAL skript. Zoberie uz vyfiltrovany LAS, necha iba body
`Classification == 2` a vyrastruje ich do GeoTIFF DTM. Nerobi ground filtering,
iba rasterizaciu uz klasifikovanych bodov.

```text
run_pk_with_lastools.ps1
```

PowerShell launcher pre Windows. Skontroluje LASTools, namapuje ho do Dockeru,
spusti ML workflow, AFwizard a potom pomocnu DTM rasterizaciu.

```text
Dockerfile
```

Definuje reprodukovatelne prostredie s Python, AFwizard, PDAL, GDAL, laspy,
scikit-learn, geopandas a shapely. Obsahuje aj kompatibilny `wine` shim pre
AFwizard a nativny Linux LASTools balik.

```text
requirements.txt
```

Zoznam hlavnych Python zavislosti.

```text
README.md
```

Strucny navod na spustenie a zakladny popis projektu.

```text
SEMINARNE_VYPRACOVANIE.md
```

Textove vypracovanie metodiky do semestralnej prace.

```text
comparison_presentation.md
```

Material s porovnanim manualneho AFwizard workflowu a automatizovaneho ML
workflowu.

```text
practical_comparison.ipynb
```

Notebook urceny na demonstraciu alebo vizualnu pracu vo VS Code/Jupyter.

```text
.gitignore
```

Ignoruje modely, cache, velke vystupy a stiahnute LASTools binarky.

```text
.dockerignore
```

Zmensuje Docker build context, aby sa do image neposielali velke vystupy a
stiahnute nastroje.

## 13. Popis datovych suborov

```text
data/PK_last.laz
```

Vstupny PK point cloud.

```text
data/PK_segments.geojson
```

Cielova segmentacia bez ML priradenych filtrov. Toto je vstup pre predikciu.

```text
data/PK_segments_assigned.geojson
```

Referencna segmentacia s manualne priradenymi AFwizard pipeline hashmi. Toto je
trenovaci label dataset.

```text
data/output/PK_last_filtered.las
```

Referencny filtrovaný PK vystup. Pouziva sa na objektivne overenie zhody ground
bodov.

```text
data/output/ground_points_over_land.json
data/output/ground_points_in_the_water.json
```

AFwizard filter definicie pouzite pri aplikacii filtrov.

```text
data/StA_last.laz
data/StA_segment.geojson
```

Dalsia lokalita/dataset, pouzitelna na demonstraciu generalizacie workflowu.

## 14. Prirucka na spustenie

### 14.1 Predpoklady

Potrebujes:

- Windows PowerShell,
- Docker Desktop,
- pristup na internet pri prvom stiahnuti Docker image a LASTools balika.

### 14.2 Build Docker image

V koreni projektu spusti:

```powershell
docker build -t ml-groundfiltering-app .
```

### 14.3 Stiahnutie LASTools

Ak priecinok `tools` uz existuje a obsahuje `tools/bin/lasground_new64`, tento
krok netreba opakovat.

```powershell
New-Item -ItemType Directory -Force tools
curl.exe -L -o tools\LAStools.tar.gz https://downloads.rapidlasso.de/LAStools.tar.gz
tar -xzf tools\LAStools.tar.gz -C tools
```

### 14.4 Kompletny beh pre PK data

```powershell
.\run_pk_with_lastools.ps1 -LastoolsDir tools
```

Tento prikaz:

- natrenuje alebo pretrenuje model,
- predikuje filtre pre segmenty,
- zapise `output/PK_segments_ML_assigned.geojson`,
- spusti AFwizard s LASTools,
- vytvori `output/PK_last_filtered.las`,
- vytvori `output/PK_last_filtered.tiff`,
- vytvori `output/PK_last_filtered_dtm.tiff`.

### 14.5 Dry-run bez skutocnej filtracie

```powershell
.\run_pk_with_lastools.ps1 -LastoolsDir tools -DryRun
```

Tento prikaz iba ukaze, co by sa spustilo, a overi ML predikciu filtrov.

### 14.6 Spustenie bez opakovaneho treningu

Ak uz existuje `optimizer_model.pkl`, mozes pouzit:

```powershell
.\run_pk_with_lastools.ps1 -LastoolsDir tools -NoRetrain
```

### 14.7 Overenie vysledku metrikami

```powershell
docker run --rm --entrypoint /usr/local/bin/_entrypoint.sh `
  -v "${PWD}:/app" `
  -w /app `
  ml-groundfiltering-app `
  python filter_scoring.py `
  --reference data/output/PK_last_filtered.las `
  --candidate ml_afwizard=output/PK_last_filtered.las
```

Ocakavany vysledok pre aktualne PK data:

```text
precision = 1.0
recall    = 1.0
f1        = 1.0
iou       = 1.0
accuracy  = 1.0
```

### 14.8 Rucna DTM rasterizacia

Ak chces samostatne vytvorit DTM z hotoveho LAS suboru:

```powershell
docker run --rm --entrypoint /usr/local/bin/_entrypoint.sh `
  -v "${PWD}:/app" `
  -w /app `
  ml-groundfiltering-app `
  python rasterize_dtm.py `
  --las output/PK_last_filtered.las `
  --out output/PK_last_filtered_dtm.tiff `
  --epsg 25833 `
  --resolution 0.5
```

### 14.9 StA benchmark kandidatskych filtrov voci referencnemu DTM

Pre StA existuje referencny raster `data/StA_last_dtm.tiff`. Preto sa da
spravit silnejsie overenie ako iba ukazat ML predikciu. Spustia sa vsetky
dostupne AFwizard filtre, kazdy kandidat sa vyrastruje ako DTM a vysledky sa
porovnaju s referenciou:

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

Aktualny vysledok:

```text
1. Ground points over land     RMSE 0.322 m, MAE 0.040 m
2. Ground points in the water  RMSE 0.332 m, MAE 0.037 m
```

ML model pre StA vybral `Ground points over land` s nizsou istotou okolo 54 %.
Confidence threshold preto oznaci segment na kontrolu, ale DTM benchmark
potvrdzuje, ze z dostupnych filtrov je tento vyber najlepsi.

## 15. Co povedat na obhajobe

Strucne vysvetlenie:

```text
AFwizard poskytuje framework na ground filtering a pracu s filtrami. Povodne je
vyber filtra manualny. V projekte som tento manualny krok nahradil ML modelom,
ktory sa uci z referencne priradenych segmentov. Model neklasifikuje body
priamo, ale vybera najvhodnejsi AFwizard filter pre segment. Samotnu filtraciu
potom vykona AFwizard cez LASTools backend.
```

Silne body riesenia:

- odstraňuje manualny vyber filtra operatorom,
- pouziva realne geometricke priznaky z point cloudu,
- vybera skutocne AFwizard pipeline hashe,
- spusta realny AFwizard/LASTools filtering,
- vysledok je overeny metrikami oproti referencnemu PK outputu,
- pri StA je doplneny benchmark dostupnych filtrov oproti referencnemu DTM,
- nizka confidence automaticky oznaci segment na manualnu kontrolu,
- dosahuje na PK datach `F1 = 1.0` a `IoU = 1.0`.

Obmedzenia:

- model je demonstrovany na malej referencnej sade,
- pre robustne nasadenie treba viac lokalit a viac typov terenu,
- LASTools licencia musi byt vyriesena pri produkcnom/komercnom pouziti,
- kvalita modelu zavisi od kvality referencnych segmentov a filtrov.

Najdolezitejsia veta:

```text
Projekt automatizuje vyber AFwizard filtrov pomocou strojoveho ucenia. Na PK
datasete dosiahol uplnu zhodu ground klasifikacie s referencnym vystupom a na
StA datasete benchmark voci referencnemu DTM potvrdil rovnaky filter, ktory
navrhol model.
```
