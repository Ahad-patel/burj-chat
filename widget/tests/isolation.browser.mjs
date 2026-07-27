/**
 * Real-browser verification of CSS isolation.
 *
 * jsdom can confirm the shadow root exists, but it cannot run the cascade —
 * and "zero CSS collision" is a claim about the cascade. So this loads the
 * built bundle into headless Chromium on a page carrying the host site's
 * actual Bootstrap, Animate.css, burj.css and jQuery 3.5.1, plus deliberately
 * hostile overrides, and reads the *computed* styles inside the shadow root.
 *
 *     node tests/isolation.browser.mjs
 *
 * Kept out of the Vitest run because it needs a browser binary; `npm run
 * verify` invokes it after a build.
 */

import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const demo = fileURLToPath(new URL("../demo/index.html", import.meta.url));

/** Styles the hostile CSS would impose if the widget were not isolated. */
const HOSTILE = {
  fontFamily: /comic sans/i,
  buttonBackground: "rgb(255, 0, 255)",
  buttonColor: "rgb(0, 255, 0)",
  inputBackground: "rgb(0, 0, 0)",
  borderColor: "rgb(0, 255, 0)",
};

const failures = [];
const passes = [];

function check(name, passed, detail = "") {
  (passed ? passes : failures).push(detail ? `${name} — ${detail}` : name);
}

const browser = await chromium.launch();
const page = await browser.newPage();

page.on("console", (message) => {
  if (message.type() === "error" && !message.text().includes("localhost:8000")) {
    check("no console errors", false, message.text());
  }
});

await page.goto(`file://${demo}`);
await page.waitForTimeout(400);

// --- The page's own assertions ------------------------------------------------
const report = await page.evaluate(() => globalThis.__collisionReport);
for (const result of report.results) {
  check(result.name, result.passed, result.detail);
}

// --- Confirm the hostile CSS actually bites unprotected elements ---------------
// Without this the whole harness could pass by the overrides simply not
// applying, which would make every isolation check meaningless.
const hostButton = await page.evaluate(() => {
  const style = getComputedStyle(document.querySelector("#plain-control"));
  return { background: style.backgroundColor, font: style.fontFamily, color: style.color };
});

check(
  "hostile CSS genuinely affects host-page elements (control)",
  hostButton.background === HOSTILE.buttonBackground &&
    HOSTILE.fontFamily.test(hostButton.font),
  `host button was ${hostButton.background} / ${hostButton.font}`,
);

// --- Computed styles *inside* the shadow root ---------------------------------
// Playwright's CSS engine pierces open shadow roots automatically, so a plain
// selector reaches inside. This is exactly the asymmetry we want: an auditing
// tool can inspect the widget, while `document.querySelector` on the host page
// still cannot (asserted above).
const launcher = page.locator(".bc-launcher");
const panel = page.locator(".bc-panel");

const launcherStyle = await launcher.evaluate((element) => {
  const style = getComputedStyle(element);
  return {
    background: style.backgroundColor,
    color: style.color,
    font: style.fontFamily,
    fontSize: style.fontSize,
    borderStyle: style.borderTopStyle,
    borderRadius: style.borderTopLeftRadius,
    padding: style.paddingTop,
    textTransform: style.textTransform,
  };
});

check(
  "launcher keeps the brand gold, not the hostile magenta",
  launcherStyle.background === "rgb(222, 179, 57)",
  `was ${launcherStyle.background}`,
);
check(
  "launcher keeps Poppins, not the forced Comic Sans",
  !HOSTILE.fontFamily.test(launcherStyle.font),
  `was ${launcherStyle.font}`,
);
check(
  "launcher keeps its own font size, not 28px",
  launcherStyle.fontSize !== "28px",
  `was ${launcherStyle.fontSize}`,
);
check(
  "launcher keeps its pill radius, not the forced 0",
  launcherStyle.borderRadius !== "0px",
  `was ${launcherStyle.borderRadius}`,
);
check(
  "launcher keeps its padding, not the forced 40px",
  launcherStyle.padding !== "40px",
  `was ${launcherStyle.padding}`,
);
check(
  "launcher is not force-uppercased",
  launcherStyle.textTransform !== "uppercase",
  `was ${launcherStyle.textTransform}`,
);
check(
  "launcher has no dashed red border",
  launcherStyle.borderStyle !== "dashed",
  `was ${launcherStyle.borderStyle}`,
);

const panelStyle = await panel.evaluate((element) => {
  const style = getComputedStyle(element);
  return { borderColor: style.borderTopColor, background: style.backgroundColor };
});

check(
  "panel is not force-bordered lime by `div { border }`",
  panelStyle.borderColor !== HOSTILE.borderColor,
  `was ${panelStyle.borderColor}`,
);

// --- Open the panel and check the composer ------------------------------------
await launcher.click();
await page.waitForTimeout(500);

const inputStyle = await page
  .locator(".bc-input")
  .evaluate((element) => {
    const style = getComputedStyle(element);
    return { background: style.backgroundColor, fontSize: style.fontSize, border: style.borderTopColor };
  });

check(
  "composer keeps its dark surface, not the hostile black",
  inputStyle.background !== HOSTILE.inputBackground,
  `was ${inputStyle.background}`,
);
check(
  "composer keeps its own font size, not the forced 30px",
  inputStyle.fontSize !== "30px",
  `was ${inputStyle.fontSize}`,
);

const svgBox = await page
  .locator(".bc-send svg")
  .evaluate((element) => element.getBoundingClientRect().width);

check(
  "icons keep their size, not the forced 200px",
  svgBox < 40,
  `send icon rendered ${svgBox}px wide`,
);

// --- Panel actually rendered at a sane size -----------------------------------
const panelBox = await panel.boundingBox();
check(
  "panel renders at its designed size",
  panelBox !== null && panelBox.width > 300 && panelBox.height > 400,
  panelBox ? `${Math.round(panelBox.width)}x${Math.round(panelBox.height)}` : "not visible",
);

await browser.close();

// --- Report -------------------------------------------------------------------
for (const name of passes) console.log(`  PASS  ${name}`);
for (const name of failures) console.log(`  FAIL  ${name}`);

console.log(`\n${passes.length}/${passes.length + failures.length} checks passed`);

if (failures.length > 0) process.exit(1);
