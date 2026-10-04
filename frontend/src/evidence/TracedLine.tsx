// The whole evidence line a citation anchored in, its excerpt marked (D105).
// An excerpt is at least eight words of one line, so a qualifier just outside
// it -- "not", "provided that", a table row's label -- would be lost if the
// excerpt were shown alone (AI-4). Every surface that shows a host-verified
// citation shows it through this. The line is shown whole, however long: it is
// one evidence block, at most 4,096 characters, and it wraps.
//
// A record from before whole-line citations (`ANY_RUN`) holds no line: its
// quote is any run of its page, so it is shown as a quote, labelled so, and
// never marked or called a source line.
import type { LineView } from "@/wire/v1";

/** What a surface calls the text it shows for a citation. */
export const LINE_LABEL = "Source line · the cited excerpt marked";
export const QUOTE_LABEL = "Quote (source line not recorded)";

/** A quote with no line beside it: a surface whose shape carries none. What
    line it came from is not known here, so it is not recorded. */
export function wholeLine(quote: string): LineView {
  return { before: "", excerpt: quote, after: "", recorded: false };
}

/** The label for a citation's text: its source line, or a bare quote. */
export function lineLabel(line: LineView): string {
  return line.recorded ? LINE_LABEL : QUOTE_LABEL;
}

/** The text a label or an accessible name reads: the whole line where it is
    recorded, the quote where it is not. */
export function lineText(line: LineView): string {
  return line.recorded ? line.before + line.excerpt + line.after : line.excerpt;
}

export function TracedLine({ line }: { line: LineView }) {
  if (!line.recorded) return <>{line.excerpt}</>;
  return (
    <>
      {line.before}
      {line.excerpt ? <mark>{line.excerpt}</mark> : null}
      {line.after}
    </>
  );
}
