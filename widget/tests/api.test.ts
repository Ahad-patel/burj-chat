import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ChatApi, ChatApiError } from "../src/api/client";

const API_URL = "https://api.example.test";

function ok(body: Record<string, unknown>, headers: Record<string, string> = {}) {
  return {
    ok: true,
    status: 200,
    headers: new Headers(headers),
    json: async () => body,
  } as unknown as Response;
}

let api: ChatApi;

beforeEach(() => {
  api = new ChatApi({ baseUrl: API_URL });
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => vi.unstubAllGlobals());

describe("conversation continuity", () => {
  it("omits the conversation id on the first message", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      ok({ conversation_id: "id-1", answer: "hi", is_fallback: false }),
    );

    await api.send("hello");

    const body = JSON.parse(vi.mocked(fetch).mock.calls[0]?.[1]?.body as string);
    // The backend mints the id. The widget never invents one — it must be a
    // UUID4 the server generated, since that id is the only thing separating
    // one visitor's history from another's.
    expect(body).not.toHaveProperty("conversation_id");
  });

  it("echoes the server's id on subsequent messages", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(ok({ conversation_id: "id-1", answer: "a", is_fallback: false }))
      .mockResolvedValueOnce(ok({ conversation_id: "id-1", answer: "b", is_fallback: false }));

    await api.send("first");
    await api.send("second");

    const body = JSON.parse(vi.mocked(fetch).mock.calls[1]?.[1]?.body as string);
    expect(body.conversation_id).toBe("id-1");
  });

  it("forgets the id on reset", async () => {
    vi.mocked(fetch).mockResolvedValue(
      ok({ conversation_id: "id-1", answer: "a", is_fallback: false }),
    );
    await api.send("first");

    api.reset();

    expect(api.currentConversationId).toBeNull();
  });
});

describe("request shape", () => {
  it("posts JSON to the versioned chat endpoint", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      ok({ conversation_id: "id", answer: "a", is_fallback: false }),
    );

    await api.send("hello");

    const [url, init] = vi.mocked(fetch).mock.calls[0] ?? [];
    expect(url).toBe(`${API_URL}/api/v1/chat`);
    expect(init?.method).toBe("POST");
  });

  it("tolerates a trailing slash in the configured base url", async () => {
    const trailing = new ChatApi({ baseUrl: `${API_URL}///` });
    vi.mocked(fetch).mockResolvedValueOnce(
      ok({ conversation_id: "id", answer: "a", is_fallback: false }),
    );

    await trailing.send("hello");

    expect(vi.mocked(fetch).mock.calls[0]?.[0]).toBe(`${API_URL}/api/v1/chat`);
  });

  it("sends no credentials — the widget holds no secret", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      ok({ conversation_id: "id", answer: "a", is_fallback: false }),
    );

    await api.send("hello");

    const headers = vi.mocked(fetch).mock.calls[0]?.[1]?.headers as Record<string, string>;
    expect(headers["Authorization"]).toBeUndefined();
    expect(JSON.stringify(headers).toLowerCase()).not.toContain("api-key");
  });
});

describe("failures are typed, not stringly", () => {
  it("distinguishes a rate limit and carries the wait time", async () => {
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: false,
      status: 429,
      headers: new Headers({ "Retry-After": "42" }),
      json: async () => ({}),
    } as unknown as Response);

    await expect(api.send("hi")).rejects.toMatchObject({
      kind: "rate_limited",
      retryAfterSeconds: 42,
    });
  });

  it("defaults the wait time when the header is absent", async () => {
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: false,
      status: 429,
      headers: new Headers(),
      json: async () => ({}),
    } as unknown as Response);

    await expect(api.send("hi")).rejects.toMatchObject({ retryAfterSeconds: 30 });
  });

  it("reports a server error", async () => {
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: false,
      status: 503,
      headers: new Headers(),
      json: async () => ({}),
    } as unknown as Response);

    await expect(api.send("hi")).rejects.toMatchObject({ kind: "server" });
  });

  it("reports a network failure", async () => {
    vi.mocked(fetch).mockRejectedValueOnce(new TypeError("Failed to fetch"));

    await expect(api.send("hi")).rejects.toMatchObject({ kind: "network" });
  });

  it("aborts rather than hanging forever", async () => {
    const quick = new ChatApi({ baseUrl: API_URL, timeoutMs: 10 });
    vi.mocked(fetch).mockImplementationOnce(
      () =>
        new Promise((_resolve, reject) => {
          setTimeout(() => reject(new DOMException("Aborted", "AbortError")), 20);
        }),
    );

    await expect(quick.send("hi")).rejects.toMatchObject({ kind: "timeout" });
  });

  it("always throws a ChatApiError, never a raw one", async () => {
    vi.mocked(fetch).mockRejectedValueOnce(new Error("something internal"));

    await expect(api.send("hi")).rejects.toBeInstanceOf(ChatApiError);
  });
});
