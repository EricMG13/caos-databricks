// The whole evidence line a citation anchored in, its excerpt marked (D105).
// An excerpt is at least eight words of one line, so a qualifier just outside
// it -- "not", "provided that", a table row's label -- would be lost if the
// excerpt were shown alone (AI-4). Every surface that shows a host-verified
// citation shows it through this. The line is shown whole, however long: it is
// one evidence block, at most 4,096 characters, and it wraps.
import type { LineView } from "@/wire/v1";

/** A quote with no line beside it is its own line: a citation from before
    excerpts, or a surface whose shape predates the line. */
export function wholeLine(quote: string): LineView {
  return { before: "", excerpt: quote, after: "" };
}

export function TracedLine({ line }: { line: LineView }) {
  return (
    <>
      {line.before}
      {line.excerpt ? <mark>{line.excerpt}</mark> : null}
      {line.after}
    </>
  );
}
