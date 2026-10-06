import path from "node:path";
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const currentDirectory = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  envDir: false,
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(currentDirectory, "./app"),
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./tests/setup.ts"],
    globals: true,
    clearMocks: true,
    restoreMocks: true,
    include: ["tests/**/*.test.{ts,tsx}"],
  },
});
