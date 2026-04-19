import { defineConfig } from "vite";
import path from "path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";

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
