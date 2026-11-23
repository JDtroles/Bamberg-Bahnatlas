# Bahnatlas Bamberg

Interaktive Karte: Bahn-Fahrzeiten und Pünktlichkeit zwischen Bamberg und den 15 deutschen
Städten mit mindestens 500.000 Einwohner:innen, werktags nachmittags (Abfahrt 14–18 Uhr),
in beide Richtungen.

**Website:** https://jdtroles.github.io/Bamberg-Bahnatlas/

## Was die Karte zeigt

- **Fahrzeit:** Median und schnellste Verbindung laut Sollfahrplan (Di–Do, 1.–3.12.2026). Städte unter 3 Stunden sind hervorgehoben.
- **Pünktlichkeit:** Wahrscheinlichkeit, alle Anschlüsse zu erreichen und weniger als 6 Minuten verspätet anzukommen, berechnet aus historischen Ist-Daten.
- **Streckenverlauf:** die häufigste Verbindung je Stadt, gezogen durch alle Halte der genutzten Züge.

## Projektaufbau

```
pipeline/journeys.py   Routensuche auf dem GTFS-Fahrplan      -> data/journeys.json
pipeline/delays.py     Pünktlichkeit aus historischen Daten   -> data/delays.json
pipeline/build.py      alles zusammen + Kartenumriss          -> docs/index.html
docs/template.html     Seitenvorlage (HTML/CSS/JS, ohne Bibliotheken)
data/cities.csv        Städte ab 500.000 Einwohner:innen mit Hauptbahnhof
```

Die Rohdaten (ca. 1,2 GB) liegen nicht im Repository. Zum Neuberechnen herunterladen nach:

- `data/raw/gtfs_fv/`, `data/raw/gtfs_rv/`: entpackte Feeds von https://download.gtfs.de/germany/fv_free/latest.zip und `.../rv_free/latest.zip`
- `data/raw/delays/data-2026-08.parquet` … `data-2026-10.parquet`: von https://huggingface.co/datasets/piebro/deutsche-bahn-data (Ordner `monthly_processed_data`)
- `data/raw/geo/countries-50m.json`: https://cdn.jsdelivr.net/npm/world-atlas@2.0.2/countries-50m.json

```powershell
python -m venv .venv
.venv\Scripts\pip install duckdb
.venv\Scripts\python pipeline\journeys.py
.venv\Scripts\python pipeline\delays.py
.venv\Scripts\python pipeline\build.py
```

`data/cities.csv` wurde aus der Destatis-Tabelle erzeugt (siehe Quellen); dafür wird zusätzlich `openpyxl` gebraucht.

## Methode

- **Routensuche:** Connection Scan über Fern- und Regionalverkehr mit höchstens 4 Umstiegen und mindestens 5 Minuten Umstiegszeit am selben Bahnhof.
  - Je Abfahrt wird die Verbindung mit der kleinsten Summe aus Ankunftszeit und 30 Minuten je Umstieg gewählt. Ein Direktzug wird also bevorzugt, solange er höchstens 30 Minuten langsamer ist.
  - Der Aufschlag dient nur der Auswahl. Alle angezeigten Fahrzeiten sind echte Fahrplanzeiten.
  - Als Ankunft in einer Stadt zählen auch weitere Fernbahnhöfe (z. B. Köln Messe/Deutz, Berlin Südkreuz, Hamburg-Harburg).
- **Pünktlichkeit:** Je Teilstrecke werden alle Ankünfte Mo–Fr, August–Oktober 2026, am Ausstiegsbahnhof zur selben Planzeit ausgewertet. Bei Fernzügen muss zusätzlich der Zugtyp übereinstimmen.
  - Verspätet heißt: 6 Minuten oder mehr (DB-Definition). Ausfälle zählen als verspätet.
  - Ein Anschluss gilt als verpasst, wenn die Verspätung des Zubringers größer ist als die geplante Umstiegszeit. Teilstrecken werden als unabhängig angenommen.
  - Verbindungen ohne passende historische Daten (z. B. nach Fahrplanänderungen) werden als „keine Daten“ ausgewiesen.
- **Preise:** nicht enthalten. Es gibt keine frei zugängliche offizielle Preis-Schnittstelle, und DB sperrt automatisierte Abfragen.

## Quellen und Lizenzen

| Daten | Quelle | Lizenz |
|---|---|---|
| Städte | Destatis, „Städte nach Fläche, Bevölkerung und Bevölkerungsdichte“, Stand 31.12.2024 – https://www.destatis.de/DE/Themen/Laender-Regionen/Regionales/Gemeindeverzeichnis/Administrativ/05-staedte.html | © Statistisches Bundesamt (Destatis), 2025; laut Deckblatt „Vervielfältigung und Verbreitung, auch auszugsweise, mit Quellenangabe gestattet“ |
| Fahrplan | GTFS.DE (Daten: DELFI e.V., GTFS.DE, OpenStreetMap-Mitwirkende), Stand 21.11.2026 – https://gtfs.de/en/feeds/ | CC BY 4.0 |
| Verspätungen | piebro, „Deutsche Bahn Data“ (aus der DB Timetables API) – https://huggingface.co/datasets/piebro/deutsche-bahn-data | CC BY 4.0 |
| Kartenumriss | Natural Earth via world-atlas 2.0.2 – https://www.npmjs.com/package/world-atlas | gemeinfrei |

## Einschränkungen

- Sollfahrplan: Kurzfristige Baustellen und Ersatzverkehr fehlen oder sind nur teilweise enthalten.
- Fußwege zwischen verschiedenen Bahnhöfen werden nicht berücksichtigt.
- Die Streckenlinien verlaufen zwischen zwei Halten gerade, weil der Fahrplan keine Gleisgeometrie enthält.
- Alle Angaben ohne Gewähr.
