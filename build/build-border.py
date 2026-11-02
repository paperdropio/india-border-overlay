#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["shapely==2.2.0"]
# ///
"""India's border, as India's official maps draw it.

OpenStreetMap draws borders by control on the ground, so its lines follow the
Line of Control and the LAC. This builds India's outline the way the Survey of
India's map does, from OpenStreetMap's own relations: India (as controlled)
plus the areas India claims and doesn't control (Azad Kashmir, Gilgit-Baltistan,
Aksai Chin, the Trans-Karakoram Tract, Demchok's eastern sector) and the small
disputed areas India holds. Jammu and Kashmir and Ladakh are put together as
India's 2019 map has them: Ladakh takes Gilgit-Baltistan, Aksai Chin and the
Trans-Karakoram Tract; Jammu and Kashmir takes Azad Kashmir. The list of
relations follows the India Boundary Corrector (github.com/ramSeraph/
india_boundary_corrector, Unlicense), the OSM India community's tool.

    uv run build/build-border.py [--refresh] [YYYYMMDD]

The OSM relations are kept in build/.cache (gitignored) after
the first fetch; --refresh fetches them again. Use it for every new date,
or the file is named for a date its data isn't from.

Writes, into data/:
  india-<YYYYMMDD>.geojson  the lines to draw on a map
  india-zones.json  small outlines (India, the claimed-not-held areas, J&K and
      Ladakh) for hiding a basemap's own lines and labels with MapLibre's
      `within` filter

Data © OpenStreetMap contributors, ODbL: the output is a derived database
under the same licence, credited wherever the map is.

Needs uv (it installs shapely) and the network (the OSM API), unless the
relations are already in build/.cache. Check the output with
`node check/check-border.mjs data/india-<YYYYMMDD>.geojson`.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
import shapely
from shapely import make_valid
from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPolygon,
    Polygon,
    Point,
    mapping,
    shape,
)
from shapely.ops import linemerge, polygonize_full, unary_union

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA = ROOT / "data"
CACHE = HERE / ".cache"
OSM_API = "https://api.openstreetmap.org/api/0.6"
AGENT = "india-border-overlay/1 (https://paperdrop.io)"

INDIA = 304716  # India, admin_level 2: the ground India controls
# India's claims it doesn't control (all of them are in India's official map).
CLAIMED = {
    "Azad Kashmir": 3780130,
    "Gilgit-Baltistan": 357995,
    "Aksai Chin": 2713465,
    "Demchok Eastern Sector": 7935425,
    "Trans-Karakoram Tract": 7935380,
    "Chumar-Chepzi": 2713482,
    "North Sikkim finger area": 20438839,
}
# Disputed areas India holds (some are already inside India's relation).
HELD = {
    "Siachen Glacier": 13559521,
    "Shipki La area": 2713485,
    "Nilang-Jadhang": 2713676,
    "Gue-Kaurik": 2713483,
    "Barahoti": 2713484,
}
# Kalapani: India's map runs the line with Nepal down
# the Kali from Kalapani. OSM's line, on ways tagged disputed, bends north
# round a strip north of the Kali by Gunji that India's relation leaves
# out. These are those ways, from Gunji's confluence to where the line
# turns east for Lipulekh; the strip is them closed along the Kali, between
# their two ends.
# India holds Kalapani (Nepal claims it), so the strip is filed as held.
KALAPANI_STRIP_WAYS = [1034908123, 775123555, 1243995206, 1564428938, 1243995205]
# Longju (Arunachal Pradesh is wholly India's): held by
# China since 1959, inside India's map south of the McMahon Line. OSM's
# "Longju area south of McMahon Line" relation is the LAC plus a short
# stretch of the McMahon Line in the east, and stops short of closing. OSM
# has no claim line for the rest, so the ring is closed along Natural
# Earth's India point-of-view line (ne_10m_admin_0_countries_ind, public
# domain, 1:10 million), which meets OSM's stretch within 150 m: from that
# stretch's west end to where it crosses the LAC.
LONGJU = 13548013
LONGJU_CLAIM_LINE = [
    (93.466347, 28.6718601),  # the OSM relation's open end
    (93.4462, 28.6719),
    (93.3554, 28.6241),
    (93.3172, 28.6035),
    (93.3028, 28.5569),
    (93.287, 28.5205),  # south of the LAC: the ring closes where they cross
]
LONGJU_INSIDE = (93.4, 28.6)
JAMMU_AND_KASHMIR = [1943188, CLAIMED["Azad Kashmir"]]
LADAKH = [
    5515045,
    HELD["Siachen Glacier"],
    CLAIMED["Gilgit-Baltistan"],
    CLAIMED["Aksai Chin"],
    CLAIMED["Demchok Eastern Sector"],
    CLAIMED["Trans-Karakoram Tract"],
    CLAIMED["Chumar-Chepzi"],
]

# India's area as built (with the territorial sea, which OSM's relation
# takes in): a build more than 1% off has lost or gained a piece.
OFFICIAL_KM2 = 3_564_000

# The served lines: about 10 m, close to OSM's own lines at street zoom.
LINE_TOLERANCE = 0.0001
# The map style's outlines are tested against at every zoom, so they stay small.
ZONE_TOLERANCE = 0.01


def fetch(url: str) -> bytes:
    last: Exception | None = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": AGENT})
            with urllib.request.urlopen(req, timeout=900) as res:
                return res.read()
        except Exception as error:  # noqa: BLE001 - retried, then raised
            last = error
            time.sleep(10 * 2**attempt)
    raise RuntimeError(f"{url}: {last}")


REFRESH = False  # --refresh: fetch every relation again


def relation(rel_id: int) -> dict:
    """The relation with its ways and nodes, from the OSM API, cached by id."""
    CACHE.mkdir(exist_ok=True)
    path = CACHE / f"{rel_id}.json"
    if REFRESH or not path.exists():
        path.write_bytes(fetch(f"{OSM_API}/relation/{rel_id}/full.json"))
    return json.loads(path.read_text())


def members(rel_id: int, roles: set[str]) -> list[tuple[dict, LineString]]:
    """The relation's ways in those roles: (the way's tags with its "id",
    its line). A way or node missing from the download stops the build: a
    lost piece of border would otherwise go unnoticed."""
    data = relation(rel_id)
    nodes = {e["id"]: (e["lon"], e["lat"]) for e in data["elements"] if e["type"] == "node"}
    ways = {e["id"]: e for e in data["elements"] if e["type"] == "way"}
    rel = next(e for e in data["elements"] if e["type"] == "relation" and e["id"] == rel_id)
    out = []
    for m in rel["members"]:
        if m["type"] != "way" or m.get("role", "") not in roles:
            continue
        if m["ref"] not in ways:
            raise RuntimeError(f"relation {rel_id}: way {m['ref']} missing")
        way = ways[m["ref"]]
        lost = [n for n in way["nodes"] if n not in nodes]
        if lost:
            raise RuntimeError(f"relation {rel_id}: way {way['id']} lacks nodes {lost}")
        pts = [nodes[n] for n in way["nodes"]]
        if len(pts) >= 2:
            out.append(({**way.get("tags", {}), "id": way["id"]}, LineString(pts)))
    return out


def rings(rel_id: int, lines: list[LineString]):
    """The areas a relation's ways enclose. Ways that close no ring (dangles,
    cut edges, invalid rings) stop the build rather than being dropped."""
    polys, cuts, dangles, invalid = polygonize_full(unary_union(lines))
    for name, left in (("dangling", dangles), ("cut", cuts), ("invalid", invalid)):
        if not left.is_empty:
            raise RuntimeError(f"relation {rel_id}: {name} ways at {left.representative_point()}")
    return unary_union(list(polys.geoms))


def area(rel_id: int) -> MultiPolygon | Polygon:
    outer = [line for _, line in members(rel_id, {"outer", ""})]
    inner = [line for _, line in members(rel_id, {"inner"})]
    shell = rings(rel_id, outer)
    if inner:
        shell = shell.difference(rings(rel_id, inner))
    shell = make_valid(shell)
    if shell.is_empty:
        raise RuntimeError(f"relation {rel_id} made no area")
    return shell


def fill_small_holes(geom, max_area: float):
    def fix(p: Polygon) -> Polygon:
        keep = [r for r in p.interiors if Polygon(r).area > max_area]
        return Polygon(p.exterior, keep)

    return unary_union([fix(p) for p in polygons(geom)])


def polygons(geom, min_area: float = 0.0) -> list[Polygon]:
    """Every polygon in a geometry, however deep (make_valid can return a
    collection holding a MultiPolygon)."""
    if isinstance(geom, Polygon):
        return [geom] if geom.area > min_area else []
    if isinstance(geom, (MultiPolygon, GeometryCollection)):
        return [p for g in geom.geoms for p in polygons(g, min_area)]
    return []


def claimed_area(official, india, held):
    """What India claims and doesn't hold. Held areas count as held even
    where India's relation leaves them out (Siachen, Nilang, Barahoti…),
    so OSM's Indian lines and names there stay."""
    held_all = unary_union([india, *held])
    return official.difference(held_all).buffer(-0.001).buffer(0.001)


