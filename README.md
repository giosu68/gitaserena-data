# gitaserena-data

Public data for the GitaSerena app.

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
