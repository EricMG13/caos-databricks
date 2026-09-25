// One treatment for an id or a digest wherever it is read (DESIGN.md "Numeric
// truth"; the 2026-09-25 brief, 6.1): mono, short on the page, whole in its
// title and to a screen reader, and one press from the clipboard. The short
// form is `shortDigest`'s, so a row in Directory and a card in Committee
// cannot drift apart.
import { useEffect, useRef, useState } from "react";
import { CheckIcon, CopyIcon } from "lucide-react";
import { shortDigest } from "./format";

/** How long "Copied" stays beside the control that copied. */
const SAID_MS = 1200;

/** Whether this browser can write the clipboard: a secure context with the
    async API. Where it cannot, no control is drawn that could only fail. */
function clipboard(): Clipboard | null {
  return typeof navigator !== "undefined" && navigator.clipboard ? navigator.clipboard : null;
}

export function Digest({
  value,
  prefix = "",
  fallback,
  copy = true,
}: {
  value: string | null;
  /** Printed before the value and copied with it (`sha256:`). */
  prefix?: string;
  /** What a missing value reads as ("not pinned"); `shortDigest`'s dash else. */
  fallback?: string;
  /** Filed output (the paper) quotes its digests and offers no control. */
  copy?: boolean;
}) {
  // What the last press did, said beside the control until SAID_MS passes.
  const [said, setSaid] = useState<"Copied" | "Not copied" | null>(null);
  const timer = useRef<number | null>(null);
  useEffect(
    () => () => {
      if (timer.current !== null) window.clearTimeout(timer.current);
    },
    [],
  );
  if (value === null) return <span className="digest">{shortDigest(null, fallback)}</span>;
  const whole = `${prefix}${value}`;
  const board = copy ? clipboard() : null;
  // A browser that refuses the write (permission, focus) is said to have, not
  // left looking as if the press did nothing.
  const answer = (words: "Copied" | "Not copied") => {
    setSaid(words);
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setSaid(null), SAID_MS);
  };
  const press = () => {
    if (board === null) return;
    board.writeText(whole).then(
      () => answer("Copied"),
      () => answer("Not copied"),
    );
  };
  const shown = (
    <>
      {prefix}
      {prefix ? <wbr /> : null}
      <span className="whitespace-nowrap">{shortDigest(value)}</span>
    </>
  );
  if (board === null) {
    return (
      <span className="digest" data-digest={whole}>
        <span className="font-mono" title={whole} aria-hidden="true">
          {shown}
        </span>
        <span className="sr-only">{whole}</span>
      </span>
    );
  }
  // The whole chip is the control, not an icon beside it: a 24px icon at a
  // card's edge lost its target size to a few pixels of sticky header.
  return (
    <span className="digest" data-digest={whole}>
      <button
        type="button"
        className="digest-copy"
        data-digest-copy=""
        title={whole}
        aria-label={`Copy ${whole}`}
        onClick={press}
      >
        <span className="font-mono">{shown}</span>
        {said === "Copied" ? <CheckIcon aria-hidden="true" /> : <CopyIcon aria-hidden="true" />}
      </button>
      {said ? (
        <span role="status" className="digest-said" data-said={said}>
          {said}
        </span>
      ) : null}
    </span>
  );
}
