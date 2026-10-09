import { useReveal } from "../hooks/useReveal.js";

// Wraps a section so it fades/lifts in once scrolled into view. `stagger` cascades children.
export default function Reveal({
  as: Tag = "div",
  stagger = false,
  className = "",
  children,
  ...rest
}) {
  const ref = useReveal();
  const cls = [stagger ? "reveal-stagger" : "reveal", className].filter(Boolean).join(" ");
  return (
    <Tag ref={ref} className={cls} {...rest}>
      {children}
    </Tag>
  );
}
