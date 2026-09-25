# Fehler-Übersicht im Dashboard — Design

## Kontext

Die Essentia-Analyse-Pipeline markiert Tracks bei einem Fehler als
`status = 'failed'`, der eigentliche Grund landet aber nur als Traceback im
Container-Log — nicht in der DB, nicht in der Web-App. Dieses Feature macht
den Fehlergrund pro Track sichtbar, direkt im Dashboard der
[Analyse- & Playlist-Web-App](2026-09-24-analysis-playlist-webapp-design.md).

## Datenmodell (Analyse-Pipeline, `crate_mind/analysis/`)

- Neue Spalte `tracks.error_message TEXT` (nullable).
- Migration in `db.py`: beim Verbindungsaufbau per `PRAGMA table_info(tracks)`
  prüfen, ob die Spalte fehlt, und falls ja per `ALTER TABLE tracks ADD
  COLUMN error_message TEXT` ergänzen (nötig, da die Tabelle auf
  `minime-3.local` bereits mit Daten existiert — `CREATE TABLE IF NOT
  EXISTS` fasst eine bestehende Tabelle nicht an).
- `upsert_track(conn, path, mtime, size, status, error_message=None)`:
  - `status="ok"` → `error_message` wird auf `NULL` gesetzt.
  - `status="failed"` → `error_message` erhält `str(exception)` (kurze,
    einzeilige Meldung, kein vollständiger Traceback — das Log bleibt für
    tiefere Fehlersuche verfügbar).
- Einmalige Migration beim nächsten Pipeline-Start: bereits vorher
  fehlgeschlagene Tracks ohne gespeicherten Grund werden auf `pending`
  zurückgesetzt, damit der normale Scan-Zyklus sie erneut versucht und dabei
  einen Grund einträgt:
  ```sql
  UPDATE tracks SET status = 'pending'
  WHERE status = 'failed' AND error_message IS NULL;
  ```
  Läuft nur einmal automatisch (Bedingung greift danach nicht mehr erneut,
  da neue Fehlschläge ab sofort immer einen `error_message` haben).

## Backend (`webapp/backend`)

- `db.py`: neue Funktion
  `search_failed_tracks(conn, query="", limit=50, offset=0) -> dict` mit
  `{"tracks": [{"path": ..., "error_message": ...}], "total": N}`, gefiltert
  auf `status = 'failed'` und optional `path LIKE '%query%'`.
- `app.py`: neuer Endpoint `GET /api/tracks/failed?q=&limit=&offset=` →
  liefert obiges Ergebnis direkt durch.

## Frontend (`webapp/frontend`)

- `api.js`: neue Funktion `getFailedTracks(q, limit, offset)`.
- `Dashboard.jsx`: die bestehende "Analyse-Fortschritt"-Kachel wird
  klickbar — ein lokaler `expanded`-State klappt darunter eine Liste auf:
  - Textfeld filtert per `q`-Parameter über den Pfad (bei jeder Eingabe neu
    geladen, `limit`/`offset` auf 0 zurückgesetzt).
  - Liste zeigt `Pfad — Fehlermeldung` je Zeile.
  - "Mehr laden"-Button erhöht `offset` um `limit` und hängt die nächste
    Seite an die bestehende Liste an; ausgeblendet, sobald
    `tracks.length >= total`.

## Fehlerbehandlung

Kein Sonderfall nötig — die Kachel existiert nur, wenn
`stats.status_counts` vorhanden ist (Dashboard zeigt bei leerer Bibliothek
ohnehin schon einen eigenen Hinweis, siehe bestehendes Design). Schlägt der
neue Endpoint fehl, zeigt die aufgeklappte Liste einfach ihre eigene
Fehlermeldung statt der Trackliste.

## Testing

`assert`-basiert, wie beim übrigen Projekt (`tests/test_diff.py`,
`webapp/backend/test_*.py`):

- Neu: `crate_mind/analysis/test_db.py` — testet die Spalten-Migration
  (Spalte fehlt → wird ergänzt; Spalte existiert schon → kein Fehler) und
  das Setzen/Löschen von `error_message` in `upsert_track`.
- Erweiterung von `webapp/backend/test_db.py` um
  `search_failed_tracks` (Filter nach Query, Limit/Offset, `total`-Zählung).
- Erweiterung von `webapp/backend/test_app.py` um den neuen
  `/api/tracks/failed`-Endpoint.

## Out of Scope

- Kein Retry-Button pro Track in der UI (die einmalige Reset-Migration
  deckt die Alt-Fehler ab; künftige Fehler werden durch den normalen
  Scan-Zyklus behandelt, sobald sich die Datei ändert).
- Kein Anzeigen des vollen Tracebacks in der UI.
