#!/usr/bin/env bash
# docker/setup.sh —— Docker 首启准备（在仓库根执行）
# 幂等：每个 YAML 目标文件不存在才从对应 .example 模板创建；已存在则跳过（带提示）。
# 用途：避开「bind mount 自动建空目录」陷阱——bind mount 的宿主路径不存在时，
#       Docker 会自动建一个空目录顶替文件，而 6 个 store 的 load_yaml 会 open(目录) 崩溃。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

create_if_missing() {
    local target="$1" template="$2"
    if [ -f "$target" ]; then
        echo "  ✓ $target 已存在，跳过"
    elif [ -f "$template" ]; then
        cp "$template" "$target"
        echo "  ✓ 已创建 $target（来源 $template）"
    else
        echo "  ✗ 未找到 $template，无法创建 $target" >&2
        exit 1
    fi
}

echo "创建配置 YAML（仅缺失的）…"
create_if_missing config.yaml            config.yaml.example
create_if_missing model_providers.yaml   model_providers.yaml.example
create_if_missing news_sources.yaml      news_sources.yaml.example
create_if_missing publish_targets.yaml   publish_targets.yaml.example
create_if_missing schedule.yaml          schedule.yaml.example
create_if_missing prompts.yaml           prompts.yaml.example
create_if_missing covers.yaml            covers.yaml.example

# 数据与登录态目录
mkdir -p data publish_cookies
echo "  ✓ data/ 与 publish_cookies/ 就绪"

echo
echo "准备完成。下一步："
echo "  1) cp .env.example .env   （按需改端口 / ComfyUI 地址 / 时区）"
echo "  2) docker compose up -d --build"
echo "  3) 浏览器打开 http://localhost:${APP_PORT:-8189}（默认登录 admin / admin）"
