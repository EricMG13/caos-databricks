// Static export: one SPA build, copied to dist/<slug>/index.html for the nine
// trailing-slash section URLs and for every pre-v2 slug, so a static host
// serves the workspace at each path and the router owns the forward. No Node
// in production.
import { copyFile, mkdir, readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const output = process.argv[2];
if (!new Set(["dist", "dist-demo"]).has(output)) {
  throw new Error("output directory must be dist or dist-demo");
}
const DIST = fileURLToPath(new URL(`../${output}/`, import.meta.url));
const ROUTES = fileURLToPath(new URL("../src/app/routes.json", import.meta.url));

const { sections, forwards } = JSON.parse(await readFile(ROUTES, "utf8"));
const slugs = [...sections, ...Object.keys(forwards)].map((path) => path.replace(/^\/|\/$/g, ""));
if (slugs.length < 9) throw new Error(`expected nine sections, found ${slugs.length}`);

for (const slug of slugs) {
  await mkdir(`${DIST}${slug}`, { recursive: true });
  await copyFile(`${DIST}index.html`, `${DIST}${slug}/index.html`);
}
console.log(`exported ${slugs.length} routes`);
