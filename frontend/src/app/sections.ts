// The nine sections and the forwarding table. A pre-v2 slug
// forwards to its new home with the query string intact, replacing history so
// the entry stays router-owned.
import routes from "./routes.json";
import { SECTIONS, type Section } from "@/wire/shared";

/** The sections served in every mode (brief 4.1, decision 9). Admin renders
    `unavailable` with no request and no event tail, demo included. Book joined
    them when `/api/v1/book` began serving real accepted CP-CF projections
    (`tests/test_book_section.py`); it is the one section beside Directory that
    is about no single case. */
export const ENABLED_SECTIONS = [
  "directory",
  "upload",
  "run",
  "analysis",
  "book",
  "model",
  "report",
  "committee",
] as const;
export type EnabledSection = (typeof ENABLED_SECTIONS)[number];

export function isEnabledSection(section: Section): section is EnabledSection {
  return (ENABLED_SECTIONS as readonly string[]).includes(section);
}

export const SECTION_LABELS: Record<Section, string> = {
  directory: "Directory",
  upload: "Upload",
  analysis: "Analysis",
  book: "Book",
  run: "Run",
  model: "Model",
  report: "Report",
  committee: "Committee",
  admin: "Admin",
};

/** The one word per section a strip rail shows at 1024 px. */
export const SECTION_ABBREVIATIONS: Record<Section, string> = {
  directory: "Di",
  upload: "Up",
  analysis: "An",
  book: "Bk",
  run: "Rn",
  model: "Md",
  report: "Rp",
  committee: "Cm",
  admin: "Ad",
};

/** The revision a link to Committee carries from a document that lists them:
    the displayed one once it is frozen or filed, else the newest that is, else
    none -- Committee reads nothing else, so an unfrozen one would only refuse.
    The list is newest first, as the read serves it. */
export function committeeRevisionOf(
  revisions: readonly { revision_id: string; state: string }[],
  displayed: string | null,
): string | null {
  const ready = revisions.filter((revision) => revision.state !== "saved");
  const shown = ready.find((revision) => revision.revision_id === displayed);
  return (shown ?? ready[0])?.revision_id ?? null;
}

export function sectionPath(section: Section): string {
  return `/${section}/`;
}

export function sectionFromPath(pathname: string): Section | null {
  const match = /^\/([a-z-]+)\/$/.exec(pathname);
  const slug = match?.[1];
  return slug && (SECTIONS as readonly string[]).includes(slug) ? (slug as Section) : null;
}

const FORWARDS: Record<string, string> = routes.forwards;
const RENAMES: Record<string, Record<string, string>> = routes.query_renames;

export interface Forward {
  to: string;
  replace: true;
}

/** The query with a slug's renames applied; untouched when there are none. */
function renamed(search: string, renames: Record<string, string> | undefined): string {
  if (!renames) return search;
  const params = new URLSearchParams(search);
  for (const [from, to] of Object.entries(renames)) {
    const value = params.get(from);
    if (value !== null) {
      params.delete(from);
      params.set(to, value);
    }
  }
  const query = params.toString();
  return query ? `?${query}` : "";
}

// Trailing slashes stripped by hand rather than `/\/+$/` — SonarQube flags
// that shape as super-linear (typescript:S8786) though it cannot backtrack;
// the loop reads the same and draws no such flag.
function stripTrailingSlashes(pathname: string): string {
  let end = pathname.length;
  while (end > 0 && pathname[end - 1] === "/") end -= 1;
  return pathname.slice(0, end);
}

/** Where a pathname forwards, with its query carried over, or null. */
export function forward(pathname: string, search: string): Forward | null {
  if (sectionFromPath(pathname)) return null;
  const bare = stripTrailingSlashes(pathname) || "/";
  // Root → Directory; a listed slug → its home; a section without its
  // trailing slash → the same section. Anything else is absent.
  const target =
    bare === "/" ? "/directory/" : (FORWARDS[bare] ?? (sectionFromPath(`${bare}/`) && `${bare}/`));
  if (!target) return null;
  return { to: `${target}${renamed(search, RENAMES[bare])}`, replace: true };
}
