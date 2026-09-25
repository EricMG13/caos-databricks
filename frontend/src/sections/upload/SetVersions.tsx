// Set versions are immutable (IA_SPEC.md 4.2). The v1 wire carries no pin
// state or pinning action -- pinning is a governed command, out of scope for
// 4.1 (brief 4.1, decision 5: "4.1 has no actions") -- so this panel lists
// each version's fingerprint and member count and nothing more.
import type { UploadDocument } from "@/wire/v1";

/** Not exported by `@/wire/v1` on its own; the shape lives only on `UploadBody`. */
type SetVersion = UploadDocument["body"]["set_versions"][number];

export function SetVersions({ versions }: { versions: SetVersion[] }) {
  return (
    <section className="pnl" aria-labelledby="set-versions-heading" data-set-versions>
      <header>
        <h2 id="set-versions-heading">Set versions</h2>
        <span className="cp">Immutable</span>
        <span className="right">
          <span className="tag">
            {versions.length} {versions.length === 1 ? "version" : "versions"}
          </span>
        </span>
      </header>
      <div className="pb flush">
        {versions.map((version) => (
          <div key={version.version} className="setrow" data-set-version={version.version}>
            <span className="nm">Version {version.version}</span>
            <span className="mt">
              {version.member_count} {version.member_count === 1 ? "source" : "sources"} ·{" "}
              <code title={version.fingerprint}>{version.fingerprint.slice(0, 12)}</code>
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}
