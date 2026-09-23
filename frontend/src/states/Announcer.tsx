// One polite live region per section, mounted for as long as the section is
// (finding FE-6, WCAG 4.1.3). A region inserted already populated is announced
// inconsistently, so the region is always there and only its sentence changes:
// a command that succeeded, a run that reached a terminal state, a tail that
// stopped being live. Failures keep their own role=alert beside the control
// that caused them; this region is for the changes nothing else announces.
import { createContext, useCallback, useContext, useState, type ReactNode } from "react";

/** Say one sentence in the section's live region. Outside a provider it says
    nothing, so a control rendered on its own still renders. */
const Context = createContext<(sentence: string) => void>(() => {});

export function useAnnouncer(): (sentence: string) => void {
  return useContext(Context);
}

export function Announcer({ children }: { children: ReactNode }) {
  // Each saying is its own node. A sentence equal to the one already there --
  // the subject pinned a second time, a preview read again -- would otherwise
  // leave the region untouched, and a region that does not change is not
  // announced: the second success would be as silent as a failure (DF-6).
  const [said, setSaid] = useState({ sentence: "", count: 0 });
  const say = useCallback(
    (sentence: string) => setSaid((current) => ({ sentence, count: current.count + 1 })),
    [],
  );
  return (
    <Context.Provider value={say}>
      <div className="sr-only" role="status" aria-live="polite" data-announcer>
        {said.sentence ? <span key={said.count}>{said.sentence}</span> : null}
      </div>
      {children}
    </Context.Provider>
  );
}
