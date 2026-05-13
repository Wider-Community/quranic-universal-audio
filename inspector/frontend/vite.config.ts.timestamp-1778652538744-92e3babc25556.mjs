// vite.config.ts
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { svelte } from "file:///mnt/c/Users/ahmed/Documents/Work/my-projects/quranic-universal-audio/inspector/frontend/node_modules/@sveltejs/vite-plugin-svelte/src/index.js";
import { defineConfig } from "file:///mnt/c/Users/ahmed/Documents/Work/my-projects/quranic-universal-audio/inspector/frontend/node_modules/vite/dist/node/index.js";
var __vite_injected_original_import_meta_url = "file:///mnt/c/Users/ahmed/Documents/Work/my-projects/quranic-universal-audio/inspector/frontend/vite.config.ts";
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
//# sourceMappingURL=data:application/json;base64,ewogICJ2ZXJzaW9uIjogMywKICAic291cmNlcyI6IFsidml0ZS5jb25maWcudHMiXSwKICAic291cmNlc0NvbnRlbnQiOiBbImNvbnN0IF9fdml0ZV9pbmplY3RlZF9vcmlnaW5hbF9kaXJuYW1lID0gXCIvbW50L2MvVXNlcnMvYWhtZWQvRG9jdW1lbnRzL1dvcmsvbXktcHJvamVjdHMvcXVyYW5pYy11bml2ZXJzYWwtYXVkaW8vaW5zcGVjdG9yL2Zyb250ZW5kXCI7Y29uc3QgX192aXRlX2luamVjdGVkX29yaWdpbmFsX2ZpbGVuYW1lID0gXCIvbW50L2MvVXNlcnMvYWhtZWQvRG9jdW1lbnRzL1dvcmsvbXktcHJvamVjdHMvcXVyYW5pYy11bml2ZXJzYWwtYXVkaW8vaW5zcGVjdG9yL2Zyb250ZW5kL3ZpdGUuY29uZmlnLnRzXCI7Y29uc3QgX192aXRlX2luamVjdGVkX29yaWdpbmFsX2ltcG9ydF9tZXRhX3VybCA9IFwiZmlsZTovLy9tbnQvYy9Vc2Vycy9haG1lZC9Eb2N1bWVudHMvV29yay9teS1wcm9qZWN0cy9xdXJhbmljLXVuaXZlcnNhbC1hdWRpby9pbnNwZWN0b3IvZnJvbnRlbmQvdml0ZS5jb25maWcudHNcIjtpbXBvcnQgeyByZXNvbHZlIH0gZnJvbSAnbm9kZTpwYXRoJztcclxuaW1wb3J0IHsgZmlsZVVSTFRvUGF0aCB9IGZyb20gJ25vZGU6dXJsJztcclxuXHJcbmltcG9ydCB7IHN2ZWx0ZSB9IGZyb20gJ0BzdmVsdGVqcy92aXRlLXBsdWdpbi1zdmVsdGUnO1xyXG5pbXBvcnQgeyBkZWZpbmVDb25maWcgfSBmcm9tICd2aXRlJztcclxuXHJcbmNvbnN0IGhlcmUgPSBmaWxlVVJMVG9QYXRoKG5ldyBVUkwoJy4nLCBpbXBvcnQubWV0YS51cmwpKTtcclxuXHJcbmV4cG9ydCBkZWZhdWx0IGRlZmluZUNvbmZpZygoeyBtb2RlIH0pID0+ICh7XHJcbiAgcm9vdDogaGVyZSxcclxuICBwdWJsaWNEaXI6ICdwdWJsaWMnLFxyXG4gIHBsdWdpbnM6IFtzdmVsdGUoKV0sXHJcbiAgYnVpbGQ6IHtcclxuICAgIG91dERpcjogJ2Rpc3QnLFxyXG4gICAgZW1wdHlPdXREaXI6IHRydWUsXHJcbiAgICBzb3VyY2VtYXA6IG1vZGUgPT09ICdkZXZlbG9wbWVudCcsXHJcbiAgICB0YXJnZXQ6ICdlczIwMjInLFxyXG4gICAgcm9sbHVwT3B0aW9uczoge1xyXG4gICAgICBpbnB1dDogcmVzb2x2ZShoZXJlLCAnaW5kZXguaHRtbCcpLFxyXG4gICAgICBvdXRwdXQ6IHtcclxuICAgICAgICBtYW51YWxDaHVua3MoaWQpIHtcclxuICAgICAgICAgIGlmIChpZC5pbmNsdWRlcygnY2hhcnQuanMnKSB8fCBpZC5pbmNsdWRlcygnY2hhcnRqcy1wbHVnaW4tYW5ub3RhdGlvbicpKSB7XHJcbiAgICAgICAgICAgIHJldHVybiAnY2hhcnRzJztcclxuICAgICAgICAgIH1cclxuICAgICAgICB9LFxyXG4gICAgICB9LFxyXG4gICAgfSxcclxuICB9LFxyXG4gIHNlcnZlcjoge1xyXG4gICAgcG9ydDogNTE3MyxcclxuICAgIHN0cmljdFBvcnQ6IHRydWUsXHJcbiAgICBwcm94eToge1xyXG4gICAgICAnL2FwaSc6IHsgdGFyZ2V0OiAnaHR0cDovLzEyNy4wLjAuMTo1MDAwJywgY2hhbmdlT3JpZ2luOiBmYWxzZSB9LFxyXG4gICAgICAnL2F1ZGlvJzogeyB0YXJnZXQ6ICdodHRwOi8vMTI3LjAuMC4xOjUwMDAnLCBjaGFuZ2VPcmlnaW46IGZhbHNlIH0sXHJcbiAgICB9LFxyXG4gIH0sXHJcbn0pKTtcclxuIl0sCiAgIm1hcHBpbmdzIjogIjtBQUEwYixTQUFTLGVBQWU7QUFDbGQsU0FBUyxxQkFBcUI7QUFFOUIsU0FBUyxjQUFjO0FBQ3ZCLFNBQVMsb0JBQW9CO0FBSjJQLElBQU0sMkNBQTJDO0FBTXpVLElBQU0sT0FBTyxjQUFjLElBQUksSUFBSSxLQUFLLHdDQUFlLENBQUM7QUFFeEQsSUFBTyxzQkFBUSxhQUFhLENBQUMsRUFBRSxLQUFLLE9BQU87QUFBQSxFQUN6QyxNQUFNO0FBQUEsRUFDTixXQUFXO0FBQUEsRUFDWCxTQUFTLENBQUMsT0FBTyxDQUFDO0FBQUEsRUFDbEIsT0FBTztBQUFBLElBQ0wsUUFBUTtBQUFBLElBQ1IsYUFBYTtBQUFBLElBQ2IsV0FBVyxTQUFTO0FBQUEsSUFDcEIsUUFBUTtBQUFBLElBQ1IsZUFBZTtBQUFBLE1BQ2IsT0FBTyxRQUFRLE1BQU0sWUFBWTtBQUFBLE1BQ2pDLFFBQVE7QUFBQSxRQUNOLGFBQWEsSUFBSTtBQUNmLGNBQUksR0FBRyxTQUFTLFVBQVUsS0FBSyxHQUFHLFNBQVMsMkJBQTJCLEdBQUc7QUFDdkUsbUJBQU87QUFBQSxVQUNUO0FBQUEsUUFDRjtBQUFBLE1BQ0Y7QUFBQSxJQUNGO0FBQUEsRUFDRjtBQUFBLEVBQ0EsUUFBUTtBQUFBLElBQ04sTUFBTTtBQUFBLElBQ04sWUFBWTtBQUFBLElBQ1osT0FBTztBQUFBLE1BQ0wsUUFBUSxFQUFFLFFBQVEseUJBQXlCLGNBQWMsTUFBTTtBQUFBLE1BQy9ELFVBQVUsRUFBRSxRQUFRLHlCQUF5QixjQUFjLE1BQU07QUFBQSxJQUNuRTtBQUFBLEVBQ0Y7QUFDRixFQUFFOyIsCiAgIm5hbWVzIjogW10KfQo=
