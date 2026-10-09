import { useEffect, useRef, useState } from "react";
import { prefersReducedMotion } from "../lib/motion.js";

const FADE_MS = 300;

// Fades the old rendering out and the new one in, in the same spot, when `value` changes.
export default function Crossfade({ value, render }) {
  const [leaving, setLeaving] = useState(null);
  const [entered, setEntered] = useState(false);
  const previous = useRef(value);

  useEffect(() => {
    if (previous.current === value) return undefined;
    const old = previous.current;
    previous.current = value;
    if (prefersReducedMotion()) return undefined;

    setLeaving(old);
    setEntered(true);
    const done = setTimeout(() => setLeaving(null), FADE_MS);
    return () => clearTimeout(done);
  }, [value]);

  return (
    <span className="xfade">
      {leaving !== null && (
        <span className="xfade-layer xfade-leave" aria-hidden="true">
          {render(leaving)}
        </span>
      )}
      <span key={value} className={`xfade-layer ${entered ? "xfade-enter" : ""}`}>
        {render(value)}
      </span>
    </span>
  );
}
