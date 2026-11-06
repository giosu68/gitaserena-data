#!/usr/bin/env python3
"""Generates events.json, upcoming events from Italian open data.

A GitHub Actions workflow runs it every week. To run it by hand:

    python build_events.py

Sources, with the licences declared on dati.gov.it:
- Ministero della Cultura, dati.cultura.gov.it (CC BY 4.0): exhibitions and
  cultural events in all of Italy. Located at comune level.
- Regione Lombardia, "Sagre e fiere su area pubblica" (CC0).
- Emilia-Romagna Turismo (CC BY 4.0).
- Comune di Bologna, "Bologna Agenda Cultura" (CC BY 4.0).
- Comune di Firenze, "Eventi a Firenze" (CC BY 4.0).

The file is not written if a source fails, so a bad run cannot silently replace
good data with less. Only the standard library is used.
"""
import csv
import datetime
import io
import json
import os
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
OUTPUT = os.path.join(ROOT, "events.json")
CACHE = os.path.join(ROOT, ".cache")
USER_AGENT = "GitaSerena events (https://github.com/giosu68/gitaserena-data)"

# Comuni with their coordinates, to place the events of the ministry.
COMUNI_QUERY = """SELECT ?c ?name ?coord WHERE {
  ?c wdt:P31 wd:Q747074; wdt:P625 ?coord; rdfs:label ?name.
  FILTER(LANG(?name)="it")
}"""

# Events that last longer are permanent displays, not something on that day.
MAX_DAYS = 200
HORIZON_DAYS = 400

SOURCES = {
    "mic": "Ministero della Cultura (CC BY 4.0)",
    "lombardia": "Regione Lombardia (CC0)",
    "emilia_romagna": "Emilia-Romagna Turismo (CC BY 4.0)",
    "bologna": "Comune di Bologna (CC BY 4.0)",
    "firenze": "Comune di Firenze (CC BY 4.0)",
}

MIC_QUERY = """PREFIX cis: <http://dati.beniculturali.it/cis/>
PREFIX ti: <https://w3id.org/italia/onto/TI/>
PREFIX clv: <https://w3id.org/italia/onto/CLV/>
PREFIX sm: <https://w3id.org/italia/onto/SM/>
PREFIX dc: <http://purl.org/dc/elements/1.1/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?e ?name ?type ?start ?end ?city ?site ?url WHERE {
  ?e a cis:CulturalEvent; rdfs:label ?name; ti:atTime ?t; cis:isHostedBySite ?s.
  ?t ti:startTime ?start; ti:endTime ?end.
  FILTER(STR(?end) >= "%s")
  ?s cis:siteAddress ?a.
  ?a clv:hasCity ?city.
  OPTIONAL { ?s rdfs:label ?site. }
  OPTIONAL { ?e dc:type ?type. }
  OPTIONAL { ?e sm:hasOnlineContactPoint ?o. ?o sm:hasWebSite ?w. ?w sm:URL ?url. }
}"""
MIC_ONLINE_ONLY = {"evento solo on-line", "Iniziative Digitali"}
MIC_CATEGORY = {"Concerto": "musica", "Festival": "festa"}


