'use client';

import { DeckGL } from '@deck.gl/react';
import { GeoJsonLayer } from '@deck.gl/layers';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';

import { formatValue, type MapPoint } from '@/lib/api';
import { buildDomain, colorFor, legendStops, rgbToCss, type RGB } from '@/lib/colorScale';

/* There is deliberately no base map here.
 *
 * The choropleth *is* the visualization — basemap imagery would only add noise behind
 * it — so this used to render a MapLibre canvas with a tile-free style whose single
 * layer painted `#0A0F1E`. That is exactly `--bg-app`, which the container below
 * already paints, so MapLibre was drawing an invisible rectangle at the cost of a
 * whole WebGL mapping library and a web worker.
 *
 * It also broke the page. maplibre-gl v6 is an ESM-only rewrite that spawns a *module*
 * worker resolved from `import.meta.url`; webpack never emitted `maplibre-gl-worker.mjs`
 * as a static asset, so the browser fetched a URL that 404'd to Next's HTML error page
 * ("non-JavaScript MIME type text/html"), the worker never started, and the map crashed
 * dereferencing its own uninitialised state. react-map-gl 8.1.1 declares
 * `maplibre-gl: ">=4.0.0"`, so npm accepted the breaking major without a peer warning.
 *
 * deck.gl already owns the canvas, the Web Mercator view, the controller and picking.
 * Nothing below needs a base map, so there is nothing to pin a version of.
 */

const INITIAL_VIEW = { longitude: 10, latitude: 25, zoom: 1.1, pitch: 0, bearing: 0 };

interface CountryFeature {
  properties: { iso3: string; name: string };
}

interface Props {
  points: MapPoint[];
  indicatorCode: string;
  indicatorName: string | null;
  unit: string | null;
}

export function WorldMap({ points, indicatorCode, indicatorName, unit }: Props) {
  const router = useRouter();
  const [geo, setGeo] = useState<unknown>(null);
  const [hovered, setHovered] = useState<{ x: number; y: number; iso3: string } | null>(null);
  const [focusIndex, setFocusIndex] = useState(-1);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    fetch('/geo/countries-110m.geojson')
      .then((r) => r.json())
      .then((d) => {
        if (!cancelled) setGeo(d);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  const byCode = useMemo(() => {
    const map = new Map<string, MapPoint>();
    for (const p of points) map.set(p.country_code, p);
    return map;
  }, [points]);

  const domain = useMemo(
    () =>
      buildDomain(
        points.map((p) => p.value).filter((v): v is number => v !== null),
        indicatorCode,
      ),
    [points, indicatorCode],
  );

  /** Countries that actually have data, for keyboard traversal. */
  const navigable = useMemo(
    () => points.filter((p) => p.value !== null).sort((a, b) => a.country_code.localeCompare(b.country_code)),
    [points],
  );

  const fillFor = useCallback(
    (f: CountryFeature): RGB => colorFor(byCode.get(f.properties.iso3)?.value, domain),
    [byCode, domain],
  );

  const layer = useMemo(
    () =>
      new GeoJsonLayer({
        id: 'countries',
        data: geo as never,
        filled: true,
        stroked: true,
        getFillColor: fillFor as never,
        getLineColor: [31, 45, 69],
        lineWidthMinPixels: 0.5,
        pickable: true,
        autoHighlight: true,
        highlightColor: [0, 212, 255, 90],
        updateTriggers: { getFillColor: [byCode, domain] },
        onClick: (info: { object?: CountryFeature }) => {
          const iso3 = info.object?.properties.iso3;
          if (iso3 && byCode.has(iso3)) router.push(`/country/${iso3}`);
        },
      }),
    [geo, fillFor, byCode, domain, router],
  );

  const hoveredPoint = hovered ? byCode.get(hovered.iso3) : null;
  const focused = focusIndex >= 0 ? navigable[focusIndex] : null;

  /** Keyboard traversal: the design system requires map regions be reachable without
   * a mouse, and every tooltip available on focus, not only on hover. */
  const onKeyDown = (event: React.KeyboardEvent) => {
    if (navigable.length === 0) return;
    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') {
      event.preventDefault();
      setFocusIndex((i) => (i + 1) % navigable.length);
    } else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') {
      event.preventDefault();
      setFocusIndex((i) => (i <= 0 ? navigable.length - 1 : i - 1));
    } else if ((event.key === 'Enter' || event.key === ' ') && focused) {
      event.preventDefault();
      router.push(`/country/${focused.country_code}`);
    }
  };

  return (
    <div
      ref={containerRef}
      className="relative h-[60vh] w-full overflow-hidden"
      style={{ background: 'var(--bg-app)' }}
    >
      <div
        role="application"
        tabIndex={0}
        aria-label={`World choropleth of ${indicatorName ?? indicatorCode}. Use arrow keys to move between countries with data, Enter to open a country profile.`}
        onKeyDown={onKeyDown}
        onBlur={() => setFocusIndex(-1)}
        className="absolute inset-0 focus:outline-none focus-visible:ring-2 focus-visible:ring-inset"
        style={{ outlineColor: 'var(--accent)' }}
      >
        <DeckGL
          initialViewState={INITIAL_VIEW}
          controller={{ dragRotate: false }}
          layers={geo ? [layer] : []}
          onHover={(info: { object?: CountryFeature; x: number; y: number }) =>
            setHovered(
              info.object ? { x: info.x, y: info.y, iso3: info.object.properties.iso3 } : null,
            )
          }
          getCursor={({ isHovering }) => (isHovering ? 'pointer' : 'grab')}
        />
      </div>

      {!geo && (
        <div
          className="absolute inset-0 animate-pulse"
          style={{ background: 'var(--bg-card)' }}
          aria-hidden
        />
      )}

      {hoveredPoint && hovered && (
        <Tooltip x={hovered.x} y={hovered.y} point={hoveredPoint} unit={unit} />
      )}

      {/* Keyboard focus read-out — mirrors the hover tooltip for non-mouse users. */}
      <div aria-live="polite" className="sr-only">
        {focused
          ? `${focused.country_name ?? focused.country_code}: ${formatValue(focused.value, unit)}${
              focused.has_anomaly ? ', anomaly flagged' : ''
            }`
          : ''}
      </div>
      {focused && (
        <div
          className="pointer-events-none absolute bottom-4 left-4 rounded-lg border px-4 py-3 text-sm"
          style={{
            background: 'var(--bg-elevated)',
            borderColor: 'var(--accent)',
            color: 'var(--text-primary)',
          }}
        >
          <div className="font-semibold">{focused.country_name ?? focused.country_code}</div>
          <div style={{ fontFamily: 'var(--font-mono)', color: 'var(--accent)' }}>
            {formatValue(focused.value, unit)}
          </div>
          <div style={{ color: 'var(--text-tertiary)' }} className="text-xs">
            Enter to open profile
          </div>
        </div>
      )}

      <Legend domain={domain} unit={unit} />
    </div>
  );
}

