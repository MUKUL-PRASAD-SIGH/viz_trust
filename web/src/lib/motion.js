// CSS media queries do not stop requestAnimationFrame, so every JS tween checks this first.
export function prefersReducedMotion() {
  return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
}
