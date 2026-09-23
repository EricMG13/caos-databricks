import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { App } from "@/app/App";
import { UNAVAILABLE_WORDING } from "@/app/transport";
import { RefusedControl } from "@/controls/RefusedControl";
import { RegionState } from "@/states/RegionState";

describe("the states", () => {
  test("test_unavailable_and_absent_route_share_one_wording", () => {
    const { unmount } = render(
      <RegionState status={{ kind: "unavailable" }}>{() => <p>never</p>}</RegionState>,
    );
    expect(screen.getByText(UNAVAILABLE_WORDING)).toBeInTheDocument();
    expect(screen.queryByText("never")).toBeNull();
    unmount();
    window.history.pushState({}, "", "/nothing/");
    render(<App />);
    expect(screen.getByRole("main")).toHaveTextContent(UNAVAILABLE_WORDING);
    expect(UNAVAILABLE_WORDING).toBe("Unavailable or not permitted.");
  });

  test("test_observed_empty_requires_timestamp", () => {
    render(
      <RegionState
        status={{ kind: "observed-empty", observed_at: "2026-09-09T14:30:00Z", document: {} }}
      >
        {() => null}
      </RegionState>,
    );
    const region = screen.getByRole("status");
    expect(region).toHaveAttribute("data-surface-state", "observed-empty");
    expect(region.querySelector("time")).toHaveAttribute("datetime", "2026-09-09T14:30:00Z");
  });

  test("observed-empty still renders the section body, so an empty directory can create", () => {
    render(
      <RegionState
        status={{ kind: "observed-empty", observed_at: "2026-09-09T14:30:00Z", document: "d" }}
      >
        {(d) => <button type="button">create from {d}</button>}
      </RegionState>,
    );
    expect(document.querySelector("[data-surface-state='observed-empty']")).not.toBeNull();
    expect(screen.getByRole("button", { name: "create from d" })).toBeInTheDocument();
  });

  test("ready renders its children with no marker", () => {
    render(
      <RegionState status={{ kind: "ready", document: 1 }}>{(n) => <p>doc {n}</p>}</RegionState>,
    );
    expect(screen.getByText("doc 1")).toBeInTheDocument();
    expect(document.querySelector("[data-surface-state]")).toBeNull();
  });

  test("stale keeps the document on screen behind its marker", () => {
    render(
      <RegionState status={{ kind: "stale", document: "d" }} onReload={() => {}}>
        {(d) => <p>body {d}</p>}
      </RegionState>,
    );
    expect(document.querySelector("[data-surface-state='stale']")).not.toBeNull();
    expect(screen.getByText("body d")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "RELOAD" })).toBeInTheDocument();
  });

  test("test_refused_control_stays_visible_with_reason", () => {
    render(
      <MemoryRouter>
        <RefusedControl
          refusal={{ code: "APPROVER_NOT_INDEPENDENT", clears: "an independent approver files it" }}
          className="rb solid"
        >
          File
        </RefusedControl>
      </MemoryRouter>,
    );
    const control = screen.getByRole("button", { name: "File" });
    expect(control).toBeVisible();
    expect(control).toHaveAttribute("aria-disabled", "true");
    expect(control).not.toHaveAttribute("disabled");
    expect(control).toHaveAttribute("data-refusal", "APPROVER_NOT_INDEPENDENT");
    // The reason is named in plain words; the code rides in the detail.
    expect(control).toHaveAccessibleDescription("Available once an independent approver files it.");
    expect(control).toHaveAttribute("title", expect.stringContaining("APPROVER_NOT_INDEPENDENT"));
    expect(screen.getByText(/an independent approver files it/)).toBeVisible();
  });
});
