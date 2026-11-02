# india-border-overlay

India's border as India's official map draws it, as GeoJSON, with the code
that builds it and a script that checks it.

OpenStreetMap draws borders by who controls the ground. So its lines follow
the Line of Control and the Line of Actual Control. A map for users in India
needs the border as the Survey of India draws it. This repository has that
border, built from OpenStreetMap's own data.

**Not an official map.** This is not a substitute for the Survey of India's
map, and Paperdrop Corp does not speak for any government. Check it against
the Survey of India's map before you rely on it.

## Who it is for

Developers who put a map in front of users in India and need it to match
India's official map. It works with MapLibre over any OpenStreetMap-based
vector basemap.

## What it draws

- All of Jammu and Kashmir and Ladakh, including Gilgit-Baltistan, Pakistan-
  administered Kashmir (PoK), Aksai Chin and the Shaksgam valley.
- All of Arunachal Pradesh, including Longju.
- Kalapani, with the line with Nepal running down the Kali.
- J&K's and Ladakh's own state lines, as India's 2019 map has them.

The land border runs from Sir Creek to the Sundarbans. Coasts are left to
your basemap.

## What is in it

| Path | What |
| --- | --- |
| `data/india-20261102.geojson` | The lines to draw. Feature `kind` is `india` (land border) or `state` (J&K and Ladakh lines). |
| `data/india-zones.json` | Small outlines to hide a basemap's own lines and labels: `outline` (India), `claimed` (claimed, not held), `north` (J&K and Ladakh), `core`. |
| `build/build-border.py` | Builds both files from OpenStreetMap relations. |
| `build/test_build_border.py` | Tests for the builder. No network. |
| `check/check-border.mjs` | Checks a built border against named places. No dependencies. |
| `check/places.json` | The place list. |
| `examples/maplibre.md` | How to use it in a MapLibre style. |

## How to use it

Serve `data/india-20261102.geojson`, add it to your style as a line layer,
and hide the basemap's own disputed lines and country labels over Indian
land. See [examples/maplibre.md](examples/maplibre.md).

## How to rebuild

You need [uv](https://docs.astral.sh/uv/) and the network (the OpenStreetMap
API). Relations are cached in `build/.cache`.

```sh
uv run build/build-border.py --refresh 20261102
```

The date in the name is the date of the data. Use `--refresh` for each new
date. The builder stops if a way, a node or a ring is missing, or if India's
area is more than 1% off. A lost piece of border should not go unnoticed.

The corrections are written in the comments of `build/build-border.py` with
the reason for each: the areas India claims and does not hold, the held
disputed areas, the Kalapani strip, and the closing of the Longju ring.

## How to check

```sh
node check/check-border.mjs data/india-20261102.geojson
```

It tests that places such as Gilgit, Muzaffarabad, Aksai Chin, Shaksgam,
Tawang, Kalapani and Longju are inside India, and that Lahore, Kathmandu,
Lhasa, Dhaka and Colombo are outside. It exits with a non-zero status and a
message on any failure. Run the builder's tests with:

```sh
uv run --with pytest --with shapely==2.2.0 pytest build/
```

## Licence

- **Code** (everything outside `data/`): MIT. See [LICENSE](LICENSE).
- **Data** (`data/`): a derived database of OpenStreetMap, under the
  [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/). Credit
  "© OpenStreetMap contributors" wherever you show a map made with it. See
  [data/LICENSE](data/LICENSE).

## Credits

- © OpenStreetMap contributors, ODbL. All lines come from OpenStreetMap
  relations.
- The list of relations follows the
  [India Boundary Corrector](https://github.com/ramSeraph/india_boundary_corrector)
  by ramSeraph (Unlicense).
- [Natural Earth](https://www.naturalearthdata.com/) (public domain): the
  builder closes the Longju ring along its India point-of-view line.

Built by [Paperdrop Corp](https://paperdrop.io) for
[Twinden](https://twinden.com).
