/**
 * Design tokens, taken from burjconstructions.com's own stylesheet.
 *
 * These are not invented. `#deb339` is the most-used colour in the site's
 * `css/burj.css` (15 occurrences), `#23262d` and `#1e2126` are its dark
 * surfaces, and Poppins is the typeface it loads from Google Fonts. A widget
 * whose palette does not match the site it lives on always reads as bolted-on.
 *
 * **The brief said "navy/gold". The site has no navy.** Its dark surfaces are
 * near-black and charcoal — greys with a faint blue cast, not blue. Building
 * navy would have produced exactly the mismatch this file exists to prevent.
 *
 * Contrast note: gold on white is **1.98:1** and fails WCAG AA badly, so gold
 * is never used as text on a light surface here. It appears as a background
 * with dark ink on top (7.8:1) or as text on charcoal (8.0:1). `contrast.ts`
 * enforces this, and the test suite fails the build if a pairing regresses.
 */

export const palette = {
  /** The brand gold. Most-used colour in the site's own CSS. */
  gold: "#deb339",
  /** Hover/active gold, also from the site. */
  goldBright: "#ffcf88",
  goldDeep: "#c99a28",

  /** Panel background — the site's darkest surface. */
  ink: "#1e2126",
  /** Raised surface: header, assistant bubbles. */
  inkRaised: "#23262d",
  /** Hairline borders on dark. */
  inkLine: "#33373f",

  /** Primary text on dark surfaces. */
  textPrimary: "#f4f4f5",
  /** Secondary text — timestamps, hints. */
  textMuted: "#a9adb6",
  /** Text that sits on gold. */
  textOnGold: "#1a1c21",

  white: "#ffffff",
  danger: "#ff8a7a",
} as const;

/**
 * Spacing scale. Only these values are used — arbitrary numbers are the
 * fastest way for a layout to start looking improvised.
 */
export const space = {
  xs: "4px",
  sm: "8px",
  md: "12px",
  lg: "16px",
  xl: "24px",
  xxl: "32px",
} as const;

export const radius = {
  sm: "8px",
  md: "12px",
  lg: "18px",
  pill: "999px",
} as const;

export const typography = {
  /** Poppins is what the host site loads. The fallback stack matters: the
   *  widget must not *depend* on the host having loaded it. */
  family: '"Poppins", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
  sizeSm: "12px",
  sizeBase: "14px",
  sizeLg: "16px",
  lineBase: "1.55",
} as const;

/**
 * Motion. Durations sit in the ranges that read as considered rather than
 * sluggish or jarring; the curves are physical rather than the browser default.
 */
export const motion = {
  /** Micro-interactions: hover, focus, button state. */
  fast: 0.18,
  /** Message entrance. */
  medium: 0.28,
  /** Panel open/close. */
  slow: 0.38,

  /** ease-out-expo — fast start, gentle settle. */
  enter: "expo.out",
  /** ease-in-expo. */
  exit: "expo.in",

  /** Per-item delay when animating a group. The single habit that reads as
   *  "expensive" more than any other. */
  stagger: 0.04,
} as const;

export const layout = {
  panelWidth: "384px",
  panelHeight: "560px",
  launcherSize: "60px",
  /** Above Bootstrap modals (1050) and most host-site chrome. */
  zIndex: "2147483000",
} as const;
