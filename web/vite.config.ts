import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

/**
 * `base` is set at build time so the same bundle works from a domain root and
 * from a project subpath like /nullsignal/ on GitHub Pages.
 */
export default defineConfig({
  base: process.env.VITE_BASE ?? "/",
  plugins: [react()],
});
