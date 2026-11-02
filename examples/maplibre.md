# Using the border with MapLibre

For an OpenStreetMap-based vector basemap (Protomaps, OpenMapTiles). Three
steps: hide the basemap's own lines, hide its labels over Indian land, add
this border. The layer names below are Protomaps'. Other schemas use other
names, so adapt them.

OpenStreetMap draws borders by who controls the ground. Left alone, a basemap
shows the LoC and LAC, and it shows Pakistan's and China's names over land
that India's map has in India.

## 1. Hide the basemap's own border lines

Drop the country layer (`boundaries_country`). Filter every other layer on the
`boundaries` source layer:

```js
const HIDDEN_BORDER_KINDS = [
  'country', 'disputed', 'indefinite', 'line_of_control', 'lac',
  'unrecognized_country',
];

const osmLines = [
  ['!', ['in', ['get', 'kind'], ['literal', HIDDEN_BORDER_KINDS]]],
  ['!=', ['get', 'disputed'], true],
  ['!', ['has', 'brk_a3']], // Natural Earth lines at low zoom
  // Nothing that touches what India claims and doesn't hold. OUTSIDE_CLAIMED
  // is the world with the zones.claimed outlines cut out (see below).
  ['within', OUTSIDE_CLAIMED],
  // J&K and Ladakh state lines come from this repo, not from OSM.
  ['any',
    ['>', ['to-number', ['get', 'kind_detail'], 0], 4],
    ['!', ['within', zones.north]]],
];
// layer.filter = ['all', ...(layer.filter ? [layer.filter] : []), ...osmLines]
```

`zones` is `data/india-zones.json`. Build `OUTSIDE_CLAIMED` as a polygon: a
world ring first, then the first ring of each `zones.claimed` polygon as a
hole:

```js
const WORLD = [[-180, -85], [180, -85], [180, 85], [-180, 85], [-180, -85]];
const OUTSIDE_CLAIMED = {
  type: 'Polygon',
  coordinates: [WORLD, ...zones.claimed.coordinates.map((p) => p[0])],
};
```

MapLibre will not mix the older filter syntax with expressions such as
`within`. If your layer uses the old syntax, convert it to an expression first.

## 2. Hide labels

Hide these names in every label layer (check `name:en`, `name`, `name2`,
`name3`):

```js
const HIDDEN_NAMES = [
  'Gilgit-Baltistan', 'Gilgit Baltistan', 'Northern Areas', 'Azad Kashmir',
  'Azad Jammu and Kashmir', 'Azad Jammu & Kashmir', 'Aksai Chin',
  'Trans-Karakoram Tract', 'South Tibet', 'Southern Tibet', 'Zangnan', '藏南',
  'گلگت بلتستان', 'آزاد کشمیر', 'آزاد جموں و کشمیر', '阿克赛钦',
];
// filter: ['!', ['in', ['coalesce', ['get', 'name:en'], ''], ['literal', HIDDEN_NAMES]]]
```

Then three layer rules:

- `places_country`: show only India's own label inside India's outline:
  `['any', ['==', ['get', 'wikidata'], 'Q668'], ['!', ['within', zones.outline]]]`
- `places_region`: `['within', OUTSIDE_CLAIMED]`.
- Road labels and shields: `['!', ['within', zones.claimed]]`.

Towns keep their names. Gilgit, Muzaffarabad and Skardu are places.

## 3. Add the border

```js
sources: {
  india: {
    type: 'geojson',
    data: '/india-20261102.geojson',
    attribution: '© OpenStreetMap contributors',
  },
},
layers: [
  // Put these where the basemap's own boundary layers were.
  { id: 'india_states', type: 'line', source: 'india',
    filter: ['==', ['get', 'kind'], 'state'],
    paint: { 'line-color': '#999', 'line-width': 0.8, 'line-dasharray': [3, 2] } },
  { id: 'india_border', type: 'line', source: 'india',
    filter: ['==', ['get', 'kind'], 'india'],
    paint: { 'line-color': '#666', 'line-width': 1.2 } },
]
```

The `india` line is the land border only, from Sir Creek to the Sundarbans.
Coasts come from the basemap. The `state` lines are J&K's and Ladakh's own.

## Check it

Look at Gilgit, Aksai Chin, Tawang, Longju (28.6 N, 93.4 E) and Kalapani
(30.2 N, 80.9 E) at zoom 6 to 12. No grey LoC or LAC line, no foreign names,
one border line.
