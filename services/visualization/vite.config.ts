import { defineConfig } from "vite";
import path from "path";
import { fileURLToPath } from "url";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
  ],

  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./app"),
    },
  },

  assetsInclude: ["**/*.svg", "**/*.csv"],

  server: {
    host: "0.0.0.0",
    port: 3000,

    allowedHosts: [
      "maps.rikon-karmakar.quest"
    ],

    proxy: {
      "/api/cities": {
        target: "http://localhost:8001",
        changeOrigin: true,
        rewrite: (path) => path.replace("/api", ""),
      },
      "/api/city-context": {
        target: "http://localhost:8001",
        changeOrigin: true,
        rewrite: (path) => path.replace("/api", ""),
      },
      "/api/hotspots": {
        target: "http://localhost:8001",
        changeOrigin: true,
        rewrite: (path) => path.replace("/api", ""),
      },
      "/api/corridor-towers": {
        target: "http://localhost:8001",
        changeOrigin: true,
        rewrite: (path) => path.replace("/api", ""),
      },
      "/api/corridor-scores": {
        target: "http://localhost:8001",
        changeOrigin: true,
        rewrite: (path) => path.replace("/api", ""),
      },
      "/api/tiles": {
        target: "http://localhost:8001",
        changeOrigin: true,
        rewrite: (path) => path.replace("/api", ""),
      },
      "/api/scores": {
        target: "http://localhost:8001",
        changeOrigin: true,
        rewrite: (path) => path.replace("/api", ""),
      },
      "/api/cache-status": {
        target: "http://localhost:8001",
        changeOrigin: true,
        rewrite: (path) => path.replace("/api", ""),
      },
      "/api/route": {
        target: "http://localhost:8002",
        changeOrigin: true,
        rewrite: (path) => path.replace("/api", ""),
      },
      "/api/preload": {
        target: "http://localhost:8002",
        changeOrigin: true,
        rewrite: (path) => path.replace("/api", ""),
      },
      "/api/test-route": {
        target: "http://localhost:8002",
        changeOrigin: true,
        rewrite: (path) => path.replace("/api", ""),
      },
      "/api/predict": {
        target: "http://localhost:8003",
        changeOrigin: true,
        rewrite: (path) => path.replace("/api", ""),
      },
    },
  },
});
