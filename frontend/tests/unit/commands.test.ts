import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import {
  admitSources,
  approveGate,
  cancelRun,
  createCase,
  createRun,
  fetchGatePreview,
  newIntent,
  pinRunInput,
  retryRun,
  sendCommand,
  startRun,
} from "@/app/commands";

const CASE = "3f1c2a4e-8b7d-4c6e-9a1f-0d2e3c4b5a69";
const RUN = "7e6d5c4b-3a29-4817-a6f5-e4d3c2b1a098";
const AT = "2026-09-14T10:00:00.123456Z";
const HASH = "a".repeat(64);

function jsonResponse(body: unknown, status = 200, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...headers },
  });
}

describe("the command transport", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("test_one_key_per_intent_is_reused_only_on_network_retry", async () => {
    const fetchSpy = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(jsonResponse({ case_id: CASE }, 201));
    vi.stubGlobal("fetch", fetchSpy);

    const intent = newIntent();
    const first = await createCase("Acme", intent);
    expect(first).toEqual({ kind: "offline" });

    const second = await createCase("Acme", intent);
    expect(second).toEqual({
      kind: "ok",
      status: 201,
      receipt: { case_id: CASE },
      replayed: false,
    });

    expect(fetchSpy).toHaveBeenCalledTimes(2);
    const firstHeaders = fetchSpy.mock.calls[0]![1].headers as Record<string, string>;
    const secondHeaders = fetchSpy.mock.calls[1]![1].headers as Record<string, string>;
    expect(firstHeaders["Idempotency-Key"]).toBe(intent.key);
    expect(secondHeaders["Idempotency-Key"]).toBe(intent.key);

    // A fresh intent for the next user action carries a different key.
    const another = newIntent();
    expect(another.key).not.toBe(intent.key);
  });

  test("test_a_receipt_is_validated_not_cast", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ case_id: CASE, extra: 1 }, 201)),
    );
    expect(await createCase("Acme")).toEqual({ kind: "error", code: "RESPONSE_INVALID" });

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ case_id: 12345 }, 201)));
    expect(await createCase("Acme")).toEqual({ kind: "error", code: "RESPONSE_INVALID" });
  });

  test("test_a_refusal_body_is_surfaced_with_its_clearance", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(
          jsonResponse({ code: "RUN_NOT_RUNNING", clears: "the run is running" }, 409),
        )
        .mockResolvedValueOnce(jsonResponse({ refusal: "STORE_UNAVAILABLE" }, 503)),
    );
    expect(await cancelRun(CASE, RUN)).toEqual({
      kind: "refused",
      refusal: { code: "RUN_NOT_RUNNING", clears: "the run is running" },
    });
    expect(await cancelRun(CASE, RUN)).toEqual({ kind: "error", code: "RESPONSE_INVALID" });
  });

  test("test_command_urls_methods_and_bodies_match_the_brief", async () => {
    const fetchSpy = vi.fn().mockResolvedValue(jsonResponse({}, 200));
    vi.stubGlobal("fetch", fetchSpy);

    await createCase("Acme");
    expect(fetchSpy.mock.calls[0]![0]).toBe("/api/v1/cases");
    expect(fetchSpy.mock.calls[0]![1].method).toBe("POST");
    expect(fetchSpy.mock.calls[0]![1].body).toBe(JSON.stringify({ title: "Acme" }));
    expect(fetchSpy.mock.calls[0]![1].headers["content-type"]).toBe("application/json");

    await createRun(CASE, {
      profile_id: "FULL_CREDIT_ASSESSMENT",
      selection_id: "S1",
      supersedes: null,
      model_extension: false,
    });
    expect(fetchSpy.mock.calls[1]![0]).toBe(`/api/v1/cases/${CASE}/runs`);
    expect(fetchSpy.mock.calls[1]![1].method).toBe("POST");
    expect(fetchSpy.mock.calls[1]![1].body).toBe(
      JSON.stringify({
        profile_id: "FULL_CREDIT_ASSESSMENT",
        selection_id: "S1",
        supersedes: null,
        model_extension: false,
      }),
    );

    const subject = {
      issuer_id: "issuer-1",
      issuer_name: "Acme Corp",
      reporting_period: "FY2025Q4",
      analysis_date: "2026-09-14",
    };
    await pinRunInput(CASE, RUN, subject, null);
    expect(fetchSpy.mock.calls[2]![0]).toBe(`/api/v1/cases/${CASE}/runs/${RUN}/input`);
    expect(fetchSpy.mock.calls[2]![1].method).toBe("POST");
    expect(fetchSpy.mock.calls[2]![1].body).toBe(JSON.stringify({ subject, research: null }));

    await fetchGatePreview(CASE, RUN, "SOURCE_SET");
    expect(fetchSpy.mock.calls[3]![0]).toBe(
      `/api/v1/cases/${CASE}/runs/${RUN}/gates/source-set/preview`,
    );
    expect(fetchSpy.mock.calls[3]![1].method).toBe("GET");
    expect(fetchSpy.mock.calls[3]![1].headers["Idempotency-Key"]).toBeUndefined();

    await approveGate(CASE, RUN, "RESEARCH_PLAN", {
      preview_sha256: HASH,
      input_fingerprint: HASH,
    });
    expect(fetchSpy.mock.calls[4]![0]).toBe(
      `/api/v1/cases/${CASE}/runs/${RUN}/gates/research-plan/approval`,
    );
    expect(fetchSpy.mock.calls[4]![1].method).toBe("POST");
    expect(fetchSpy.mock.calls[4]![1].body).toBe(
      JSON.stringify({ preview_sha256: HASH, input_fingerprint: HASH }),
    );

    await startRun(CASE, RUN, { input_fingerprint: HASH });
    expect(fetchSpy.mock.calls[5]![0]).toBe(`/api/v1/cases/${CASE}/runs/${RUN}/start`);
    expect(fetchSpy.mock.calls[5]![1].body).toBe(JSON.stringify({ input_fingerprint: HASH }));

    await retryRun(CASE, RUN, { input_fingerprint: HASH });
    expect(fetchSpy.mock.calls[6]![0]).toBe(`/api/v1/cases/${CASE}/runs/${RUN}/retry`);
    expect(fetchSpy.mock.calls[6]![1].body).toBe(JSON.stringify({ input_fingerprint: HASH }));

    await cancelRun(CASE, RUN);
    expect(fetchSpy.mock.calls[7]![0]).toBe(`/api/v1/cases/${CASE}/runs/${RUN}/cancel`);
    expect(fetchSpy.mock.calls[7]![1].body).toBe(JSON.stringify({}));

    // Every POST carries an Idempotency-Key; the preview GET carries none.
    for (const index of [0, 1, 2, 4, 5, 6, 7]) {
      const headers = fetchSpy.mock.calls[index]![1].headers as Record<string, string>;
      expect(headers["Idempotency-Key"]).toMatch(
        /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/,
      );
    }
  });

  test("test_admission_sends_multipart_document_parts", async () => {
    const fetchSpy = vi
      .fn()
      .mockResolvedValue(jsonResponse({ case_id: CASE, source_ids: [] }, 201));
    vi.stubGlobal("fetch", fetchSpy);

    const files = [
      new File(["one"], "one.pdf", { type: "application/pdf" }),
      new File(["two"], "two.txt", { type: "text/plain" }),
    ];
    const result = await admitSources(CASE, files);
    expect(result).toEqual({
      kind: "ok",
      status: 201,
      receipt: { case_id: CASE, source_ids: [] },
      replayed: false,
    });

    const call = fetchSpy.mock.calls[0]!;
    expect(call[0]).toBe(`/api/v1/cases/${CASE}/sources`);
    expect(call[1].method).toBe("POST");
    const form = call[1].body as FormData;
    expect(form).toBeInstanceOf(FormData);
    const parts = form.getAll("document");
    expect(parts).toHaveLength(2);
    expect((parts[0] as File).name).toBe("one.pdf");
    expect((parts[1] as File).name).toBe("two.txt");
    // No content-type header set: the browser draws its own multipart boundary.
    expect(call[1].headers["content-type"]).toBeUndefined();
  });

  test("a replayed answer surfaces as replayed", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          jsonResponse({ case_id: CASE }, 201, { "Idempotency-Replayed": "true" }),
        ),
    );
    expect(await createCase("Acme")).toEqual({
      kind: "ok",
      status: 201,
      receipt: { case_id: CASE },
      replayed: true,
    });
  });

  test("test_gate_preview_document_is_validated", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({
          run_id: RUN,
          gate: "SOURCE_SET",
          content: "the preview text",
          preview_sha256: HASH,
          input_fingerprint: HASH,
          observed_at: AT,
        }),
      ),
    );
    expect(await fetchGatePreview(CASE, RUN, "SOURCE_SET")).toEqual({
      kind: "ok",
      status: 200,
      receipt: {
        run_id: RUN,
        gate: "SOURCE_SET",
        content: "the preview text",
        preview_sha256: HASH,
        input_fingerprint: HASH,
        observed_at: AT,
      },
      replayed: false,
    });
  });

  test("sendCommand itself is reusable for a caller that wants the primitive", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ case_id: CASE }, 201)));
    const intent = newIntent();
    const result = await sendCommand(
      intent,
      { method: "POST", url: "/api/v1/cases", body: JSON.stringify({ title: "Acme" }) },
      (value: unknown) => {
        if (typeof value === "object" && value !== null && "case_id" in value) {
          return value as { case_id: string };
        }
        throw new Error("not a case");
      },
    );
    expect(result.kind).toBe("ok");
  });

  test("test_no_cast_of_parsed_json_in_commands", () => {
    const code = readFileSync(resolve(process.cwd(), "src/app/commands.ts"), "utf8")
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .replace(/\/\/.*$/gm, "")
      .replace(/^import\s[^;]*;/gm, "");
    expect(code.length).toBeGreaterThan(500);
    expect(code.match(/\bas\s+(?!const\b)[A-Za-z_{[(]/g) ?? []).toEqual([]);
    expect(code).not.toMatch(/<\s*[A-Z]\w*\s*>\s*(JSON|value|body)/);
  });
});
