// Only this engine failure at navigation is retryable. Readiness, axe and
// layout checks remain outside this helper and retain their original verdicts.
const WEBKIT_INTERNAL_ERROR = /^page\.goto: WebKit encountered an internal error(?:\r?\n|$)/;

export async function gotoWithInternalErrorRetry(page, url, options) {
  try {
    return await page.goto(url, options);
  } catch (error) {
    const retryable =
      error instanceof Error && error.name === "Error" && WEBKIT_INTERNAL_ERROR.test(error.message);
    if (!retryable) {
      throw error;
    }
  }
  // The second failure propagates unchanged; it cannot enter the catch above.
  return page.goto(url, options);
}
