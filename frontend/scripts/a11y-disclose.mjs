// The disclosure a matrix route names (`disclose=<name>`), opened before the
// scan so what a reader who asks for it meets is what is scanned.
const DISCLOSURES = {
  // The signed record is closed by default (D107, F506).
  record: { root: "details[data-artifact-record-disclosure]", body: "pre" },
};

/** Opens the named disclosure on `page` and waits for its body to show. A name
    that is not known is a scan error, never a quiet scan of the closed control. */
export async function openDisclosure(page, name) {
  const known = Object.hasOwn(DISCLOSURES, name) ? DISCLOSURES[name] : null;
  if (known === null) throw new Error(`unknown disclosure "${name}"`);
  const disclosure = page.locator(known.root).first();
  await disclosure.locator("summary").click();
  await disclosure.locator(known.body).first().waitFor({ state: "visible", timeout: 15_000 });
}
