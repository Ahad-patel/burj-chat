import { closePanel, enterGroup, enterMessage, openPanel, startIdlePulse } from "./animations/motion";
import { ChatApi, ChatApiError } from "./api/client";
import { buildDom, type WidgetElements } from "./components/dom";
import { styles } from "./styles/styles";

/**
 * The widget: state, events, and accessibility wiring.
 *
 * Mounted into an **open** shadow root.
 *
 * Closed was the first choice — it stops the host page's jQuery reaching in
 * through `element.shadowRoot` — and it was wrong. The protection is largely
 * illusory: a hostile host page loads before this script and can override
 * `Element.prototype.attachShadow` to capture the root regardless, or simply
 * intercept `fetch`. What closed *reliably* blocks is the honest traffic —
 * Playwright, axe-core, browser devtools, and accessibility extensions cannot
 * see inside, so the isolation claim becomes unverifiable and the a11y tree
 * un-auditable.
 *
 * Style isolation, which is the actual requirement here, is identical either
 * way: host CSS cannot cross the boundary in open or closed mode, and
 * `document.querySelector` / jQuery still cannot select the widget's
 * internals. Tests assert both.
 */

export interface WidgetOptions {
  apiUrl: string;
  title?: string;
  subtitle?: string;
  placeholder?: string;
  greeting?: string;
  suggestions?: string[];
}

const DEFAULTS = {
  title: "Burj Assistant",
  subtitle: "Usually replies instantly",
  placeholder: "Ask about our projects…",
  greeting:
    "Hello! I can answer questions about Burj Constructions — our projects, amenities, locations, and how to reach us. What would you like to know?",
  suggestions: [
    "What projects are ongoing?",
    "Where is Burj Chishti located?",
    "What amenities are included?",
    "How do I contact your team?",
  ],
} as const;

/** Keys that must not be intercepted from the host page's own handlers. */
const ESCAPE = "Escape";
const ENTER = "Enter";

export class BurjChatWidget {
  private readonly options: Required<WidgetOptions>;
  private readonly api: ChatApi;
  private readonly host: HTMLElement;
  private readonly shadow: ShadowRoot;
  private readonly el: WidgetElements;

  private isOpen = false;
  private isSending = false;
  private hasEngaged = false;
  private stopPulse: () => void = () => undefined;

  constructor(options: WidgetOptions, container: HTMLElement = document.body) {
    this.options = { ...DEFAULTS, ...options, suggestions: [...DEFAULTS.suggestions] };
    this.api = new ChatApi({ baseUrl: this.options.apiUrl });

    this.host = document.createElement("div");
    this.host.setAttribute("data-burj-chat", "");

    this.shadow = this.host.attachShadow({ mode: "open" });

    const sheet = document.createElement("style");
    sheet.textContent = styles;
    this.shadow.appendChild(sheet);

    this.el = buildDom(document, {
      title: this.options.title,
      subtitle: this.options.subtitle,
      placeholder: this.options.placeholder,
    });
    this.shadow.appendChild(this.el.root);

    container.appendChild(this.host);

    this.bindEvents();
    this.stopPulse = startIdlePulse(this.el.launcher);
  }

  // -------------------------------------------------------------------------
  // Events
  // -------------------------------------------------------------------------

  private bindEvents(): void {
    this.el.launcher.addEventListener("click", () => this.open());
    this.el.closeButton.addEventListener("click", () => this.close());

    this.el.input.addEventListener("input", () => {
      this.autoGrow();
      this.refreshSendState();
    });

    this.el.input.addEventListener("keydown", (event) => {
      // Enter sends; Shift+Enter inserts a newline. Composition guard keeps
      // IME users (Hindi, Marathi, Arabic transliteration) from sending
      // half-composed text when they press Enter to accept a candidate.
      if (event.key === ENTER && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        void this.submit();
      }
    });

    this.el.sendButton.addEventListener("click", (event) => {
      event.preventDefault();
      void this.submit();
    });

    // Escape closes from anywhere inside the panel and returns focus to the
    // launcher, so a keyboard user is never stranded.
    this.el.panel.addEventListener("keydown", (event) => {
      if (event.key === ESCAPE) {
        event.stopPropagation();
        this.close();
      }
    });
  }

  // -------------------------------------------------------------------------
  // Open / close
  // -------------------------------------------------------------------------

  open(): void {
    if (this.isOpen) return;

    this.isOpen = true;
    this.el.panel.dataset["open"] = "true";
    this.el.launcher.setAttribute("aria-expanded", "true");
    this.el.launcher.hidden = false;

    // Permanently, not paused: a launcher still pulsing after the visitor has
    // engaged reads as broken rather than eager.
    this.stopPulse();
    this.el.launcherDot.remove();

    openPanel(this.el.panel, this.el.launcher);

    if (!this.hasEngaged) {
      this.hasEngaged = true;
      this.renderGreeting();
    }

    // Deferred so focus lands after the panel is visible; moving focus to a
    // hidden element is silently dropped by some screen readers.
    globalThis.setTimeout(() => this.el.input.focus(), 60);
  }

