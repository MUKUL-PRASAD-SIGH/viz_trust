import { useEffect, useRef } from "react";
import { prefersReducedMotion } from "../lib/motion.js";

// Counts from the last shown value (or `from` on first mount) to `value`: 500ms, ease-out.
// Frames write the text node directly instead of going through React state: 60 renders a
// second for one number is wasteful, and the final value must land even when frames stall.
export default function AnimatedNumber({ value, from, duration = 500 }) {
  const element = useRef(null);
  const shown = useRef(from ?? value);
  const initialText = useRef(String(from ?? value)); // React renders this once, never again

  useEffect(() => {
    const node = element.current;
    const start = shown.current;
    const paint = (n) => {
      shown.current = n;
      node.textContent = String(n);
    };
    if (start === value) return undefined;
    if (prefersReducedMotion()) {
      paint(value);
      return undefined;
    }

    const began = performance.now();
    let frame;
    const step = (now) => {
      // rAF timestamps can predate `began`; clamp so the tween never runs backwards.
      const t = Math.max(0, Math.min(1, (now - began) / duration));
      paint(Math.round(start + (value - start) * (1 - Math.pow(1 - t, 3))));
      if (t < 1) frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    // Frames pause in background tabs; always land on the real number.
    const settle = setTimeout(() => paint(value), duration + 100);

    return () => {
      cancelAnimationFrame(frame);
      clearTimeout(settle);
    };
  }, [value, duration]);

  return (
    <span ref={element} className="tabular">
      {initialText.current}
    </span>
  );
}
