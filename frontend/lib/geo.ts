/** Geometry helpers for the choropleth.
 *
 * The committed world file carries polygons and an ISO-3 code and nothing else,
 * so anything the map needs to place *at* a country — an anomaly marker, the
 * position a sweep should reach it at — has to be derived from the outline.
 */

export interface CountryFeature {
  properties: { iso3: string; name: string };
  geometry: {
    type: 'Polygon' | 'MultiPolygon';
    coordinates: number[][][] | number[][][][];
  };
}

export interface FeatureCollection {
  features: CountryFeature[];
}

/** Longitude and latitude of a country's largest ring, plus its longitude
 * expressed 0–1 across the map.
 *
 * The *largest* ring rather than all of them: averaging every ring puts France
 * in the Atlantic somewhere between the mainland and French Guiana, and Norway
 * out past Svalbard. Taking the biggest piece puts the marker where a reader
 * would point.
 */
export interface Anchor {
  lon: number;
  lat: number;
  /** 0 at the western edge of the projection, 1 at the eastern. */
  sweep: number;
}

export function buildAnchors(collection: FeatureCollection): Map<string, Anchor> {
  const anchors = new Map<string, Anchor>();

  for (const feature of collection.features ?? []) {
    const iso3 = feature.properties?.iso3;
    if (!iso3 || !feature.geometry) continue;

    const rings =
      feature.geometry.type === 'MultiPolygon'
        ? (feature.geometry.coordinates as number[][][][]).map((polygon) => polygon[0])
        : [(feature.geometry.coordinates as number[][][])[0]];

    let best: number[][] | null = null;
    let bestArea = -1;
    for (const ring of rings) {
      if (!ring || ring.length < 3) continue;
      const area = Math.abs(shoelace(ring));
      if (area > bestArea) {
        bestArea = area;
        best = ring;
      }
    }
    if (!best) continue;

    let lon = 0;
    let lat = 0;
    for (const [x, y] of best) {
      lon += x;
      lat += y;
    }
    lon /= best.length;
    lat /= best.length;

    anchors.set(iso3, { lon, lat, sweep: (lon + 180) / 360 });
  }

  return anchors;
}

function shoelace(ring: number[][]): number {
  let sum = 0;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    sum += (ring[j][0] + ring[i][0]) * (ring[j][1] - ring[i][1]);
  }
  return sum / 2;
}
