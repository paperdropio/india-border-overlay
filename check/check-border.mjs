#!/usr/bin/env node
// Checks a built border against named places. No dependencies.
//
//   node check/check-border.mjs data/india-20261102.geojson [data/india-zones.json]
//
// 1. The `india` line is the land border only, from Sir Creek round to the
//    Sundarbans. The ring is closed through the sea, south of Sri Lanka, so
//    the whole peninsula is inside (a straight chord would cut India in two).
//    Islands and Sri Lanka are judged by the zones file only ("zonesOnly").
//    Every place in places.json "inside" must be in that ring, every "outside"
//    place out of it.
// 2. If the zones file is given (default: india-zones.json next to the
//    geojson), the same places are tested against its "outline", and the
//    "claimed" places against its "claimed" zone.
// 3. Lines of kind "state" must stay inside the outline.
// Exits 1 with a message for every failure.
import { readFileSync, existsSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const geoPath = process.argv[2];
if (!geoPath) {
  console.error('usage: node check/check-border.mjs <india-YYYYMMDD.geojson> [india-zones.json]');
  process.exit(2);
}
const zonesPath =
  process.argv[3] ?? (existsSync(join(dirname(resolve(geoPath)), 'india-zones.json'))
    ? join(dirname(resolve(geoPath)), 'india-zones.json') : null);
const read = (p) => JSON.parse(readFileSync(p, 'utf8'));
const geo = read(geoPath);
const places = read(join(here, 'places.json'));
const failures = [];
const fail = (m) => failures.push(m);

const rayIn = ([x, y], ring) => {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
};
// A MultiPolygon's coordinates: [polygon][ring][point]; the first ring is the
// outer edge, the others are holes.
const inMulti = (pt, g) => {
  const polys = g.type === 'Polygon' ? [g.coordinates] : g.coordinates;
  return polys.some(([outer, ...holes]) => rayIn(pt, outer) && !holes.some((h) => rayIn(pt, h)));
};

const feature = (kind) => geo.features?.find((f) => f.properties?.kind === kind);
const partsOf = (g) => (g.type === 'LineString' ? [g.coordinates] : g.coordinates);

const india = feature('india');
if (!india) { console.error('FAIL: no feature with kind "india"'); process.exit(1); }
const [land] = partsOf(india.geometry);
const start = land[0];
const end = land[land.length - 1];
if (!(start[0] < 69.5)) fail(`the india line should start at Sir Creek (lon < 69.5), starts at ${start}`);
if (!(end[0] > 88.5)) fail(`the india line should end at the Sundarbans (lon > 88.5), ends at ${end}`);
const ring = [...land, [89.1, 21], [89.1, 4], [67.5, 4], [67.5, 23.5], start];

let n = 0;
const lineOnly = (name) => !places.zonesOnly.includes(name);
for (const [name, pt] of Object.entries(places.inside)) {
  if (!lineOnly(name)) continue;
  n++;
  if (!rayIn(pt, ring)) fail(`${name} ${pt} should be inside India's line, is outside`);
}
for (const [name, pt] of Object.entries(places.outside)) {
  if (!lineOnly(name)) continue;
  n++;
  if (rayIn(pt, ring)) fail(`${name} ${pt} should be outside India's line, is inside`);
}

if (zonesPath) {
  const zones = read(zonesPath);
  for (const [name, pt] of Object.entries(places.inside)) {
    n++;
    if (!inMulti(pt, zones.outline)) fail(`${name} should be inside the zones file's outline`);
  }
  for (const [name, pt] of Object.entries(places.outside)) {
    n++;
    if (inMulti(pt, zones.outline)) fail(`${name} should be outside the zones file's outline`);
  }
  for (const name of places.claimed) {
    n++;
    const pt = places.inside[name];
    if (!pt) { fail(`claimed place ${name} is not in "inside"`); continue; }
    if (!inMulti(pt, zones.claimed)) fail(`${name} should be in the claimed-not-held zone`);
  }
  for (const name of ['Srinagar', 'Leh', 'Tawang', 'Delhi', 'Kalapani / Lipulekh', 'Gunji']) {
    n++;
    if (inMulti(places.inside[name], zones.claimed)) fail(`${name} is held by India, but is in the claimed zone`);
  }
  const states = feature('state');
  if (states) {
    const bad = partsOf(states.geometry).flat().filter((p) => !inMulti(p, zones.outline));
    if (bad.length) fail(`${bad.length} state-line points lie outside India's outline, first at ${bad[0]}`);
  }
} else {
  console.warn('note: no zones file found, skipping the zone checks');
}

if (failures.length) {
  console.error(`FAIL: ${failures.length} problem(s)\n` + failures.map((f) => `  - ${f}`).join('\n'));
  process.exit(1);
}
console.log(`OK: ${n} checks passed on ${geoPath}`);
