'use client';

import { DeckGL } from '@deck.gl/react';
import { GeoJsonLayer, ScatterplotLayer } from '@deck.gl/layers';
import { Globe, Keyboard } from '@phosphor-icons/react/dist/ssr';
import { useReducedMotion } from 'motion/react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';

import { Spotlight } from '@/components/motion/Spotlight';
import { Figure, Meta, SourceMark } from '@/components/primitives';
import { formatValue, type MapPoint } from '@/lib/api';
import {
  buildDomain,
  colorFor,
  mixRgb,
  NO_DATA_COLOR,
  rampCss,
  type RGB,
} from '@/lib/colorScale';
import { buildAnchors, type Anchor, type CountryFeature, type FeatureCollection } from '@/lib/geo';

/* There is deliberately no base map here.
 *
 * The choropleth *is* the visualization — basemap imagery would only add noise
 * behind it — so this used to render a MapLibre canvas with a tile-free style
 * whose single layer painted `#0A0F1E`, which is exactly the page background
 * behind it. MapLibre was drawing an invisible rectangle at the cost of a WebGL
 * mapping library and a web worker, and it crashed the deployed page when v6
 * shipped a module worker webpack never emitted (decision #20).
 *
 * deck.gl already owns the canvas, the Web Mercator view, the controller and
 * picking. Nothing below needs a base map, so there is nothing to pin.
 */

/** Longitude 12 rather than 10, which buys the Americas enough clearance to sit
 * out from under the caption block in the top-left corner. */
const INITIAL_VIEW = { longitude: 12, latitude: 26, zoom: 1.05, pitch: 0, bearing: 0 };

const SWEEP_MS = 1250;
/** How much of the sweep a single country takes to fill. Wide enough that the
 * leading edge reads as a soft front rather than a hard wipe. */
const SWEEP_FEATHER = 0.22;
/** 48 steps over 1.25s. Quantised because the visible difference between this
 * and a value updated every frame is nothing, and the difference in React
 * renders is 48 against roughly 75. */
const SWEEP_STEPS = 48;

interface Props {
  points: MapPoint[];
  indicatorCode: string;
  indicatorName: string | null;
  unit: string | null;
  source: string | null;
  /** Rank by country code for the current indicator, so hovering surfaces where
   * a country sits in the whole field rather than only its value. */
  ranks?: Record<string, { rank: number; of: number }>;
}

