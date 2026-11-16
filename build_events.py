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
- Regione Lombardia, "Manifestazioni Fieristiche Locali" (CC0).
- Regione Piemonte, "Manifestazioni fieristiche", the regional calendar of
  fiere and sagre (CC BY 4.0). A zipped Shapefile, updated once a year.
- Open Data Hub Alto Adige / Südtirol, NOI Techpark (CC0, checked per record).
- Regione Puglia, "Cosa fare in Puglia - eventi e attività" (CC BY 4.0).
- Comune di Torino, eventi.comune.torino.it (CC BY 4.0, from the "Note legali"
  of the Comune). Read from the public WordPress API of the site.
- Comune di Cuneo, the events API of its site (CC BY 4.0, "Note legali").
- Comuni on OpenCity, the municipal site of OpenContent, from its open data
  API (CC BY 4.0, "Note legali" of each comune). The list is OPENCITY.

The file is not written if a source fails or gives no events, so a bad run
cannot silently replace good data with less. Only the standard library is used.
"""
import csv
import concurrent.futures
import html
import math
import struct
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
import zipfile

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
    "piemonte": "Regione Piemonte (CC BY 4.0)",
    "alto_adige": "Open Data Hub Alto Adige (CC0)",
    "puglia": "Regione Puglia (CC BY 4.0)",
    "torino": "Comune di Torino (CC BY 4.0)",
    "cuneo": "Comune di Cuneo (CC BY 4.0)",
}

# Comuni whose site is OpenCity, with the open data API at /api/opendata/v2.
# Found on 15 November 2026 by asking the API of every comune site listed in
# IndicePA; kept only the ones with upcoming events whose "Note legali" declare
# CC BY 4.0 with commercial use. Source key: comune name.
OPENCITY = {
    "alba_adriatica": ("Alba Adriatica", "https://www.comune.alba-adriatica.te.it"),
    "albano_sant_alessandro": ("Albano Sant'Alessandro", "https://www.comune.albano.bg.it"),
    "aldeno": ("Aldeno", "https://www.comune.aldeno.tn.it"),
    "alezio": ("Alezio", "https://www.comune.alezio.le.it"),
    "alfonsine": ("Alfonsine", "https://www.comune.alfonsine.ra.it"),
    "altavalle": ("Altavalle", "https://www.comune.altavalle.tn.it"),
    "annone_di_brianza": ("Annone di Brianza", "https://www.comune.annone-di-brianza.lc.it"),
    "arco": ("Arco", "https://www.comune.arco.tn.it"),
    "asolo": ("Asolo", "https://www.comune.asolo.tv.it"),
    "avio": ("Avio", "https://www.comune.avio.tn.it"),
    "bagnacavallo": ("Bagnacavallo", "https://www.comune.bagnacavallo.ra.it"),
    "bagnara_di_romagna": ("Bagnara di Romagna", "https://www.comune.bagnaradiromagna.ra.it"),
    "besenello": ("Besenello", "https://www.comune.besenello.tn.it"),
    "bolzano": ("Bolzano", "https://www.comune.bolzano.bz.it"),
    "bondone": ("Bondone", "https://www.comune.bondone.tn.it"),
    "borgo_chiese": ("Borgo Chiese", "https://www.comune.borgochiese.tn.it"),
    "borgo_d_anaunia": ("Borgo D'Anaunia", "https://www.comune.borgodanaunia.tn.it"),
    "borgo_lares": ("Borgo Lares", "https://www.comune.borgolares.tn.it"),
    "caderzone_terme": ("Caderzone Terme", "https://www.comune.caderzoneterme.tn.it"),
    "calci": ("Calci", "https://www.comune.calci.pi.it"),
    "caldonazzo": ("Caldonazzo", "https://www.comune.caldonazzo.tn.it"),
    "calvisano": ("Calvisano", "https://www.comune.calvisano.bs.it"),
    "campodenno": ("Campodenno", "https://www.comune.campodenno.tn.it"),
    "canal_san_bovo": ("Canal San Bovo", "https://www.comune.canalsanbovo.tn.it"),
    "canazei": ("Canazei", "https://www.comune.canazei.tn.it"),
    "carenno": ("Carenno", "https://www.comune.carenno.lc.it"),
    "castel_condino": ("Castel Condino", "https://www.comune.castelcondino.tn.it"),
    "castello_molina_di_fiemme": ("Castello-Molina di Fiemme", "https://www.comune.castellomolinadifiemme.tn.it"),
    "cavalese": ("Cavalese", "https://www.comune.cavalese.tn.it"),
    "cavedine": ("Cavedine", "https://www.comune.cavedine.tn.it"),
    "cesiomaggiore": ("Cesiomaggiore", "https://www.comune.cesiomaggiore.bl.it"),
    "chianocco": ("Chianocco", "https://www.comune.chianocco.to.it"),
    "civezzano": ("Civezzano", "https://www.comune.civezzano.tn.it"),
    "cles": ("Cles", "https://www.comune.cles.tn.it"),
    "colico": ("Colico", "https://www.comune.colico.lc.it"),
    "comano_terme": ("Comano Terme", "https://www.comune.comanoterme.tn.it"),
    "conselice": ("Conselice", "https://www.comune.conselice.ra.it"),
    "conta": ("Conta", "https://www.comune.conta.tn.it"),
    "cortina_d_ampezzo": ("Cortina d'Ampezzo", "https://www.comune.cortinadampezzo.bl.it"),
    "cotignola": ("Cotignola", "https://www.comune.cotignola.ra.it"),
    "croviana": ("Croviana", "https://www.comune.croviana.tn.it"),
    "denno": ("Denno", "https://www.comune.denno.tn.it"),
    "drena": ("Drena", "https://www.comune.drena.tn.it"),
    "dro": ("Dro", "https://www.comune.dro.tn.it"),
    "empoli": ("Empoli", "https://www.comune.empoli.fi.it"),
    "escalaplano": ("Escalaplano", "https://www.comune.escalaplano.ca.it"),
    "fai_della_paganella": ("Fai della Paganella", "https://www.comune.faidellapaganella.tn.it"),
    "fermo": ("Fermo", "https://www.comune.fermo.it"),
    "fiano_romano": ("Fiano Romano", "https://www.comune.fianoromano.rm.it"),
    "folgaria": ("Folgaria", "https://www.comune.folgaria.tn.it"),
    "fusignano": ("Fusignano", "https://www.comune.fusignano.ra.it"),
    "garniga_terme": ("Garniga Terme", "https://www.comune.garnigaterme.tn.it"),
    "la_valletta_brianza": ("La Valletta Brianza", "https://www.comune.lavallettabrianza.lc.it"),
    "lavarone": ("Lavarone", "https://www.comune.lavarone.tn.it"),
    "lecco": ("Lecco", "https://www.comune.lecco.it"),
    "ledro": ("Ledro", "https://www.comune.ledro.tn.it"),
    "livo": ("Livo", "https://www.comune.livo.tn.it"),
    "lodrino": ("Lodrino", "https://www.comune.lodrino.bs.it"),
    "lograto": ("Lograto", "https://www.comune.lograto.bs.it"),
    "lona_lases": ("Lona-lases", "https://www.comune.lonalases.tn.it"),
    "lugo": ("Lugo", "https://www.comune.lugo.ra.it"),
    "madruzzo": ("Madruzzo", "https://www.comune.madruzzo.tn.it"),
    "manerbio": ("Manerbio", "https://www.comune.manerbio.bs.it"),
    "marcheno": ("Marcheno", "https://www.comune.marcheno.bs.it"),
    "martina_franca": ("Martina Franca", "https://www.comune.martinafranca.ta.it"),
    "massa_lombarda": ("Massa Lombarda", "https://www.comune.massalombarda.ra.it"),
    "massimeno": ("Massimeno", "https://www.comune.massimeno.tn.it"),
    "masullas": ("Masullas", "https://www.comune.masullas.or.it"),
    "mazzin": ("Mazzin", "https://www.comune.mazzin.tn.it"),
    "mezzana": ("Mezzana", "https://www.comune.mezzana.tn.it"),
    "mezzano": ("Mezzano", "https://www.comune.mezzano.tn.it"),
    "montespertoli": ("Montespertoli", "https://www.comune.montespertoli.fi.it"),
    "montevecchia": ("Montevecchia", "https://www.comune.montevecchia.lc.it"),
    "mori": ("Mori", "https://www.comune.mori.tn.it"),
    "nago_torbole": ("Nago-Torbole", "https://www.comune.nago-torbole.tn.it"),
    "nogaredo": ("Nogaredo", "https://www.comune.nogaredo.tn.it"),
    "offlaga": ("Offlaga", "https://www.comune.offlaga.bs.it"),
    "olgiate_molgora": ("Olgiate Molgora", "https://www.comune.olgiatemolgora.lc.it"),
    "orzinuovi": ("Orzinuovi", "https://www.comune.orzinuovi.bs.it"),
    "orzivecchi": ("Orzivecchi", "https://www.comune.orzivecchi.bs.it"),
    "palu_del_fersina": ("Palu' del Fersina", "https://www.comune.paludelfersina.tn.it"),
    "panchia": ("Panchia'", "https://www.comune.panchia.tn.it"),
    "pantelleria": ("Pantelleria", "https://www.comune.pantelleria.tp.it"),
    "peio": ("Peio", "https://www.comune.peio.tn.it"),
    "pelugo": ("Pelugo", "https://www.comune.pelugo.tn.it"),
    "pieve_tesino": ("Pieve Tesino", "https://www.comune.pievetesino.tn.it"),
    "pineto": ("Pineto", "https://www.comune.pineto.te.it"),
    "pinzolo": ("Pinzolo", "https://www.comune.pinzolo.tn.it"),
    "piovene_rocchette": ("Piovene Rocchette", "https://www.comune.piovene-rocchette.vi.it"),
    "pisa": ("Pisa", "https://www.comune.pisa.it"),
    "polaveno": ("Polaveno", "https://www.comune.polaveno.bs.it"),
    "pomarolo": ("Pomarolo", "https://www.comune.pomarolo.tn.it"),
    "pompu": ("Pompu", "https://www.comune.pompu.or.it"),
    "predaia": ("Predaia", "https://www.comune.predaia.tn.it"),
    "primaluna": ("Primaluna", "https://www.comune.primaluna.lc.it"),
    "primiero_san_martino_di_castrozza": ("Primiero San Martino di Castrozza", "https://www.comune.primierosanmartinodicastrozza.tn.it"),
    "riva_del_garda": ("Riva del Garda", "https://www.comune.rivadelgarda.tn.it"),
    "rivoli": ("Rivoli", "https://www.comune.rivoli.to.it"),
    "roncegno_terme": ("Roncegno Terme", "https://www.comune.roncegnoterme.tn.it"),
    "ronchi_valsugana": ("Ronchi Valsugana", "https://www.comune.ronchi.tn.it"),
    "ronzo_chienis": ("Ronzo Chienis", "https://www.comune.ronzo-chienis.tn.it"),
    "rosignano_marittimo": ("Rosignano Marittimo", "https://www.comune.rosignano.livorno.it"),
    "rovere_della_luna": ("Rovere' della Luna", "https://www.comune.roveredellaluna.tn.it"),
    "rovereto": ("Rovereto", "https://www.comune.rovereto.tn.it"),
    "rumo": ("Rumo", "https://www.comune.rumo.tn.it"),
    "samarate": ("Samarate", "https://www.comune.samarate.va.it"),
    "san_felice_del_benaco": ("San Felice del Benaco", "https://www.comune.sanfelicedelbenaco.bs.it"),
    "san_lorenzo_dorsino": ("San Lorenzo Dorsino", "https://www.comune.sanlorenzodorsino.tn.it"),
    "san_michele_all_adige": ("San Michele all'Adige", "https://www.comune.sanmichelealladige.tn.it"),
    "san_vito_di_leguzzano": ("San Vito di Leguzzano", "https://www.comune.sanvitodileguzzano.vi.it"),
    "sant_orsola_terme": ("Sant'Orsola Terme", "https://www.comune.santorsolaterme.tn.it"),
    "santa_giustina": ("Santa Giustina", "https://www.comune.santagiustina.bl.it"),
    "santorso": ("Santorso", "https://www.comune.santorso.vi.it"),
    "schio": ("Schio", "https://www.comune.schio.vi.it"),
    "segonzano": ("Segonzano", "https://www.comune.segonzano.tn.it"),
    "sover": ("Sover", "https://www.comune.sover.tn.it"),
    "spiazzo": ("Spiazzo", "https://www.comune.spiazzo.tn.it"),
    "spormaggiore": ("Spormaggiore", "https://www.comune.spormaggiore.tn.it"),
    "stenico": ("Stenico", "https://www.comune.stenico.tn.it"),
    "storo": ("Storo", "https://www.comune.storo.tn.it"),
    "tavagnacco": ("Tavagnacco", "https://www.comune.tavagnacco.ud.it"),
    "telve_di_sopra": ("Telve di Sopra", "https://www.comune.telvedisopra.tn.it"),
    "torcegno": ("Torcegno", "https://www.comune.torcegno.tn.it"),
    "travagliato": ("Travagliato", "https://www.comune.travagliato.bs.it"),
    "valdaone": ("Valdaone", "https://www.comune.valdaone.tn.it"),
    "valli_del_pasubio": ("Valli del Pasubio", "https://www.comune.vallidelpasubio.vi.it"),
    "velo_d_astico": ("Velo D'Astico", "https://www.comune.velodastico.vi.it"),
    "verbania": ("Verbania", "https://www.comune.verbania.it"),
    "vicopisano": ("Vicopisano", "https://www.comune.vicopisano.pi.it"),
    "villaverla": ("Villaverla", "https://www.comune.villaverla.vi.it"),
    "ville_d_anaunia": ("Ville D'Anaunia", "https://www.comune.villedanaunia.tn.it"),
    "zane": ("Zane'", "https://www.comune.zane.vi.it"),
    "ziano_di_fiemme": ("Ziano di Fiemme", "https://www.comune.ziano.tn.it"),
}
for _key, (_name, _) in OPENCITY.items():
    SOURCES[_key] = f"Comune di {_name} (CC BY 4.0)"


# Words in a title or a type that tell what kind of event it is, first match
# wins. Used by the sources without a usable category.
KEYWORDS = (
    ("sagr", "sagra"),
    ("degustazion", "sagra"),
    ("mercat", "mercatino"),
    ("markt", "mercatino"),
    ("fiera", "festa"),
    ("festa", "festa"),
    ("fest", "festa"),
    ("törggelen", "sagra"),
    ("krampus", "festa"),
    ("rievocazion", "festa"),
    ("carnevale", "festa"),
    ("concert", "musica"),
    ("musica", "musica"),
    ("banda", "musica"),
)


def category_from_words(*texts, default=None):
    text = " ".join(t for t in texts if t).lower()
    for word, category in KEYWORDS:
        if word in text:
            return category
    return default

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


def fetch(url, data=None, headers=None, timeout=180, attempts=3):
    request = urllib.request.Request(
        url, data=data, headers={"User-Agent": USER_AGENT, **(headers or {})}
    )
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except Exception as e:
            if attempt == attempts - 1:
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
        result = json.loads(fetch(f"https://emiliaromagnaturismo.it/opendata/v1/events?lang=it&page={page}"))
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


def from_lombardia_fiere(_):
    """Local fairs and markets, beside the sagre of the dataset above."""
    body = fetch("https://www.dati.lombardia.it/api/views/tchp-wt8f/rows.csv?accessType=DOWNLOAD")
    output = []
    for row in csv.DictReader(io.StringIO(body.decode("utf8"))):
        if not row["GEO_X"] or not row["GEO_Y"]:
            continue
        output.append(
            event(
                "lombardia",
                f"fiera-{row['ID']}",
                sentence_case(row["DENOM"]),
                category_from_words(row["DENOM"], row["TIPO"], default="mercatino"),
                iso(row["DATA_IN"]),
                iso(row["DATA_FINE"]),
                row["GEO_Y"],
                row["GEO_X"],
                row["COMUNE"].title(),
                web_url(row["SITO_WEB"]),
            )
        )
    return output


def utm32_to_wgs84(x, y):
    """ETRS89 / UTM zone 32N (EPSG:25832) to latitude and longitude."""
    a, f, k0 = 6378137.0, 1 / 298.257222101, 0.9996
    e2 = f * (2 - f)
    ep2 = e2 / (1 - e2)
    x -= 500000.0
    m = y / k0
    mu = m / (a * (1 - e2 / 4 - 3 * e2**2 / 64 - 5 * e2**3 / 256))
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    phi1 = (
        mu
        + (3 * e1 / 2 - 27 * e1**3 / 32) * math.sin(2 * mu)
        + (21 * e1**2 / 16 - 55 * e1**4 / 32) * math.sin(4 * mu)
        + (151 * e1**3 / 96) * math.sin(6 * mu)
        + (1097 * e1**4 / 512) * math.sin(8 * mu)
    )
    sin1, cos1, tan1 = math.sin(phi1), math.cos(phi1), math.tan(phi1)
    n1 = a / math.sqrt(1 - e2 * sin1**2)
    t1 = tan1**2
    c1 = ep2 * cos1**2
    r1 = a * (1 - e2) / (1 - e2 * sin1**2) ** 1.5
    d = x / (n1 * k0)
    lat = phi1 - (n1 * tan1 / r1) * (
        d**2 / 2
        - (5 + 3 * t1 + 10 * c1 - 4 * c1**2 - 9 * ep2) * d**4 / 24
        + (61 + 90 * t1 + 298 * c1 + 45 * t1**2 - 252 * ep2 - 3 * c1**2) * d**6 / 720
    )
    lon = (
        d
        - (1 + 2 * t1 + c1) * d**3 / 6
        + (5 - 2 * c1 + 28 * t1 - 3 * c1**2 + 8 * ep2 + 24 * t1**2) * d**5 / 120
    ) / cos1
    return math.degrees(lat), 9.0 + math.degrees(lon)


def read_dbf(data):
    """Rows of a dBase file, as dicts of text. Only what a Shapefile needs."""
    count, header, record = struct.unpack("<4xIHH", data[:12])
    fields, pos = [], 32
    while data[pos] != 0x0D:
        name = data[pos:pos + 11].split(b"\0")[0].decode("ascii")
        fields.append((name, data[pos + 16]))
        pos += 32
    rows = []
    for i in range(count):
        raw = data[header + i * record: header + (i + 1) * record]
        if raw[:1] == b"*":  # deleted record
            continue
        row, offset = {}, 1
        for name, length in fields:
            row[name] = raw[offset:offset + length].decode("utf8", "replace").strip()
            offset += length
        rows.append(row)
    return rows


def from_piemonte(_):
    body = fetch(
        "https://www.datigeo-piem-download.it/direct/Geoportale/RegionePiemonte/"
        "Commercio/Manifestazioni_fieristiche.zip"
    )
    archive = zipfile.ZipFile(io.BytesIO(body))
    name = next(n for n in archive.namelist() if n.lower().endswith(".dbf"))
    comuni = {comune_key(c["name"]): c for c in load_comuni().values()}
    output = []
    for row in read_dbf(archive.read(name)):
        try:
            lat, lon = utm32_to_wgs84(float(row["x"]), float(row["y"]))
        except ValueError:
            comune = comuni.get(comune_key(row["com_min"]))
            if comune is None:
                continue
            lat, lon = comune["lat"], comune["lon"]
        kind = row["tipo_manif"]
        category = (
            "sagra"
            if kind == "Sagra"
            else category_from_words(
                row["denominaz"],
                default="mercatino" if kind == "Fiera Commerciale" else "festa",
            )
        )
        # "il 19/04/2026 ; il 26/04/2026" or "dal 15/11/2026 al 17/11/2026":
        # one event per part.
        for n, part in enumerate(row["data_event"].split(";")):
            dates = re.findall(r"\d\d/\d\d/\d{4}", part)
            if not dates:
                continue
            output.append(
                event(
                    "piemonte",
                    f"{row['codice_man'] or row['id']}-{n}",
                    " ".join(row["denominaz"].split()),
                    category,
                    iso(dates[0]),
                    iso(dates[-1]),
                    lat,
                    lon,
                    row["luogo_svol"].title() or row["com_min"],
                    web_url(
                        row["url_organ"]
                        if row["url_organ"].startswith("http")
                        else f"https://{row['url_organ']}" if row["url_organ"] else None
                    ),
                )
            )
    return output


def from_alto_adige(today):
    """Tourism events of South Tyrol. Many are courses or talks: only the
    festive ones, recognised by their title, are kept."""
    comuni = {comune_key(c["name"]): c for c in load_comuni().values()}
    horizon = (datetime.date.fromisoformat(today) + datetime.timedelta(days=HORIZON_DAYS)).isoformat()
    output, page, pages = [], 1, 1
    while page <= pages:
        result = json.loads(
            fetch(
                "https://tourism.api.opendatahub.com/v1/Event?"
                + urllib.parse.urlencode({
                    "pagesize": 200,
                    "pagenumber": page,
                    "begindate": today,
                    "enddate": horizon,
                    "active": "true",
                    "removenullvalues": "true",
                    "language": "it",
                })
            )
        )
        pages = result.get("TotalPages") or 1
        page += 1
        time.sleep(1)  # the anonymous quota is small
        for item in result.get("Items") or []:
            licence = item.get("LicenseInfo") or {}
            if licence.get("ClosedData") or licence.get("License") != "CC0":
                continue
            detail = item.get("Detail") or {}
            title = next(
                (detail[lang]["Title"] for lang in ("it", "de", "en")
                 if (detail.get(lang) or {}).get("Title")),
                None,
            )
            category = category_from_words(title) if title else None
            if category is None:
                continue
            lat, lon = item.get("Latitude") or 0, item.get("Longitude") or 0
            town = (((item.get("LocationInfo") or {}).get("MunicipalityInfo") or {})
                    .get("Name") or {}).get("it") or ""
            if not lat or not lon:
                comune = comuni.get(comune_key(town))
                if comune is None:
                    continue
                lat, lon = comune["lat"], comune["lon"]
            contact = (item.get("ContactInfos") or {}).get("it") or {}
            output.append(
                event(
                    "alto_adige",
                    item["Id"],
                    " ".join(title.split()),
                    category,
                    iso(item.get("DateBegin")),
                    iso(item.get("DateEnd")),
                    lat,
                    lon,
                    town,
                    web_url(contact.get("Url")),
                )
            )
    return output


PUGLIA_TYPES = {
    "Sagra": "sagra",
    "Degustazione": "sagra",
    "Festa patronale/Festa dei santi": "festa",
    "Festa/Serata": "festa",
    "Festival": "festa",
    "Rievocazione storica": "festa",
    "Concerto": "musica",
    "Manifestazione musicale (Concerto di musica)": "musica",
    "Spettacolo teatrale": "cultura",
    "Spettacolo di danza": "cultura",
    "Mostra": "cultura",
}


def from_puglia(_):
    """Events and activities of the regional tourism board. Tours, guided
    visits and courses are left out: they are not something on that day."""
    body = fetch(
        "https://osservatorio.dms.puglia.it/opendata/puglia_eventi_attivita/eventi_attivita.json"
    )
    output = []
    for row in json.loads(body)["data"]:
        kind = row.get("tipologia") or ""
        category = PUGLIA_TYPES.get(kind) or category_from_words(kind)
        if category is None or not row.get("latitudine") or not row.get("longitudine"):
            continue
        site = (row.get("sito") or "").strip()
        output.append(
            event(
                "puglia",
                row["id_periodo"],
                " ".join((row.get("nm_evento_it") or "").split()),
                category,
                iso(row.get("data_inizio")),
                iso(row.get("data_fine")),
                row["latitudine"],
                row["longitudine"],
                row.get("nome_location") or row.get("comune") or "",
                web_url(site if site.startswith("http") else f"https://{site}" if site else None),
            )
        )
    return output


# Categories of eventi.comune.torino.it. Courses and workshops are left out:
# they are not something on that day. "Varie" goes by the words of the title.
TORINO_CATEGORIES = {
    "Mostra": "cultura",
    "Teatro": "cultura",
    "Danza": "cultura",
    "Cinema": "cultura",
    "Lettura": "cultura",
    "Conferenza": "cultura",
    "Musica": "musica",
    "Festival": "festa",
    "Raduno": "festa",
    "Fiera": "mercatino",
    "Sport": "sport",
}
TORINO_SKIPPED = {"Laboratorio", "Formazione"}
TORINO_API = "https://eventi.comune.torino.it/wp-json/wp/v2/"


def torino_place(content):
    """The venue and its comune, from the event page: the venue is the first
    line of the location, the comune ends the address ("corso X, 18 - Torino").
    Some events give only "CAP 10100" as venue: then the address is used."""
    match = re.search(
        r'class="entry-location">(.*?)(?:<br|</span>)', content, re.S
    )
    venue = " ".join(html.unescape(re.sub(r"<[^>]+>", "", match.group(1))).split()) if match else ""
    match = re.search(r'class="entry-address">(.*?)</span>', content, re.S)
    address = " ".join(html.unescape(re.sub(r"<[^>]+>", "", match.group(1))).split()) if match else ""
    town = address.rsplit(" - ", 1)[1].strip() if " - " in address else "Torino"
    if not venue or venue.upper().startswith("CAP"):
        venue = address.rsplit(" - ", 1)[0].strip() if address else town
    return venue, town


def from_torino(today):
    """Events of the Comune di Torino. The site has no open data export: its
    public WordPress API gives the events, with the coordinates only inside
    the page of the event (the map link). Without them, the event goes at
    the centre of its comune."""
    comuni = {comune_key(c["name"]): c for c in load_comuni().values()}
    names = {
        c["id"]: c["name"]
        for c in json.loads(
            fetch(TORINO_API + "event-categories?per_page=100&lang=it&_fields=id,name")
        )
    }
    output, page, pages = [], 1, 1
    while page <= pages:
        request = urllib.request.Request(
            TORINO_API + "events?" + urllib.parse.urlencode({
                "per_page": 100,
                "page": page,
                "lang": "it",
                "_fields": "id,link,title,content,event_start_date,event_end_date,event-categories",
            }),
            headers={"User-Agent": USER_AGENT},
        )
        with urllib.request.urlopen(request, timeout=180) as response:
            pages = int(response.headers.get("X-WP-TotalPages") or 1)
            items = json.loads(response.read())
        page += 1
        time.sleep(1)  # a small municipal site
        for item in items:
            end = iso(item.get("event_end_date")) or iso(item.get("event_start_date"))
            if not end or end < today:
                continue
            kinds = [names.get(i, "") for i in item.get("event-categories") or []]
            if any(k in TORINO_SKIPPED for k in kinds):
                continue
            title = " ".join(html.unescape(re.sub(r"<[^>]+>", "", item["title"]["rendered"])).split())
            category = next((TORINO_CATEGORIES[k] for k in kinds if k in TORINO_CATEGORIES), None)
            if category is None:
                category = category_from_words(title, default="cultura")
            content = item["content"]["rendered"]
            venue, town = torino_place(content)
            match = re.search(r"query=(-?\d+\.\d+),(-?\d+\.\d+)", content)
            if match:
                lat, lon = match.group(1), match.group(2)
            else:
                comune = comuni.get(comune_key(town))
                if comune is None:
                    continue
                lat, lon = comune["lat"], comune["lon"]
            output.append(
                event(
                    "torino",
                    item["id"],
                    title,
                    category,
                    iso(item.get("event_start_date")),
                    end,
                    lat,
                    lon,
                    venue,
                    web_url(item.get("link")),
                )
            )
    return output


# Typologies of the Cuneo agenda. Courses and guided visits are left out, as
# for the other sources: they are not something on that day.
CUNEO_CATEGORIES = {
    "Evento culturale": "cultura",
    "Mostra": "cultura",
    "Spettacolo teatrale": "cultura",
    "Convegno": "cultura",
    "Festival": "festa",
    "Evento Sportivo": "sport",
}


def from_cuneo(_):
    """The agenda of the Comune di Cuneo. Only upcoming events, in one answer.
    No coordinates: the events go at the centre of Cuneo."""
    cuneo = {comune_key(c["name"]): c for c in load_comuni().values()}[comune_key("Cuneo")]
    output = []
    for item in json.loads(fetch("https://www.comune.cuneo.it/wp-json/wp/v2/eventi?per_page=100")):
        title = " ".join(html.unescape(item.get("titolo") or "").split())
        kind = CUNEO_CATEGORIES.get(item.get("tipologia") or "")
        if not title or kind is None:
            continue
        place = " ".join((item.get("luogo") or "").split())
        output.append(
            event(
                "cuneo",
                item["id"],
                title,
                category_from_words(title, default=kind),
                iso(item.get("data_inizio")),
                iso(item.get("data_fine")),
                cuneo["lat"],
                cuneo["lon"],
                "Cuneo" if not place or place.lower() == "luoghi vari" else place,
                web_url((item.get("sorgente") or {}).get("url")),
            )
        )
    return output


# Words in a title that mark a course, a workshop or a routine service of the
# comune, left out: nobody plans a trip for them.
OPENCITY_SKIPPED = re.compile(
    r"\b(laborator|corso|corsi|ginnastica|seminari|sportello|comitato|consiglio comunale"
    r"|assemblea|terza et|mercato (settimanale|alimentare|periodico|contadino|agricolo"
    r"|del (luned|marted|mercoled|gioved|venerd|sabato|domenica)))",
    re.I,
)
# An event repeated on this many separate days is a routine (a weekly
# meeting, a market), not an occasion.
OPENCITY_MAX_REPEATS = 20
# Per comune: the pages read after this many seconds are left out.
OPENCITY_SECONDS = 180
OPENCITY_WORKERS = 4


def opencity_spans(interval):
    """The days of an OpenCity event, as (start, end) spans: the recurrences
    on following days join, so "every day until the 21st" is one event and
    "every Saturday" is one event a week."""
    days = sorted(
        (r["start"][:10], r["end"][:10])
        for r in interval.get("recurrences") or []
    )
    if not days:
        given = interval.get("input") or {}
        days = [(given.get("startDateTime", "")[:10], given.get("endDateTime", "")[:10])]
    spans = []
    for start, end in days:
        if spans:
            last_end = datetime.date.fromisoformat(spans[-1][1])
            if datetime.date.fromisoformat(start) <= last_end + datetime.timedelta(days=1):
                spans[-1] = (spans[-1][0], max(spans[-1][1], end))
                continue
        spans.append((start, end))
    return spans


def opencity_name(value):
    """A name of the API: text, or {"ita-IT": text} in the plain schema."""
    if isinstance(value, dict):
        value = value.get("ita-IT") or next(iter(value.values()), "")
    return " ".join(html.unescape(value or "").split())


def opencity_events(source, base, today):
    """Two schemas exist. The newer one gives the places with coordinates
    (virtual_takes_place_in). The older one gives "geo", often empty, and the
    places only by id: their coordinates are read once per place. Without any,
    the event goes at the centre of the comune."""
    horizon = (datetime.date.fromisoformat(today) + datetime.timedelta(days=HORIZON_DAYS)).isoformat()
    query = f"classes [event] and calendar[time_interval] = [{today},{horizon}] limit 50"
    url = f"{base}/api/opendata/v2/content/search/" + urllib.parse.quote(query)
    centre = {comune_key(c["name"]): c for c in load_comuni().values()}.get(
        comune_key(OPENCITY[source][0])
    )
    places = {}

    def place(ref):
        """(name, lat, lon) of a place given by id, read once."""
        item = str(ref.get("id"))
        if item not in places:
            try:
                data = json.loads(fetch(f"{base}/api/opendata/v2/content/read/{item}", timeout=20, attempts=2))
                address = ((data.get("data") or {}).get("ita-IT") or {}).get("has_address") or {}
                places[item] = (address.get("latitude") or 0, address.get("longitude") or 0)
                time.sleep(0.5)
            except Exception:
                places[item] = (0, 0)
        return places[item]

    output = []
    deadline = time.monotonic() + OPENCITY_SECONDS
    while url:
        if time.monotonic() > deadline:
            log(f"  opencity: {OPENCITY[source][0]} too slow, later pages left out")
            break
        # Short: one slow comune among many must not hold up the weekly run.
        result = json.loads(fetch(url, timeout=30, attempts=2))
        time.sleep(1)  # the sites share the servers of OpenContent
        url = (result.get("nextPageQuery") or "").replace("http://", "https://")
        for hit in result.get("searchHits") or []:
            data = (hit.get("data") or {}).get("ita-IT") or {}
            title = opencity_name(data.get("event_title"))
            if not title or OPENCITY_SKIPPED.search(title):
                continue
            located = [
                p for p in data.get("virtual_takes_place_in") or []
                if p.get("latitude") and p.get("longitude")
            ]
            refs = data.get("takes_place_in") or []
            geo = data.get("geo") or {}
            if located:
                name, lat, lon = located[0].get("name"), located[0]["latitude"], located[0]["longitude"]
            elif geo.get("latitude") and geo.get("longitude"):
                name = opencity_name(refs[0].get("name")) if refs else ""
                lat, lon = geo["latitude"], geo["longitude"]
            elif refs and all(place(refs[0])):
                name = opencity_name(refs[0].get("name"))
                lat, lon = place(refs[0])
            elif centre is not None:
                name = opencity_name(refs[0].get("name")) if refs else centre["name"]
                lat, lon = centre["lat"], centre["lon"]
            else:
                continue
            kinds = " ".join(
                t.get("name", "") if isinstance(t, dict) else str(t)
                for t in data.get("virtual_has_public_event_typology")
                or data.get("has_public_event_typology")
                or []
            )
            category = category_from_words(
                title,
                kinds,
                default="sport" if "sportivo" in kinds
                else "mercatino" if "commerciale" in kinds
                else "festa" if kinds == "Evento sociale"
                else "cultura",
            )
            spans = opencity_spans(data.get("time_interval") or {})
            if "mostra" in title.lower() and spans:
                # An exhibition open on some days: one event, first to last day.
                spans = [(spans[0][0], spans[-1][1])]
            if len(spans) >= OPENCITY_MAX_REPEATS:
                continue
            item = hit["metadata"]["id"]
            for n, (start, end) in enumerate(spans):
                output.append(
                    event(
                        source,
                        f"{item}-{n}",
                        title,
                        category,
                        iso(start),
                        iso(end),
                        lat,
                        lon,
                        opencity_name(name) or OPENCITY[source][0],
                        f"{base}/openpa/object/{item}",
                    )
                )
    return output


def from_opencity(today):
    """All the comuni of OPENCITY. One comune that fails is logged and left
    out, so many small sites cannot stop the run; the run stops only when no
    comune answers."""
    load_comuni()  # downloaded once, before the threads read it

    def read(source, name, base):
        try:
            events = opencity_events(source, base, today)
        except Exception as e:
            log(f"  opencity: {name} failed ({e})")
            return []
        log(f"  opencity: {name} {len(events)}")
        return events

    # A few comuni at a time: they are on different sites, but some share the
    # servers of OpenContent, which answer 429 to many requests together.
    with concurrent.futures.ThreadPoolExecutor(max_workers=OPENCITY_WORKERS) as pool:
        futures = [pool.submit(read, s, n, b) for s, (n, b) in OPENCITY.items()]
        return [e for f in futures for e in f.result()]


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
        "lombardia_fiere": from_lombardia_fiere,
        "piemonte": from_piemonte,
        "alto_adige": from_alto_adige,
        "puglia": from_puglia,
        "torino": from_torino,
        "cuneo": from_cuneo,
        "opencity": from_opencity,
    }
    events = []
    seen = set()
    for name, reader in readers.items():
        started = time.monotonic()
        rows = reader(today_iso)
        log(f"{name}: {len(rows)} rows in {time.monotonic() - started:.0f} s")
        # A source that answers but gives nothing has changed, not emptied:
        # stop, so the published file keeps its events.
        if not rows:
            raise SystemExit(f"{name}: 0 events read, events.json not written")
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
        {
            # Date and time, UTC: two files of the same day stay ordered.
            "generatedAt": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "sources": SOURCES,
            "events": events,
        },
    )
    log(f"events: {len(events)}, {os.path.getsize(OUTPUT) / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
