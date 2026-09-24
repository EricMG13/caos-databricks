// Section → view. Each view receives the section's whole document and the
// active tab id; it composes the body and nothing above it.
//
// Each view is its own chunk (N65): a first load fetches the shell and the
// section on screen, not all nine. The workspace asks for the chunk when it
// asks for the document (`preloadView`), so the two travel together rather
// than one after the other.
import { lazy, type ComponentType } from "react";
import { ViewNotLoaded } from "@/states/SectionBoundary";
import type { Section } from "@/wire";
import type {
  AnalysisDocument,
  BookDocument,
  CommitteeDocument,
  DirectoryDocument,
  ModelDocument,
  ReportDocument,
  RunSectionDocument,
  UploadDocument,
} from "@/wire/v1";

/** Each enabled section's v1 document, by section. */
interface V1Documents {
  directory: DirectoryDocument;
  book: BookDocument;
  upload: UploadDocument;
  run: RunSectionDocument;
  analysis: AnalysisDocument;
  model: ModelDocument;
  report: ReportDocument;
  committee: CommitteeDocument;
}

/** Admin is unavailable in every mode and is never mounted with a document,
    so `never` is what its shell is typed on (decision D2). Book left that set
    when the section began rendering real accepted projections. */
export type DocumentFor<S extends Section> = S extends keyof V1Documents ? V1Documents[S] : never;

type ViewFor<S extends Section> = ComponentType<{ document: DocumentFor<S>; tab: string | null }>;

/** Each view's chunk, typed on exactly its own document, so a section wired
    to the wrong parser is a compile error here rather than a render error
    later. A second call returns the module the first one loaded. */
const LOADERS: { [S in Section]: () => Promise<ViewFor<S>> } = {
  directory: () => import("@/sections/directory/DirectorySection").then((m) => m.DirectorySection),
  upload: () => import("@/sections/upload/UploadSection").then((m) => m.UploadSection),
  analysis: () => import("@/sections/analysis/AnalysisSection").then((m) => m.AnalysisSection),
  book: () => import("@/sections/book/BookSection").then((m) => m.BookSection),
  run: () => import("@/sections/run/RunSection").then((m) => m.RunSection),
  model: () => import("@/sections/model/ModelSection").then((m) => m.ModelSection),
  report: () => import("@/sections/report/ReportSection").then((m) => m.ReportSection),
  committee: () => import("@/sections/committee/CommitteeSection").then((m) => m.CommitteeSection),
  admin: () => import("@/sections/admin/AdminSection").then((m) => m.AdminSection),
};

/** A view that loads its code when first mounted and asks again after a
    failure (W7 of the API review). React keeps a failed lazy view's error
    for good, and a section boundary retrying re-renders the element it
    already holds, so the component it names must stay the same: this one
    does, and draws the current lazy view. A failure throws `ViewNotLoaded`
    carrying `retry`, which puts a fresh lazy view in place; only the section
    boundary calls it, on "Try again" or the next document. Not on its own:
    React re-renders a suspended view when its load settles, and a fresh one
    there would ask again at once, and again, for a file that is gone. */
export function retryingView<P extends object>(
  load: () => Promise<ComponentType<P>>,
): ComponentType<P> {
  const fresh = () =>
    lazy(() =>
      load().then(
        (view) => ({ default: view }),
        () => {
          throw new ViewNotLoaded(() => {
            current = fresh();
          });
        },
      ),
    );
  let current = fresh();
  return function RetryingView(props: P) {
    const Current = current;
    return <Current {...props} />;
  };
}

function lazyView<S extends Section>(section: S): ViewFor<S> {
  return retryingView(LOADERS[section]) as ViewFor<S>;
}

/** The views the workspace mounts, each suspending until its chunk is in.
    The workspace erases the key at its one lookup site. */
export const SECTION_VIEWS: { [S in Section]: ViewFor<S> } = {
  directory: lazyView("directory"),
  upload: lazyView("upload"),
  analysis: lazyView("analysis"),
  book: lazyView("book"),
  run: lazyView("run"),
  model: lazyView("model"),
  report: lazyView("report"),
  committee: lazyView("committee"),
  admin: lazyView("admin"),
};

/** Start fetching a section's chunk; what `SECTION_VIEWS` then mounts is the
    module this loaded. A failed fetch is left for the mount to meet, where the
    section boundary shows it; the promise only says the attempt settled. */
export function preloadView(section: Section): Promise<void> {
  return LOADERS[section]().then(
    () => undefined,
    () => undefined,
  );
}