export function WorldMap({
  points,
  indicatorCode,
  indicatorName,
  unit,
  source,
  ranks,
}: Props) {
  const router = useRouter();
  const reduced = useReducedMotion();
  const [geo, setGeo] = useState<FeatureCollection | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const [focusIndex, setFocusIndex] = useState(-1);
  const [sweep, setSweep] = useState(0);

  useEffect(() => {
    let cancelled = false;
    fetch('/geo/countries-110m.geojson')
      .then((r) => r.json())
      .then((d: FeatureCollection) => {
        if (!cancelled) setGeo(d);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  const anchors = useMemo(() => (geo ? buildAnchors(geo) : new Map<string, Anchor>()), [geo]);

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

  /* The sweep. Countries resolve west to east as a front crosses the map, which
   * is the one moment on this page that says "this is being read from a
   * database" rather than "this is a picture". It runs once per indicator.
   *
   * **The map must never be waiting on it.** Every country is painted from the
   * no-data colour, so a sweep that starts and does not finish leaves a blank
   * world — and `requestAnimationFrame` does not run in a hidden tab, which was
   * measured doing exactly that. So the animation only starts when the document
   * is visible, it completes immediately if the tab is hidden part-way through,
   * and reduced motion skips it outright. In every case the resting state is a
   * fully painted map; the sweep is the enhancement, not the mechanism.
   */
  useEffect(() => {
    if (!geo) return;
    if (reduced || document.visibilityState !== 'visible') {
      setSweep(1);
      return;
    }

    setSweep(0);
    let frame = 0;
    const start = performance.now();

    const step = (now: number) => {
      const linear = Math.min(1, (now - start) / SWEEP_MS);
      const eased = 1 - Math.pow(1 - linear, 3);
      setSweep(Math.round(eased * SWEEP_STEPS) / SWEEP_STEPS);
      if (linear < 1) frame = requestAnimationFrame(step);
    };

    const finishIfHidden = () => {
      if (document.visibilityState === 'visible') return;
      cancelAnimationFrame(frame);
      frame = 0;
      setSweep(1);
    };

    frame = requestAnimationFrame(step);
    document.addEventListener('visibilitychange', finishIfHidden);
    return () => {
      if (frame !== 0) cancelAnimationFrame(frame);
      document.removeEventListener('visibilitychange', finishIfHidden);
    };
  }, [geo, indicatorCode, reduced]);

  const fillFor = useCallback(
    (feature: CountryFeature): RGB => {
      const point = byCode.get(feature.properties.iso3);
      const target = colorFor(point?.value, domain);
      if (sweep >= 1) return target;
      const at = anchors.get(feature.properties.iso3)?.sweep ?? 0.5;
      // The front leads the country it is about to fill by one feather width.
      const progress = (sweep * (1 + SWEEP_FEATHER) - at) / SWEEP_FEATHER;
      return mixRgb(NO_DATA_COLOR, target, progress);
    },
    [byCode, domain, anchors, sweep],
  );

  /** Countries whose latest observation was flagged. The design system asks for
   * these to be marked on the map itself, not only in the tooltip. */
  const flagged = useMemo(
    () =>
      points
        .filter((p) => p.has_anomaly && anchors.has(p.country_code))
        .map((p) => ({ ...p, anchor: anchors.get(p.country_code)! })),
    [points, anchors],
  );

  const layers = useMemo(() => {
    if (!geo) return [];
    return [
      new GeoJsonLayer({
        id: 'countries',
        data: geo as never,
        filled: true,
        stroked: true,
        getFillColor: fillFor as never,
        getLineColor: [24, 36, 58],
        lineWidthMinPixels: 0.5,
        pickable: true,
        autoHighlight: true,
        highlightColor: [0, 212, 255, 60],
        updateTriggers: { getFillColor: [byCode, domain, sweep] },
        onClick: (info: { object?: CountryFeature }) => {
          const iso3 = info.object?.properties.iso3;
          if (iso3 && byCode.has(iso3)) router.push(`/country/${iso3}?indicator=${indicatorCode}`);
        },
      }),
      new ScatterplotLayer({
        id: 'anomalies',
        data: flagged,
        getPosition: (d: (typeof flagged)[number]) => [d.anchor.lon, d.anchor.lat],
        getFillColor: [245, 158, 11, 210],
        getLineColor: [245, 158, 11, 70],
        stroked: true,
        lineWidthMinPixels: 4,
        radiusMinPixels: 2.5,
        radiusMaxPixels: 3.5,
        getRadius: 3,
        // Fades in behind the sweep rather than sitting there before the
        // country underneath has a colour.
        opacity: Math.max(0, sweep * 1.4 - 0.4),
        pickable: false,
      }),
    ];
  }, [geo, fillFor, byCode, domain, sweep, flagged, router, indicatorCode]);

  /* Keyboard traversal. The design system requires every map region be
   * reachable without a mouse and every readout available on focus. */
  const navigable = useMemo(
    () =>
      points
        .filter((p) => p.value !== null)
        .sort((a, b) => a.country_code.localeCompare(b.country_code)),
    [points],
  );
  const focused = focusIndex >= 0 ? navigable[focusIndex] : null;

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
      router.push(`/country/${focused.country_code}?indicator=${indicatorCode}`);
    }
  };

  const readout = focused ?? (hovered ? byCode.get(hovered) ?? null : null);

  return (
    <div className="relative h-[clamp(30rem,66vh,48rem)] w-full overflow-hidden">
      <div
        role="application"
        tabIndex={0}
        aria-label={`World choropleth of ${indicatorName ?? indicatorCode}. Arrow keys move between countries with data; Enter opens a country profile.`}
        onKeyDown={onKeyDown}
        onBlur={() => setFocusIndex(-1)}
        className="absolute inset-0 focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[color:var(--signal)]"
      >
        <DeckGL
          initialViewState={INITIAL_VIEW}
          controller={{ dragRotate: false }}
          layers={layers}
          onHover={(info: { object?: CountryFeature }) =>
            setHovered(info.object?.properties.iso3 ?? null)
          }
          getCursor={({ isHovering }) => (isHovering ? 'pointer' : 'default')}
        />
      </div>

      {/* Sits over the canvas and takes no pointer events, so picking is
          unaffected while the cursor still lifts the surface it moves across. */}
      <Spotlight size={460} intensity={0.075} />

      {!geo && (
        <div
          aria-hidden
          className="absolute inset-0"
          style={{
            background: 'var(--plane-1)',
            animation: 'breathe 1.8s var(--ease-in-out) infinite',
          }}
        />
      )}

      {/* Keyboard read-out, mirroring the panel for non-mouse users. */}
      <div aria-live="polite" className="sr-only">
        {focused
          ? `${focused.country_name ?? focused.country_code}: ${formatValue(focused.value, unit)}${
              focused.has_anomaly ? ', anomaly flagged' : ''
            }`
          : ''}
      </div>

      <Readout
        point={readout}
        unit={unit}
        source={source}
        rank={readout ? ranks?.[readout.country_code] : undefined}
        countriesWithData={navigable.length}
        keyboard={Boolean(focused)}
      />

      <Legend domain={domain} unit={unit} />
    </div>
  );
}

/** The hover panel. Pinned rather than following the cursor: a panel this size
 * chasing the pointer is unreadable, and it would cover the country it
 * describes. Never empty — with nothing under the cursor it reports the field
 * as a whole, which is a real fact rather than a prompt to do something. */
function Readout({
  point,
  unit,
  source,
  rank,
  countriesWithData,
  keyboard,
}: {
  point: MapPoint | null;
  unit: string | null;
  source: string | null;
  rank?: { rank: number; of: number };
  countriesWithData: number;
  keyboard: boolean;
}) {
  return (
    <div className="pointer-events-none absolute bottom-5 right-5 w-[16.5rem]">
      <div
        className="rounded-lg border border-[color:var(--edge)] p-3.5 backdrop-blur-xl"
        style={{
          background: 'var(--plane-glass)',
          boxShadow: 'inset 0 1px 0 var(--edge-lit), 0 18px 50px -24px rgb(0 0 0 / 0.9)',
          transition: 'border-color var(--dur-2) var(--ease-out)',
          borderColor: point ? 'var(--edge-strong)' : 'var(--edge)',
        }}
      >
        {point ? (
          <>
            <div className="mb-2 flex items-start justify-between gap-2">
              <p className="text-[13px] font-medium leading-snug text-ink">
                {point.country_name ?? point.country_code}
              </p>
              <Meta className="pt-0.5">{point.country_code}</Meta>
            </div>
            <Figure size="lg" tone="signal">
              {formatValue(point.value, unit)}
            </Figure>
            <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">
              <Meta>{point.date?.slice(0, 7) ?? 'undated'}</Meta>
              {rank && (
                <Meta className="text-ink-muted">
                  rank {rank.rank} of {rank.of}
                </Meta>
              )}
            </div>
            {point.has_anomaly && (
              <p className="mt-2 flex items-center gap-1.5 text-[11px] text-alert">
                <span
                  aria-hidden
                  className="size-1.5 rounded-full"
                  style={{ background: 'var(--alert)', boxShadow: '0 0 8px var(--alert)' }}
                />
                Latest reading flagged
              </p>
            )}
          </>
        ) : (
          <>
            <div className="mb-2 flex items-center gap-2 text-ink-muted">
              <Globe aria-hidden className="size-3.5" />
              <p className="text-[13px] font-medium">Whole field</p>
            </div>
            <Figure size="lg">{countriesWithData}</Figure>
            <Meta className="ml-1.5">countries reporting</Meta>
            <p className="mt-2 flex items-center gap-1.5 text-[11px] text-ink-dim">
              <Keyboard aria-hidden className="size-3.5 shrink-0" />
              Hover a country, or tab here and use the arrow keys
            </p>
          </>
        )}
        <div className="mt-3 border-t border-[color:var(--hairline)] pt-2">
          <SourceMark source={source} />
        </div>
      </div>
    </div>
  );
}

/** The continuous ramp the map actually paints with, rather than five sampled
 * swatches. No-data is shown beside it and never inside it: the two must not be
 * confusable, which is why the value ramp starts one stop above the no-data
 * colour in the first place. */
function Legend({
  domain,
  unit,
}: {
  domain: ReturnType<typeof buildDomain>;
  unit: string | null;
}) {
  const label = (value: number) => value.toFixed(Math.abs(value) >= 100 ? 0 : 1);
  return (
    <div className="pointer-events-none absolute bottom-5 left-5 sm:left-6">
      <div className="w-[13rem]">
        <div
          aria-hidden
          className="h-1.5 w-full rounded-full"
          style={{ background: rampCss(domain) }}
        />
        <div className="mt-1.5 flex items-center justify-between">
          <Meta>
            {label(domain.min)}
            {unit === '%' ? '%' : ''}
          </Meta>
          <Meta>
            {label(domain.max)}
            {unit === '%' ? '%' : ''}
          </Meta>
        </div>
        <div className="mt-2 flex items-center gap-1.5">
          <span
            aria-hidden
            className="h-1.5 w-5 rounded-full border border-[color:var(--hairline)]"
            style={{ background: 'rgb(26,34,53)' }}
          />
          <Meta>no data</Meta>
          <span aria-hidden className="ml-2 size-1.5 rounded-full bg-alert" />
          <Meta>flagged</Meta>
        </div>
      </div>
    </div>
  );
}
