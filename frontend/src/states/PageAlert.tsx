// The page-level alert: one sentence, never engine text (IA_SPEC.md 6).
export function PageAlert({ sentence }: { sentence: string }) {
  return (
    <div role="alert" className="pagealert" data-page-alert>
      {sentence}
    </div>
  );
}
