# gitaserena-data

Public data for the GitaSerena app, and its [privacy policy](PRIVACY.md) (in Italian).

## config.json

Addresses of the public services the app calls. The app downloads this file at
most once a day and applies it at the next start, so a service can be replaced
without an app update. An empty value turns a service off: the app then falls
back to its estimate, to no restaurants, or to its bundled events.

- `routing`: OSRM server with the car profile, for travel times.
- `overpass`: Overpass API server, for restaurants.
- `events`: the events file described below.

Only HTTPS addresses are accepted. Anything else is ignored and the app keeps
its built-in address.

The `app` section controls updates:

- `minVersion`: an installed version below this shows only an update screen,
  and the app cannot be used until it is updated. Raise it only when old
  versions really stop working: stores roll updates out over hours or days.
- `latestVersion`: below this the app shows a banner that can be closed.
- `storeUrls`: the store pages opened by the "Aggiorna" button. When `android`
  is empty, the app uses its Play Store page; when `ios` is empty, the update
  screen only tells the user to open the App Store.

A version that cannot be read, such as `1.0-beta`, is ignored, so a typo
cannot lock users out. The app checks at most once a day.

## events.json

Upcoming events in Italy, from open data. The workflow in
`.github/workflows/events.yml` rebuilds the file every Monday. It can also be
started by hand from the Actions tab.

The app downloads it from:

```
https://raw.githubusercontent.com/giosu68/gitaserena-data/main/events.json
```

To build it locally, with Python 3.12 and no other dependency:

```bash
python build_events.py
```

If a source fails, the script writes nothing, so the published file never
loses data because of one bad run.

### Format

```json
{
  "generatedAt": "2026-11-06",
  "sources": { "mic": "Ministero della Cultura (CC BY 4.0)" },
  "events": [
    {
      "id": "mic-...",
      "title": "...",
      "category": "cultura",
      "start": "2026-11-06",
      "end": "2026-11-30",
      "lat": 45.07,
      "lon": 7.68,
      "place": "...",
      "url": "https://...",
      "source": "mic"
    }
  ]
}
```

`category` is one of `sagra`, `festa`, `mercatino`, `musica`, `cultura`.

### Sources and licences

As declared on dati.gov.it:

- Ministero della Cultura, dati.cultura.gov.it: CC BY 4.0
- Regione Lombardia, "Sagre e fiere su area pubblica": CC0
- Emilia-Romagna Turismo: CC BY 4.0
- Comune di Bologna, "Bologna Agenda Cultura": CC BY 4.0
- Comune di Firenze, "Eventi a Firenze": CC BY 4.0
- Coordinates of the comuni: Wikidata, CC0

Whoever reuses the file must credit the sources above.
