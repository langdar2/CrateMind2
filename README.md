# CrateMind2

Analysiert eine lokale Musikbibliothek mit Essentia und baut daraus Playlists —
nach Klang, nach Geschmack oder beides gemischt. Läuft im Heimnetz neben einem
[VuIO](https://github.com/)-Medienserver und spielt auf DLNA-, AirPlay- und
Chromecast-Geräten ab.

![Dashboard](docs/images/dashboard.jpg)

## Was es tut

Ein Hintergrunddienst scannt die Musikordner und berechnet pro Track BPM,
Tonart, fünf Stimmungswerte (happy, aggressive, relaxed, party, danceability)
und ein 200-dimensionales Klang-Embedding. Die Weboberfläche nutzt diese Daten,
um Playlists zusammenzustellen, sie an VuIO zu übergeben und auf einem
Abspielgerät zu starten.

Dazu kommt ein Geschmacksmodell: aus einem Apple-Music-Export importierte
Abspielzahlen, eigene mitgezählte Wiedergaben und manuelle Bewertungen ergeben
pro Track ein Perzentil, das in die Auswahl einfließt.

## Einrichtung

Voraussetzungen: Docker, ein laufender VuIO-Server, die Musik als Dateien im
Dateisystem.

```bash
git clone <repo> && cd CrateMind2
docker compose up -d --build
```

Die Oberfläche läuft danach auf Port **8008**. Der erste Scan dauert je nach
Bibliotheksgröße Stunden — der Fortschritt steht im Dashboard.

### Konfiguration

Die Pfade in `docker-compose.yml` anpassen, vor allem den Musikordner:

```yaml
volumes:
  - /Volumes/Platte/Musik:/music:ro
```

| Variable | Standard | Bedeutung |
|---|---|---|
| `MUSIC_DIR` | `/music` | Musikordner im Container |
| `DB_PATH` | `/data/library.db` | SQLite-Datenbank |
| `SCAN_INTERVAL_SECONDS` | `1800` | Abstand zwischen Scans |
| `VUIO_BASE_URL` | — | VuIO-Server |
| `VUIO_MUSIC_DIR` | = `MUSIC_DIR` | Musikordner, wie **VuIO** ihn sieht |
| `OMLX_BASE_URL` | — | lokales LLM (OpenAI-kompatibel) |
| `TYPESAFE_API_KEY` | — | nur für den Smart-Modus |
| `TZ` | `Europe/Berlin` | Zeitzone für die Zeitpläne |

`VUIO_MUSIC_DIR` ist der häufigste Stolperstein: Beide Dienste indizieren
dieselben Dateien, mounten sie aber oft unter verschiedenen Wurzeln. Stimmt die
Angabe nicht, findet CrateMind die Tracks in VuIO nicht wieder.

Das lokale LLM und der Smart-Modus sind optional. Fällt eines aus, funktioniert
alles andere weiter.

## Playlists bauen

![Playlists](docs/images/playlists.jpg)

Fünf Modi:

**Manuell** — Schieberegler für BPM, Stimmungen und Vorliebe. Kostenlos und
ohne LLM, die Vorschau aktualisiert sich beim Schieben.

**Prompt** — Freitext wie *„energiegeladenes Workout, nur Lieblingstracks"*.
Das lokale Modell übersetzt das in Schwellenwerte für Tempo und Stimmung,
filtert damit die Bibliothek und bewertet die Treffer anhand von Künstler und
Titel noch einmal nach, wie gut sie zum Thema passen. Das dauert rund eine halbe
Minute.

Er funktioniert gut bei Aktivitäten und Tempo (*Partystimmung*, *Workout*,
*ruhiger Hintergrund*) und schwächer bei Themen, die sich nicht im Klang
zeigen. *„Romantisches Abendessen mit Liebesliedern"* ergibt zwar ruhige
Musik, aber auch Wiegenlieder und Filmmusik, denn aus den Audiowerten lässt
sich nicht ablesen, ob ein Text von Liebe handelt, und das kleine lokale Modell
bewertet nicht zuverlässig. Für solche Fälle ist **Smart (Vibe)** die bessere
Wahl.

Sind die Grenzen, die das Modell wählt, unerfüllbar (etwa „höchstens 0,0
aggressiv"), werden sie schrittweise gelockert, statt eine leere Liste zu
liefern.

**Seed-Track** — ein Track als Ausgangspunkt, der Rest nach Klangähnlichkeit.
Der Regler *Klang ↔ Geschmack* mischt bei, wie sehr Vorlieben mitreden.

**Smart (Vibe)** — eine Stimmungsbeschreibung, die ein externes Modell über
eine Vorauswahl von 150 Kandidaten sortiert. Der einzige Modus, der Kosten
verursacht.

**Wunschliste** — eine Liste konkreter Titel, die auf jeden Fall drin sein
sollen. Der Rest wird mit passenden Titeln aufgefüllt (siehe unten).

Zwei Regler gelten modusübergreifend:

- **Vorliebe** filtert nach Perzentil („Top 10%"). Achtung: Zwei Drittel der
  Bibliothek haben keinen Geschmacks-Score — sobald der Regler greift, fallen
  die komplett raus.
- **Entdeckung** gibt deshalb einen Teil der Plätze an genau diese Tracks
  zurück, zufällig gezogen und gleichmäßig eingewoben.

Jede Playlist bekommt höchstens 5 Titel pro Künstler und keine doppelten
Aufnahmen. Vor dem Speichern lassen sich Name und Beschreibung vom lokalen
Modell vorschlagen oder von Hand eintragen.

### Wunschliste

![Wunschliste](docs/images/wishlist.jpg)

Titel einfügen, einen pro Zeile. Verstanden werden:

```
Falco - Vienna Calling
Die Ärzte – Schrei nach Liebe
Nothing Else Matters by Metallica
03. Udo Lindenberg - Cello
Wonderwall
```

Tracknummern und Aufzählungszeichen aus kopierten Listen werden ignoriert,
ebenso Groß- und Kleinschreibung, Akzente und Klammerzusätze wie „(Live)" oder
„(Remastered)".

Die gefundenen Titel stehen am Anfang der Playlist, in der angegebenen
Reihenfolge. Danach wird auf 50 Tracks aufgefüllt (per Regler 10 bis 100), und
zwar mit Titeln, die am ähnlichsten klingen wie die Wunschliste *als Ganzes* —
nicht wie ein einzelner Song daraus. Es gelten die üblichen Regeln: höchstens
5 Titel pro Künstler, keine doppelten Versionen.

Darüber steht, wie viele Wunschtitel gefunden wurden, und darunter die
fehlenden, rot markiert und mit *Liste kopieren* in die Zwischenablage zu
holen. Praktisch als Einkaufsliste.

Gut zu wissen:

- Gibt es einen Song in mehreren Fassungen, gewinnt die Albumfassung vor
  Live-, Remix-, Demo- oder Akustikversionen. Ein Remaster zählt als
  Albumfassung.
- Ein Titel **ohne Künstler** trifft nur, wenn genau ein Künstler in der
  Bibliothek einen Song dieses Namens hat. „Wonderwall" klappt, „Intro" wird
  als fehlend gemeldet, statt zu raten.
- Der Titel muss bis auf Klammerzusätze stimmen. Ein Tippfehler ergibt
  „fehlt", auch wenn der Song vorhanden ist.

## Automatische Mixe

![Zeitpläne](docs/images/schedules.jpg)

Eine Playlist merkt sich das Rezept, aus dem sie entstanden ist, und kann
wöchentlich daraus neu befüllt werden — gleiche Playlist-ID, neue Tracks, neue
Beschreibung. Wochentag und Uhrzeit sind hier einstellbar, dazu Pausieren und
sofortiges Neubefüllen.

Das geht mit jeder Playlist, die in CrateMind angelegt wurde, egal aus
welchem Modus. Was sich pro Lauf ändert, hängt vom Modus ab:

- **Manuell, Prompt, Seed:** Die Entdeckungsplätze werden neu gezogen, ein
  wöchentlicher Mix enthält also jedes Mal anderes unbekanntes Material.
- **Klang-Graph:** Pro Künstler wird aus den besser bewerteten Titeln neu
  gelost, nicht immer dieselben drei genommen.
- **Wunschliste:** Die Wunschtitel bleiben immer drin, nur die Auffüller
  wechseln.

Playlists, die außerhalb von CrateMind entstanden sind, haben kein Rezept und
werden hier nicht zum Einplanen angeboten.

## Klang-Graph

![Graph](docs/images/graph.jpg)

Zeigt einen Künstler mit seinen klanglich nächsten Nachbarn. Knotengröße ist
die Trackzahl, Farbe das Geschmacks-Perzentil (grau = keine Daten). Ein Klick
springt weiter zur Nachbarschaft des angeklickten Künstlers.

Die Kanten bedeuten *klingt ähnlich* — sie stammen aus den Essentia-Embeddings,
nicht aus Metadaten. Mit *Diese Künstler als Playlist* wandert die sichtbare
Auswahl in den Playlists-Tab — und lässt sich dort speichern und wöchentlich
neu befüllen wie jede andere Playlist.

## Lokales LLM

Im Tab „LLM" stellst du ein, welcher oMLX-Server und welches Modell für Namen, Beschreibungen, Prompt-Filter und das Nachbewerten genutzt wird: Server-Adresse, API-Key und Modell (die Liste kommt direkt vom Server). „Verbindung testen" prüft den Key, holt die Modellliste und lässt das Modell einmal antworten. Gespeichert wird in der Datenbank, die Änderung gilt sofort ohne Neustart. Der Key steht nur dort (nicht im Repo) und wird in der Oberfläche nie im Klartext angezeigt. Ohne gespeicherte Werte gelten `OMLX_BASE_URL`, `OMLX_MODEL` und `OMLX_API_KEY` aus der Umgebung.

## Abspielen

![Renderer](docs/images/renderers.jpg)

Zeigt die von VuIO gefundenen Geräte. Eine angelegte Playlist lässt sich direkt
auf eines davon casten. Die Statusleiste unten zeigt den laufenden Titel.

Wiedergaben werden mitgezählt: länger als 30 Sekunden gilt als gespielt,
kürzer als Skip. Das fließt in den Geschmacks-Score ein — und erfasst vor allem
die Musik, die der Apple-Export nie gesehen hat.

## Geschmacksdaten importieren

Optional, verbessert aber die Auswahl deutlich. Aus einem Apple-Media-Services-
Export:

```bash
python3 scripts/import_preferences.py \
  --library-json "Apple Music Library Tracks.json" \
  --db data/library.db \
  --history-csv "Apple Music - Play History Daily Tracks.csv"
```

Ohne `--history-csv` zählt ein Abspielvorgang von 2012 so viel wie einer von
letzter Woche. Mit ihr verfallen alte Wiedergaben (Halbwertszeit zwei Jahre,
über `--half-life-years` einstellbar), sodass der Score dem aktuellen Geschmack
folgt.

Die Zuordnung läuft über die Dateipfade. Wie gut das klappt, verrät vorab:

```bash
python3 scripts/match_probe.py \
  --library-json "Apple Music Library Tracks.json" --db data/library.db
```

## Tests

```bash
cd webapp/backend && for t in test_*.py; do python3 "$t"; done
python3 scripts/test_import_preferences.py
```

Keine Frameworks, jede Datei ist direkt ausführbar.

## Architektur

Zwei Container auf einer gemeinsamen SQLite-Datenbank:

- **analysis** — scannt und analysiert, schreibt `tracks` und `features`.
  Läuft unter `linux/amd64`, weil es für `essentia-tensorflow` kein
  arm64-Paket gibt.
- **webapp** — FastAPI plus React, liest die Analysedaten und besitzt
  Bewertungen, Abspielzahlen, Rezepte und Zeitpläne.

Die Webapp hält Tracks und Künstlergraph im Speicher und lädt sie alle zwei
Minuten neu, wenn der Analysedienst etwas hinzugefügt hat.

Die Oberfläche ist im LCARS-Stil gehalten — schwarz mit orangefarbenen
Pillenformen, aus Spaß an der Sache.