def check_valid(name: str, geometry: dict) -> None:
    """Rounding can fold a thin outline over itself; stop if it did."""
    if not shape(geometry).is_valid:
        raise RuntimeError(f"the {name} outline isn't valid after rounding")


def kalapani_strip() -> Polygon:
    """The strip north of the Kali by Gunji that India's map has and OSM's
    relation leaves out (KALAPANI_STRIP_WAYS)."""
    ways = {t["id"]: l for t, l in members(INDIA, {"outer", ""})}
    missing = [w for w in KALAPANI_STRIP_WAYS if w not in ways]
    if missing:
        raise RuntimeError(f"Kalapani: ways {missing} are no longer India's border")
    line = linemerge([ways[w] for w in KALAPANI_STRIP_WAYS])
    if not isinstance(line, LineString):
        raise RuntimeError("Kalapani: the ways no longer make one line")
    strip = Polygon(line.coords)
    if not strip.is_valid or not 0.0005 < strip.area < 0.003:
        raise RuntimeError(f"Kalapani: the strip changed shape ({strip.area:.4f})")
    return strip


def longju() -> Polygon:
    """The Longju area (LONGJU), its ring closed along LONGJU_CLAIM_LINE.
    The LAC's end past the crossing and the line's tail are left over."""
    own = [l for _, l in members(LONGJU, {"outer", ""})]
    faces = polygonize_full(unary_union([*own, LineString(LONGJU_CLAIM_LINE)]))[0]
    found = [p for p in faces.geoms if p.contains(Point(LONGJU_INSIDE))]
    if len(found) != 1 or not 0.005 < found[0].area < 0.025:
        raise RuntimeError("Longju: the area no longer closes as it did")
    return found[0]


