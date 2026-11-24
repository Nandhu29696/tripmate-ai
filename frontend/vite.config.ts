/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The FastAPI app serves the built files in production. In development, Vite
// serves the UI and forwards API and auth calls to the backend on :8000, so
// cookies and redirects behave exactly as they do in production.
const backend = "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": backend,
      "/auth": backend,
      "/health": backend,
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    // Keep every script external: the app's Content-Security-Policy forbids inline scripts.
    assetsInlineLimit: 0,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