  close(): void {
    if (!this.isOpen) return;

    this.isOpen = false;
    this.el.launcher.setAttribute("aria-expanded", "false");

    closePanel(this.el.panel, this.el.launcher, () => {
      this.el.panel.dataset["open"] = "false";
    });

    this.el.launcher.focus();
  }

  toggle(): void {
    this.isOpen ? this.close() : this.open();
  }

  // -------------------------------------------------------------------------
  // Messaging
  // -------------------------------------------------------------------------

  private async submit(): Promise<void> {
    const text = this.el.input.value.trim();
    if (!text || this.isSending) return;

    this.el.input.value = "";
    this.autoGrow();
    this.appendMessage(text, "user");
    this.setSending(true);

    const typing = this.showTyping();

    try {
      const reply = await this.api.send(text);
      typing.remove();
      this.appendMessage(reply.answer, "assistant");
    } catch (error) {
      typing.remove();
      this.appendMessage(this.describeError(error), "error");
    } finally {
      this.setSending(false);
      this.el.input.focus();
    }
  }

  /**
   * Turn a failure into something a visitor can act on.
   *
   * Never surfaces the underlying error text: it says nothing useful to a
   * customer and can leak infrastructure detail. Each branch tells them what
   * to do instead.
   */
  private describeError(error: unknown): string {
    if (error instanceof ChatApiError) {
      switch (error.kind) {
        case "rate_limited":
          return `You've sent a lot of messages just now. Please wait about ${error.retryAfterSeconds ?? 30} seconds and try again.`;
        case "timeout":
          return "That took longer than expected. Please try again.";
        default:
          return "I couldn't reach our servers just now. Please try again, or call +91 98199 62446.";
      }
    }
    return "Something went wrong. Please try again, or call +91 98199 62446.";
  }

  private appendMessage(text: string, kind: "user" | "assistant" | "error"): HTMLDivElement {
    const bubble = document.createElement("div");
    bubble.className = `bc-msg bc-msg--${kind}`;
    // textContent, never innerHTML. The answer is model output rendered into a
    // page; treating it as markup would be an XSS vector that no amount of
    // server-side guardrail can close.
    bubble.textContent = text;

    this.el.log.appendChild(bubble);
    enterMessage(bubble);
    this.scrollToLatest();

    return bubble;
  }

  private renderGreeting(): void {
    const greeting = this.appendMessage(this.options.greeting, "assistant");

    const chips = document.createElement("div");
    chips.className = "bc-chips";

    const buttons = this.options.suggestions.map((suggestion) => {
      const chip = document.createElement("button");
      chip.className = "bc-chip";
      chip.type = "button";
      chip.textContent = suggestion;
      chip.addEventListener("click", () => {
        this.el.input.value = suggestion;
        this.refreshSendState();
        chips.remove();
        void this.submit();
      });
      chips.appendChild(chip);
      return chip;
    });

    this.el.log.appendChild(chips);
    // Staggered, not as one block — the detail that reads as designed.
    enterGroup([greeting, ...buttons]);
  }

  private showTyping(): HTMLDivElement {
    const typing = document.createElement("div");
    typing.className = "bc-typing";
    typing.setAttribute("aria-hidden", "true");
    typing.innerHTML = "<span></span><span></span><span></span>";

    this.el.log.appendChild(typing);
    this.scrollToLatest();
    // Announced separately, because the dots themselves are decorative.
    this.announce("Assistant is typing");

    return typing;
  }

  // -------------------------------------------------------------------------
  // UI state
  // -------------------------------------------------------------------------

  private setSending(sending: boolean): void {
    this.isSending = sending;
    this.el.input.disabled = sending;
    this.refreshSendState();
  }

  private refreshSendState(): void {
    const ready = this.el.input.value.trim().length > 0 && !this.isSending;
    this.el.sendButton.dataset["ready"] = String(ready);
    this.el.sendButton.disabled = !ready;
  }

  /** Grow the textarea with its content, up to the CSS max-height. */
  private autoGrow(): void {
    const input = this.el.input;
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 108)}px`;
  }

  private scrollToLatest(): void {
    this.el.log.scrollTop = this.el.log.scrollHeight;
  }

  private announce(message: string): void {
    this.el.announcer.textContent = message;
  }

  /** Remove the widget entirely. Used by tests and by SPA teardown. */
  destroy(): void {
    this.stopPulse();
    this.host.remove();
  }

  /** Convenience accessor used by the test suite. */
  get _shadowForTests(): ShadowRoot {
    return this.shadow;
  }
}
