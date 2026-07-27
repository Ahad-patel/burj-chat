import { BurjChatWidget, type WidgetOptions } from "./widget";

/**
 * Entry point — auto-mounts from the script tag that loaded it.
 *
 * The host is an ASP.NET WebForms site that cannot be given a build step or an
 * init call in application code, so configuration rides on the tag itself:
 *
 *   <script src="https://cdn.example.com/burj-chat.js"
 *           data-api-url="https://api.burjconstructions.com"
 *           defer></script>
 *
 * `document.currentScript` is read at module evaluation time — it is null once
 * any async work has happened, so it must be captured immediately.
 */

const currentScript = document.currentScript as HTMLScriptElement | null;

function readConfig(script: HTMLScriptElement | null): WidgetOptions | null {
  const apiUrl = script?.dataset["apiUrl"];

  if (!apiUrl) {
    // Fail loudly in the console rather than silently rendering a widget that
    // cannot talk to anything — a chat button that does nothing when clicked
    // is worse for the client than no chat button.
    console.error(
      "[burj-chat] Missing data-api-url on the script tag; widget not mounted.",
    );
    return null;
  }

  const options: WidgetOptions = { apiUrl };

  const title = script?.dataset["title"];
  const greeting = script?.dataset["greeting"];
  if (title) options.title = title;
  if (greeting) options.greeting = greeting;

  return options;
}

function mount(): void {
  const config = readConfig(currentScript);
  if (!config) return;

  // Guard against the tag being included twice — a real risk on a
  // template-driven site where a partial can end up on a page more than once.
  if (document.querySelector("[data-burj-chat]")) {
    console.warn("[burj-chat] Already mounted; ignoring duplicate script tag.");
    return;
  }

  const widget = new BurjChatWidget(config);

  // A minimal handle for the host page, should it ever want to open the widget
  // from its own "Contact us" button.
  (globalThis as Record<string, unknown>)["BurjChat"] = {
    open: () => widget.open(),
    close: () => widget.close(),
    toggle: () => widget.toggle(),
    destroy: () => widget.destroy(),
  };
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", mount, { once: true });
} else {
  mount();
}

export { BurjChatWidget };
export type { WidgetOptions };
