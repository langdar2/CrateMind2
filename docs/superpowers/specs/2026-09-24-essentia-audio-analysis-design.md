# Essentia Audio-Analyse-Pipeline — Design

## Kontext

CrateMind2 baut ein Hör-Profil aus dem Apple-Music-Verlauf, das gegen die
lokale VuIO-DLNA-Bibliothek (`minime-3.local`, `/Volumes/Platte/Musik`,
~32.500 Audiodateien) gematcht wird. Neben tag-basiertem Matching (Artist,
Genre, Album — aus vorhandenen ID3-Tags) soll eine zweite Signalquelle
entstehen: Audio-Features und Embeddings pro Track, extrahiert mit
[Essentia](https://essentia.upf.edu/), lokal auf dem VuIO-Host, ohne
Cloud-Dienst.

Dieses Dokument beschreibt nur die Analyse-Pipeline (Scan → Essentia →
SQLite). Scoring/Matching gegen den Apple-Music-Verlauf und die Web-App sind
eigene, spätere Specs.

## Architektur

Ein Docker-Container läuft dauerhaft auf `minime-3.local` (Docker bereits
vorhanden) und führt alle 30 Minuten einen Zyklus aus:

```
[Scan] → [Diff gegen SQLite] → [Essentia-Analyse neuer/geänderter Dateien] → [SQLite schreiben]
```

- **Scan**: rekursiv über den gemounteten Musik-Ordner, sammelt
  `(path, mtime, size)`
- **Diff**: gegen die `tracks`-Tabelle — neu, geändert (mtime/size
  abweichend) oder verschwunden (Datei existiert nicht mehr → Zeile entfernt)
- **Analyse**: nur die Differenzmenge durchläuft Essentia, nicht die gesamte
  Bibliothek pro Zyklus
- **Schreiben**: Tags + Embedding pro Track, ein Commit pro Track

Kein Cron-Daemon im Container — einfache `while True: scan(); sleep(1800)`
Schleife als Entrypoint.

Kein Abgleich über VuIOs interne File-IDs: VuIO bietet kein REST-Listing der
Bibliothek (nur UPnP/SOAP-Browse oder der MCP-Endpoint selbst). Die Pipeline
nutzt stattdessen den **Dateipfad** als Schlüssel, der zwischen VuIO und
dieser Pipeline übereinstimmt und für spätere Zuordnung (Web-App → Pfad →
VuIO-Wiedergabe) ausreicht.

## Komponenten

1. **Docker-Image**: Python 3.11 + `essentia-tensorflow` (pip) + `ffmpeg`
   (Dekodierung diverser Audioformate)

2. **Essentia-Modelle** (im Image gebündelt, kein Laden zur Laufzeit von
   extern):
   - **MusiCNN-Embedding** (`msd-musicnn-1`) als Basis-Feature-Vektor
   - **Mood-Klassifikatoren** auf demselben Embedding: happy, aggressive,
     relaxed, party, plus Danceability
   - **Kein ML-Genre-Modell** — Genre kommt bereits aus vorhandenen ID3-Tags
     (redundant, daher nicht dupliziert)
   - **Tempo (BPM) & Key**: klassische (nicht ML-basierte) Essentia-
     Algorithmen (`RhythmExtractor2013`, `KeyExtractor`) — schnell, direkt
     aus dem Audiosignal

3. **Scan-Script** (Python): Traversierung, Diff-Logik, Essentia-Aufruf pro
   Track, DB-Schreiben

4. **SQLite-Schema**:
   ```sql
   CREATE TABLE tracks (
     path TEXT PRIMARY KEY,
     mtime REAL NOT NULL,
     size INTEGER NOT NULL,
     status TEXT NOT NULL DEFAULT 'pending', -- pending | ok | failed
     last_scanned REAL NOT NULL
   );

   CREATE TABLE features (
     path TEXT PRIMARY KEY REFERENCES tracks(path),
     bpm REAL,
     key TEXT,
     mood_happy REAL,
     mood_aggressive REAL,
     mood_relaxed REAL,
     mood_party REAL,
     danceability REAL,
     embedding BLOB -- float32-Array, serialisiert
   );
   ```

5. **Scheduler**: siehe Architektur — einfache Sleep-Loop, kein Cron.

## Datenfluss

```
Scan-Loop (alle 30 Min)
  └─> os.walk() über /music (Mount von /Volumes/Platte/Musik)
        └─> pro Datei: (path, mtime, size)
              └─> Vergleich mit tracks-Tabelle:
                    - unbekannt/mtime geändert → Analyse-Queue
                    - unverändert → skip
                    - Pfad in DB, Datei fehlt auf Platte → Zeile löschen
                      (tracks + features)
              └─> Analyse-Queue sequentiell abarbeiten:
                    load audio → MusiCNN-Embedding → Mood-Heads → BPM/Key
                    → INSERT/UPDATE tracks + features (eine Transaktion
                      pro Track)
  └─> Sleep 1800s
```

Analyse läuft **sequentiell**, kein Multiprocessing — bewusste
Vereinfachung, da TensorFlow-Inferenz CPU-lastig ist und naive
Parallelisierung auf dem Mac mini eher Speicherdruck/Threading-Probleme
bringt als Zeit spart. Für den initialen Backfill (~32.500 Tracks) bedeutet
das: mehrere Stunden bis ~1-2 Tage verteilt über wiederholte 30-Minuten-
Zyklen — unkritisch, da kein interaktiver Nutzer wartet.

## Fehlerbehandlung

- **Datei nicht dekodierbar**: Fehler loggen, `tracks.status = 'failed'`,
  kein automatischer Retry jeden Zyklus — nur bei geänderter `mtime` erneut
  versucht (verhindert, dass eine kaputte Datei dauerhaft Ressourcen bindet)
- **Container-Crash/Neustart mitten im Batch**: unkritisch, da jeder Track
  einzeln committet wird — nächster Zyklus setzt an der DB fort, kein
  Halbzustand über mehrere Tracks hinweg
- **Essentia/Modell-Fehler pro Track**: try/except je Track, Fortsetzung mit
  dem nächsten — ein fehlerhafter Track darf den Scan-Zyklus nie abbrechen

## Testing

- **Diff-Logik** (`test_diff.py`, reine Funktion ohne Audio): `assert`-
  basierte Checks für die vier Fälle neu/geändert/unverändert/gelöscht,
  gegen Fake-DB-Zeilen und Fake-Filesystem-Listing
- **Essentia-Pipeline-Smoke-Test** (`analyze.py --self-test`): verarbeitet
  eine mitgelieferte kurze Test-Audiodatei end-to-end und prüft:
  - BPM in plausiblem Bereich (20–300)
  - Embedding hat erwartete Dimension (200 für MusiCNN)
  - Mood-Werte liegen in [0, 1]

Kein Test-Framework (pytest/Fixtures) — beide Checks sind einzelne, direkt
ausführbare Python-Dateien.

## Out of Scope (bewusst nicht Teil dieses Designs)

- Scoring/Matching der Features gegen den Apple-Music-Verlauf
- Web-App / UI
- VuIO-Integration über dessen MCP- oder SOAP-Interface (Pipeline ist
  komplett unabhängig von VuIOs Bibliotheks-API)
- Genre-Klassifikation per ML (siehe Komponenten — redundant zu ID3-Tags)
