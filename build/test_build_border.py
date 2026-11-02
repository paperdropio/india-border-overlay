# /// script
# requires-python = ">=3.10"
# dependencies = ["shapely==2.2.0", "pytest==8.3.3"]
# ///
"""Tests for build-border.py's guards: a lost piece of OSM data
stops the build instead of quietly leaving a hole in India's border.

    uv run --with pytest --with shapely==2.2.0 pytest build/

No network: the relations are written to a temporary cache.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from shapely.geometry import GeometryCollection, MultiPolygon, Point, Polygon

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("build_border", HERE / "build-border.py")
bb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bb)


def square_relation(rel_id: int, drop_way: bool = False, drop_node: bool = False,
                    open_ring: bool = False) -> dict:
    """A unit square drawn by two ways, as the OSM API returns it."""
    nodes = [
        {"type": "node", "id": i, "lon": x, "lat": y}
        for i, (x, y) in enumerate([(0, 0), (1, 0), (1, 1), (0, 1)], 1)
    ]
    if drop_node:
        nodes = nodes[:-1]
    ways = [
        {"type": "way", "id": 10, "nodes": [1, 2, 3]},
        {"type": "way", "id": 11, "nodes": [3, 4] if open_ring else [3, 4, 1]},
    ]
    if drop_way:
        ways = ways[:1]
    rel = {
        "type": "relation",
        "id": rel_id,
        "members": [
            {"type": "way", "ref": 10, "role": "outer"},
            {"type": "way", "ref": 11, "role": "outer"},
        ],
    }
    return {"elements": [*nodes, *ways, rel]}


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(bb, "CACHE", tmp_path)

    def put(rel_id: int, data: dict) -> None:
        (tmp_path / f"{rel_id}.json").write_text(json.dumps(data))

    return put


def test_a_whole_relation_makes_its_area(cache):
    cache(1, square_relation(1))
    assert bb.area(1).area == pytest.approx(1.0)


def test_a_missing_way_stops_the_build(cache):
    cache(1, square_relation(1, drop_way=True))
    with pytest.raises(RuntimeError, match="way 11 missing"):
        bb.area(1)


def test_a_missing_node_stops_the_build(cache):
    cache(1, square_relation(1, drop_node=True))
    with pytest.raises(RuntimeError, match="lacks nodes"):
        bb.area(1)


def test_a_ring_that_does_not_close_stops_the_build(cache):
    cache(1, square_relation(1, open_ring=True))
    with pytest.raises(RuntimeError, match="dangling"):
        bb.area(1)


def test_polygons_inside_a_collection_are_kept():
    a = Polygon([(0, 0), (1, 0), (1, 1)])
    b = Polygon([(2, 0), (3, 0), (3, 1)])
    nested = GeometryCollection([MultiPolygon([a, b]), Point(5, 5)])
    assert len(bb.polygons(nested)) == 2
    assert bb.fill_small_holes(nested, 0.01).area == pytest.approx(1.0)


def test_refresh_fetches_again(cache, monkeypatch):
    cache(1, square_relation(1))
    fetched = []

    def fetch(url: str) -> bytes:
        fetched.append(url)
        return json.dumps(square_relation(1)).encode()

    monkeypatch.setattr(bb, "fetch", fetch)
    bb.relation(1)
    assert fetched == []
    monkeypatch.setattr(bb, "REFRESH", True)
    bb.relation(1)
    assert fetched == [f"{bb.OSM_API}/relation/1/full.json"]


def test_held_areas_outside_indias_relation_are_not_claimed():
    india = Polygon([(0, 0), (4, 0), (4, 4), (0, 4)])
    held = Polygon([(4, 0), (5, 0), (5, 1), (4, 1)])
    claimed = Polygon([(4, 2), (6, 2), (6, 4), (4, 4)])
    official = india.union(held).union(claimed)
    left = bb.claimed_area(official, india, [held])
    assert left.area == pytest.approx(claimed.area, rel=0.01)
    assert not left.contains(Point(4.5, 0.5))


def test_an_outline_folded_by_rounding_stops_the_build():
    bowtie = {"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]]]}
    with pytest.raises(RuntimeError, match="isn't valid"):
        bb.check_valid("claimed", bowtie)
    bb.check_valid("claimed", {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]})


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
