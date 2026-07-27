import { chatIcon, closeIcon, sendIcon } from "./icons";

/**
 * Builds the widget's DOM once, and hands back typed references.
 *
 * Kept separate from behaviour so the structure — and in particular the ARIA
 * wiring — can be read in one pass rather than reconstructed from scattered
 * `createElement` calls.
 */

export interface WidgetElements {
  root: HTMLDivElement;
  launcher: HTMLButtonElement;
  launcherDot: HTMLSpanElement;
  panel: HTMLDivElement;
  closeButton: HTMLButtonElement;
  log: HTMLDivElement;
  input: HTMLTextAreaElement;
  sendButton: HTMLButtonElement;
  announcer: HTMLDivElement;
}

export interface DomOptions {
  title: string;
  subtitle: string;
  placeholder: string;
}

export function buildDom(document: Document, options: DomOptions): WidgetElements {
  const root = document.createElement("div");

  // --- Launcher -----------------------------------------------------------
  const launcher = document.createElement("button");
  launcher.className = "bc-launcher";
  launcher.type = "button";
  // The icon is decorative, so the button needs its own accessible name.
  launcher.setAttribute("aria-label", `Open ${options.title}`);
  launcher.setAttribute("aria-expanded", "false");
  launcher.innerHTML = chatIcon;

  const launcherDot = document.createElement("span");
  launcherDot.className = "bc-launcher__dot";
  launcher.appendChild(launcherDot);

  // --- Panel --------------------------------------------------------------
  const panel = document.createElement("div");
  panel.className = "bc-panel";
  panel.dataset["open"] = "false";
  panel.setAttribute("role", "dialog");
  panel.setAttribute("aria-labelledby", "bc-title");
  // Not `aria-modal`: the widget deliberately does not trap the whole page.
  // A visitor must always be able to Tab back out to the site itself — this is
  // an assistant sitting beside the content, not a modal interrupting it.

  const header = document.createElement("div");
  header.className = "bc-header";

  const mark = document.createElement("div");
  mark.className = "bc-header__mark";
  mark.textContent = "B";
  mark.setAttribute("aria-hidden", "true");

  const headerText = document.createElement("div");
  headerText.className = "bc-header__text";

  const title = document.createElement("h2");
  title.className = "bc-header__title";
  title.id = "bc-title";
  title.textContent = options.title;

  const status = document.createElement("p");
  status.className = "bc-header__status";
  status.textContent = options.subtitle;

  headerText.append(title, status);

  const closeButton = document.createElement("button");
  closeButton.className = "bc-close";
  closeButton.type = "button";
  closeButton.setAttribute("aria-label", "Close chat");
  closeButton.innerHTML = closeIcon;

  header.append(mark, headerText, closeButton);

  // --- Message log --------------------------------------------------------
  const log = document.createElement("div");
  log.className = "bc-log";
  log.setAttribute("role", "log");
  // `polite` rather than `assertive`: replies should be announced when the
  // screen reader reaches a natural pause, not cut off whatever it is saying.
  log.setAttribute("aria-live", "polite");
  log.setAttribute("aria-atomic", "false");
  log.setAttribute("aria-label", "Conversation");

  // --- Composer -----------------------------------------------------------
  const composer = document.createElement("form");
  composer.className = "bc-composer";

  const input = document.createElement("textarea");
  input.className = "bc-input";
  input.rows = 1;
  input.placeholder = options.placeholder;
  input.setAttribute("aria-label", "Type your message");
  // Matches the backend's own ceiling, so the visitor is stopped by the
  // control rather than by a 422.
  input.maxLength = 2000;

  const sendButton = document.createElement("button");
  sendButton.className = "bc-send";
  sendButton.type = "submit";
  sendButton.dataset["ready"] = "false";
  sendButton.disabled = true;
  sendButton.setAttribute("aria-label", "Send message");
  sendButton.innerHTML = sendIcon;

  composer.append(input, sendButton);

  const footer = document.createElement("div");
  footer.className = "bc-footer";
  footer.textContent = "Answers come from Burj Constructions' published information.";

  // A separate live region for status that is not a message — errors, "sending"
  // — so those announcements do not appear as chat bubbles.
  const announcer = document.createElement("div");
  announcer.className = "bc-sr-only";
  announcer.setAttribute("role", "status");
  announcer.setAttribute("aria-live", "polite");

  panel.append(header, log, composer, footer, announcer);
  root.append(panel, launcher);

  return { root, launcher, launcherDot, panel, closeButton, log, input, sendButton, announcer };
}
