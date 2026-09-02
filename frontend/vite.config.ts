import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The app always calls relative URLs (`/api/...`). In dev this proxy forwards
// them to the api container; in prod nginx does the same job. That keeps the
// browser on a single origin, so there is no CORS preflight and no
// VITE_API_URL to rebuild the bundle for when the host changes.
// GitHub Pages serves a project site from https://<user>.github.io/<repo>/,
// so every asset URL needs that prefix. BASE_PATH is set by the Pages workflow
// and defaults to "/" for local development, where the app is served at root.
const base = process.env.BASE_PATH ?? "/";

export default defineConfig({
  base,
  plugins: [react()],
  server: {
    host: "0.0.0.0", // bind all interfaces, or the port publish cannot reach it
    port: 5173,
    strictPort: true,
    // Vite 5.4+ rejects requests whose Host header it does not recognise (a
    // DNS-rebinding mitigation). Bare IPs are allowed automatically, but any
    // HOSTNAME returns 403 unless listed here -- which is what you hit when
    // reaching the dev server over a VPN by its FQDN rather than its IP.
    // A leading dot matches subdomains.
    allowedHosts: (process.env.VITE_ALLOWED_HOSTS ?? ".netbird.cloud,.ts.net,localhost")
      .split(",")
      .map((h) => h.trim())
      .filter(Boolean),
    watch: {
      // Bind mounts on some hosts (macOS/Windows, and virtiofs) do not deliver
      // inotify events into the container, so HMR silently stops working.
      // Polling costs a little CPU and always works.
      usePolling: process.env.VITE_USE_POLLING === "1",
      interval: 300,
    },
    proxy: {
      "/api": { target: process.env.VITE_PROXY_TARGET ?? "http://api:8000", changeOrigin: true },
      "/health": { target: process.env.VITE_PROXY_TARGET ?? "http://api:8000", changeOrigin: true },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
  },
});
