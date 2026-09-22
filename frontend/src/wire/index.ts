import type { SectionDocument } from "./shared";

// Every enabled section -- Directory, Upload, Run, Analysis, Model, Report and
// Committee -- reads the v1 wire only (brief 4.1, decision 9; slices 4.1h-k
// and Phase 4). Book and Admin, the two unavailable in every mode, were
// reduced to their shells on the owner's D2 decision of 17 September 2026 and
// their legacy body types went with them, so no section has one left. What
// stays is the envelope: the legacy chrome fixtures those two still carry are
// what the chrome suite drives the rail and the ribbon over, and it reads
// `chrome` alone.
export type AnyDocument = SectionDocument<unknown>;

export * from "./shared";
