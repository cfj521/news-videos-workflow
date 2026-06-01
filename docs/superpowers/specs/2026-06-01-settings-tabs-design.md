# 设置页改 Tab 分组 — 设计文档

## 背景与目标

Settings 页目前是一长列 section（顺序：文章摘要、文本模型、图片模型、文档解析模型、语音合成、流水线默认值、视频输出、存储目录、LTX-2.3 视频生成、提示词）。改为 **Tab 模式**分组，便于浏览；并为后续 ComfyUI 工作流配置预留一个 tab。

本次**只动前端**，不碰后端 / config.py。

## 范围与决策

- **D1 只前端**：仅改 `frontend/src/pages/Settings.tsx`。后端、`config.py`、`client.ts` 的 `ltx` 字段、`EMPTY_SETTINGS.ltx` 全部保留不动（Python 库版 LTX 路径 `video_route=="ltx"` 不受影响）。
- **D2 ComfyUI tab 空白**：本次「视频生成」tab 只做空白占位（"待后端接入完成后配置"），ComfyUI 各工作流的具体配置等后端集成完成后再填（届时单独走设计/实现）。
- **D3 移除 LTX section 的 UI**：删掉「LTX-2.3 视频生成」那段 `<Section>` 渲染；但 `settings.ltx` 仍随整体加载/保存（不丢数据、不破后端）。

## Tab 分组

| Tab | 包含 section（沿用现有 JSX） |
|---|---|
| **AI 服务** | 文本模型、图片模型、文档解析模型、文章摘要、语音合成 |
| **流水线** | 流水线默认值、视频输出、存储目录 |
| **提示词** | 提示词 |
| **视频生成** | 空白占位（ComfyUI；LTX-2.3 section 不再渲染） |

## 详细设计（`frontend/src/pages/Settings.tsx`）

- 新增 `const [activeTab, setActiveTab] = useState<TabKey>("ai")`，`TabKey = "ai" | "pipeline" | "prompts" | "video"`。
- 在标题行下方加一个 tab 栏（按钮组，激活态高亮，复用现有按钮样式 token）。
- 把现有各 section 的 JSX **原样**放进对应 tab 的条件渲染块（`{activeTab === "ai" && (<>...</>)}` 等），不改 section 内部任何字段/逻辑。
- 顶部「保存」按钮保持**全局**：`settings` 状态含全部分组，保存写全部，与当前激活 tab 无关；`dirty`、`handleSave`、`patch`、`useSWR` 全不变。
- 「视频生成」tab 面板内容：一段占位说明文案（如"ComfyUI 工作流配置将在后端接入完成后开放"），不含任何输入控件。
- 删除「LTX-2.3 视频生成」`<Section>...</Section>` 整段（约 460-510 行）。`patch("ltx", ...)` 调用一并随之移除。

## 边界

- `settings.ltx` 不在 UI 出现，但仍在 `settings` 状态里、保存时原样回写——后端 Python 库版 LTX 配置不变。
- 切换 tab 不重置 `dirty`、不丢未保存编辑（`settings` 状态是单一来源，跨 tab 共享）。
- 移动端/窄屏：tab 栏允许横向换行或滚动（用现有 flex-wrap 即可，不追求复杂响应式）。

## 测试/验收

- `pnpm build` 通过（无 TS 错误）。
- 人工验收（用户）：4 个 tab 可切换；各 tab 下原有配置项齐全可编辑；改任一 tab 的项后顶部「保存」可存且生效；「视频生成」tab 为占位空白；页面不再出现「LTX-2.3 视频生成」。

## 影响文件

- `frontend/src/pages/Settings.tsx`（tab 状态 + tab 栏 + 分装各 section + 删 LTX section + 视频生成占位）

不涉及后端、config、client.ts、测试新增（前端纯结构调整，靠 build + 人工验收）。
