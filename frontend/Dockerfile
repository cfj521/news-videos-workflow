# 前端镜像：多阶段构建（Node 构建静态资源 → Nginx 提供 + 反代 /api）
FROM node:20-alpine AS build
WORKDIR /app

# 依赖层（用 package-lock.json，npm ci 可复现）
COPY package.json package-lock.json ./
RUN npm ci

# 构建（tsc -b && vite build）
COPY . .
RUN npm run build

# ---- 运行阶段：Nginx 静态托管 + /api 反向代理到后端 ----
FROM nginx:alpine
# 作为模板：nginx 官方 entrypoint 会用 envsubst 把 ${BACKEND_PORT} 替换后写入 conf.d
# （只替换环境中定义的变量，$host/$uri 等 nginx 变量不受影响）
COPY nginx.conf /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
# 实际监听端口由 ${FRONTEND_PORT} 经 envsubst 注入（见 compose environment）
EXPOSE 8190
