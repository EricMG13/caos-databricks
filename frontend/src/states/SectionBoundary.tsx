// A section that throws while rendering becomes its region's typed error, and
// the workspace around it keeps drawing (brief 4.4, R4). Nothing of the thrown
// error is shown or logged: it may carry document-derived text.
import { Component, type ReactNode } from "react";
import { RegionState } from "./RegionState";

const RENDER_FAILED = {
  code: "RENDER_FAILED",
  clears: "the section can render the document it was given",
};

/** Thrown when a section view's code did not load (N65's lazy views): a
    dropped connection, or a deploy that replaced the files an open page
    asked for. Not the document's fault, so the boundary says what will
    clear it rather than blame the document. `retry` readies the view to ask
    for its code again; the boundary calls it before it draws the view anew. */
export class ViewNotLoaded extends Error {
  constructor(readonly retry: () => void = () => undefined) {
    super("a section view's code did not load");
  }
}

/** The first failure is worth another try: a dropped connection passes. */
const VIEW_NOT_LOADED = {
  code: "VIEW_NOT_LOADED",
  clears: "it is tried again",
};
/** A second in a row is a stale page: a deploy removed the files this page
    names, and only a reload fetches the ones that replaced them. */
const VIEW_STALE = {
  code: "VIEW_NOT_LOADED",
  clears: "the page is reloaded",
};

interface State {
  failed: "render" | "load" | null;
  /** Readies a view that did not load to ask again (`ViewNotLoaded.retry`). */
  retry: (() => void) | null;
  loadFailures: number;
}

/** `resetOn` is what the failure was about — the workspace passes the
    document's `observed_at`. A boundary that latched until it was unmounted
    would keep refusing a document that renders perfectly well, so a changed
    `resetOn` is taken as a new attempt rather than as the same one. */
export class SectionBoundary extends Component<
  { children: ReactNode; resetOn?: string | number },
  State
> {
  override state: State = { failed: null, retry: null, loadFailures: 0 };

  static getDerivedStateFromError(error: unknown): Partial<State> {
    return error instanceof ViewNotLoaded
      ? { failed: "load", retry: error.retry }
      : { failed: "render", retry: null };
  }

  override componentDidCatch(error: unknown) {
    if (error instanceof ViewNotLoaded) {
      this.setState((state) => ({ loadFailures: state.loadFailures + 1 }));
    }
  }

  override componentDidUpdate(previous: { resetOn?: string | number }) {
    if (this.state.failed && previous.resetOn !== this.props.resetOn) {
      this.state.retry?.();
      this.setState({ failed: null, retry: null, loadFailures: 0 });
    }
  }

  private readonly tryAgain = () => {
    this.state.retry?.();
    this.setState({ failed: null, retry: null });
  };

  override render() {
    const { failed, loadFailures } = this.state;
    if (!failed) return this.props.children;
    if (failed === "render") {
      return (
        <RegionState status={{ kind: "error", refusal: RENDER_FAILED }}>{() => null}</RegionState>
      );
    }
    const stale = loadFailures >= 2;
    return (
      <RegionState
        status={{ kind: "error", refusal: stale ? VIEW_STALE : VIEW_NOT_LOADED }}
        onRetry={stale ? undefined : this.tryAgain}
        onReload={stale ? () => window.location.reload() : undefined}
      >
        {() => null}
      </RegionState>
    );
  }
}
