# Automatická optimalizácia filtrácie oblaku bodov (AFwizard ML)

Tento projekt poskytuje zdrojový kód pre realizáciu automatizácie ladenia parametrov filtračných algoritmov LiDAR bodového mračna za použitia strojového učenia, na základe nástroja AFwizard. Vďaka tomuto riešeniu odstraňujeme manuálnu operátorskú "human-in-the-loop" fázu (`af.pipeline_tuning`).

## Štruktúra projektu

- `feature_extraction.py`: Skript, ktorý (v tomto návrhu) extrahuje geometrické vlastnosti bodového mračna pre špecifické polygónové segmenty v priestore. Príznaky zahŕňajú hustotu (density) a varianciu výšky.
- `ml_optimizer.py`: Scikit-learn (RandomForest) model strojového učenia, ktorý pre daný segment a sadu jeho príznakov predpovedá, ktorá `.json` filtračná pipeline poskytuje najpresnejšie odfiltrovanie vegetácie a zanechá presný digitálny model terénu (DTM).
- `main.py`: Hlavný spúšťací skript prepájajúci extrakciu a ML predikciu k autonómnemu spusteniu filtra na dopytovaný LAZ/LAS súbor.
- `Dockerfile`: Konfigurácia pre beh vo vzdialenom/izolovanom reprodukovateľnom prostredí.
- `requirements.txt`: Zoznam Python knižníc prerekvizít.

## Spustenie pomocou Docker

Aplikácia je plne paralelizovaná v rámci Docker kontajnera, čo znamená, že nevyžaduje lokálnu inštaláciu Python závislostí.

### Vytvorenie Docker Image
Je potrebné postaviť (build) docker image v koreňovom adresári tohto projektu (`ml_groundfiltering`):

```bash
docker build -t ml-groundfiltering-app .
```

### Spustenie testovania cez CLI

Spustenie adaptívneho filtru prebieha cez namapované *volumes*. Uistite sa, že používate správnu syntax pre Váš operačný systém.

**Pre používateľov Linux / MacOS (Bash):**

*Otestovanie nad dátami z Lokality 1 (Monastery St. Anna):*
```bash
docker run --rm \
    -v $(pwd)/data:/app/data \
    -v $(pwd)/output:/app/output \
    ml-groundfiltering-app --las /app/data/StA_last.laz --geojson /app/data/StA_segment.geojson --outdir /app/output --epsg 31256
```

*Otestovanie nad dátami z Lokality 2 (Oblasť PK):*
```bash
docker run --rm \
    -v $(pwd)/data:/app/data \
    -v $(pwd)/output:/app/output \
    ml-groundfiltering-app --las /app/data/PK_last.laz --geojson /app/data/PK_segments.geojson --outdir /app/output --epsg 31256
```

**Pre používateľov Windows (PowerShell):**

*Otestovanie nad dátami z Lokality 1 (Monastery St. Anna):*
```powershell
docker run --rm -v "${PWD}/data:/app/data" -v "${PWD}/output:/app/output" ml-groundfiltering-app --las /app/data/StA_last.laz --geojson /app/data/StA_segment.geojson --outdir /app/output --epsg 31256
```

*Otestovanie nad dátami z Lokality 2 (Oblasť PK):*
```powershell
docker run --rm -v "${PWD}/data:/app/data" -v "${PWD}/output:/app/output" ml-groundfiltering-app --las /app/data/PK_last.laz --geojson /app/data/PK_segments.geojson --outdir /app/output --epsg 31256
```

> **Poznámka k fallback režimu:** V prípade, že nezadáš `--las` a `--geojson` príkazy a skutočné súbory chýbajú, skript si automaticky nageneruje simulované ("stub") údaje a vykoná testovaciu slučku naprázdno, aby overil funkčnosť kódovacieho frameworku.

## Praktická ukážka v Jupyter Notebook priamo vo VS Code

Pre priame vizuálne a akademické demonštrovanie metód sme pripravili priamo spustiteľný `practical_comparison.ipynb`. Pre spustenie bez nutnosti lokálnych inštalácií, použite Jupyter Server dodávaný priamo v Docker kontajneri:

1. Spustite premostenie Jupyter serveru (kód prispôsobený na **priame skopírovanie v akomkoľvek OS** do jedného riadku):
   ```bash
   docker run --rm -p 8888:8888 -v "${PWD}:/app" -w /app ml-groundfiltering-app jupyter notebook --ip=0.0.0.0 --port=8888 --no-browser --allow-root
   ```
2. V termináli vyhľadajte a **skopírujte URL adresu**, ktorá začína na `http://127.0.0.1:8888?token=...`
3. Otvorte si súbor `practical_comparison.ipynb` priamo vo vašom prostredí **VS Code**.
4. V notebook editore vpravo hore kliknite na **Select Kernel** (Vybrať Kernel) > **Existing Jupyter Server...**.
5. Vložte skopírovanú URL z Terminálu a potvrďte. Váš lokálny VS Code ihneď nadviaže spojenie s AFwizard knižnicami v kontajneri. Následne už len spúšťajte bunky kódu priamo vo vašom IDE.

1. **Vstup**: Prijme sa rozľahlý LiDAR dataset (`StA_last.laz`).
2. **Segmentácia a Feature extrakcia**: Pomocou `laspy` sa pre každý lokálny segment získajú 3D charakteristiky.
3. **ML Optimizer**: Model na pozadí, v reálnom prostredí trénovaný na HELIOS++ syntetických "ground truth" dátach, posúdi segment a vráti názov adaptívnej pipeline vhodnej pre daný lesný alebo zrázný terén.
4. **Automatické priradenie**: Systém prepíše pipeline segmentom v AFwizard logike a cez `bash` zavolá `afwizard --segmentation --output-dir`. Modifikované segmenty sa použijú na hromadnú optimalizovanú filtráciu.
