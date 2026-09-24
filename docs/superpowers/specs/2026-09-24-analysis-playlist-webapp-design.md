# Analyse- & Playlist-Web-App — Design

## Kontext

Die Essentia-Analyse-Pipeline (siehe
[Design](2026-09-24-essentia-audio-analysis-design.md)) füllt eine SQLite-DB
(`tracks`, `features`) auf `minime-3.local` mit Audio-Features pro Track:
BPM, Key, vier Mood-Scores, Danceability, 200-dim MusiCNN-Embedding.

Dieses Dokument beschreibt eine Web-App, die diese Daten nutzbar macht:
Analyse-Dashboard über die Bibliothek + Generierung von Playlists, die
direkt in VuIO angelegt und abgespielt werden können.

Apple-Music-Matching/Scoring gegen den Hörverlauf ist bewusst nicht Teil
dieses Designs — kommt später als eigenes Feature. Schema und API bleiben
so offen, dass ein Score-Feld sich später ergänzen lässt, ohne Bestehendes
zu brechen.

## Architektur

Ein neuer Service `webapp` im selben `docker-compose.yml` auf
`minime-3.local`, neben dem bestehenden `analysis`-Container:

- **Backend** (FastAPI, Python): liest read-only aus derselben
  `library.db` (SQLite), berechnet Aggregationen und Embedding-Ähnlichkeiten,
  spricht mit VuIOs lokaler HTTP-API für Playlist-Anlage und Wiedergabe
  (dieselbe API, die auch die vorhandenen VuIO-MCP-Tools nutzen — exakte
  Endpunkte werden bei der Implementierung direkt gegen den laufenden
  Server auf `minime-3.local` geklärt).
- **Frontend**: React-SPA, Top-Nav-Layout mit den Seiten *Dashboard*,
  *Playlists*, *Renderer*.
- Kein Login — reiner Heimnetz-Zugriff, wie VuIO selbst.

## Komponenten

### Backend (FastAPI)

- `GET /api/stats` — Aggregationen für's Dashboard: Mood-Verteilung,
  BPM-Histogramm, Key-Verteilung, Analyse-Fortschritt (Anzahl
  ok/failed/pending)
- `GET /api/tracks?...` — paginierte/filterbare Tracklisten (z.B. nach
  Mood-Schwellwert, BPM-Bereich, Textsuche)
- `GET /api/presets` — feste Presets (Workout, Chill, Party, ...) mit
  ihren Mood-/BPM-/Danceability-Schwellwerten
- `POST /api/playlists/preview` — generiert eine Kandidatenliste, entweder
  aus einem Preset ODER aus einem `seed_path` (Embedding-Cosine-Ähnlichkeit
  via `numpy`; alle Embeddings werden beim Start in den Speicher geladen —
  bei ~32.500 Tracks × 200 floats ≈ 25 MB, unproblematisch)
- `POST /api/playlists` — legt die (vom Nutzer editierte) Liste als echte
  Playlist in VuIO an
- `POST /api/playlists/{id}/cast` — startet Wiedergabe der Playlist auf
  einem gewählten Renderer

### Frontend (React)

- **Dashboard**: Kacheln mit den Diagrammen aus `/api/stats` (z.B. mit
  `recharts`)
- **Playlists**: Preset wählen ODER Seed-Track suchen → Vorschau-Liste →
  Tracks entfernen/neu anordnen → "In VuIO anlegen" → optional direkt auf
  einen Renderer casten
- **Renderer**: Liste der VuIO-Renderer mit aktuellem Wiedergabestatus

## Datenfluss

```
Dashboard-Aufruf → Backend aggregiert SQLite-Query → JSON → Charts

Playlist-Generierung:
  Preset gewählt → SQL-Filter auf features (mood/bpm/danceability)
  ODER
  Seed-Track gewählt → Embedding laden → Cosine-Similarity gegen alle
                        Embeddings → Top-N
  → Vorschau im Frontend → Nutzer editiert (entfernen/umsortieren)
  → "Anlegen" → Backend ruft VuIO-API: Playlist erstellen + Tracks
                hinzufügen
  → optional: Backend ruft VuIO-API: auf Renderer casten
```

Nur Tracks mit `status = 'ok'` und vorhandenem Embedding sind
Playlist-Kandidaten — `failed`/`pending`-Tracks werden stillschweigend
ausgeschlossen.

## Fehlerbehandlung

- **VuIO nicht erreichbar** (Container-Neustart, Netzwerkproblem): Backend
  antwortet mit 502 und Klartext-Fehlermeldung; Frontend zeigt die
  Fehlermeldung an statt stillem Fehlschlag. Kein automatischer Retry —
  der Nutzer klickt bei Bedarf einfach erneut.
- **Leere Bibliothek / noch kein Track mit `status = 'ok'`**: Dashboard
  zeigt einen Hinweis ("noch keine Analyse-Daten"), Playlist-Generierung
  ist deaktiviert statt abzustürzen.

## Testing

Kein Test-Framework-Overhead. Reine Funktionen (Similarity-Ranking,
Preset-Filter-Logik) werden über `assert`-basierte Skripte getestet, wie
bereits bei `test_diff.py` in der Analyse-Pipeline. Kein Browser-/E2E-Test
— manuelles Durchklicken reicht für dieses Ein-Personen-Heimprojekt.

## Out of Scope (bewusst nicht Teil dieses Designs)

- Apple-Music-Matching/Scoring gegen den Hörverlauf (eigenes, späteres
  Feature — Schema/API bleiben dafür erweiterbar)
- Login/Authentifizierung
- Mobile App
- 2D-Embedding-Cluster-Visualisierung (z.B. t-SNE/UMAP) — eigenes
  Nice-to-have, nicht Teil dieses ersten Wurfs
