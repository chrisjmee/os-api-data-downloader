import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// base "./" so the built site works from any folder: GitHub Pages, Live Server or a shared drive
export default defineConfig({
  plugins: [react()],
  base: "./",
  server: { open: true },
  build: { chunkSizeWarningLimit: 800 },
});
