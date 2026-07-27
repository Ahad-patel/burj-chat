import { layout, palette, radius, space, typography } from "../tokens";

/**
 * All widget CSS, as a string injected into the shadow root.
 *
 * Two things make this safe inside an ASP.NET WebForms page carrying Bootstrap,
 * Animate.css, Swiper, and jQuery UI:
 *
 * 1. **Shadow DOM.** Host styles cannot reach in; these cannot leak out. This
 *    is the single highest-leverage decision for an embedded widget.
 * 2. **No generic class names.** Every selector is `bc-` prefixed. Even though
 *    the shadow boundary makes collisions impossible, a `.btn` or `.card` in
 *    here would be a trap for whoever later needs to render part of this
 *    outside the shadow root.
 *
 * `all: initial` on the host element is belt-and-braces: it neutralises
 * inherited properties (font, colour, line-height, direction) that *do* cross
 * the shadow boundary.
 */
export const styles = `
/*
 * The host element sits in the *light* DOM, so the page's cascade reaches it
 * even though nothing inside the shadow root is touched. A real harness run
 * caught this: \`div { border: 2px solid lime !important }\` on the host page
 * put a lime border around the whole widget.
 *
 * Per CSS Cascading 4, importance reverses the usual shadow ordering — for
 * !important declarations the *inner* (shadow) context wins over the outer
 * document. So this block, and only this block, uses !important: it is the one
 * place where an outer !important must be beaten.
 */
:host {
  position: fixed !important;
  bottom: ${space.xl} !important;
  right: ${space.xl} !important;
  left: auto !important;
  top: auto !important;
  z-index: ${layout.zIndex} !important;
  display: block !important;
  width: auto !important;
  height: auto !important;
  margin: 0 !important;
  padding: 0 !important;
  border: 0 !important;
  background: transparent !important;
  box-shadow: none !important;
  float: none !important;
  clip-path: none !important;
  transform: none !important;
  opacity: 1 !important;
  visibility: visible !important;
  pointer-events: auto !important;
}

:host {
  all: initial;
  font-family: ${typography.family};
  font-size: ${typography.sizeBase};
  line-height: ${typography.lineBase};
  position: fixed;
  bottom: ${space.xl};
  right: ${space.xl};
  z-index: ${layout.zIndex};
  color: ${palette.textPrimary};
  -webkit-font-smoothing: antialiased;
}

*, *::before, *::after { box-sizing: border-box; }

/* ---------------------------------------------------------------------------
   Launcher
--------------------------------------------------------------------------- */
.bc-launcher {
  width: ${layout.launcherSize};
  height: ${layout.launcherSize};
  border-radius: ${radius.pill};
  border: none;
  background: ${palette.gold};
  color: ${palette.textOnGold};
  cursor: pointer;
  display: grid;
  place-items: center;
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.28);
  /* transform/opacity only — animating width or box-shadow janks. */
  transition: transform 180ms cubic-bezier(0.16, 1, 0.3, 1),
              background-color 180ms cubic-bezier(0.16, 1, 0.3, 1);
  position: absolute;
  bottom: 0;
  right: 0;
}
.bc-launcher:hover { background: ${palette.goldBright}; transform: scale(1.06); }
.bc-launcher:active { transform: scale(0.97); }
.bc-launcher:focus-visible {
  outline: 3px solid ${palette.goldBright};
  outline-offset: 3px;
}
.bc-launcher[hidden] { display: none; }
.bc-launcher svg { width: 26px; height: 26px; pointer-events: none; }

/* Unread nudge — only shown before first engagement. */
.bc-launcher__dot {
  position: absolute;
  top: 4px; right: 4px;
  width: 12px; height: 12px;
  border-radius: ${radius.pill};
  background: ${palette.danger};
  border: 2px solid ${palette.ink};
}

/* ---------------------------------------------------------------------------
   Panel
--------------------------------------------------------------------------- */
.bc-panel {
  width: ${layout.panelWidth};
  height: ${layout.panelHeight};
  max-width: calc(100vw - ${space.xl});
  max-height: calc(100vh - ${space.xxl});
  background: ${palette.ink};
  border-radius: ${radius.lg};
  border: 1px solid ${palette.inkLine};
  box-shadow: 0 24px 60px rgba(0, 0, 0, 0.45);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  position: absolute;
  bottom: 0;
  right: 0;
  /* Anchored at the launcher's corner so the panel grows *out of* the button
     it opened from, rather than fading in at screen centre. */
  transform-origin: bottom right;
  opacity: 0;
  visibility: hidden;
}
.bc-panel[data-open="true"] { visibility: visible; }

.bc-header {
  display: flex;
  align-items: center;
  gap: ${space.md};
  padding: ${space.lg};
  background: ${palette.inkRaised};
  border-bottom: 1px solid ${palette.inkLine};
  flex-shrink: 0;
}
.bc-header__mark {
  width: 36px; height: 36px;
  border-radius: ${radius.sm};
  background: ${palette.gold};
  color: ${palette.textOnGold};
  display: grid; place-items: center;
  font-weight: 700; font-size: ${typography.sizeLg};
  flex-shrink: 0;
}
.bc-header__text { flex: 1; min-width: 0; }
.bc-header__title {
  margin: 0;
  font-size: ${typography.sizeLg};
  font-weight: 600;
  color: ${palette.textPrimary};
}
.bc-header__status {
  margin: 0;
  font-size: ${typography.sizeSm};
  color: ${palette.textMuted};
  display: flex; align-items: center; gap: ${space.xs};
}
.bc-header__status::before {
  content: "";
  width: 6px; height: 6px;
  border-radius: ${radius.pill};
  background: #4ade80;
}
.bc-close {
  background: transparent;
  border: none;
  color: ${palette.textMuted};
  cursor: pointer;
  padding: ${space.sm};
  border-radius: ${radius.sm};
  display: grid; place-items: center;
  transition: color 180ms cubic-bezier(0.16, 1, 0.3, 1),
              background-color 180ms cubic-bezier(0.16, 1, 0.3, 1);
}
.bc-close:hover { color: ${palette.textPrimary}; background: rgba(255,255,255,0.07); }
.bc-close:focus-visible { outline: 2px solid ${palette.gold}; outline-offset: 2px; }
.bc-close svg { width: 18px; height: 18px; pointer-events: none; }

/* ---------------------------------------------------------------------------
   Messages
--------------------------------------------------------------------------- */
.bc-log {
  flex: 1;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: ${space.lg};
  display: flex;
  flex-direction: column;
  gap: ${space.md};
  scrollbar-width: thin;
  scrollbar-color: ${palette.inkLine} transparent;
}
.bc-log::-webkit-scrollbar { width: 6px; }
.bc-log::-webkit-scrollbar-thumb {
  background: ${palette.inkLine};
  border-radius: ${radius.pill};
}

.bc-msg {
  max-width: 85%;
  /* Generous padding — cramped bubbles are a fast low-budget tell. */
  padding: ${space.md} ${space.lg};
  border-radius: ${radius.md};
  font-size: ${typography.sizeBase};
  line-height: ${typography.lineBase};
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.bc-msg--assistant {
  align-self: flex-start;
  background: ${palette.inkRaised};
  color: ${palette.textPrimary};
  border-bottom-left-radius: ${radius.sm};
}
.bc-msg--user {
  align-self: flex-end;
  background: ${palette.gold};
  color: ${palette.textOnGold};
  border-bottom-right-radius: ${radius.sm};
}
.bc-msg--error {
  align-self: flex-start;
  background: rgba(255, 138, 122, 0.12);
  color: ${palette.danger};
  border: 1px solid rgba(255, 138, 122, 0.3);
}

/* Suggested opening questions. */
.bc-chips { display: flex; flex-wrap: wrap; gap: ${space.sm}; }
.bc-chip {
  background: transparent;
  border: 1px solid ${palette.inkLine};
  color: ${palette.textPrimary};
  border-radius: ${radius.pill};
  padding: ${space.sm} ${space.md};
  font-size: ${typography.sizeSm};
  font-family: inherit;
  cursor: pointer;
  transition: border-color 180ms cubic-bezier(0.16, 1, 0.3, 1),
              background-color 180ms cubic-bezier(0.16, 1, 0.3, 1);
}
.bc-chip:hover { border-color: ${palette.gold}; background: rgba(222, 179, 57, 0.1); }
.bc-chip:focus-visible { outline: 2px solid ${palette.gold}; outline-offset: 2px; }

/* Typing indicator — dots bounce on *offset* timing. Perfectly synchronised
   dots read as a stock component; the offset is what makes it feel alive. */
.bc-typing {
  align-self: flex-start;
  display: flex;
  gap: ${space.xs};
  padding: ${space.md} ${space.lg};
  background: ${palette.inkRaised};
  border-radius: ${radius.md};
  border-bottom-left-radius: ${radius.sm};
}
.bc-typing span {
  width: 7px; height: 7px;
  border-radius: ${radius.pill};
  background: ${palette.textMuted};
  animation: bc-bounce 1.3s ease-in-out infinite;
}
.bc-typing span:nth-child(2) { animation-delay: 0.16s; }
.bc-typing span:nth-child(3) { animation-delay: 0.32s; }

@keyframes bc-bounce {
  0%, 60%, 100% { transform: translateY(0); opacity: 0.5; }
  30% { transform: translateY(-5px); opacity: 1; }
}

/* ---------------------------------------------------------------------------
   Composer
--------------------------------------------------------------------------- */
.bc-composer {
  display: flex;
  align-items: flex-end;
  gap: ${space.sm};
  padding: ${space.md};
  border-top: 1px solid ${palette.inkLine};
  background: ${palette.inkRaised};
  flex-shrink: 0;
}
.bc-input {
  flex: 1;
  background: ${palette.ink};
  border: 1px solid ${palette.inkLine};
  border-radius: ${radius.md};
  color: ${palette.textPrimary};
  font-family: inherit;
  font-size: ${typography.sizeBase};
  line-height: ${typography.lineBase};
  padding: ${space.md};
  resize: none;
  max-height: 108px;
  transition: border-color 180ms cubic-bezier(0.16, 1, 0.3, 1);
}
.bc-input::placeholder { color: ${palette.textMuted}; }
.bc-input:focus { outline: none; border-color: ${palette.gold}; }
.bc-input:disabled { opacity: 0.6; cursor: not-allowed; }

/* Disabled -> enabled morphs colour and icon together, not just opacity. */
.bc-send {
  width: 40px; height: 40px;
  flex-shrink: 0;
  border: none;
  border-radius: ${radius.md};
  background: ${palette.inkLine};
  color: ${palette.textMuted};
  cursor: not-allowed;
  display: grid; place-items: center;
  transition: background-color 180ms cubic-bezier(0.16, 1, 0.3, 1),
              color 180ms cubic-bezier(0.16, 1, 0.3, 1),
              transform 180ms cubic-bezier(0.16, 1, 0.3, 1);
}
.bc-send[data-ready="true"] {
  background: ${palette.gold};
  color: ${palette.textOnGold};
  cursor: pointer;
}
.bc-send[data-ready="true"]:hover { background: ${palette.goldBright}; transform: scale(1.05); }
.bc-send:focus-visible { outline: 2px solid ${palette.goldBright}; outline-offset: 2px; }
.bc-send svg { width: 18px; height: 18px; pointer-events: none; }

.bc-footer {
  padding: 0 ${space.md} ${space.sm};
  background: ${palette.inkRaised};
  font-size: 11px;
  color: ${palette.textMuted};
  text-align: center;
}

/* Visible only to screen readers. */
.bc-sr-only {
  position: absolute;
  width: 1px; height: 1px;
  padding: 0; margin: -1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
  border: 0;
}

/* ---------------------------------------------------------------------------
   Reduced motion — an accessibility requirement, not optional polish.
   GSAP timelines are separately short-circuited in motion.ts; this covers the
   CSS-driven animation and transitions.
--------------------------------------------------------------------------- */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
  .bc-typing span { animation: none; opacity: 0.75; }
}

/* Small screens: fill the viewport rather than float a cramped card. */
@media (max-width: 480px) {
  :host { bottom: ${space.md}; right: ${space.md}; left: ${space.md}; }
  .bc-panel {
    width: auto;
    left: 0; right: 0;
    height: min(${layout.panelHeight}, calc(100vh - ${space.xxl}));
  }
}
`;
