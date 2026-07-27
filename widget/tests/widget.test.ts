import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BurjChatWidget } from "../src/widget";

/**
 * Widget behaviour, accessibility, and isolation.
 *
 * jsdom supports Shadow DOM, so the isolation guarantees can be asserted
 * directly rather than eyeballed in a browser.
 */

const API_URL = "https://api.example.test";

function reply(answer: string, isFallback = false) {
  return {
    ok: true,
    status: 200,
    headers: new Headers(),
    json: async () => ({
      conversation_id: "0f3a5c4e-9a6b-4c1d-8e2f-1a2b3c4d5e6f",
      answer,
      is_fallback: isFallback,
    }),
  } as unknown as Response;
}

let widget: BurjChatWidget;
let shadow: ShadowRoot;

function q<T extends Element>(selector: string): T {
  const found = shadow.querySelector<T>(selector);
  if (!found) throw new Error(`not found: ${selector}`);
  return found;
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async () => reply("A grounded answer.")));
  // jsdom has no matchMedia; the widget must not assume one exists.
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })),
  );

  widget = new BurjChatWidget({ apiUrl: API_URL });
  shadow = widget._shadowForTests;
});

afterEach(() => {
  widget.destroy();
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

describe("style isolation", () => {
  it("mounts into a shadow root", () => {
    expect(shadow).toBeTruthy();
    expect(q(".bc-launcher")).toBeTruthy();
  });

  it("uses an open shadow root, so the isolation claim stays verifiable", () => {
    // Closed was tried first and reverted: it blocks Playwright, axe-core, and
    // devtools far more reliably than it blocks an attacker, who can override
    // attachShadow before this script loads. Style isolation is identical
    // either way — see the two tests below, which are what actually matter.
    const hostElement = document.querySelector("[data-burj-chat]");

    expect(hostElement).toBeTruthy();
    expect(hostElement?.shadowRoot).not.toBeNull();
  });

  it("host-page queries still cannot select widget internals", () => {
    // This is the property that matters, and it holds for an open root too:
    // shadow DOM encapsulates selectors, so the site's jQuery sweeps find
    // nothing inside.
    expect(document.querySelector(".bc-launcher")).toBeNull();
    expect(document.querySelector(".bc-input")).toBeNull();
    expect(document.getElementById("bc-title")).toBeNull();
  });

  it("leaks no elements into the host document", () => {
    // Everything the widget renders lives behind the boundary; the host page
    // sees exactly one anonymous div.
    expect(document.querySelectorAll(".bc-launcher")).toHaveLength(0);
    expect(document.querySelectorAll(".bc-panel")).toHaveLength(0);
    expect(document.querySelectorAll("button")).toHaveLength(0);
  });

  it("uses no generic class names that a host stylesheet would define", () => {
    // Bootstrap defines .btn, .card, .modal, .close, .form-control. Shadow DOM
    // makes a collision impossible, but a generic name here would be a trap
    // for anyone who later renders part of this outside the boundary.
    const markup = shadow.innerHTML;
    const generic = ["btn", "card", "modal", "form-control", "container", "row", "col"];

    for (const name of generic) {
      expect(markup).not.toMatch(new RegExp(`class="[^"]*\\b${name}\\b`));
    }
  });

  it("prefixes every class with bc-", () => {
    const classed = shadow.querySelectorAll("[class]");

    for (const element of classed) {
      for (const name of element.classList) {
        expect(name).toMatch(/^bc-/);
      }
    }
  });
});

describe("opening and closing", () => {
  it("starts closed", () => {
    expect(q<HTMLElement>(".bc-panel").dataset["open"]).toBe("false");
    expect(q(".bc-launcher").getAttribute("aria-expanded")).toBe("false");
  });

  it("opens on launcher click", () => {
    q<HTMLButtonElement>(".bc-launcher").click();

    expect(q<HTMLElement>(".bc-panel").dataset["open"]).toBe("true");
    expect(q(".bc-launcher").getAttribute("aria-expanded")).toBe("true");
  });

  it("closes on the close button", () => {
    q<HTMLButtonElement>(".bc-launcher").click();
    q<HTMLButtonElement>(".bc-close").click();

    expect(q(".bc-launcher").getAttribute("aria-expanded")).toBe("false");
  });

  it("shows a greeting and suggestions on first open only", () => {
    q<HTMLButtonElement>(".bc-launcher").click();
    const afterFirst = shadow.querySelectorAll(".bc-msg").length;

    widget.close();
    widget.open();

    expect(shadow.querySelectorAll(".bc-msg")).toHaveLength(afterFirst);
  });

  it("removes the attention dot once engaged", () => {
    expect(shadow.querySelector(".bc-launcher__dot")).toBeTruthy();

    q<HTMLButtonElement>(".bc-launcher").click();

    expect(shadow.querySelector(".bc-launcher__dot")).toBeNull();
  });
});

describe("keyboard operation", () => {
  beforeEach(() => q<HTMLButtonElement>(".bc-launcher").click());

  it("sends on Enter", async () => {
    const input = q<HTMLTextAreaElement>(".bc-input");
    input.value = "What amenities are there?";
    input.dispatchEvent(new Event("input"));

    input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    await vi.waitFor(() => expect(fetch).toHaveBeenCalled());

    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("inserts a newline on Shift+Enter instead of sending", () => {
    const input = q<HTMLTextAreaElement>(".bc-input");
    input.value = "line one";
    input.dispatchEvent(new Event("input"));

    input.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Enter", shiftKey: true, bubbles: true }),
    );

    expect(fetch).not.toHaveBeenCalled();
  });

  it("does not send mid-composition", () => {
    // IME users typing Hindi, Marathi, or transliterated Arabic press Enter to
    // accept a candidate. Sending then would fire half-composed text.
    const input = q<HTMLTextAreaElement>(".bc-input");
    input.value = "आवास";
    input.dispatchEvent(new Event("input"));

    const event = new KeyboardEvent("keydown", { key: "Enter", bubbles: true });
    Object.defineProperty(event, "isComposing", { value: true });
    input.dispatchEvent(event);

    expect(fetch).not.toHaveBeenCalled();
  });

  it("closes on Escape", () => {
    q(".bc-panel").dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));

    expect(q(".bc-launcher").getAttribute("aria-expanded")).toBe("false");
  });

  it("every interactive element is reachable by keyboard", () => {
    // No positive tabindex, nothing removed from the tab order.
    const interactive = shadow.querySelectorAll("button, textarea, input, a[href]");

    expect(interactive.length).toBeGreaterThan(0);
    for (const element of interactive) {
      const tabindex = element.getAttribute("tabindex");
      expect(tabindex === null || Number(tabindex) >= 0).toBe(true);
    }
  });
});

describe("ARIA", () => {
  it("announces new messages through a polite live region", () => {
    const log = q(".bc-log");

    expect(log.getAttribute("role")).toBe("log");
    // polite, not assertive: replies should wait for a natural pause rather
    // than interrupt whatever the screen reader is currently saying.
    expect(log.getAttribute("aria-live")).toBe("polite");
  });

  it("labels the dialog", () => {
    const panel = q(".bc-panel");

    expect(panel.getAttribute("role")).toBe("dialog");
    expect(panel.getAttribute("aria-labelledby")).toBe("bc-title");
    expect(shadow.querySelector("#bc-title")?.textContent).toBeTruthy();
  });

  it("does not trap the page in a modal", () => {
    // A site assistant sits beside the content; a visitor must always be able
    // to Tab back out to the page itself.
    expect(q(".bc-panel").getAttribute("aria-modal")).toBeNull();
  });

  it("gives every icon-only control an accessible name", () => {
    for (const selector of [".bc-launcher", ".bc-close", ".bc-send"]) {
      expect(q(selector).getAttribute("aria-label")).toBeTruthy();
    }
  });

  it("hides decorative icons from screen readers", () => {
    for (const svg of shadow.querySelectorAll("svg")) {
      expect(svg.getAttribute("aria-hidden")).toBe("true");
    }
  });
});

describe("sending", () => {
  beforeEach(() => q<HTMLButtonElement>(".bc-launcher").click());

  it("keeps send disabled until there is text", () => {
    const send = q<HTMLButtonElement>(".bc-send");
    expect(send.disabled).toBe(true);

    const input = q<HTMLTextAreaElement>(".bc-input");
    input.value = "hello";
    input.dispatchEvent(new Event("input"));

    expect(send.disabled).toBe(false);
    expect(send.dataset["ready"]).toBe("true");
  });

  it("stays disabled for whitespace only", () => {
    const input = q<HTMLTextAreaElement>(".bc-input");
    input.value = "     ";
    input.dispatchEvent(new Event("input"));

    expect(q<HTMLButtonElement>(".bc-send").disabled).toBe(true);
  });

  it("renders the user message and the reply", async () => {
    const input = q<HTMLTextAreaElement>(".bc-input");
    input.value = "What amenities are there?";
    input.dispatchEvent(new Event("input"));
    q<HTMLButtonElement>(".bc-send").click();

    await vi.waitFor(() => expect(shadow.querySelector(".bc-msg--user")).toBeTruthy());
    await vi.waitFor(() =>
      expect(shadow.querySelectorAll(".bc-msg--assistant").length).toBeGreaterThan(1),
    );
  });

  it("renders answers as text, never as markup", async () => {
    // The answer is model output being placed into a page. Treating it as HTML
    // would be an XSS vector that no server-side guardrail can close.
    vi.mocked(fetch).mockResolvedValueOnce(
      reply('<img src=x onerror="globalThis.__pwned=1">'),
    );

    const input = q<HTMLTextAreaElement>(".bc-input");
    input.value = "tell me";
    input.dispatchEvent(new Event("input"));
    q<HTMLButtonElement>(".bc-send").click();

    await vi.waitFor(() =>
      expect(shadow.querySelectorAll(".bc-msg--assistant").length).toBeGreaterThan(1),
    );

    expect(shadow.querySelector("img")).toBeNull();
    expect((globalThis as Record<string, unknown>)["__pwned"]).toBeUndefined();
  });

  it("clears the input after sending", async () => {
    const input = q<HTMLTextAreaElement>(".bc-input");
    input.value = "hello";
    input.dispatchEvent(new Event("input"));
    q<HTMLButtonElement>(".bc-send").click();

    await vi.waitFor(() => expect(input.value).toBe(""));
  });
});

describe("failure handling", () => {
  beforeEach(() => q<HTMLButtonElement>(".bc-launcher").click());

  async function send(text = "hello") {
    const input = q<HTMLTextAreaElement>(".bc-input");
    input.value = text;
    input.dispatchEvent(new Event("input"));
    q<HTMLButtonElement>(".bc-send").click();
    await vi.waitFor(() => expect(shadow.querySelector(".bc-msg--error")).toBeTruthy());
  }

  it("shows an actionable message when the network fails", async () => {
    vi.mocked(fetch).mockRejectedValueOnce(new TypeError("Failed to fetch"));
    await send();

    const error = q(".bc-msg--error").textContent ?? "";
    expect(error).toContain("98199 62446");
  });

  it("explains a rate limit with the wait time", async () => {
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: false,
      status: 429,
      headers: new Headers({ "Retry-After": "45" }),
      json: async () => ({}),
    } as unknown as Response);

    await send();

    expect(q(".bc-msg--error").textContent).toContain("45");
  });

  it("never surfaces the raw error text", async () => {
    vi.mocked(fetch).mockRejectedValueOnce(
      new Error("ECONNREFUSED 10.0.0.5:8000 internal-api"),
    );
    await send();

    const error = q(".bc-msg--error").textContent ?? "";
    expect(error).not.toContain("ECONNREFUSED");
    expect(error).not.toContain("10.0.0.5");
  });

  it("re-enables the composer after a failure", async () => {
    vi.mocked(fetch).mockRejectedValueOnce(new TypeError("Failed to fetch"));
    await send();

    expect(q<HTMLTextAreaElement>(".bc-input").disabled).toBe(false);
  });
});

describe("teardown", () => {
  it("removes itself from the host document", () => {
    widget.destroy();

    expect(document.querySelector("[data-burj-chat]")).toBeNull();
  });
});
