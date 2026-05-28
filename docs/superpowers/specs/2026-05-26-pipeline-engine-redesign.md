# Pipeline Engine Redesign — API 驱动的异步可选流程

## Stages

| # | Name | Description | Depends |
|---|------|-------------|---------|
| 1 | 搜索整理 | 采集→去重→合规→评分→选 top N | — |
| 2 | 脚本生成 | AI 分镜脚本 | 1 |
| 3 | 素材生成 | AI 图片 + TTS 音频 | 2 |
| 4 | 预览 | 时间轴 + 静态分镜审核页 + Hyperframes HTML | 3 |
| 5 | 成片渲染 | Hyperframes→MP4 | 4 |
| 6 | 发布 | 推送到选中平台 | 5 |

创建 Run 时 checkbox 勾选 stages，有依赖的自动关联。

## Execution

- FastAPI BackgroundTasks 异步执行，DB 记录状态
- `app/pipeline/runner.py` — 核心执行函数，遍历 selected_stages 依次执行
- manual 模式每个 stage 完成后暂停等 resume
- `progress_detail` 字段实时更新子进度 (如 "生成图片 3/7")

## DB: PipelineRun 新增字段

- `selected_stages: str` — `[1,2,3,4]`
- `progress_detail: str` — 当前进度
- `publish_platforms: str` — `["youtube"]`
- `preview_path: str | null`

## API

- `POST /api/pipeline/runs` — 新增 selected_stages, publish_platforms, 触发后台执行
- `GET /api/pipeline/runs/:id` — 含 progress_detail, preview_path
- `GET /api/pipeline/runs/:id/preview` — 静态分镜审核页
- `GET /api/pipeline/runs/:id/hyperframes` — Hyperframes HTML
- `POST /api/pipeline/runs/:id/resume` — 继续

## Frontend

- CreateRunDialog: stage checkbox + 发布平台多选
- RunDetail: 实时 progress_detail，stage 4 后显示预览按钮
- 删除 run_pipeline.py
