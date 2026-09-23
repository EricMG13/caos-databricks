// The qualification label is separate from a section's conclusion: it binds a
// global performed-evidence identity, which the URL must name exactly.
import { useEffect, useState } from "react";
import { fetchQualification, type QualificationStatus } from "@/app/transport";
import { SEVERITY_BADGE, SeverityMark, toneOf } from "./SeverityMark";
import { sentence } from "./compose";
import { Badge } from "@/components/ui/badge";
import type { Severity } from "@/wire";

const HASH = /^[0-9a-f]{64}$/;

function display(status: QualificationStatus | null): {
  label: string;
  sentence: string;
  severity: Severity;
} {
  if (status === null)
    return { label: "LOADING", sentence: "Reading qualification.", severity: "RUNNING" };
  if (status.kind === "offline") {
    return {
      label: "OFFLINE",
      sentence: "Qualification status did not reach the server.",
      severity: "CRITICAL",
    };
  }
  if (status.kind === "unavailable") {
    return {
      label: "UNAVAILABLE",
      sentence: "Qualification evidence is unavailable.",
      severity: "IDLE",
    };
  }
  if (status.kind === "error") {
    return { label: "UNAVAILABLE", sentence: status.refusal.clears, severity: "CRITICAL" };
  }
  const { state, expires_at: expiresAt } = status.document;
  if (state === "QUALIFIED") {
    return {
      label: state,
      sentence: `Current authenticated review expires ${expiresAt ?? "unavailable"}.`,
      severity: "SUCCESS",
    };
  }
  if (state === "RESTRICTED") {
    return {
      label: state,
      sentence: "Qualification metadata requires an analyst role.",
      severity: "WARNING",
    };
  }
  if (state === "UNAVAILABLE") {
    return {
      label: state,
      sentence: "Qualification evidence cannot be verified.",
      severity: "CRITICAL",
    };
  }
  return {
    label: state,
    sentence: "No current authenticated review binds this exact evidence.",
    severity: "WARNING",
  };
}

export function QualificationStrip({ evidenceSha256 }: { evidenceSha256: string | null }) {
  const bound = evidenceSha256 !== null && HASH.test(evidenceSha256);
  const [held, setHeld] = useState<{ evidenceSha256: string; status: QualificationStatus } | null>(
    null,
  );

  useEffect(() => {
    if (!bound || evidenceSha256 === null) return undefined;
    const controller = new AbortController();
    void fetchQualification(evidenceSha256, controller.signal).then((status) => {
      if (!controller.signal.aborted) setHeld({ evidenceSha256, status });
    });
    return () => controller.abort();
  }, [bound, evidenceSha256]);

  const status = held?.evidenceSha256 === evidenceSha256 ? held.status : null;
  if (!bound) return null;
  const view = display(status);
  return (
    <section
      className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl bg-card px-4 py-3 text-sm ring-1 ring-foreground/10"
      aria-label="Qualification"
      data-tone={toneOf(view.severity)}
    >
      <Badge variant={SEVERITY_BADGE[view.severity]} className="gap-1.5">
        <SeverityMark severity={view.severity} pulse decorative />
        {sentence(view.label)}
      </Badge>
      <span className="text-pretty">{view.sentence}</span>
    </section>
  );
}
