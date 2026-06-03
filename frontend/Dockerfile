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
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
