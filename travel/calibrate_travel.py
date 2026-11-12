#!/usr/bin/env python3
"""Calibrates the offline travel estimate of the app on real road routes.

Runs OSRM on this computer, in Docker, on the OpenStreetMap extract of Italy:
no public routing server is used, so the volume of requests is ours to
choose. From thousands of trips between comuni and the places of the
catalogue it measures, per distance band, kind of destination and region,
how much longer the road is than the straight line and how fast it is driven.
The result is lib/domain/usecases/travel_model.dart, a table of constants:
the app computes its estimate without any network.

    python tool/calibrate_travel.py prepare   # once: ~1 hour, ~10 GB
    python tool/calibrate_travel.py serve     # starts OSRM on port 5000
    python tool/calibrate_travel.py sample    # asks OSRM for the routes
    python tool/calibrate_travel.py fit       # writes travel_model.dart
    python tool/calibrate_travel.py stop

Map data: © OpenStreetMap contributors, ODbL. Durations are OSRM's car
profile, without traffic, like the routes the app shows.
"""
import datetime
import json
import math
import os
import random
import statistics
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "tool", ".routing_cache")
PBF = "italy-latest.osm.pbf"
IMAGE = "ghcr.io/project-osrm/osrm-backend:v5.27.1"
CONTAINER = "gitaserena-osrm"
PORT = 5000
SAMPLES = os.path.join(CACHE, "samples.jsonl")
OUTPUT = os.path.join(ROOT, "lib", "domain", "usecases", "travel_model.dart")

ORIGINS = 2500  # comuni, chosen by population
PER_ORIGIN = 20  # destinations per origin, one table request each
BANDS = [10, 25, 50, 100, 200]  # upper limits of the straight-line bands, km
CONTEXTS = ["mare", "citta", "montagna", "borgo", "lago"]
DART_CONTEXT = {
    "mare": "sea",
    "citta": "city",
    "montagna": "mountain",
    "borgo": "village",
    "lago": "lake",
}


def log(message):
    print(f"{datetime.datetime.now():%H:%M:%S} {message}", flush=True)


def docker(*args):
    volume = f"{os.path.abspath(CACHE)}:/data"
    command = ["docker", "run", "--rm", "-v", volume, IMAGE, *args]
    log(" ".join(command[4:]))
    subprocess.run(command, check=True)


def prepare():
    if not os.path.exists(os.path.join(CACHE, PBF)):
        raise SystemExit(f"download {PBF} from download.geofabrik.de into {CACHE}")
    name = PBF.removesuffix(".osm.pbf")
    if not os.path.exists(os.path.join(CACHE, f"{name}.osrm.cells")):
        docker("osrm-extract", "-p", "/opt/car.lua", f"/data/{PBF}")
        docker("osrm-partition", f"/data/{name}.osrm")
    docker("osrm-customize", f"/data/{name}.osrm")
    log("ready")


def serve():
    name = PBF.removesuffix(".osm.pbf")
    subprocess.run(["docker", "rm", "-f", CONTAINER], capture_output=True)
    subprocess.run(
        [
            "docker", "run", "-d", "--name", CONTAINER, "-p", f"{PORT}:5000",
            "-v", f"{os.path.abspath(CACHE)}:/data", IMAGE,
            "osrm-routed", "--algorithm", "mld", "--max-table-size", "1000",
            f"/data/{name}.osrm",
        ],
        check=True,
    )
    for _ in range(120):
        try:
            urllib.request.urlopen(
                f"http://localhost:{PORT}/route/v1/driving/7.68,45.07;7.77,45.14",
                timeout=5,
            )
            log(f"OSRM ready on port {PORT}")
            return
        except Exception:
            time.sleep(2)
    raise SystemExit("OSRM did not start: docker logs " + CONTAINER)


def stop():
    subprocess.run(["docker", "rm", "-f", CONTAINER], check=False)


def straight_km(a, b):
    """Same formula as GeoUtils.distanceKm in the app."""
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 6371.0 * 2 * math.asin(math.sqrt(h))


def band(km):
    for i, limit in enumerate(BANDS):
        if km < limit:
            return i
    return len(BANDS)


