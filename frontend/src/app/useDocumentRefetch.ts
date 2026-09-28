import { createContext, useCallback, useContext, useLayoutEffect, useRef, useState } from "react";

/** Workspace and command reads share a request order. */
export const DocumentReadContext = createContext<{
  reads: { begin: () => number; isCurrent: (version: number) => boolean };
  version: number;
} | null>(null);

/** Null means the read was superseded or its view was unmounted. */
export type DocumentRefetch<T> = (load: () => Promise<T | null>) => Promise<boolean | null>;

/** A later request supersedes earlier reads, regardless of which finishes first. */
export function useDocumentRefetch<T>(initial: T) {
  const order = useContext(DocumentReadContext);
  const reads = order?.reads;
  const localSequence = useRef(0);
  const [live, setLive] = useState({
    document: initial,
    version: order?.version ?? 0,
    failed: false,
  });
  const [seen, setSeen] = useState(initial);
  if (initial !== seen) {
    setSeen(initial);
    // A parent update already queued before a command read may render after it.
    if (order === null || order.version >= live.version) {
      setLive({ document: initial, version: order?.version ?? 0, failed: false });
    }
  }
  const mounted = useRef(false);
  useLayoutEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      // Leaving this reader cancels its commands, not a Workspace read in flight.
      localSequence.current += 1;
    };
  }, [reads]);
  useLayoutEffect(() => {
    // Standalone sections have no Workspace request ticket; a new prop is authoritative.
    if (!reads) localSequence.current += 1;
  }, [initial, reads]);
  const refetch: DocumentRefetch<T> = useCallback(
    async (load) => {
      if (!mounted.current) return null;
      const lifecycle = (localSequence.current += 1);
      const version = reads?.begin() ?? lifecycle;
      const next = await load();
      if (lifecycle !== localSequence.current || (reads && !reads.isCurrent(version))) return null;
      setLive((current) => ({
        document: next ?? current.document,
        version,
        failed: next === null,
      }));
      return next !== null;
    },
    [reads],
  );
  return { live: live.document, failed: live.failed, refetch };
}
