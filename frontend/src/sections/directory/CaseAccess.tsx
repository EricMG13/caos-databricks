// Case access (O21): who holds standing on each case, and the two membership
// commands. The register keeps its one action per row; membership is its own
// panel so a row still means "open this case". Members are served only to a
// case's ADMIN, the one member who may change them; everyone else is shown the
// two controls refused with the code the command would answer -- never hidden
// (CLAUDE.md "Persona is not authority"). The commands recheck at commit
// whatever this panel shows, and on success the section re-reads its own
// document, which is what says the membership changed.
import { useState } from "react";
import { grantStanding, revokeStanding } from "@/app/commands";
import { ConfirmedControl } from "@/controls/ConfirmedControl";
import { RefusedControl } from "@/controls/RefusedControl";
import { TextInput } from "@/ds/TextInput";
import { CommandOutcome, useCommand } from "@/sections/run/controls";
import type { ActionView, CaseRow, MemberRow, StandingGranted, StandingRevoked } from "@/wire/v1";

const STANDINGS = ["READER", "WRITER", "APPROVER", "ADMIN"] as const;
type Standing = (typeof STANDINGS)[number];

const actionOf = (row: CaseRow, name: ActionView["action"]) =>
  row.actions.find((view) => view.action === name);

function RevokeMember({
  caseId,
  member,
  action,
  onChanged,
}: {
  caseId: string;
  member: MemberRow | null;
  action: ActionView | undefined;
  onChanged: () => void;
}) {
  const { pending, result, run } = useCommand<StandingRevoked>();
  const refusal = action?.refusal ?? null;

  async function submit() {
    if (refusal || pending || !member) return;
    const outcome = await run(member.user_id, (intent) =>
      revokeStanding(caseId, member.user_id, intent),
    );
    if (outcome?.kind === "ok") onChanged();
  }

  return (
    <>
      {/* Ending a membership is a governed change with no reverse command on
          the v1 wire, so it asks once more and names the member (FE-7). */}
      <ConfirmedControl
        refusal={refusal}
        busy={pending}
        step={{
          act: "Revoke standing",
          subject: member ? `${member.user_id} on case ${caseId}` : `case ${caseId}`,
          digest: null,
        }}
        onConfirm={action && member ? () => void submit() : undefined}
        className="rb"
        action="REVOKE_STANDING"
        aria-label={member ? `Revoke ${member.user_id}` : "Revoke standing"}
      >
        {pending ? "Revoking…" : "Revoke"}
      </ConfirmedControl>
      <CommandOutcome result={result} success="Standing revoked. Reading the register back." />
    </>
  );
}

function GrantMember({
  caseId,
  action,
  onChanged,
}: {
  caseId: string;
  action: ActionView | undefined;
  onChanged: () => void;
}) {
  const [userId, setUserId] = useState("");
  const [standing, setStanding] = useState<Standing>("READER");
  const { pending, result, run } = useCommand<StandingGranted>();
  const refusal = action?.refusal ?? null;
  const inputId = `grant-user-${caseId}`;
  const selectId = `grant-standing-${caseId}`;

  async function submit() {
    const trimmed = userId.trim();
    if (refusal || pending || trimmed.length === 0) return;
    const outcome = await run({ trimmed, standing }, (intent) =>
      grantStanding(caseId, trimmed, standing, intent),
    );
    if (outcome?.kind !== "ok") return;
    setUserId("");
    onChanged();
  }

  return (
    <div className="fld" data-grant={caseId}>
      <label htmlFor={inputId}>Member id</label>
      <TextInput
        id={inputId}
        type="text"
        value={userId}
        placeholder="User id (UUID)"
        onChange={(event) => setUserId(event.target.value)}
      />
      <label htmlFor={selectId}>Standing</label>
      <select
        id={selectId}
        value={standing}
        onChange={(event) => setStanding(event.target.value as Standing)}
      >
        {STANDINGS.map((value) => (
          <option key={value} value={value}>
            {value}
          </option>
        ))}
      </select>
      <RefusedControl
        refusal={refusal}
        onClick={action ? () => void submit() : undefined}
        busy={pending}
        className="rb solid"
        reasonDisplay="inline"
        data-action="GRANT_STANDING"
        aria-label="Grant standing"
      >
        {pending ? "Granting…" : "Grant"}
      </RefusedControl>
      <CommandOutcome result={result} success="Standing granted. Reading the register back." />
    </div>
  );
}

function CaseMembers({ row, onChanged }: { row: CaseRow; onChanged: () => void }) {
  const revoke = actionOf(row, "REVOKE_STANDING");
  return (
    // A named group per case, so a screen reader hears which case a repeated
    // "Grant standing" or "Revoke" belongs to.
    <div
      className="access"
      data-access={row.case_id}
      role="group"
      aria-labelledby={`access-${row.case_id}`}
    >
      <h3 id={`access-${row.case_id}`}>{row.title}</h3>
      {row.members === null ? (
        <>
          <p className="note" data-members-withheld>
            Members are shown to the case&apos;s administrator. Your standing is {row.standing}.
          </p>
          <RevokeMember caseId={row.case_id} member={null} action={revoke} onChanged={onChanged} />
        </>
      ) : (
        <ul className="members">
          {row.members.map((member) => (
            <li key={member.user_id} data-member={member.user_id}>
              <span className="m">{member.user_id}</span> <span>{member.standing}</span>{" "}
              <RevokeMember
                caseId={row.case_id}
                member={member}
                action={revoke}
                onChanged={onChanged}
              />
            </li>
          ))}
        </ul>
      )}
      <GrantMember
        caseId={row.case_id}
        action={actionOf(row, "GRANT_STANDING")}
        onChanged={onChanged}
      />
    </div>
  );
}

export function CaseAccess({ rows, onChanged }: { rows: CaseRow[]; onChanged: () => void }) {
  if (rows.length === 0) return null;
  return (
    <section className="pnl" aria-labelledby="directory-access-heading">
      <header>
        <h2 id="directory-access-heading">Case access</h2>
        <span className="cp">WHO HOLDS STANDING ON EACH CASE</span>
      </header>
      <div className="pb">
        {rows.map((row) => (
          <CaseMembers key={row.case_id} row={row} onChanged={onChanged} />
        ))}
      </div>
    </section>
  );
}
