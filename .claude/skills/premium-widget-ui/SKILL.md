---
name: premium-widget-ui
description: Use whenever building a UI that needs to feel like a polished, premium (agency/$5000-quality) product — chat widgets, floating launchers, embeddable components, or any interface that will be dropped into an existing website. Trigger this any time the user asks to make something "look professional," "look premium," "feel expensive," or references matching top SaaS/open-source product polish, even if they don't say "widget" explicitly. Covers style isolation from host pages, motion/micro-interaction design, and accessibility for motion — the details that separate a functional UI from one that reads as premium.
---

# Premium Widget UI & Motion

A UI reads as "cheap" or "premium" almost entirely based on details most people can't name: isolation from the host page, timing curves, staggering, and whether motion respects the user. This skill encodes those details so they're applied consistently, not reinvented per prompt.

## 1. Visual isolation (critical for anything embedded into an existing site)

- Use **Shadow DOM** so the widget's styles can never leak into, or be leaked into by, the host page's existing CSS (Bootstrap, jQuery UI themes, legacy stylesheets). This is the single highest-leverage decision for an embedded widget — skipping it is the most common reason embedded widgets look "bolted on."
- Never rely on generic global class names (`.btn`, `.card`, `.modal`) inside the widget — the host page likely already defines conflicting ones. If Shadow DOM genuinely isn't possible, prefix every class uniquely (e.g. `pwui-btn`) and scope a reset at the widget root.
- Always test the widget dropped into a page that already has heavy CSS loaded (Bootstrap, Animate.css, etc.) — not just in isolation — before calling it done.

## 2. Motion principles

- Every meaningful state change animates, but subtly. Micro-interactions: 150–250ms. Larger transitions (panel open/close): 300–400ms. Longer than that reads as sluggish, shorter reads as jarring.
- Never use the browser default `ease` or `linear`. Use curves that feel physical:
  - Entrances: `cubic-bezier(0.16, 1, 0.3, 1)` (ease-out-expo — fast start, gentle settle)
  - Exits: `cubic-bezier(0.7, 0, 0.84, 0)` (ease-in-expo)
- Stagger related elements (list items, chips, sequential message chunks) by 30–50ms each instead of animating as one block. This single habit reads as "expensive" more than almost anything else.
- Respect `prefers-reduced-motion: reduce` — always provide an instant, non-animated fallback. Never force motion on users who've disabled it; this is an accessibility requirement, not optional polish.

## 3. Libraries

- **React-based widget** → Framer Motion (`motion` package). Use `AnimatePresence` for exit animations, layout animations for reflow, gesture support for drag/swipe if needed.
- **Vanilla/lightweight embed (no framework)** → GSAP. Best-in-class timeline and easing control; the free core covers everything a widget needs.
- Reserve plain CSS transitions for simple hover/focus states only. Anything stateful (open/close, reordering, list entrance) gets unmanageable fast in CSS alone — use the JS library instead.

## 4. Chat-widget-specific patterns (the details that actually read as premium)

- **Launcher button**: a subtle idle animation (gentle scale-breathing, ~3s loop, low amplitude) draws the eye without nagging. Pause it permanently after the first interaction — a launcher that keeps pulsing after the user has already engaged reads as broken, not eager.
- **Message entrance**: fade + small upward translate (8–12px), staggered across consecutive bot message chunks rather than all at once.
- **Typing indicator**: three dots with *offset* bounce timing. Perfectly synchronized dots read as a cheap default component — the offset is what makes it feel alive.
- **Send button**: the disabled → enabled transition should morph color and icon together, not just toggle opacity.
- **Voice mode**: if there's a listening/speaking state, drive it from actual audio amplitude (even a simple canvas amplitude visualizer) — a generic looping "listening..." GIF or static icon is an instant tell that the voice feature is superficial.
- **Panel open/close**: scale + fade with `transform-origin` anchored at the launcher button's corner, so the panel visibly "grows out of" the button it opened from — not a generic center-screen fade.

## 5. Layout & spacing

- Use a consistent spacing scale only: 4 / 8 / 12 / 16 / 24 / 32px. No arbitrary values.
- Generous internal padding on message bubbles (12–16px) — cramped bubbles are one of the fastest "low-budget" tells.
- Pull the host site's actual brand colors and fonts rather than guessing or defaulting to a generic blue — a widget whose palette doesn't match the site it lives on always reads as bolted-on rather than native.

## 6. Accessibility (non-negotiable, not a nice-to-have)

- Full keyboard navigation: Tab through interactive elements, Enter to send, Escape to close.
- An ARIA live region wrapping new messages so screen readers announce them as they arrive.
- Color contrast meeting WCAG AA at minimum, checked against the actual brand palette in use, not just the design mockup.

## 7. Before calling it done — checklist

- [ ] Tested with `prefers-reduced-motion: reduce` enabled — everything still functions, just without motion.
- [ ] Tested embedded in the actual target site, not only in a blank sandbox — confirms no CSS collision.
- [ ] All animations run on `transform` / `opacity` only (GPU-accelerated). Animating `width`, `height`, `top`, or `left` directly causes visible jank — refactor to `transform: scale()`/`translate()` instead.
- [ ] Keyboard-only pass: can a user operate the entire widget without a mouse?
