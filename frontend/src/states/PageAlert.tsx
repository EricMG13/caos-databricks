// The page-level alert: one sentence, never engine text (IA_SPEC.md 6).
export function PageAlert({ sentence }: { sentence: string }) {
  return (
    <div role="alert" className="pagealert" data-page-alert>
      {sentence}
    </div>
  );
}

/** The document on screen is still the server's, but it has stopped following
    the case: a refetch that did not answer, or an event tail the server
    refused (findings FE-2 and FE-3). Polite, not an alert -- nothing has gone
    wrong with what is being read, and nothing is asked of the reader. `mark`
    names which of the two, so a test and a reader read the same thing. */
export function NotLive({ mark, sentence }: { mark: "refresh" | "tail"; sentence: string }) {
  return (
    <div role="status" className="pagealert warn" data-not-live={mark}>
      {sentence}
    </div>
  );
}
