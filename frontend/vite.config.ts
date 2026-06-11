import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import { fileURLToPath, URL } from "node:url";

export default defineConfig({
  base: "/app/",
  plugins: [vue()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  build: {
    outDir: "../static/app",
    emptyOutDir: true,
    sourcemap: false,
    chunkSizeWarningLimit: 600,
    rollupOptions: {
      output: {
        // Keep all non-echarts third-party code in a single chunk: Naive UI's
        // transitive deps (vooks / vueuc / @css-render) need Vue available at
        // module init time, and splitting them across chunks reorders eval
        // and breaks with "Cannot access X before initialization" TDZ errors.
        manualChunks(id) {
          if (
            id.includes("node_modules/echarts") ||
            id.includes("node_modules/vue-echarts") ||
            id.includes("node_modules/zrender")
          ) {
            return "vendor-echarts";
          }
          if (id.includes("node_modules/")) {
            return "vendor";
          }
        },
      },
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": "http://127.0.0.1:5050",
    },
  },
});
