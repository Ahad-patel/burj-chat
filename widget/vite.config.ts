/// <reference types="vitest/config" />
import { resolve } from "node:path";
// vitest/config re-exports vite's defineConfig with the `test` block typed,
// so build and test settings can live in one file.
import { defineConfig } from "vitest/config";

/**
 * Builds one self-contained IIFE.
 *
 * The host is an ASP.NET WebForms site we cannot modify — no bundler, no
 * module graph, no build step of their own. The only viable delivery is a
 * single `<script src>` that runs on load, so every setting below exists to
 * collapse the output to exactly that: no chunks, no separate CSS file, no
 * dynamic imports to resolve at runtime.
 */
export default defineConfig({
  build: {
    lib: {
      entry: resolve(__dirname, "src/index.ts"),
      name: "BurjChat",
      formats: ["iife"],
      fileName: () => "burj-chat.js",
    },
    // Styles are injected into the shadow root as a string, so there is no
    // stylesheet to emit or for the host page to load.
    cssCodeSplit: false,
    // Inline anything that would otherwise become a second request. A widget
    // that needs two files is a widget someone will deploy half of.
    assetsInlineLimit: 100_000_000,
    rollupOptions: {
      output: {
        inlineDynamicImports: true,
      },
    },
    target: "es2019",
    sourcemap: true,
    minify: "esbuild",
    reportCompressedSize: true,
  },
  test: {
    environment: "jsdom",
    globals: true,
    include: ["tests/**/*.test.ts"],
    coverage: {
      provider: "v8",
      include: ["src/**/*.ts"],
    },
  },
});
