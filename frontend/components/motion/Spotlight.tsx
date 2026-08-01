'use client';

/** A light that follows the cursor across a surface.
 *
 * The position is written straight onto the element as two custom properties.
 * No state, no re-render, no Motion value: a CSS variable read by a gradient is
 * the cheapest way to move light across a large area, and the compositor keeps
 * it off the main thread. The layer itself is `pointer-events-none`, so it can
 * sit over an interactive canvas — which is exactly where the map needs it.
 *
 * Suppressed for coarse pointers and reduced motion, where a cursor-tracking
 * highlight is either impossible or unwanted.
 */

import { useEffect, useRef } from 'react';
import { useReducedMotion } from 'motion/react';

import { cn } from '@/lib/utils';

interface Props {
  /** Radius of the light in pixels. */
  size?: number;
  /** Peak opacity at the centre. Kept low: this is a lift, not a lamp. */
  intensity?: number;
  /** Defaults to the signal cyan. */
  color?: string;
  className?: string;
}

export function Spotlight({
  size = 380,
  intensity = 0.1,
  color = '0, 212, 255',
  className,
}: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const reduced = useReducedMotion();

  useEffect(() => {
    const layer = ref.current;
    const host = layer?.parentElement;
    if (!layer || !host || reduced) return;
    if (!window.matchMedia('(pointer: fine) and (hover: hover)').matches) return;

    let frame = 0;
    let x = 0;
    let y = 0;

    const paint = () => {
      frame = 0;
      layer.style.setProperty('--spot-x', `${x}px`);
      layer.style.setProperty('--spot-y', `${y}px`);
    };

    const onMove = (event: PointerEvent) => {
      const box = host.getBoundingClientRect();
      x = event.clientX - box.left;
      y = event.clientY - box.top;
      if (frame === 0) frame = requestAnimationFrame(paint);
    };

    const onEnter = (event: PointerEvent) => {
      onMove(event);
      layer.style.opacity = '1';
    };

    const onLeave = () => {
      layer.style.opacity = '0';
    };

    host.addEventListener('pointermove', onMove, { passive: true });
    host.addEventListener('pointerenter', onEnter, { passive: true });
    host.addEventListener('pointerleave', onLeave, { passive: true });
    return () => {
      host.removeEventListener('pointermove', onMove);
      host.removeEventListener('pointerenter', onEnter);
      host.removeEventListener('pointerleave', onLeave);
      if (frame !== 0) cancelAnimationFrame(frame);
    };
  }, [reduced]);

  return (
    <div
      ref={ref}
      aria-hidden
      className={cn('pointer-events-none absolute inset-0 opacity-0', className)}
      style={{
        transition: 'opacity var(--dur-3) var(--ease-out)',
        background: `radial-gradient(${size}px circle at var(--spot-x, 50%) var(--spot-y, 50%), rgb(${color} / ${intensity}), transparent 72%)`,
      }}
    />
  );
}
