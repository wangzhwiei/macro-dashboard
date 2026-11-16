import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

export default defineConfig({
  root: "static",
  base: "./",
  publicDir: "../public",
  plugins: [react()],
  build: {
    rollupOptions: { input: { main: fileURLToPath(new URL('./static/index.html', import.meta.url)), admin: fileURLToPath(new URL('./static/admin.html', import.meta.url)) } },
    outDir: "../docs",
    emptyOutDir: true,
  },
});