def sample():
    random.seed(42)
    comuni = list(
        json.load(open(os.path.join(CACHE, "..", ".catalog_cache", "comuni.json"),
                       encoding="utf8")).values()
    )
    places = [
        p for p in json.load(open(os.path.join(ROOT, "assets", "data", "places.json"),
                                  encoding="utf8"))
        if p.get("context") in CONTEXTS
    ]
    # Origins as users would start: weighted by population.
    weights = [max(c.get("population") or 0, 300) for c in comuni]
    origins = random.choices(comuni, weights=weights, k=ORIGINS)

    # Places in coarse cells, to find destinations near an origin quickly.
    cells = {}
    for p in places:
        cells.setdefault((int(p["lat"]), int(p["lon"])), []).append(p)

    done = 0
    with open(SAMPLES, "w", encoding="utf8") as out:
        for origin in origins:
            o = (origin["lat"], origin["lon"])
            near = [
                p
                for dy in range(-3, 4)
                for dx in range(-3, 4)
                for p in cells.get((int(o[0]) + dy, int(o[1]) + dx), [])
            ]
            # Every distance band equally, up to 300 km.
            by_band = {}
            for p in near:
                km = straight_km(o, (p["lat"], p["lon"]))
                if 2 <= km <= 300:
                    by_band.setdefault(band(km), []).append((p, km))
            chosen = []
            for _ in range(PER_ORIGIN):
                if not by_band:
                    break
                b = random.choice(list(by_band))
                chosen.append(random.choice(by_band[b]))
            if not chosen:
                continue
            coords = ";".join(
                [f"{o[1]},{o[0]}"] + [f"{p['lon']},{p['lat']}" for p, _ in chosen]
            )
            url = (
                f"http://localhost:{PORT}/table/v1/driving/{coords}"
                f"?sources=0&annotations=duration,distance"
            )
            answer = json.load(urllib.request.urlopen(url, timeout=60))
            if answer.get("code") != "Ok":
                continue
            for (p, km), seconds, metres in zip(
                chosen, answer["durations"][0][1:], answer["distances"][0][1:]
            ):
                if seconds is None or metres is None or metres <= 0:
                    continue
                out.write(json.dumps({
                    "straight": round(km, 3),
                    "road": round(metres / 1000, 3),
                    "minutes": round(seconds / 60, 2),
                    "context": p["context"],
                    "region": p.get("region") or "",
                }) + "\n")
            done += 1
            if done % 250 == 0:
                log(f"sample: {done}/{ORIGINS} origins")
    log(f"sample: {done} origins written to {SAMPLES}")


