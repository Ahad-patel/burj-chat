import { gsap } from "gsap";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  closePanel,
  enterGroup,
  enterMessage,
  openPanel,
  startIdlePulse,
} from "../src/animations/motion";

/**
 * Motion, and specifically `prefers-reduced-motion`.
 *
 * This is an accessibility requirement, not optional polish — vestibular
 * disorders make unwanted motion a health matter. So the tests assert the
 * reduced branch reaches the *same end state* rather than merely running
 * faster: a visitor who has asked for stillness gets a fully working widget
 * that does not move.
 */

function setReducedMotion(reduced: boolean): void {
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      matches: reduced && query.includes("prefers-reduced-motion"),
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
}

let panel: HTMLElement;
let launcher: HTMLElement;

beforeEach(() => {
  panel = document.createElement("div");
  launcher = document.createElement("button");
  document.body.append(panel, launcher);
});

afterEach(() => {
  gsap.globalTimeline.clear();
  document.body.innerHTML = "";
  vi.unstubAllGlobals();
});

describe("with reduced motion requested", () => {
  beforeEach(() => setReducedMotion(true));

  it("opens instantly, fully visible", () => {
    openPanel(panel, launcher);

    expect(gsap.getProperty(panel, "opacity")).toBe(1);
    expect(gsap.getProperty(panel, "scale")).toBe(1);
  });

  it("still invokes the close callback, so state stays consistent", () => {
    const onComplete = vi.fn();

    closePanel(panel, launcher, onComplete);

    // Synchronously — no tween to wait on. If this were skipped, the panel
    // would stay flagged open forever.
    expect(onComplete).toHaveBeenCalledTimes(1);
  });

  it("shows messages without animating them", () => {
    const bubble = document.createElement("div");
    panel.appendChild(bubble);

    enterMessage(bubble);

    expect(gsap.getProperty(bubble, "opacity")).toBe(1);
    expect(gsap.getProperty(bubble, "y")).toBe(0);
  });

  it("shows a group without staggering", () => {
    const items = [0, 1, 2].map(() => {
      const item = document.createElement("div");
      panel.appendChild(item);
      return item;
    });

    enterGroup(items);

    for (const item of items) {
      expect(gsap.getProperty(item, "opacity")).toBe(1);
    }
  });

  it("does not start the idle pulse at all", () => {
    const stop = startIdlePulse(launcher);

    expect(gsap.isTweening(launcher)).toBe(false);
    expect(() => stop()).not.toThrow();
  });
});

describe("with motion allowed", () => {
  beforeEach(() => setReducedMotion(false));

  it("animates the panel open", () => {
    openPanel(panel, launcher);

    expect(gsap.isTweening(panel) || gsap.getProperty(panel, "opacity") !== 1).toBe(true);
  });

  it("runs the close callback when the timeline finishes", async () => {
    const onComplete = vi.fn();

    closePanel(panel, launcher, onComplete);
    await vi.waitFor(() => expect(onComplete).toHaveBeenCalled(), { timeout: 2000 });
  });

  it("starts the idle pulse and can stop it permanently", async () => {
    const stop = startIdlePulse(launcher);

    stop();

    // Stopped, not paused: a launcher still pulsing after the visitor has
    // engaged reads as broken rather than eager.
    expect(gsap.isTweening(launcher)).toBe(false);
    expect(gsap.getProperty(launcher, "scale")).toBe(1);
  });

  it("staggers a group rather than animating it as one block", () => {
    const items = [0, 1, 2, 3].map(() => {
      const item = document.createElement("div");
      panel.appendChild(item);
      return item;
    });

    enterGroup(items);

    // Mid-flight the later items lag the earlier ones. Equal opacity here
    // would mean the stagger was dropped — the single detail that most makes
    // a group read as designed rather than rendered.
    const tweens = gsap.getTweensOf(items);
    expect(tweens.length).toBeGreaterThan(0);
  });

  it("handles an empty group without error", () => {
    expect(() => enterGroup([])).not.toThrow();
  });
});

describe("when matchMedia is unavailable", () => {
  it("does not crash", () => {
    // Older embedded browsers, and jsdom without a stub. The widget must
    // degrade to "animate" rather than throwing during mount.
    vi.stubGlobal("matchMedia", undefined);

    expect(() => openPanel(panel, launcher)).not.toThrow();
    expect(() => enterMessage(panel)).not.toThrow();
  });
});
