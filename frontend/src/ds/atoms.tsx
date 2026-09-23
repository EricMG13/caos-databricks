// Small shared atoms.

/** A labelled list of server strings, or the word "none": limitation flags,
    validation warnings. A `data-*` marker names the note for a test. */
export function NoteList({
  label,
  values,
  ...marks
}: {
  label: string;
  values: readonly string[];
  [mark: `data-${string}`]: string | boolean | undefined;
}) {
  return (
    <div className="note" {...marks}>
      <b>{label}</b> {values.length ? values.join(", ") : "none"}
    </div>
  );
}
