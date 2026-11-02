import { defineConfig } from "vite";
export default defineConfig({
  build: {
    rollupOptions: { output: { manualChunks: { plotly: ["plotly.js-cartesian-dist-min"] } } },
  },
  server: {
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8001",
        rewrite: (p) => p.replace(/^\/api/, ""),
      },
    },
  },
});
