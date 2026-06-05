import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// 本地 dev：端口取自 .env（FRONTEND_PORT/APP_PORT），缺省 5173 / 8000。
// 用 loadEnv 显式读取 .env（vite 不会自动把 .env 注入 process.env），
// 也兼容 shell 里已 export 的同名变量。
export default defineConfig(({ mode }) => {
  const env = { ...loadEnv(mode, process.cwd(), ""), ...process.env };
  const frontendPort = Number(env.FRONTEND_PORT) || 5173;
  const appPort = env.APP_PORT || "8000";
  return {
    plugins: [react(), tailwindcss()],
    server: {
      port: frontendPort,
      proxy: {
        "/api": {
          target: `http://localhost:${appPort}`,
          changeOrigin: true,
        },
      },
    },
  };
});
