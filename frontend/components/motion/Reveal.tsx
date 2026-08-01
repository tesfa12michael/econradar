'use client';

/** Scroll reveals, with the failure mode designed out.
 *
 * A reveal starts its element at `opacity: 0`, and Motion writes that into the
 * server-rendered markup — so the naive version ships a page whose rankings and
 * feed are *invisible* to anyone without JavaScript, and to any renderer that
 * never runs a frame. This project already server-renders its indicator tabs so
 * they work without JavaScript; a decorative animation quietly undoing that is
 * a worse bug than having no animation at all.
 *
 * Every element here therefore carries `data-reveal`, and `globals.css` forces
 * that attribute back to its resting state in two situations the animation
 * cannot be relied on to reach: inside `<noscript>`, and under reduced motion.
 * The animation is an enhancement over a page that is already complete.
 *
 * `once: true` throughout: content that re-animates every time it scrolls back
 * into view is content the reader waits for twice.
 */

import { motion, useReducedMotion, type HTMLMotionProps } from 'motion/react';

import { DURATION, IN_VIEW, riseVariants, staggerVariants } from '@/lib/motion';

type RevealProps = HTMLMotionProps<'div'> & {
  /** Travel distance in pixels. 0 gives a plain crossfade. */
  distance?: number;
  delay?: number;
};

export function Reveal({ distance = 14, delay = 0, children, ...rest }: RevealProps) {
  const reduced = useReducedMotion() ?? false;
  return (
    <motion.div
      data-reveal
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
      data-reveal
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

export function RevealItem({ distance = 8, children, ...rest }: RevealProps) {
  const reduced = useReducedMotion() ?? false;
  return (
    <motion.div data-reveal variants={riseVariants(reduced, distance, DURATION.base)} {...rest}>
      {children}
    </motion.div>
  );
}