def lines_of(geom) -> list[LineString]:
    if geom.is_empty:
        return []
    if isinstance(geom, LineString):
        return [geom]
    if isinstance(geom, MultiLineString):
        return list(geom.geoms)
    if hasattr(geom, "geoms"):
        return [l for g in geom.geoms for l in lines_of(g)]
    return []


def coords(geom, digits: int):
    """GeoJSON geometry with rounded coordinates."""
    def r(c):
        if isinstance(c[0], (int, float)):
            return [round(c[0], digits), round(c[1], digits)]
        return [r(x) for x in c]

    g = mapping(geom)
    return {"type": g["type"], "coordinates": r(g["coordinates"])}


def main() -> None:
    global REFRESH
    args = sys.argv[1:]
    REFRESH = "--refresh" in args
    args = [a for a in args if a != "--refresh"]
    date = args[0] if args else dt.date.today().strftime("%Y%m%d")
    if not (len(date) == 8 and date.isdigit()):
        sys.exit("build-border: the date must be YYYYMMDD")

    india = area(INDIA)
    claimed = {name: area(rid) for name, rid in CLAIMED.items()}
    claimed["Longju"] = longju()
    held = {name: area(rid) for name, rid in HELD.items()}
    held["Kalapani strip"] = kalapani_strip()
    official = fill_small_holes(
        make_valid(unary_union([india, *claimed.values(), *held.values()])), 0.01
    )
    # A lost relation member or ring shows here (sinusoidal, equal-area).
    km2 = shapely.transform(
        official,
        lambda c: np.column_stack(
            (c[:, 0] * 111.32 * np.cos(np.radians(c[:, 1])), c[:, 1] * 110.57)
        ),
    ).area
    if abs(km2 - OFFICIAL_KM2) > OFFICIAL_KM2 / 100:
        raise RuntimeError(f"India's area is {km2:,.0f} km², not about {OFFICIAL_KM2:,}")
    jk = fill_small_holes(
        make_valid(unary_union([area(r) for r in JAMMU_AND_KASHMIR])), 0.01
    )
    # Slivers between relations that don't share a way exactly (J&K's
    # relation and Gilgit-Baltistan's run side by side along the LoC at
    # Gurez) are filled, then Ladakh is the rest of the north: J&K and
    # Ladakh share their edge exactly, so its line has no gaps.
    north = fill_small_holes(
        make_valid(unary_union([jk, *[area(r) for r in LADAKH]])), 0.01
    )
    ladakh = make_valid(north.difference(jk))

    # India's border: the outline without its sea edges (OSM's admin
    # boundary runs 12 nautical miles out; the map draws coasts already).
    sea = unary_union(
        [l for tags, l in members(INDIA, {"outer", "inner", ""})
         if tags.get("maritime") == "yes"]
    ).buffer(1e-6)
    border = linemerge(lines_of(official.boundary.difference(sea)))
    border = border.simplify(LINE_TOLERANCE, preserve_topology=False)

    # J&K and Ladakh's own lines (with each other and with Himachal Pradesh
    # and Punjab), as India's map has them; India's border is drawn above.
    # The edge is taken about 20 m wide: J&K's relation and India's don't
    # always share their ways, and India's border is drawn there anyway.
    # Short leftovers go only after the merge, so a line made of short
    # pieces stays whole.
    edge = official.boundary.buffer(2e-4)
    states = unary_union([jk.boundary, ladakh.boundary]).difference(edge)
    states = MultiLineString(
        [l for l in lines_of(linemerge(lines_of(states))) if l.length > 0.001]
    )
    states = states.simplify(LINE_TOLERANCE, preserve_topology=False)

    osm_base = max(
        e.get("timestamp", "") for e in relation(INDIA)["elements"]
    )
    served = {
        "type": "FeatureCollection",
        "name": f"india-{date}",
        "attribution": "© OpenStreetMap contributors (ODbL)",
        "osm_base": osm_base,
        "features": [
            {"type": "Feature", "properties": {"kind": "india"},
             "geometry": coords(border, 4)},
            {"type": "Feature", "properties": {"kind": "state"},
             "geometry": coords(states, 4)},
        ],
    }
    DATA.mkdir(exist_ok=True)
    out = DATA / f"india-{date}.geojson"
    out.write_text(json.dumps(served, separators=(",", ":")) + "\n")

    # The outlines a map style tests against (small: MapLibre's `within`
    # tests them for every label and line it lays out).
    # - outline: India as its official map shows it (country labels hide in it).
    # - claimed: what India claims and doesn't hold, shrunk by 600 m so
    #   Indian lines that end on the LoC or LAC don't touch it. OSM's lines
    #   that touch it hide, and so do region labels in it. Simplifying
    #   (400 m) and rounding (to 0.001°) eat into that: at worst about
    #   150 m is left.
    # - north: J&K and Ladakh grown by 1 km, so OSM's own state lines along
    #   their edges fall in it; the map draws J&K and Ladakh's lines. After
    #   simplifying and rounding, at least about 500 m.
    # - core: J&K and Ladakh shrunk by about 3 km, for checking a basemap only.
    claimed_only = claimed_area(official, india, held.values())
    zone = lambda g, tol, min_area: coords(  # noqa: E731
        MultiPolygon(polygons(g.simplify(tol), min_area)), 3
    )
    zones = {
        "version": f"india-{date}",
        "attribution": "© OpenStreetMap contributors (ODbL)",
        "outline": zone(official, 0.02, 0.002),
        "claimed": zone(claimed_only.buffer(-0.006), 0.004, 0.001),
        "north": zone(north.buffer(0.01), 0.005, 0.001),
        "core": zone(north.buffer(-0.03), 0.01, 0.001),
    }
    for name in ("outline", "claimed", "north", "core"):
        check_valid(name, zones[name])
    zones_path = DATA / "india-zones.json"
    zones_path.write_text(json.dumps(zones, separators=(",", ":")) + "\n")

    print(f"OSM data as of {osm_base}")
    print(f"{out.relative_to(ROOT)}: {out.stat().st_size // 1024} KB")
    print(f"{zones_path.relative_to(ROOT)}: {zones_path.stat().st_size // 1024} KB")
    print(
        "outline polygons:", len(zones["outline"]["coordinates"]),
        "claimed polygons:", len(zones["claimed"]["coordinates"]),
        "north polygons:", len(zones["north"]["coordinates"]),
        "points:", sum(len(r) for k in ("outline", "claimed", "north")
                       for poly in zones[k]["coordinates"] for r in poly),
    )


if __name__ == "__main__":
    main()