def fit():
    rows = [json.loads(line) for line in open(SAMPLES, encoding="utf8")]
    random.seed(7)
    random.shuffle(rows)
    test, train = rows[: len(rows) // 5], rows[len(rows) // 5:]
    log(f"fit: {len(train)} routes to fit, {len(test)} to check")

    def table(key):
        """Median of key(row) per (band, context), falling back to the band."""
        per_band = {}
        per_cell = {}
        for r in train:
            b = band(r["straight"])
            per_band.setdefault(b, []).append(key(r))
            per_cell.setdefault((b, r["context"]), []).append(key(r))
        result = {}
        for c in CONTEXTS:
            result[c] = []
            for b in range(len(BANDS) + 1):
                values = per_cell.get((b, c), [])
                if len(values) < 30:
                    values = per_band[b]
                result[c].append(round(statistics.median(values), 3))
        return result

    road_factor = table(lambda r: r["road"] / r["straight"])
    minutes_per_km = table(lambda r: r["minutes"] / r["straight"])

    # What is left per region, after the table: mountains, coasts, islands.
    def per_region(table_values, value):
        by_region = {}
        for r in train:
            expected = r["straight"] * table_values[r["context"]][band(r["straight"])]
            by_region.setdefault(r["region"], []).append(value(r) / expected)
        return {
            region: round(statistics.median(values), 3)
            for region, values in sorted(by_region.items())
            if region and len(values) >= 100
        }

    region_factor = per_region(minutes_per_km, lambda r: r["minutes"])
    region_road_factor = per_region(road_factor, lambda r: r["road"])

    def estimate(r):
        b = band(r["straight"])
        k = region_factor.get(r["region"], 1.0)
        return (
            r["straight"] * road_factor[r["context"]][b]
            * region_road_factor.get(r["region"], 1.0),
            r["straight"] * minutes_per_km[r["context"]][b] * k,
        )

    def old_estimate(r):
        """TravelEstimator before the calibration, for comparison."""
        road = r["straight"] * 1.3
        speed = 42 if road < 25 else 58 if road < 70 else 72 if road < 150 else 80
        speed *= {"montagna": 0.85, "citta": 0.9, "lago": 0.92}.get(r["context"], 1)
        return road, road / speed * 60 + 8

    def errors(model):
        km, minutes = [], []
        for r in test:
            road, mins = model(r)
            km.append(abs(road - r["road"]) / r["road"])
            minutes.append(abs(mins - r["minutes"]) / r["minutes"])
        km.sort()
        minutes.sort()
        pick = lambda v, q: round(100 * v[int(len(v) * q)], 1)
        return {
            "km_median_%": pick(km, 0.5),
            "km_p90_%": pick(km, 0.9),
            "minutes_median_%": pick(minutes, 0.5),
            "minutes_p90_%": pick(minutes, 0.9),
        }

    before, after = errors(old_estimate), errors(estimate)
    log(f"error before: {before}")
    log(f"error after:  {after}")

    def dart_table(values):
        lines = []
        for c in CONTEXTS:
            numbers = ", ".join(str(v) for v in values[c])
            lines.append(f"    PlaceContext.{DART_CONTEXT[c]}: [{numbers}],")
        return "\n".join(lines)

    def dart_map(values):
        # Double quotes: "Valle d'Aosta" has an apostrophe.
        return "\n".join(f'    "{k}": {v},' for k, v in values.items())

    regions = dart_map(region_factor)
    road_regions = dart_map(region_road_factor)
    today = datetime.date.today().isoformat()
    open(OUTPUT, "w", encoding="utf8", newline="\n").write(f"""// Generated by tool/calibrate_travel.py on {today}: do not edit by hand.
// From {len(rows)} car routes computed with OSRM on OpenStreetMap data
// (© OpenStreetMap contributors, ODbL), without traffic.
// Error on {len(test)} routes not used to fit, as a share of the real value:
// km median {after['km_median_%']} %, 90th percentile {after['km_p90_%']} %;
// minutes median {after['minutes_median_%']} %, 90th percentile {after['minutes_p90_%']} %.
// Before the calibration: km median {before['km_median_%']} %, minutes median {before['minutes_median_%']} %.

import '../entities/entities.dart';

/// Road distance and driving time from the straight-line distance, measured
/// on real routes. Bands of straight-line km: below {', '.join(str(b) for b in BANDS)}, and above.
class TravelModel {{
  const TravelModel._();

  static const bandLimitsKm = <double>[{', '.join(str(float(b)) for b in BANDS)}];

  /// Road km per straight-line km.
  static const roadFactor = <PlaceContext, List<double>>{{
{dart_table(road_factor)}
  }};

  /// Driving minutes per straight-line km.
  static const minutesPerKm = <PlaceContext, List<double>>{{
{dart_table(minutes_per_km)}
  }};

  /// Correction of the minutes by region of the destination.
  static const regionFactor = <String, double>{{
{regions}
  }};

  /// Correction of the road km by region of the destination.
  static const regionRoadFactor = <String, double>{{
{road_regions}
  }};

  static int band(double straightKm) {{
    for (var i = 0; i < bandLimitsKm.length; i++) {{
      if (straightKm < bandLimitsKm[i]) return i;
    }}
    return bandLimitsKm.length;
  }}
}}
""")
    log(f"fit: wrote {OUTPUT}")


STAGES = {"prepare": prepare, "serve": serve, "sample": sample, "fit": fit, "stop": stop}

if __name__ == "__main__":
    os.makedirs(CACHE, exist_ok=True)
    for stage in sys.argv[1:] or ["prepare", "serve", "sample", "fit", "stop"]:
        STAGES[stage]()
