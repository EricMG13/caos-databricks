import type { KeyboardEvent } from "react";

/** Keyboard scroll makes static, wide canonical text reachable in every
    browser: a focused `<pre>` pans by arrow key where a pointer would drag. */
export function scrollArtifact(event: KeyboardEvent<HTMLPreElement>): void {
  if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
    event.preventDefault();
    event.currentTarget.scrollBy({ left: event.key === "ArrowRight" ? 40 : -40 });
  }
}
