import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// 本地 dev：/api 代理到本地后端，端口取自 BACKEND_PORT（与 .env 一致），缺省 8189
const backendPort = process.env.BACKEND_PORT || "8189";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: `http://localhost:${backendPort}`,
        changeOrigin: true,
      },
    },
  },
});
