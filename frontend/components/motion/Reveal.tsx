'use client';

/** Scroll reveals, with the failure mode designed out.
 *
 * A reveal that gates visibility on a class or a transition ships blank when
 * the transition never fires — on a background tab, in a headless renderer, in
 * a screenshot. These start from an already-laid-out element and animate
 * `opacity` and `y` off it, and under reduced motion they render their end
 * state immediately, so content is never *conditional* on motion running.
 *
 * `once: true` throughout: content that re-animates every time it scrolls back
 * into view is content the reader has to wait for twice.
 */

import { motion, useReducedMotion, type HTMLMotionProps } from 'motion/react';

import { IN_VIEW, riseVariants, staggerVariants } from '@/lib/motion';

type RevealProps = HTMLMotionProps<'div'> & {
  /** Travel distance in pixels. 0 gives a plain crossfade. */
  distance?: number;
  delay?: number;
};

export function Reveal({ distance = 14, delay = 0, children, ...rest }: RevealProps) {
  const reduced = useReducedMotion() ?? false;
  return (
    <motion.div
      initial="hidden"
      whileInView="shown"
      viewport={IN_VIEW}
      variants={riseVariants(reduced, distance)}
      transition={{ delay: reduced ? 0 : delay }}
      {...rest}
    >
      {children}
    </motion.div>
  );
}

/** Parent for a list whose children should arrive in sequence. Pair with
 * `RevealItem` — the two must live in the same client component tree for the
 * stagger to propagate. */
export function RevealGroup({
  step,
  children,
  ...rest
}: HTMLMotionProps<'div'> & { step?: number }) {
  const reduced = useReducedMotion() ?? false;
  return (
    <motion.div
      initial="hidden"
      whileInView="shown"
      viewport={IN_VIEW}
      variants={staggerVariants(reduced, step)}
      {...rest}
    >
      {children}
    </motion.div>
  );
}

export function RevealItem({ distance = 10, children, ...rest }: RevealProps) {
  const reduced = useReducedMotion() ?? false;
  return (
    <motion.div variants={riseVariants(reduced, distance)} {...rest}>
      {children}
    </motion.div>
  );
}
