// `documents.ts` (slice 4.1f, not owned here) exports only the four section
// document types and their bodies. These are the nested v1 shapes this
// section reads; derived from `V1_SHAPES` rather than duplicated by hand, so
// a schema change there is still one edit, not two.
import type { Infer } from "@/wire/v1/shape";
import type { V1_SHAPES } from "@/wire/v1/documents";

export type EdgeView = Infer<typeof V1_SHAPES.EdgeView>;
export type AttemptView = Infer<typeof V1_SHAPES.AttemptView>;
export type GateView = Infer<typeof V1_SHAPES.GateView>;
export type BlockedByView = Infer<typeof V1_SHAPES.BlockedByView>;