def fetch(url, data=None, headers=None):
    request = urllib.request.Request(
        url, data=data, headers={"User-Agent": USER_AGENT, **(headers or {})}
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                return response.read()
        except Exception as e:
            if attempt == 2:
                raise
            log(f"  {url[:70]} failed ({e}), trying again")
            time.sleep(10 * (attempt + 1))


def log(message):
    print(f"{datetime.datetime.now():%H:%M:%S} {message}", flush=True)


def write_json(path, value):
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf8") as f:
        json.dump(value, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(temporary, path)


def load_comuni():
    """From Wikidata, once: kept in .cache for the runs that follow."""
    path = os.path.join(CACHE, "comuni.json")
    if os.path.exists(path):
        with open(path, encoding="utf8") as f:
            return json.load(f)
    body = fetch(
        "https://query.wikidata.org/sparql",
        data=urllib.parse.urlencode({"query": COMUNI_QUERY}).encode(),
        headers={"Accept": "application/sparql-results+json"},
    )
    comuni = {}
    for row in json.loads(body)["results"]["bindings"]:
        coord = row["coord"]["value"]
        if not coord.startswith("Point("):
            continue
        lon, lat = coord[6:-1].split(" ")[:2]
        item = row["c"]["value"].rsplit("/", 1)[1]
        comuni.setdefault(
            item, {"name": row["name"]["value"], "lat": float(lat), "lon": float(lon)}
        )
    os.makedirs(CACHE, exist_ok=True)
    write_json(path, comuni)
    log(f"comuni: {len(comuni)}")
    return comuni


def iso(text):
    """Accepts 2026-11-05, 2026-11-05 00:00:00 and 05/11/2026."""
    text = (text or "").strip()[:10]
    for pattern in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.datetime.strptime(text, pattern).date().isoformat()
        except ValueError:
            pass
    return None


def sentence_case(text):
    """FESTA DELLA BIRRA becomes Festa della birra. Mixed case is left alone."""
    text = " ".join(text.split())
    return text[:1] + text[1:].lower() if text.isupper() else text


def web_url(*candidates):
    """Only web addresses: the app opens this value, and it is third-party data."""
    for url in candidates:
        url = (url or "").strip()
        if url.startswith(("https://", "http://")):
            return url
    return None


def event(source, item_id, title, category, start, end, lat, lon, place, url):
    return {
        "id": f"{source}-{item_id}",
        "title": title,
        "category": category,
        "start": start,
        "end": end or start,
        "lat": round(float(lat), 5),
        "lon": round(float(lon), 5),
        "place": place,
        "url": url,
        "source": source,
    }


def comune_key(name):
    """The ministry writes Forli and Quarto d Altino: compare only the letters."""
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]", "", plain.lower())


# Names of the ministry that differ from the official name of the comune.
MIC_COMUNE_ALIAS = {comune_key("Reggio di Calabria"): comune_key("Reggio Calabria")}


def from_mic(today):
    comuni = {
        comune_key(c["name"]): c
        for c in load_comuni().values()
    }
    body = fetch(
        "https://dati.cultura.gov.it/sparql",
        data=urllib.parse.urlencode({"query": MIC_QUERY % today}).encode(),
        headers={"Accept": "application/sparql-results+json"},
    )
    output = {}
    unknown = set()
    for row in json.loads(body)["results"]["bindings"]:
        kind = row.get("type", {}).get("value", "")
        item = row["e"]["value"].rsplit("/", 1)[1]
        if kind in MIC_ONLINE_ONLY or item in output:
            continue
        city = urllib.parse.unquote(row["city"]["value"].rsplit("/", 1)[1]).replace("_", " ")
        key = comune_key(city)
        comune = comuni.get(MIC_COMUNE_ALIAS.get(key, key))
        if comune is None:
            unknown.add(city)
            continue
        site = row.get("site", {}).get("value", "").removeprefix("Sede di ").strip()
        output[item] = event(
            "mic",
            item,
            " ".join(row["name"]["value"].split()),
            MIC_CATEGORY.get(kind, "cultura"),
            iso(row["start"]["value"]),
            iso(row["end"]["value"]),
            comune["lat"],
            comune["lon"],
            site or comune["name"],
            web_url(row.get("url", {}).get("value")),
        )
    if unknown:
        log(f"  mic: comuni not recognised: {sorted(unknown)}")
    return list(output.values())


def from_lombardia(_):
    body = fetch("https://www.dati.lombardia.it/api/views/hs8z-dcey/rows.csv?accessType=DOWNLOAD")
    output = []
    for row in csv.DictReader(io.StringIO(body.decode("utf8"))):
        if not row["GEO_X"] or not row["GEO_Y"]:
            continue
        output.append(
            event(
                "lombardia",
                row["ID"],
                sentence_case(row["DENOM"]),
                "sagra" if row["TIPO"] == "Sagra" else "mercatino",
                iso(row["DATA_IN"]),
                iso(row["DATA_FINE"]),
                row["GEO_Y"],
                row["GEO_X"],
                row["COMUNE"].title(),
                web_url(row["SITO_WEB"], row["PROGRAMMA"]),
            )
        )
    return output


def emilia_romagna_category(names):
    text = " ".join(names).lower()
    for word, category in (
        ("sagr", "sagra"),
        ("mercat", "mercatino"),
        ("music", "musica"),
        ("concert", "musica"),
        ("sport", "sport"),
        ("fest", "festa"),
    ):
        if word in text:
            return category
    return "cultura"


def from_emilia_romagna(_):
    output = []
    page, last = 1, 1
    while page <= last:
        result = json.loads(fetch(f"https://emiliaromagnaturismo.it/opendata/v1/events?page={page}"))
        last = result["meta"]["last_page"]
        page += 1
        for item in result["data"]:
            located = [l for l in item.get("locations") or [] if l.get("lat") and l.get("lng")]
            dates = item.get("dates") or {}
            if not located:
                continue
            output.append(
                event(
                    "emilia_romagna",
                    item["id"],
                    item["title"].strip(),
                    emilia_romagna_category(c["name"] for c in item.get("category") or []),
                    iso(dates.get("from")),
                    iso(dates.get("to")),
                    located[0]["lat"],
                    located[0]["lng"],
                    located[0].get("city") or located[0].get("province") or "",
                    web_url(item.get("permalink")),
                )
            )
    return output


def from_bologna(_):
    body = fetch(
        "https://opendata.comune.bologna.it/api/v2/catalog/datasets/"
        "eventi-bologna-agenda-cultura/exports/json"
    )
    output = []
    for item in json.loads(body):
        where = item.get("coordinate")
        if not where or item.get("online") == "SI":
            continue
        categories = " ".join(
            filter(None, (item.get(f"categories_{i}") for i in (1, 2, 3)))
        ).lower()
        output.append(
            event(
                "bologna",
                item["id"],
                " ".join(item["title"].split()),
                "musica" if "musica" in categories else "cultura",
                iso(item.get("start")),
                iso(item.get("end")),
                where["lat"],
                where["lon"],
                "Bologna",
                web_url(item.get("url")),
            )
        )
    return output


def from_firenze(_):
    body = fetch(
        "https://data.comune.fi.it/datastore/download.php"
        "?id=6289&type=99&format=url&file_format=csv&file_id=23096"
    )
    output = []
    for index, row in enumerate(csv.DictReader(io.StringIO(body.decode("utf8")))):
        match = re.search(r"\(\(?\s*([\d.]+) ([\d.]+)", row.get("wkt") or "")
        if not match:
            continue
        output.append(
            event(
                "firenze",
                f"{row['data_inizio']}-{index}",
                row["titolo"].strip(),
                "cultura",
                iso(row["data_inizio"]),
                iso(row["data_fine"]),
                match.group(2),
                match.group(1),
                (row.get("comuni") or "Firenze").strip(),
                web_url(row.get("feelflorence_link"), row.get("link")),
            )
        )
    return output


def main():
    today = datetime.date.today()
    horizon = (today + datetime.timedelta(days=HORIZON_DAYS)).isoformat()
    today_iso = today.isoformat()

    readers = {
        "mic": from_mic,
        "lombardia": from_lombardia,
        "emilia_romagna": from_emilia_romagna,
        "bologna": from_bologna,
        "firenze": from_firenze,
    }
    events = []
    seen = set()
    for name, reader in readers.items():
        rows = reader(today_iso)
        kept = 0
        for row in rows:
            start, end = row["start"], row["end"]
            if not start or not end or end < today_iso or start > horizon or end < start:
                continue
            days = (datetime.date.fromisoformat(end) - datetime.date.fromisoformat(start)).days
            if days > MAX_DAYS:
                continue
            # Bologna appears both in its own agenda and in the regional one.
            key = (re.sub(r"\W+", "", row["title"]).lower(), start)
            if key in seen:
                continue
            seen.add(key)
            events.append(row)
            kept += 1
        log(f"{name}: {len(rows)} read, {kept} upcoming")

    events.sort(key=lambda e: (e["start"], e["id"]))
    write_json(
        OUTPUT,
        {"generatedAt": today_iso, "sources": SOURCES, "events": events},
    )
    log(f"events: {len(events)}, {os.path.getsize(OUTPUT) / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
