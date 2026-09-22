// The snapshot-binding ledger a section reads through: one accepted snapshot
// per compared case on screen (IA_SPEC.md 5). It outlives the documents a
// section renders, so a later document carrying a different snapshot for a
// bound case is refused, and only an explicit lens switch moves the binding.
import { createContext, useContext, useMemo, useRef, type ReactNode } from "react";
import { INITIAL, bind, release, type Authority } from "./authority";
import type { Refusal } from "@/wire";

export interface Ledger {
  /** Bind a case to a snapshot; the refusal when it is already bound elsewhere. */
  bind(caseId: string, snapshot: string): Refusal | null;
  /** The explicit lens switch: forget the binding so the next bind takes. */
  release(caseId: string): void;
}

const Context = createContext<Ledger | null>(null);

export function LedgerProvider({ children }: { children: ReactNode }) {
  const authority = useRef<Authority>(INITIAL);
  const ledger = useMemo<Ledger>(
    () => ({
      bind(caseId, snapshot) {
        const bound = bind(authority.current, caseId, snapshot);
        authority.current = bound.authority;
        return bound.refusal;
      },
      release(caseId) {
        authority.current = release(authority.current, caseId);
      },
    }),
    [],
  );
  return <Context.Provider value={ledger}>{children}</Context.Provider>;
}

export function useLedger(): Ledger {
  const ledger = useContext(Context);
  if (!ledger) throw new Error("useLedger outside a LedgerProvider");
  return ledger;
}
