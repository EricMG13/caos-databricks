// A section that throws while rendering becomes its region's typed error, and
// the workspace around it keeps drawing (brief 4.4, R4). Nothing of the thrown
// error is shown or logged: it may carry document-derived text.
import { Component, type ReactNode } from "react";
import { RegionState } from "./RegionState";

const RENDER_FAILED = {
  code: "RENDER_FAILED",
  clears: "the section can render the document it was given",
};

/** `resetOn` is what the failure was about — the workspace passes the
    document's `observed_at`. A boundary that latched until it was unmounted
    would keep refusing a document that renders perfectly well, so a changed
    `resetOn` is taken as a new attempt rather than as the same one. */
export class SectionBoundary extends Component<
  { children: ReactNode; resetOn?: string | number },
  { failed: boolean }
> {
  override state = { failed: false };

  static getDerivedStateFromError(): { failed: boolean } {
    return { failed: true };
  }

  override componentDidUpdate(previous: { resetOn?: string | number }) {
    if (this.state.failed && previous.resetOn !== this.props.resetOn) {
      this.setState({ failed: false });
    }
  }

  override render() {
    if (!this.state.failed) return this.props.children;
    return (
      <RegionState status={{ kind: "error", refusal: RENDER_FAILED }}>{() => null}</RegionState>
    );
  }
}
