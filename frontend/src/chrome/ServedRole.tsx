// The served role, read-only beside the rail and never a control. Persona is
// composition, not authority (IA_SPEC.md 2).
import type { ServedRole as ServedRoleWire } from "@/wire";

export function ServedRole({ role }: { role: ServedRoleWire }) {
  return (
    <div className="railrole" data-served-role={role.standing ?? role.role}>
      <span>SERVED ROLE</span>
      <span className="ro">
        {role.role} · {role.standing ?? "NO STANDING"}
      </span>
    </div>
  );
}
