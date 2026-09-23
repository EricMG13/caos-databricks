// A chart's SVG is drawn at its container's real pixel width, never scaled by
// a viewBox, so its text stays at the type floors whatever the panel's size.
import { useLayoutEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { FALLBACK_WIDTH } from "./scale";

/** The width of the element `ref` is attached to, in whole CSS pixels, kept
    current by a ResizeObserver. Observed from a layout effect, whose first
    report lands before the first paint, and committed at once, so the chart
    never paints at the fallback and then jumps. Where there is no observer
    (jsdom) it stays at `fallback`, so the chart still draws. */
export function useWidth<T extends HTMLElement>(fallback: number = FALLBACK_WIDTH) {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(fallback);
  useLayoutEffect(() => {
    const node = ref.current;
    if (!node || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver((entries) => {
      const next = Math.floor(entries[0]?.contentRect.width ?? 0);
      if (next > 0) flushSync(() => setWidth(next));
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  return { ref, width };
}
