import { gsap } from "gsap";
import { motion } from "../tokens";

/**
 * Every animation in the widget, in one place.
 *
 * Two rules hold throughout:
 *
 * 1. **`transform` and `opacity` only.** Animating `width`, `height`, `top`, or
 *    `left` forces layout on every frame and janks visibly. Where a size change
 *    is wanted, it is expressed as `scale`.
 * 2. **`prefers-reduced-motion` short-circuits, it does not degrade.** Each
 *    function jumps straight to the end state. The widget stays fully
 *    functional; it simply stops moving. Vestibular disorders make this a
 *    health matter, not a preference.
 *
 * The media query is read live rather than cached at module load, so a user
 * changing the OS setting mid-session is respected without a reload.
 */

function prefersReducedMotion(): boolean {
  return (
    typeof globalThis.matchMedia === "function" &&
    globalThis.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

/** Panel opening — grows out of the launcher's corner. */
export function openPanel(panel: HTMLElement, launcher: HTMLElement): void {
  if (prefersReducedMotion()) {
    gsap.set(panel, { opacity: 1, scale: 1, y: 0 });
    gsap.set(launcher, { opacity: 0, scale: 0.8 });
    return;
  }

  gsap
    .timeline()
    .to(launcher, { opacity: 0, scale: 0.8, duration: motion.fast, ease: motion.exit }, 0)
    .fromTo(
      panel,
      { opacity: 0, scale: 0.9, y: 12 },
      { opacity: 1, scale: 1, y: 0, duration: motion.slow, ease: motion.enter },
      0.04,
    );
}

/** Panel closing — collapses back toward the launcher. */
export function closePanel(
  panel: HTMLElement,
  launcher: HTMLElement,
  onComplete: () => void,
): void {
  if (prefersReducedMotion()) {
    gsap.set(panel, { opacity: 0, scale: 0.95 });
    gsap.set(launcher, { opacity: 1, scale: 1 });
    onComplete();
    return;
  }

  gsap
    .timeline({ onComplete })
    .to(panel, { opacity: 0, scale: 0.94, y: 8, duration: motion.medium, ease: motion.exit }, 0)
    .to(
      launcher,
      { opacity: 1, scale: 1, duration: motion.medium, ease: motion.enter },
      motion.medium * 0.5,
    );
}

/** Message entrance — fade plus a small rise. */
export function enterMessage(element: HTMLElement): void {
  if (prefersReducedMotion()) {
    gsap.set(element, { opacity: 1, y: 0 });
    return;
  }

  gsap.fromTo(
    element,
    { opacity: 0, y: 10 },
    { opacity: 1, y: 0, duration: motion.medium, ease: motion.enter },
  );
}

/**
 * Group entrance — staggered rather than animated as one block.
 *
 * This is the habit that reads as considered more than any other single
 * detail: four chips appearing together look like a render, the same four
 * arriving 40ms apart look designed.
 */
export function enterGroup(elements: HTMLElement[]): void {
  if (elements.length === 0) return;

  if (prefersReducedMotion()) {
    gsap.set(elements, { opacity: 1, y: 0 });
    return;
  }

  gsap.fromTo(
    elements,
    { opacity: 0, y: 8 },
    {
      opacity: 1,
      y: 0,
      duration: motion.medium,
      ease: motion.enter,
      stagger: motion.stagger,
    },
  );
}

/**
 * Launcher idle breathing — draws the eye without nagging.
 *
 * Returns a handle that must be called once the visitor engages. A launcher
 * still pulsing after someone has already opened it reads as broken, not
 * eager, so this is stopped permanently rather than paused.
 */
export function startIdlePulse(launcher: HTMLElement): () => void {
  if (prefersReducedMotion()) {
    return () => undefined;
  }

  const tween = gsap.to(launcher, {
    scale: 1.05,
    duration: 1.5,
    ease: "sine.inOut",
    repeat: -1,
    yoyo: true,
    delay: 2,
  });

  return () => {
    tween.kill();
    gsap.set(launcher, { scale: 1 });
  };
}

/** Exposed for tests, which need to assert the reduced-motion branch. */
export const _internal = { prefersReducedMotion };
