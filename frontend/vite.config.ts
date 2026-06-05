import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// 本地 dev：端口取自 .env（FRONTEND_PORT/BACKEND_PORT），缺省 5173 / 8189
const frontendPort = Number(process.env.FRONTEND_PORT) || 5173;
const backendPort = process.env.BACKEND_PORT || "8189";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: frontendPort,
    proxy: {
      "/api": {
        target: `http://localhost:${backendPort}`,
        changeOrigin: true,
      },
    },
  },
});
