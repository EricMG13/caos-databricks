import { createContext, useState, type Dispatch, type ReactNode, type SetStateAction } from "react";

export const DraftContext = createContext<{
  draft: string;
  setDraft: Dispatch<SetStateAction<string>>;
} | null>(null);

export function ReportDraftProvider({ children }: { children: ReactNode }) {
  const [draft, setDraft] = useState("");
  return <DraftContext.Provider value={{ draft, setDraft }}>{children}</DraftContext.Provider>;
}
