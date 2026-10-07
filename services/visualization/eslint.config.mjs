import eslint from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

const activeTypeScriptFiles = [
  "app/**/*.{ts,tsx}",
  "tests/**/*.{ts,tsx}",
  "vite.config.ts",
  "vitest.config.ts",
  "playwright.config.ts",
  "e2e/**/*.ts",
];

export default tseslint.config(
  {
    ignores: [
      "dist/**",
      "node_modules/**",
      "visualization/**",
    ],
  },
  {
    ...eslint.configs.recommended,
    files: ["*.config.mjs"],
    languageOptions: {
      globals: globals.node,
    },
  },
  ...tseslint.configs.recommended.map((config) => ({
    ...config,
    files: activeTypeScriptFiles,
  })),
  {
    files: activeTypeScriptFiles,
    languageOptions: {
      globals: globals.browser,
    },
    plugins: {
      "react-hooks": reactHooks,
    },
    rules: {
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "error",
      "@typescript-eslint/no-unused-vars": [
        "error",
        { "argsIgnorePattern": "^_", "varsIgnorePattern": "^_" }
      ],
    },
  },
  {
    files: ["vite.config.ts", "vitest.config.ts", "playwright.config.ts", "e2e/**/*.ts"],
    languageOptions: {
      globals: globals.node,
    },
  },
);