function Tooltip({
  x,
  y,
  point,
  unit,
}: {
  x: number;
  y: number;
  point: MapPoint;
  unit: string | null;
}) {
  return (
    <div
      className="pointer-events-none absolute z-10 rounded-lg border px-3 py-2 text-sm shadow-lg"
      style={{
        left: x + 12,
        top: y + 12,
        background: 'var(--bg-elevated)',
        borderColor: 'var(--border)',
        color: 'var(--text-primary)',
      }}
    >
      <div className="font-semibold">{point.country_name ?? point.country_code}</div>
      <div style={{ fontFamily: 'var(--font-mono)', color: 'var(--accent)' }}>
        {formatValue(point.value, unit)}
      </div>
      {point.has_anomaly && (
        <div style={{ color: 'var(--warn)' }} className="mt-1 flex items-center gap-1 text-xs">
          <span aria-hidden>▲</span> Anomaly flagged
        </div>
      )}
    </div>
  );
}

function Legend({
  domain,
  unit,
}: {
  domain: ReturnType<typeof buildDomain>;
  unit: string | null;
}) {
  const stops = legendStops(domain);
  return (
    <div
      className="absolute bottom-4 right-4 rounded-lg border px-3 py-2"
      style={{ background: 'var(--bg-card)', borderColor: 'var(--border)' }}
    >
      <div style={{ color: 'var(--text-secondary)' }} className="mb-1.5 text-xs">
        {unit ? `Value (${unit})` : 'Value'}
      </div>
      <div className="flex items-center gap-1">
        {stops.map((s, i) => (
          <div key={i} className="flex flex-col items-center gap-1">
            <div
              className="h-3 w-8 rounded-sm"
              style={{ background: rgbToCss(s.color) }}
              aria-hidden
            />
            <span
              style={{ color: 'var(--text-tertiary)', fontFamily: 'var(--font-mono)' }}
              className="text-[10px]"
            >
              {s.label}
            </span>
          </div>
        ))}
      </div>
      <div className="mt-2 flex items-center gap-1.5">
        <div
          className="h-3 w-8 rounded-sm border"
          style={{ background: 'rgb(26,34,53)', borderColor: 'var(--border)' }}
          aria-hidden
        />
        <span style={{ color: 'var(--text-tertiary)' }} className="text-[10px]">
          No data
        </span>
      </div>
    </div>
  );
}
