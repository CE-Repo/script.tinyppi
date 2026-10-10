// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 U3knOwn

// Lint for the dashboard's scripts (resources/web/js).  They are classic
// scripts loaded in order by index.html and share one global scope:
// core.js, theme.js, colour.js, cover-tint.js and readings.js each publish
// one global object.

import js from "@eslint/js";
import globals from "globals";

export default [
  js.configs.recommended,
  {
    files: ["resources/web/js/**/*.js"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "script",
      globals: {
        ...globals.browser,
        TinyPPI: "writable",
        TinyPPIColour: "writable",
        TinyPPICover: "writable",
        TinyPPIReadings: "writable",
        TinyPPITheme: "writable",
      },
    },
    rules: {
      // Storage can throw (private windows); those catches are empty on purpose.
      "no-empty": ["error", { allowEmptyCatch: true }],
      "no-unused-vars": ["error", { args: "none", caughtErrors: "none" }],
      eqeqeq: ["error", "smart"],
      "no-var": "error",
      "prefer-const": "error",
    },
  },
  {
    // The tests for those scripts (npm test, npm run test:browser): ES
    // modules run by Node.
    files: ["tests/web/**/*.mjs", "tests/browser/**/*.mjs"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      globals: globals.node,
    },
  },
  {
    // The browser test also hands functions to the page, which run there.
    files: ["tests/browser/**/*.mjs"],
    languageOptions: { globals: { ...globals.node, ...globals.browser } },
  },
];
