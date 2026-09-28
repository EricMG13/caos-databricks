import { act, renderHook } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { DocumentReadContext, useDocumentRefetch } from "@/app/useDocumentRefetch";

test.each([false, true])(
  "a queued parent render cannot replace a newer command result (failed: %s)",
  async (failed) => {
    const sequence = { current: 0 };
    const reads = {
      begin: () => (sequence.current += 1),
      isCurrent: (version: number) => version === sequence.current,
    };
    let version = 0;
    const { result, rerender } = renderHook(({ document }) => useDocumentRefetch(document), {
      initialProps: { document: "initial" },
      wrapper: ({ children }: PropsWithChildren) => (
        <DocumentReadContext.Provider value={{ reads, version }}>
          {children}
        </DocumentReadContext.Provider>
      ),
    });
    // Workspace has accepted read 1, but React has not committed its parent update.
    version = ++sequence.current;
    await act(async () => {
      expect(await result.current.refetch(async () => (failed ? null : "command"))).toBe(!failed);
    });
    rerender({ document: "parent" });
    expect(result.current.live).toBe(failed ? "initial" : "command");
    expect(result.current.failed).toBe(failed);
  },
);
