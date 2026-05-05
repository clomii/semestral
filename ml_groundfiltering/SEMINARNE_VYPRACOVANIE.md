# Filtrovanie point cloudu pre tvorbu DTM s vyuzitim strojoveho ucenia

## 1. Zadanie a ciel prace

Cielom prace je navrhnut proces automatickej optimalizacie filtracie LiDAR
point cloudu pre tvorbu digitalneho modelu terenu (DTM). Pri DTM su
najdolezitejsie body odrazene od zeme. Body vegetacie, budov, vody alebo
inych objektov maju byt odfiltrovane, pripadne nemaju byt pouzite ako ground
body.

Ako zaklad je pouzity AFwizard:

- dokumentacia: https://afwizard.readthedocs.io/en/latest/
- workshop: https://3dgeo-heidelberg.github.io/trail-groundfiltering/

AFwizard podporuje interaktivne ladenie filtrov, pracu s filter kniznicami a
priestorovo adaptivnu aplikaciu filtrov na segmenty. Povodny workflow je vsak
zavislý na operatorovi, ktory vizualne kontroluje vysledky a rucne vybera
vhodny filter pre kazdy typ povrchu. Navrhnute riesenie tuto cast nahradza
modelom strojoveho ucenia.

## 2. Problem

Vstupom je surovy LAS/LAZ point cloud a segmentacny GeoJSON. Pre kazdy segment
treba priradit AFwizard filter tak, aby vysledok co najviac zodpovedal
referencnym ground bodom. V workshopovych PK datach je referencny vystup
`data/output/PK_last_filtered.las`; ground body su v LAS klasifikacii oznacene
hodnotou `Classification == 2`.

Problem teda nie je ucit model klasifikovat kazdy bod samostatne. Praktickejsie
je ucit model ako meta-optimalizator:

```text
geometricke priznaky segmentu -> najlepsi AFwizard pipeline hash
```

Samotnu filtraciu potom vykona AFwizard s backendom LASTools/PDAL/OPALS.

## 3. Navrhnuty workflow

1. Vytvori sa referencna sada segmentov, kde kazdy segment ma priradeny
   najlepsi AFwizard filter. V projekte je to `data/PK_segments_assigned.geojson`.
2. Z point cloudu sa pre kazdy polygon alebo mensiu dlazdicu vypocitaju
   priznaky:
   - hustota bodov,
   - smerodajna odchylka vysky,
   - vyskovy rozsah,
   - percentilovy rozsah P95-P05,
   - IQR vysky,
   - sklon aproximovanej roviny,
   - chyba aproximacie roviny ako roughness,
   - podiel bodov vyssich ako P10 + 1 m a P10 + 3 m.
3. Cielova trieda `y` je hodnota `properties.pipeline` v AFwizard GeoJSON-e.
   AFwizard nepouziva cestu k filtru, ale hash/metadatovy odkaz na filter v
   registrovanej kniznici filtrov.
4. Natrenuje sa `RandomForestClassifier`.
5. Pre novy segmentacny GeoJSON sa extrahuju rovnake priznaky.
6. Model predikuje najlepsi `pipeline` hash.
7. Program zapise `pipeline`, `pipeline_title` a `ml_confidence` do noveho
   GeoJSON-u.
8. AFwizard CLI pouzije tento GeoJSON na priestorovo adaptivnu filtraciu.

## 4. Trening modelu

Povodny demonstracny kod trenoval model na nahodnych cislach, preto nemohol
optimalizovat zhodu s PK ground outputom. Upraveny kod pouziva realne data:

- `feature_extraction.py` cita LAS/LAZ cez `laspy`,
- body vybera podla GeoJSON polygonov cez `shapely`,
- `ml_optimizer.py` trenuje Random Forest na skutocnych priznakoch,
- `main.py` spaja trening, predikciu a zapis AFwizard segmentacie.

Pretoze v PK ukazke su iba dva velke segmenty (`veg` a `UW`), segmenty sa pri
treningu delia na mensie dlazdice. Kazda dlazdica dedi label povodneho
segmentu. Tym vznikne viac lokalnych trenovacich vzoriek a model sa neuci iba
dva riadky tabulky.

## 5. Objektivna cielova funkcia

Ak su dostupne vysledky viacerych kandidatskych filtrov, najlepsi filter sa da
vybrat automaticky podla zhody s referencnymi ground bodmi:

```text
reference_ground = Classification == 2 v referencnom LAS
candidate_ground = Classification == 2 v kandidatskom LAS
```

Pre kazdy kandidat sa pocita:

- precision,
- recall,
- F1 score,
- IoU,
- accuracy.

Najvhodnejsi filter je ten, ktory maximalizuje F1 alebo IoU. F1 je vhodna
metrika, pretoze tresta false positives aj false negatives. IoU je prisnejsia
metrika prekryvu ground masky.

V projekte je na toto pripraveny skript `filter_scoring.py`.

## 6. Implementacny vystup

Typicky prikaz:

```powershell
docker run --rm -v "${PWD}:/app" -w /app ml-groundfiltering-app --retrain
```

Vystupom je:

- natrenovany model `optimizer_model.pkl`,
- nova segmentacia `output/PK_segments_ML_assigned.geojson`,
- AFwizard prikaz na batch filtraciu.

Pre realne spustenie AFwizard:

```powershell
docker run --rm -v "${PWD}:/app" -w /app ml-groundfiltering-app --retrain --run-afwizard --lastools /path/to/LAStools
```

## 7. Zhodnotenie

Navrhnute riesenie automatizuje manualny krok AFwizard workflowu. Operator uz
nemusi pre kazdy segment vizualne hladat filter. Model sa nauci vztah medzi
geometriou terenu a vhodnou pipeline a nasledne vie pipeline zapisat priamo do
AFwizard GeoJSON segmentacie.

Najvacsie obmedzenie je mnozstvo referencnych dat. Dva segmenty su dostatocne
na demonstraciu principu, ale nie na robustny univerzalny model. Pre produkcne
pouzitie treba pridat viac lokalit, viac typov povrchu a viac kandidatskych
filtrov. Silna stranka riesenia je, ze po doplneni dat sa nemeni architektura:
meni sa iba trenovacia sada a model sa znovu natrenuje.
