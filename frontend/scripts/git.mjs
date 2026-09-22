// Absolute path to `git`, resolved once from PATH's own directories (mirrors
// scripts/tracked.py's shutil.which) -- a gate then runs that resolved path,
// never the bare name "git" left for the child to look up. One copy for both
// gates, so the check cannot drift between them.
import { accessSync, constants, statSync } from "node:fs";
import { delimiter, resolve } from "node:path";

export function resolveGit() {
  const name = process.platform === "win32" ? "git.exe" : "git";
  for (const dir of (process.env.PATH ?? "").split(delimiter)) {
    if (!dir) continue;
    const candidate = resolve(dir, name);
    try {
      accessSync(candidate, constants.X_OK);
      // X_OK alone passes on an ordinary directory (its search/traverse bit),
      // so a PATH entry that is a directory named "git" would otherwise be
      // accepted here and crash the later execFileSync with EACCES -- the same
      // pitfall shutil.which's own _access_check guards against with
      // `not os.path.isdir(fn)`. This mirrors that check.
      if (!statSync(candidate).isDirectory()) return candidate;
    } catch {
      // not here; keep looking
    }
  }
  throw new Error("git is not on PATH; the gate cannot determine what a PR carries");
}
