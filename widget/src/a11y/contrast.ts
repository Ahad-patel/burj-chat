/**
 * WCAG relative luminance and contrast ratio.
 *
 * This exists so accessibility is *asserted* rather than asserted-about. The
 * skill's requirement is "contrast meeting WCAG AA, checked against the actual
 * brand palette in use, not just the design mockup" — a claim in a README
 * cannot fail a build, and a hand-checked value goes stale the first time
 * someone nudges a colour.
 *
 * Implements the WCAG 2.1 definition directly:
 * https://www.w3.org/TR/WCAG21/#dfn-relative-luminance
 */

export const AA_NORMAL_TEXT = 4.5;
export const AA_LARGE_TEXT = 3;
export const AAA_NORMAL_TEXT = 7;

interface Rgb {
  r: number;
  g: number;
  b: number;
}

export function parseHex(hex: string): Rgb {
  const cleaned = hex.replace("#", "").trim();

  const expanded =
    cleaned.length === 3
      ? cleaned
          .split("")
          .map((char) => char + char)
          .join("")
      : cleaned;

  if (!/^[0-9a-f]{6}$/i.test(expanded)) {
    throw new Error(`Not a hex colour: ${hex}`);
  }

  return {
    r: Number.parseInt(expanded.slice(0, 2), 16),
    g: Number.parseInt(expanded.slice(2, 4), 16),
    b: Number.parseInt(expanded.slice(4, 6), 16),
  };
}

/** Linearise one sRGB channel, per the WCAG formula. */
function linearise(channel: number): number {
  const normalised = channel / 255;
  return normalised <= 0.03928
    ? normalised / 12.92
    : Math.pow((normalised + 0.055) / 1.055, 2.4);
}

export function relativeLuminance(hex: string): number {
  const { r, g, b } = parseHex(hex);
  return 0.2126 * linearise(r) + 0.7152 * linearise(g) + 0.0722 * linearise(b);
}

/** Contrast ratio between two colours, 1:1 (identical) to 21:1 (black/white). */
export function contrastRatio(foreground: string, background: string): number {
  const a = relativeLuminance(foreground);
  const b = relativeLuminance(background);
  const lighter = Math.max(a, b);
  const darker = Math.min(a, b);
  return (lighter + 0.05) / (darker + 0.05);
}

export function meetsAA(foreground: string, background: string, large = false): boolean {
  const required = large ? AA_LARGE_TEXT : AA_NORMAL_TEXT;
  return contrastRatio(foreground, background) >= required;
}
