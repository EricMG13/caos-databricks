// The served role, read-only at the sidebar's foot and never a control.
// Persona is composition, not authority.
import { sentence } from "./compose";
import type { ServedRole as ServedRoleWire } from "@/wire";

export function ServedRole({ role }: { role: ServedRoleWire }) {
  return (
    <div
      className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm group-data-[collapsible=icon]:justify-center group-data-[collapsible=icon]:px-0"
      data-served-role={role.standing ?? role.role}
      role="group"
      aria-label={`Served role: ${sentence(role.role)}, ${role.standing ? sentence(role.standing) : "no standing"}`}
    >
      <span
        aria-hidden="true"
        className="flex size-8 shrink-0 items-center justify-center rounded-full bg-sidebar-accent text-xs font-semibold text-sidebar-accent-foreground"
      >
        {role.role.charAt(0)}
      </span>
      <span
        className="grid min-w-0 leading-tight group-data-[collapsible=icon]:hidden"
        aria-hidden="true"
      >
        <span className="truncate font-medium">{sentence(role.role)}</span>
        <span className="truncate text-xs text-muted-foreground">
          {role.standing ? sentence(role.standing) : "No standing"}
        </span>
      </span>
    </div>
  );
}
