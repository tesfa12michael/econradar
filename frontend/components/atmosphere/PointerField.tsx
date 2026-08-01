'use client';

/** One pointer listener for the whole application.
 *
 * Everything cursor-reactive in EconRadar reads from here: the atmosphere
 * parallax, the map spotlight, the magnetic controls. The alternative — each
 * effect attaching its own `pointermove` — costs a listener and a spring per
 * effect, and they drift out of phase with each other because each one smooths
 * independently.
 *
 * Positions are Motion values, never React state. A `useState` holding the
 * cursor re-renders the tree on every mouse event, which is the single most
 * reliable way to make an interface that looks alive feel slow.
 *
 * The listener is not attached at all when the pointer is coarse (there is no
 * cursor to follow on a touchscreen) or when the reader has asked for reduced
 * motion. In both cases the values stay at their neutral centre, so consumers
 * render exactly as if the cursor were at rest — no branch needed at the call
 * site, and no dead listener running.
 */

import { createContext, useContext, useEffect, useMemo, useState } from 'react';
import {
  useMotionValue,
  useReducedMotion,
  useSpring,
  type MotionValue,
} from 'motion/react';

import { POINTER_SPRING } from '@/lib/motion';

interface PointerField {
  /** Cursor offset from viewport centre, -0.5 to 0.5. Smoothed. */
  nx: MotionValue<number>;
  ny: MotionValue<number>;
  /** Raw viewport coordinates in pixels. Unsmoothed, for hit-accurate effects. */
  cx: MotionValue<number>;
  cy: MotionValue<number>;
  /** False when there is no pointer to track, or motion is suppressed. */
  live: boolean;
}

const PointerContext = createContext<PointerField | null>(null);

export function PointerProvider({ children }: { children: React.ReactNode }) {
  const reduced = useReducedMotion();
  const fine = useFinePointer();
  const live = fine && !reduced;

  const rawX = useMotionValue(0);
  const rawY = useMotionValue(0);
  const cx = useMotionValue(0);
  const cy = useMotionValue(0);

  const nx = useSpring(rawX, POINTER_SPRING);
  const ny = useSpring(rawY, POINTER_SPRING);

  useEffect(() => {
    if (!live) return;

    let frame = 0;
    let pendingX = 0;
    let pendingY = 0;

    const flush = () => {
      frame = 0;
      cx.set(pendingX);
      cy.set(pendingY);
      rawX.set(pendingX / window.innerWidth - 0.5);
      rawY.set(pendingY / window.innerHeight - 0.5);
    };

    // Coalesced to one write per frame: a high-polling-rate mouse fires well
    // above 60Hz and there is no display to show the extra samples on.
    const onMove = (event: PointerEvent) => {
      pendingX = event.clientX;
      pendingY = event.clientY;
      if (frame === 0) frame = requestAnimationFrame(flush);
    };

    window.addEventListener('pointermove', onMove, { passive: true });
    return () => {
      window.removeEventListener('pointermove', onMove);
      if (frame !== 0) cancelAnimationFrame(frame);
    };
  }, [live, cx, cy, rawX, rawY]);

  const value = useMemo<PointerField>(
    () => ({ nx, ny, cx, cy, live }),
    [nx, ny, cx, cy, live],
  );

  return <PointerContext.Provider value={value}>{children}</PointerContext.Provider>;
}

/** The shared pointer field. Returns inert values outside a provider, so a
 * component using this never needs to know whether one is mounted. */
export function usePointerField(): PointerField {
  const context = useContext(PointerContext);
  const fallbackNx = useMotionValue(0);
  const fallbackNy = useMotionValue(0);
  const fallbackCx = useMotionValue(0);
  const fallbackCy = useMotionValue(0);
  const fallback = useMemo<PointerField>(
    () => ({ nx: fallbackNx, ny: fallbackNy, cx: fallbackCx, cy: fallbackCy, live: false }),
    [fallbackNx, fallbackNy, fallbackCx, fallbackCy],
  );
  return context ?? fallback;
}

/** True when the primary input can hover and points precisely.
 *
 * Read after mount rather than during render: the server has no media query to
 * answer with, and guessing produces a hydration mismatch on every touch device.
 * Starting `false` means a touch device never attaches the listener at all.
 */
function useFinePointer(): boolean {
  const [fine, setFine] = useState(false);

  useEffect(() => {
    const query = window.matchMedia('(pointer: fine) and (hover: hover)');
    setFine(query.matches);
    const onChange = (event: MediaQueryListEvent) => setFine(event.matches);
    query.addEventListener('change', onChange);
    return () => query.removeEventListener('change', onChange);
  }, []);

  return fine;
}
