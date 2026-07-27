import { describe, expect, it } from "vitest";
import {
  AA_LARGE_TEXT,
  AA_NORMAL_TEXT,
  contrastRatio,
  meetsAA,
  parseHex,
  relativeLuminance,
} from "../src/a11y/contrast";
import { palette } from "../src/tokens";

/**
 * Contrast is asserted, not claimed.
 *
 * The skill requires contrast "checked against the actual brand palette in
 * use, not just the design mockup". A number written into a README goes stale
 * the first time someone nudges a colour; these fail the build instead.
 */

describe("WCAG maths", () => {
  it("computes the reference luminances", () => {
    expect(relativeLuminance("#ffffff")).toBeCloseTo(1, 5);
    expect(relativeLuminance("#000000")).toBeCloseTo(0, 5);
  });

  it("computes the reference contrast ratio", () => {
    expect(contrastRatio("#ffffff", "#000000")).toBeCloseTo(21, 1);
  });

  it("is order independent", () => {
    expect(contrastRatio(palette.gold, palette.ink)).toBeCloseTo(
      contrastRatio(palette.ink, palette.gold),
      5,
    );
  });

  it("expands three-digit hex", () => {
    expect(parseHex("#fff")).toEqual(parseHex("#ffffff"));
  });

  it("rejects nonsense", () => {
    expect(() => parseHex("burgundy")).toThrow();
  });
});

describe("every pairing the widget actually renders", () => {
  const pairings: Array<[string, string, string, boolean]> = [
    // [description, foreground, background, isLargeText]
    ["body text on the panel", palette.textPrimary, palette.ink, false],
    ["body text on raised surfaces", palette.textPrimary, palette.inkRaised, false],
    ["assistant bubble text", palette.textPrimary, palette.inkRaised, false],
    ["user bubble text on gold", palette.textOnGold, palette.gold, false],
    ["header title", palette.textPrimary, palette.inkRaised, false],
    ["send-button icon on gold", palette.textOnGold, palette.gold, false],
    ["launcher icon on gold", palette.textOnGold, palette.gold, false],
    ["chip label", palette.textPrimary, palette.ink, false],
    ["error text", palette.danger, palette.ink, false],
    // Muted text is used only for secondary information at 12px, but 12px is
    // not "large" under WCAG, so it is held to the full 4.5:1 anyway.
    ["muted secondary text", palette.textMuted, palette.inkRaised, false],
    ["muted secondary text on panel", palette.textMuted, palette.ink, false],
  ];

  it.each(pairings)("%s meets AA", (_label, foreground, background, large) => {
    const ratio = contrastRatio(foreground, background);
    const required = large ? AA_LARGE_TEXT : AA_NORMAL_TEXT;

    expect(
      ratio,
      `${foreground} on ${background} is ${ratio.toFixed(2)}:1, needs ${required}:1`,
    ).toBeGreaterThanOrEqual(required);
  });
});

describe("the constraint that shapes the whole design", () => {
  it("gold text on white fails AA, which is why it is never used that way", () => {
    // 1.98:1. This is not a defect being documented — it is the reason gold
    // appears only as a background with dark ink on top, or as text on
    // charcoal. If someone later puts gold text on a light surface, this test
    // is the note explaining why they should not.
    expect(meetsAA(palette.gold, palette.white)).toBe(false);
    expect(contrastRatio(palette.gold, palette.white)).toBeLessThan(2.5);
  });

  it("gold as a background with dark ink passes comfortably", () => {
    expect(contrastRatio(palette.textOnGold, palette.gold)).toBeGreaterThan(7);
  });

  it("gold as text on the panel passes comfortably", () => {
    expect(contrastRatio(palette.gold, palette.ink)).toBeGreaterThan(7);
  });
});
