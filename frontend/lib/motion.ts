/** Motion vocabulary for the whole product.
 *
 * One set of durations and one family of curves, so a chart drawing itself and
 * a panel arriving feel like the same system moving. Exponential ease-out
 * throughout: motion here is data resolving, and data does not bounce.
 *
 * Everything below animates `transform` or `opacity`. Nothing animates a
 * property that triggers layout.
 */

import type { Transition, Variants } from 'motion/react';

export const DURATION = {
  instant: 0.12,
  quick: 0.2,
  base: 0.32,
  slow: 0.56,
  ambient: 0.9,
} as const;

/** cubic-bezier(0.16, 1, 0.3, 1) — the same curve as `--ease-out` in globals.css. */
export const EASE_OUT = [0.16, 1, 0.3, 1] as const;
export const EASE_OUT_SOFT = [0.165, 0.84, 0.44, 1] as const;

export const transition = {
  quick: { duration: DURATION.quick, ease: EASE_OUT },
  base: { duration: DURATION.base, ease: EASE_OUT },
  slow: { duration: DURATION.slow, ease: EASE_OUT },
} satisfies Record<string, Transition>;

/** Pointer-tracking spring. Loose enough to feel like weight, tight enough that
 * the highlight never lags visibly behind the cursor. */
export const POINTER_SPRING = { stiffness: 140, damping: 22, mass: 0.6 } as const;

/** A panel arriving: it rises a little and settles.
 *
 * **Transform only. Nothing here animates opacity, and that is a correctness
 * rule rather than a stylistic one.** A reveal that starts at `opacity: 0` has
 * Motion write that into the server-rendered HTML, and it was measured doing
 * exactly what the failure mode predicts: with the tab hidden, `requestAnimation
 * Frame` stops, the animation freezes at zero, and the rankings rail and the
 * flagged feed are *invisible* — and the same markup is what a reader with
 * JavaScript off receives. Content must never be conditional on an animation
 * having run. Animating only `y` makes that structurally impossible: the worst
 * case is a section sitting eight pixels low.
 *
 * The arrival still reads, because what carries it is the stagger and the
 * exponential ease, not the fade.
 *
 * `duration` is a parameter because a section and a table row are not the same
 * event. A row inside a staggered list already waits its turn, so giving it the
 * slow curve on top of that delay means the last of nine lands almost a second
 * after the first and the list reads as loading rather than arriving.
 */
export function riseVariants(
  reduced: boolean,
  distance = 14,
  duration: number = DURATION.slow,
): Variants {
  return {
    hidden: { y: reduced ? 0 : distance },
    shown: {
      y: 0,
      transition: reduced ? { duration: 0 } : { duration, ease: EASE_OUT },
    },
  };
}

/** Stagger for a list whose items are peers. Held short: past about 60ms per
 * item a ten-row list reads as loading rather than arriving. */
export function staggerVariants(reduced: boolean, step = 0.045): Variants {
  return {
    hidden: {},
    shown: {
      transition: reduced ? { staggerChildren: 0 } : { staggerChildren: step, delayChildren: 0.04 },
    },
  };
}

/** Viewport trigger shared by every scroll reveal, so sections resolve at the
 * same point on screen instead of each choosing its own. */
export const IN_VIEW = { once: true, amount: 0.25 } as const;
