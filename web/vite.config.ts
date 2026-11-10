import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The browser only ever talks to this origin. In development Vite forwards
// /api and /agent to the backend services; in Docker nginx does the same.
// One origin means no CORS and no need to expose the APIs separately.
const API_TARGET = process.env.API_TARGET ?? "http://localhost:8000";
const AGENT_TARGET = process.env.AGENT_TARGET ?? "http://localhost:8100";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: API_TARGET, rewrite: (path) => path.replace(/^\/api/, "") },
      "/agent": { target: AGENT_TARGET, rewrite: (path) => path.replace(/^\/agent/, "") },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
