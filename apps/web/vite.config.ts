import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Backend for the dev proxy. Override when :8000 is taken, e.g. GRAPHATHON_API_URL=http://127.0.0.1:8001
const API_TARGET = process.env.GRAPHATHON_API_URL ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": { target: API_TARGET, changeOrigin: false },
      "/healthz": { target: API_TARGET, changeOrigin: false },
      "/readyz": { target: API_TARGET, changeOrigin: false },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    restoreMocks: true,
    css: false,
  },
});
