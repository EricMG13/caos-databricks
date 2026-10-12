import assert from "node:assert/strict";
import test from "node:test";
import { gotoWithInternalErrorRetry } from "../../scripts/a11y-navigation.mjs";

const url = "http://localhost:4173/model?basis=base";
const options = { waitUntil: "domcontentloaded", timeout: 30_000 };
const internal = () => new Error("page.goto: WebKit encountered an internal error\nCall log:");

function pageWith(outcomes) {
  const calls = [];
  const page = {
    async goto(givenUrl, givenOptions) {
      assert.equal(this, page);
      assert.equal(givenUrl, url);
      assert.equal(givenOptions, options);
      calls.push([givenUrl, givenOptions]);
      const outcome = outcomes[calls.length - 1];
      assert.notEqual(outcome, undefined, "no unbounded retry");
      if (outcome instanceof Error || typeof outcome === "string") throw outcome;
      return outcome;
    },
  };
  return { page, calls };
}

test("first navigation returns its response without retry, including HTTP 500", async () => {
  const response = { status: 500 };
  const { page, calls } = pageWith([response]);
  assert.equal(await gotoWithInternalErrorRetry(page, url, options), response);
  assert.equal(calls.length, 1);
});

test("one exact WebKit internal failure retries the same page, URL and options", async () => {
  const response = { status: 200 };
  const { page, calls } = pageWith([internal(), response]);
  assert.equal(await gotoWithInternalErrorRetry(page, url, options), response);
  assert.equal(calls.length, 2);
});

test("a repeated internal failure propagates the second error after two calls", async () => {
  const second = internal();
  const { page, calls } = pageWith([internal(), second]);
  await assert.rejects(gotoWithInternalErrorRetry(page, url, options), (error) => error === second);
  assert.equal(calls.length, 2);
});

for (const message of [
  "page.goto: Timeout 30000ms exceeded",
  "page.goto: net::ERR_CONNECTION_REFUSED",
  "page.goto: HTTP 500",
  "page.evaluate: WebKit encountered an internal error",
  "WebKit encountered an internal error",
  "page.goto: WebKit encountered an internal error: unrelated suffix",
  "axe violations found",
  "target size failure",
]) {
  test(`other failures propagate without retry: ${message}`, async () => {
    const first = new Error(message);
    const { page, calls } = pageWith([first]);
    await assert.rejects(
      gotoWithInternalErrorRetry(page, url, options),
      (error) => error === first,
    );
    assert.equal(calls.length, 1);
  });
}

test("a TimeoutError never retries even with the internal-error text", async () => {
  const first = internal();
  first.name = "TimeoutError";
  const { page, calls } = pageWith([first]);
  await assert.rejects(gotoWithInternalErrorRetry(page, url, options), (error) => error === first);
  assert.equal(calls.length, 1);
});

test("a non-Error rejection never retries", async () => {
  const first = "page.goto: WebKit encountered an internal error";
  const { page, calls } = pageWith([first]);
  await assert.rejects(gotoWithInternalErrorRetry(page, url, options), (error) => error === first);
  assert.equal(calls.length, 1);
});

test("a single-line internal error can retry, but a failed retry stays final", async () => {
  const first = new Error("page.goto: WebKit encountered an internal error");
  const second = new Error("page.goto: net::ERR_CONNECTION_REFUSED");
  const { page, calls } = pageWith([first, second]);
  await assert.rejects(gotoWithInternalErrorRetry(page, url, options), (error) => error === second);
  assert.equal(calls.length, 2);
});
