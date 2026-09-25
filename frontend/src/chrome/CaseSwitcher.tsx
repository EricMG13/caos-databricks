// The case the workspace is about, and the way to another one. The list is the
// directory's own read, asked for when the menu opens and never before: a page
// that is not switching cases sends nothing for it.
import { useRef, useState } from "react";
import { Link } from "react-router";
import { ChevronsUpDownIcon, FolderOpenIcon } from "lucide-react";
import { sectionPath } from "@/app/sections";
import { fetchSection } from "@/app/transport";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar";
import type { Section, Subject } from "@/wire";
import type { DirectoryDocument } from "@/wire/v1";

type Listed =
  | { kind: "idle" | "loading" | "failed" }
  | { kind: "ready"; cases: DirectoryDocument["body"]["cases"] };

/** A switch keeps the reader in the section they are on where it opens on a
    case alone; from Directory, Book, Report or Committee -- which need a
    portfolio, a run or a revision -- it lands on the case's analysis. */
const CASE_SECTIONS = new Set<Section>(["upload", "analysis", "run", "model"]);

export function caseTarget(section: Section | null, caseId: string): string {
  const where = section && CASE_SECTIONS.has(section) ? section : "analysis";
  return `${sectionPath(where)}?case=${encodeURIComponent(caseId)}`;
}

/** The switcher's two lines: the issuer's name and, beneath it, the listing
    its title carries ("Carvana Co. (NYSE: CVNA)") or else the case's short
    id -- never the title cut at the sidebar's width, since the whole of it is
    in the trail (brief 5, the chrome). */
export function switcherLines(
  issuer: string | null,
  caseId: string | null,
): { name: string; detail: string } {
  const short = caseId ? `Case ${caseId.slice(0, 8)}` : "Credit workspace";
  if (issuer === null) return { name: caseId ? "Case" : "CAOS", detail: short };
  const open = issuer.lastIndexOf(" (");
  const listing = open > 0 && issuer.endsWith(")") ? issuer.slice(open + 2, -1) : "";
  return listing.includes(":")
    ? { name: issuer.slice(0, open), detail: listing }
    : { name: issuer, detail: short };
}

export function CaseSwitcher({
  section,
  subject,
  caseId,
}: {
  section: Section | null;
  subject: Subject | null;
  caseId: string | null;
}) {
  const { isMobile, setOpenMobile } = useSidebar();
  const [listed, setListed] = useState<Listed>({ kind: "idle" });
  const flight = useRef<AbortController | null>(null);
  const open = (next: boolean) => {
    if (!next || flight.current || listed.kind === "ready") return;
    const controller = new AbortController();
    flight.current = controller;
    setListed({ kind: "loading" });
    void fetchSection("directory", { case: null, run: null, revision: null }, controller.signal)
      .then((status) =>
        setListed(
          "document" in status
            ? { kind: "ready", cases: (status.document as DirectoryDocument).body.cases }
            : { kind: "failed" },
        ),
      )
      .finally(() => {
        flight.current = null;
      });
  };
  const lines = switcherLines(subject?.issuer ?? null, caseId);
  const leave = () => setOpenMobile(false);
  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <DropdownMenu onOpenChange={open}>
          <DropdownMenuTrigger
            render={<SidebarMenuButton size="lg" className="data-popup-open:bg-sidebar-accent" />}
          >
            <span
              aria-hidden="true"
              className="flex aspect-square size-8 items-center justify-center rounded-lg bg-sidebar-primary font-mono text-sm font-semibold text-sidebar-primary-foreground"
            >
              C
            </span>
            <span className="grid min-w-0 flex-1 text-left leading-tight">
              <span className="sr-only">Switch case, now </span>
              <span className="truncate font-semibold" title={subject?.issuer}>
                {lines.name}
              </span>
              <span className="truncate text-xs text-muted-foreground">{lines.detail}</span>
            </span>
            <ChevronsUpDownIcon className="ml-auto text-muted-foreground" />
          </DropdownMenuTrigger>
          <DropdownMenuContent
            className="w-(--anchor-width) min-w-60"
            side={isMobile ? "bottom" : "right"}
            align="start"
            sideOffset={isMobile ? 4 : 8}
          >
            <DropdownMenuGroup>
              <DropdownMenuLabel>Cases</DropdownMenuLabel>
              {listed.kind === "ready" ? (
                listed.cases.length ? (
                  listed.cases.map((row) => (
                    <DropdownMenuItem
                      key={row.case_id}
                      render={<Link to={caseTarget(section, row.case_id)} onClick={leave} />}
                      data-case-option={row.case_id}
                    >
                      <span className="min-w-0 flex-1 truncate">{row.title}</span>
                      {row.case_id === caseId ? (
                        <span className="text-xs text-muted-foreground">Open</span>
                      ) : null}
                    </DropdownMenuItem>
                  ))
                ) : (
                  <p className="px-1.5 py-1 text-sm text-muted-foreground">
                    You hold standing on no case yet.
                  </p>
                )
              ) : (
                <p className="px-1.5 py-1 text-sm text-muted-foreground" role="status">
                  {listed.kind === "failed" ? "The case list did not load." : "Reading cases…"}
                </p>
              )}
            </DropdownMenuGroup>
            <DropdownMenuSeparator />
            <DropdownMenuItem render={<Link to={sectionPath("directory")} onClick={leave} />}>
              <FolderOpenIcon />
              All cases
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </SidebarMenuItem>
    </SidebarMenu>
  );
}
