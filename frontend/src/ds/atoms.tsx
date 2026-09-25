// Small shared atoms.

/** A labelled list of server strings, or the word "none" -- limitation flags,
    validation warnings -- as a label row of the card's own `dl.kv`, so a card
    reads one label style rather than label rows and bold-led lines (brief
    6.9). Server strings break inside a token only where one cannot fit, so a
    long flag never sets the list's width. A `data-*` marker names the value
    for a test. */
export function NoteRows({
  label,
  values,
  ...marks
}: {
  label: string;
  values: readonly string[];
  [mark: `data-${string}`]: string | boolean | undefined;
}) {
  return (
    <>
      <dt>{label}</dt>
      <dd className="wrap" {...marks}>
        {values.length ? values.join(", ") : "none"}
      </dd>
    </>
  );
}
