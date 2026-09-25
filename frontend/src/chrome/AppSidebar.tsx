// The only navigation: the nine sections, each with its count and its one-line
// state, then the section-local group; the case switcher heads it and the foot
// carries the served role and two refused controls (IA_SPEC.md 3), all inside
// the one landmark. On a phone the same sidebar is a sheet.
import { NavLink } from "react-router";
import {
  ChartSplineIcon,
  FileTextIcon,
  FileUpIcon,
  FolderOpenIcon,
  GavelIcon,
  LibraryIcon,
  LogOutIcon,
  MessageSquareIcon,
  RouteIcon,
  ScanSearchIcon,
  SettingsIcon,
} from "lucide-react";
import { CaseSwitcher } from "./CaseSwitcher";
import { ServedRole } from "./ServedRole";
import { SECTION_LABELS, isEnabledSection, sectionPath } from "@/app/sections";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
  useSidebar,
} from "@/components/ui/sidebar";
import { RefusedControl } from "@/controls/RefusedControl";
import {
  SECTIONS,
  type RailEntry,
  type RailLocal,
  type Section,
  type ServedRole as Role,
  type Subject,
} from "@/wire";

const ICONS: Record<Section, typeof RouteIcon> = {
  directory: FolderOpenIcon,
  upload: FileUpIcon,
  analysis: ScanSearchIcon,
  book: LibraryIcon,
  run: RouteIcon,
  model: ChartSplineIcon,
  report: FileTextIcon,
  committee: GavelIcon,
  admin: SettingsIcon,
};

const ASK_SCOPE: Record<Section, string> = {
  directory: "the register",
  upload: "the source pack",
  analysis: "this case",
  book: "the book",
  run: "this run",
  model: "the projection",
  report: "this revision",
  committee: "the deliverable",
  admin: "the deployment",
};

/** The foot's two controls, refused on every page: quiet, with no dashed edge
    to read as unfinished chrome, their reason on hover and focus (brief 5). */
const FOOT_CONTROL =
  "flex-1 justify-start aria-disabled:border-transparent group-data-[collapsible=icon]:size-8 group-data-[collapsible=icon]:p-0";

/** What a section entry says: the section, what it holds, and its one-line
    state. A section the document does not serve says only its name. */
export function railLabel(id: Section, entry: RailEntry | undefined): string {
  if (!entry) return SECTION_LABELS[id];
  const count = entry.count === null ? "" : `, ${entry.count}`;
  return `${SECTION_LABELS[id]}${count}, ${entry.state}`;
}

export function AppSidebar({
  section,
  entries,
  local,
  servedRole,
  searchFor,
  subject,
  caseId,
}: {
  section: Section | null;
  entries: RailEntry[] | null;
  local: RailLocal | null;
  servedRole: Role | null;
  /** The query each entry carries, so the case -- and the run and revision a
      section needs to open -- travels with the reader. */
  searchFor: (section: Section) => string;
  subject: Subject | null;
  caseId: string | null;
}) {
  const { setOpenMobile } = useSidebar();
  const byId = new Map((entries ?? []).map((entry) => [entry.section, entry]));
  const ask = section ? ASK_SCOPE[section] : "the workspace";
  return (
    <Sidebar collapsible="icon" variant="inset">
      <nav aria-label="Workspace" className="flex min-h-0 flex-1 flex-col">
        <SidebarHeader>
          <CaseSwitcher section={section} subject={subject} caseId={caseId} />
        </SidebarHeader>
        <SidebarContent>
          <SidebarGroup>
            <SidebarGroupLabel>Workspace</SidebarGroupLabel>
            <SidebarMenu>
              {SECTIONS.map((id) => {
                const entry = byId.get(id);
                const Icon = ICONS[id];
                // A section this deployment does not serve says so in words;
                // a served one needs none (its state is the link itself).
                const off = !isEnabledSection(id);
                return (
                  <SidebarMenuItem key={id}>
                    <SidebarMenuButton
                      render={
                        <NavLink
                          to={`${sectionPath(id)}${searchFor(id)}`}
                          onClick={() => setOpenMobile(false)}
                        />
                      }
                      isActive={id === section}
                      tooltip={
                        off && entry ? `${SECTION_LABELS[id]} · ${entry.state}` : SECTION_LABELS[id]
                      }
                      aria-label={railLabel(id, entry)}
                      data-section={id}
                      data-off={off || undefined}
                      className="data-off:text-muted-foreground"
                    >
                      <Icon />
                      <span>{SECTION_LABELS[id]}</span>
                      {off && entry ? (
                        <span className="ml-auto text-xs text-muted-foreground">{entry.state}</span>
                      ) : null}
                    </SidebarMenuButton>
                    {entry?.count != null ? (
                      <SidebarMenuBadge className="font-mono">{entry.count}</SidebarMenuBadge>
                    ) : null}
                  </SidebarMenuItem>
                );
              })}
            </SidebarMenu>
          </SidebarGroup>
          {local ? (
            <SidebarGroup role="group" aria-label={local.title}>
              <SidebarGroupLabel>{local.title}</SidebarGroupLabel>
              <SidebarMenu>
                {local.items.map((item) => (
                  <SidebarMenuItem
                    key={item.label}
                    data-on={item.on || undefined}
                    className="flex h-8 items-center gap-2 rounded-md px-2 text-sm group-data-[collapsible=icon]:hidden data-on:bg-sidebar-accent data-on:font-medium"
                  >
                    <span className="min-w-0 flex-1 truncate">{item.label}</span>
                    <span className="font-mono text-xs text-muted-foreground">{item.meta}</span>
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            </SidebarGroup>
          ) : null}
        </SidebarContent>
        <SidebarFooter>
          {servedRole ? <ServedRole role={servedRole} /> : null}
          <div className="flex gap-1 group-data-[collapsible=icon]:flex-col" data-sidebar-foot>
            <RefusedControl
              variant="ghost"
              size="sm"
              className={FOOT_CONTROL}
              reasonDisplay="tooltip"
              refusal={{
                code: "ASK_UNPLACED",
                // Its own reason, no longer borrowed from `ACTION_UNPLACED`'s:
                // there is no Ask route at all, which is a different thing from a
                // control the section's read cannot judge.
                clears: `the API serves an Ask route scoped to ${ask}`,
              }}
              aria-label={`Ask about ${ask}`}
            >
              <MessageSquareIcon />
              <span className="group-data-[collapsible=icon]:hidden">Ask</span>
            </RefusedControl>
            <RefusedControl
              variant="ghost"
              size="sm"
              className={FOOT_CONTROL}
              reasonDisplay="tooltip"
              refusal={{
                code: "SIGN_OUT_UNPLACED",
                clears:
                  "the authenticating proxy serves sign-out — this workspace holds no session of its own",
              }}
              aria-label="Sign out"
            >
              <LogOutIcon />
              <span className="group-data-[collapsible=icon]:hidden">Sign out</span>
            </RefusedControl>
          </div>
        </SidebarFooter>
        <SidebarRail />
      </nav>
    </Sidebar>
  );
}
