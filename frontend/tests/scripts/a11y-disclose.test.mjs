import assert from "node:assert/strict";
import test from "node:test";
import { openDisclosure } from "../../scripts/a11y-disclose.mjs";

function pageRecording() {
  const log = [];
  const locator = (path) => ({
    first: () => locator([...path, "first"]),
    locator: (selector) => locator([...path, selector]),
    click: async () => log.push(["click", ...path]),
    waitFor: async (options) => log.push(["waitFor", ...path, options]),
  });
  return { page: { locator: (selector) => locator([selector]) }, log };
}

test("the record disclosure is opened by its summary, then its body awaited", async () => {
  const { page, log } = pageRecording();
  await openDisclosure(page, "record");
  const root = "details[data-artifact-record-disclosure]";
  assert.deepEqual(log, [
    ["click", root, "first", "summary"],
    ["waitFor", root, "first", "pre", "first", { state: "visible", timeout: 15_000 }],
  ]);
});

test("an unknown disclosure is a scan error that touches nothing", async () => {
  const { page, log } = pageRecording();
  await assert.rejects(openDisclosure(page, "nope"), /unknown disclosure "nope"/);
  await assert.rejects(openDisclosure(page, "toString"), /unknown disclosure "toString"/);
  assert.deepEqual(log, []);
});
