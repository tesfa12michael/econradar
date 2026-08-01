'use client';

/** Gives a control a little weight, so the cursor feels like it is pulling on
 * something rather than sliding over it.
 *
 * The pull is deliberately small — a few pixels at the edge of the element.
 * Large magnetism is a party trick and it makes a target harder to hit, which
 * is the opposite of what a control is for.
 *
 * Transform only, spring-smoothed, and off entirely for coarse pointers and
 * reduced motion.
 */

import { motion, useMotionValue, useReducedMotion, useSpring } from 'motion/react';
import { useRef, type ReactNode } from 'react';

import { cn } from '@/lib/utils';

interface Props {
  children: ReactNode;
  /** Maximum travel in pixels. */
  strength?: number;
  className?: string;
}

export function Magnetic({ children, strength = 5, className }: Props) {
  const ref = useRef<HTMLSpanElement>(null);
  const reduced = useReducedMotion();

  const rawX = useMotionValue(0);
  const rawY = useMotionValue(0);
  const x = useSpring(rawX, { stiffness: 260, damping: 20, mass: 0.4 });
  const y = useSpring(rawY, { stiffness: 260, damping: 20, mass: 0.4 });

  const onMove = (event: React.PointerEvent<HTMLSpanElement>) => {
    if (reduced || event.pointerType !== 'mouse' || !ref.current) return;
    const box = ref.current.getBoundingClientRect();
    rawX.set(((event.clientX - box.left) / box.width - 0.5) * 2 * strength);
    rawY.set(((event.clientY - box.top) / box.height - 0.5) * 2 * strength);
  };

  const release = () => {
    rawX.set(0);
    rawY.set(0);
  };

  return (
    <motion.span
      ref={ref}
      onPointerMove={onMove}
      onPointerLeave={release}
      onBlur={release}
      style={{ x, y }}
      className={cn('inline-flex', className)}
    >
      {children}
    </motion.span>
  );
}
