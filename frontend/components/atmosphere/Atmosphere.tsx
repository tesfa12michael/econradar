'use client';

/** The substrate every page sits on.
 *
 * Three fixed layers, none of them decoration for its own sake:
 *
 *  1. Two slow gradient blooms, which give the darkness somewhere to be lighter
 *     and stop a full-viewport near-black from reading as a dead surface.
 *  2. A graticule — meridians and parallels, the geographer's grid. This is a
 *     map product, so the structural ornament is a map element rather than the
 *     square CSS grid that gets painted behind every dark landing page.
 *  3. A vignette that keeps the edges dark, so content near the viewport border
 *     never has to compete with the bloom behind it.
 *
 * The two moving layers parallax at different rates against the shared pointer
 * field, which is the whole reason the depth reads at all: identical motion on
 * both would look like one flat image sliding. Every transform comes from a
 * Motion value, so pointer movement never re-renders React.
 */

import { motion, useReducedMotion, useTransform } from 'motion/react';
import { useMemo } from 'react';

import { usePointerField } from './PointerField';

export function Atmosphere() {
  const { nx, ny, live } = usePointerField();
  const reduced = useReducedMotion();

  // The near layer travels further than the far one. Small numbers on purpose:
  // this should be felt at the edge of attention, not watched.
  const bloomX = useTransform(nx, [-0.5, 0.5], [34, -34]);
  const bloomY = useTransform(ny, [-0.5, 0.5], [26, -26]);
  const gridX = useTransform(nx, [-0.5, 0.5], [-14, 14]);
  const gridY = useTransform(ny, [-0.5, 0.5], [-10, 10]);

  return (
    <div
      aria-hidden
      className="pointer-events-none fixed inset-0 overflow-hidden"
      style={{ zIndex: 'var(--z-base)' }}
    >
      <motion.div
        className="absolute inset-[-12%]"
        style={{ x: bloomX, y: bloomY, willChange: live ? 'transform' : undefined }}
      >
        <div
          className="absolute left-[6%] top-[-22%] h-[86vh] w-[86vh] rounded-full blur-[110px]"
          style={{
            background:
              'radial-gradient(circle, rgb(0 150 200 / 0.24) 0%, rgb(0 120 175 / 0.09) 46%, transparent 70%)',
            animation: reduced ? undefined : 'drift-a 46s ease-in-out infinite',
          }}
        />
        <div
          className="absolute right-[-4%] top-[18%] h-[100vh] w-[100vh] rounded-full blur-[130px]"
          style={{
            background:
              'radial-gradient(circle, rgb(52 78 140 / 0.34) 0%, rgb(30 64 128 / 0.13) 48%, transparent 72%)',
            animation: reduced ? undefined : 'drift-b 62s ease-in-out infinite',
          }}
        />
        <div
          className="absolute bottom-[-30%] left-[28%] h-[70vh] w-[70vh] rounded-full blur-[130px]"
          style={{
            background:
              'radial-gradient(circle, rgb(24 60 110 / 0.30) 0%, transparent 68%)',
            animation: reduced ? undefined : 'drift-a 74s ease-in-out infinite reverse',
          }}
        />
      </motion.div>

      <motion.div
        className="absolute inset-0"
        style={{ x: gridX, y: gridY, willChange: live ? 'transform' : undefined }}
      >
        <Graticule />
      </motion.div>

      {/* Enough to keep the corners quiet and content legible over the blooms,
          and no more: a heavier vignette flattens the layers underneath it back
          into the single dead surface they exist to replace. */}
      <div
        className="absolute inset-0"
        style={{
          background:
            'radial-gradient(135% 105% at 50% 4%, transparent 46%, rgb(10 15 30 / 0.3) 82%, rgb(10 15 30 / 0.62) 100%)',
        }}
      />
    </div>
  );
}

/** An orthographic globe graticule, drawn large and anchored off the top-left
 * corner so what reaches the page is a field of arcs rather than a whole ball
 * sitting behind the content. */
function Graticule() {
  const { meridians, parallels } = useMemo(buildGraticule, []);
  const cx = 340;
  const cy = 90;
  const r = 880;

  return (
    <svg
      className="absolute inset-0 h-full w-full"
      viewBox="0 0 1600 900"
      preserveAspectRatio="xMidYMid slice"
      fill="none"
    >
      <defs>
        {/* The arcs fade out toward the lower right so they never run under the
            densest content on any page. */}
        <radialGradient id="graticule-falloff" cx="21%" cy="10%" r="92%">
          <stop offset="0%" stopColor="#8b9ec7" stopOpacity="0.62" />
          <stop offset="50%" stopColor="#8b9ec7" stopOpacity="0.26" />
          <stop offset="100%" stopColor="#8b9ec7" stopOpacity="0" />
        </radialGradient>
        <mask id="graticule-mask">
          <rect width="1600" height="900" fill="url(#graticule-falloff)" />
        </mask>
      </defs>

      <g mask="url(#graticule-mask)" stroke="#8b9ec7" strokeWidth="1" vectorEffect="non-scaling-stroke">
        <circle cx={cx} cy={cy} r={r} opacity="0.7" />
        {meridians.map((rx, i) => (
          <ellipse key={`m${i}`} cx={cx} cy={cy} rx={rx * r} ry={r} opacity="0.5" />
        ))}
        {parallels.map(({ y, rx, ry }, i) => (
          <ellipse key={`p${i}`} cx={cx} cy={cy + y * r} rx={rx * r} ry={ry * r} opacity="0.5" />
        ))}
      </g>
    </svg>
  );
}

/** Meridian widths and parallel positions for a globe tilted slightly toward
 * the viewer. Computed once at module scope — deterministic, so the server and
 * the client draw the same arcs. */
function buildGraticule() {
  const longitudes = [15, 40, 65, 90];
  const latitudes = [-60, -35, -12, 12, 35, 60];
  const tilt = 0.19;

  return {
    meridians: longitudes.map((deg) => Math.abs(Math.cos((deg * Math.PI) / 180))),
    parallels: latitudes.map((deg) => {
      const phi = (deg * Math.PI) / 180;
      const rx = Math.cos(phi);
      return { y: -Math.sin(phi), rx, ry: rx * tilt };
    }),
  };
}
