// vite.config.ts
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { svelte } from "file:///C:/Users/Ahmed/Desktop/code/WIDER/quranic-universal-audio/inspector/frontend/node_modules/@sveltejs/vite-plugin-svelte/src/index.js";
import { defineConfig } from "file:///C:/Users/Ahmed/Desktop/code/WIDER/quranic-universal-audio/inspector/frontend/node_modules/vite/dist/node/index.js";
var __vite_injected_original_import_meta_url = "file:///C:/Users/Ahmed/Desktop/code/WIDER/quranic-universal-audio/inspector/frontend/vite.config.ts";
var here = fileURLToPath(new URL(".", __vite_injected_original_import_meta_url));
var vite_config_default = defineConfig(({ mode }) => ({
  root: here,
  publicDir: "public",
  plugins: [svelte()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: mode === "development",
    target: "es2022",
    rollupOptions: {
      input: resolve(here, "index.html"),
      output: {
        manualChunks(id) {
          if (id.includes("chart.js") || id.includes("chartjs-plugin-annotation")) {
            return "charts";
          }
        }
      }
    }
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": { target: "http://127.0.0.1:5000", changeOrigin: false },
      "/audio": { target: "http://127.0.0.1:5000", changeOrigin: false }
    }
  }
}));
export {
  vite_config_default as default
};
//# sourceMappingURL=data:application/json;base64,ewogICJ2ZXJzaW9uIjogMywKICAic291cmNlcyI6IFsidml0ZS5jb25maWcudHMiXSwKICAic291cmNlc0NvbnRlbnQiOiBbImNvbnN0IF9fdml0ZV9pbmplY3RlZF9vcmlnaW5hbF9kaXJuYW1lID0gXCJDOlxcXFxVc2Vyc1xcXFxBaG1lZFxcXFxEZXNrdG9wXFxcXGNvZGVcXFxcV0lERVJcXFxccXVyYW5pYy11bml2ZXJzYWwtYXVkaW9cXFxcaW5zcGVjdG9yXFxcXGZyb250ZW5kXCI7Y29uc3QgX192aXRlX2luamVjdGVkX29yaWdpbmFsX2ZpbGVuYW1lID0gXCJDOlxcXFxVc2Vyc1xcXFxBaG1lZFxcXFxEZXNrdG9wXFxcXGNvZGVcXFxcV0lERVJcXFxccXVyYW5pYy11bml2ZXJzYWwtYXVkaW9cXFxcaW5zcGVjdG9yXFxcXGZyb250ZW5kXFxcXHZpdGUuY29uZmlnLnRzXCI7Y29uc3QgX192aXRlX2luamVjdGVkX29yaWdpbmFsX2ltcG9ydF9tZXRhX3VybCA9IFwiZmlsZTovLy9DOi9Vc2Vycy9BaG1lZC9EZXNrdG9wL2NvZGUvV0lERVIvcXVyYW5pYy11bml2ZXJzYWwtYXVkaW8vaW5zcGVjdG9yL2Zyb250ZW5kL3ZpdGUuY29uZmlnLnRzXCI7aW1wb3J0IHsgcmVzb2x2ZSB9IGZyb20gJ25vZGU6cGF0aCc7XHJcbmltcG9ydCB7IGZpbGVVUkxUb1BhdGggfSBmcm9tICdub2RlOnVybCc7XHJcblxyXG5pbXBvcnQgeyBzdmVsdGUgfSBmcm9tICdAc3ZlbHRlanMvdml0ZS1wbHVnaW4tc3ZlbHRlJztcclxuaW1wb3J0IHsgZGVmaW5lQ29uZmlnIH0gZnJvbSAndml0ZSc7XHJcblxyXG5jb25zdCBoZXJlID0gZmlsZVVSTFRvUGF0aChuZXcgVVJMKCcuJywgaW1wb3J0Lm1ldGEudXJsKSk7XHJcblxyXG5leHBvcnQgZGVmYXVsdCBkZWZpbmVDb25maWcoKHsgbW9kZSB9KSA9PiAoe1xyXG4gIHJvb3Q6IGhlcmUsXHJcbiAgcHVibGljRGlyOiAncHVibGljJyxcclxuICBwbHVnaW5zOiBbc3ZlbHRlKCldLFxyXG4gIGJ1aWxkOiB7XHJcbiAgICBvdXREaXI6ICdkaXN0JyxcclxuICAgIGVtcHR5T3V0RGlyOiB0cnVlLFxyXG4gICAgc291cmNlbWFwOiBtb2RlID09PSAnZGV2ZWxvcG1lbnQnLFxyXG4gICAgdGFyZ2V0OiAnZXMyMDIyJyxcclxuICAgIHJvbGx1cE9wdGlvbnM6IHtcclxuICAgICAgaW5wdXQ6IHJlc29sdmUoaGVyZSwgJ2luZGV4Lmh0bWwnKSxcclxuICAgICAgb3V0cHV0OiB7XHJcbiAgICAgICAgbWFudWFsQ2h1bmtzKGlkKSB7XHJcbiAgICAgICAgICBpZiAoaWQuaW5jbHVkZXMoJ2NoYXJ0LmpzJykgfHwgaWQuaW5jbHVkZXMoJ2NoYXJ0anMtcGx1Z2luLWFubm90YXRpb24nKSkge1xyXG4gICAgICAgICAgICByZXR1cm4gJ2NoYXJ0cyc7XHJcbiAgICAgICAgICB9XHJcbiAgICAgICAgfSxcclxuICAgICAgfSxcclxuICAgIH0sXHJcbiAgfSxcclxuICBzZXJ2ZXI6IHtcclxuICAgIHBvcnQ6IDUxNzMsXHJcbiAgICBzdHJpY3RQb3J0OiB0cnVlLFxyXG4gICAgcHJveHk6IHtcclxuICAgICAgJy9hcGknOiB7IHRhcmdldDogJ2h0dHA6Ly8xMjcuMC4wLjE6NTAwMCcsIGNoYW5nZU9yaWdpbjogZmFsc2UgfSxcclxuICAgICAgJy9hdWRpbyc6IHsgdGFyZ2V0OiAnaHR0cDovLzEyNy4wLjAuMTo1MDAwJywgY2hhbmdlT3JpZ2luOiBmYWxzZSB9LFxyXG4gICAgfSxcclxuICB9LFxyXG59KSk7XHJcbiJdLAogICJtYXBwaW5ncyI6ICI7QUFBd2EsU0FBUyxlQUFlO0FBQ2hjLFNBQVMscUJBQXFCO0FBRTlCLFNBQVMsY0FBYztBQUN2QixTQUFTLG9CQUFvQjtBQUpvUCxJQUFNLDJDQUEyQztBQU1sVSxJQUFNLE9BQU8sY0FBYyxJQUFJLElBQUksS0FBSyx3Q0FBZSxDQUFDO0FBRXhELElBQU8sc0JBQVEsYUFBYSxDQUFDLEVBQUUsS0FBSyxPQUFPO0FBQUEsRUFDekMsTUFBTTtBQUFBLEVBQ04sV0FBVztBQUFBLEVBQ1gsU0FBUyxDQUFDLE9BQU8sQ0FBQztBQUFBLEVBQ2xCLE9BQU87QUFBQSxJQUNMLFFBQVE7QUFBQSxJQUNSLGFBQWE7QUFBQSxJQUNiLFdBQVcsU0FBUztBQUFBLElBQ3BCLFFBQVE7QUFBQSxJQUNSLGVBQWU7QUFBQSxNQUNiLE9BQU8sUUFBUSxNQUFNLFlBQVk7QUFBQSxNQUNqQyxRQUFRO0FBQUEsUUFDTixhQUFhLElBQUk7QUFDZixjQUFJLEdBQUcsU0FBUyxVQUFVLEtBQUssR0FBRyxTQUFTLDJCQUEyQixHQUFHO0FBQ3ZFLG1CQUFPO0FBQUEsVUFDVDtBQUFBLFFBQ0Y7QUFBQSxNQUNGO0FBQUEsSUFDRjtBQUFBLEVBQ0Y7QUFBQSxFQUNBLFFBQVE7QUFBQSxJQUNOLE1BQU07QUFBQSxJQUNOLFlBQVk7QUFBQSxJQUNaLE9BQU87QUFBQSxNQUNMLFFBQVEsRUFBRSxRQUFRLHlCQUF5QixjQUFjLE1BQU07QUFBQSxNQUMvRCxVQUFVLEVBQUUsUUFBUSx5QkFBeUIsY0FBYyxNQUFNO0FBQUEsSUFDbkU7QUFBQSxFQUNGO0FBQ0YsRUFBRTsiLAogICJuYW1lcyI6IFtdCn0K
