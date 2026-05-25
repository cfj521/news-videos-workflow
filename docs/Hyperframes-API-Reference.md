# Hyperframes 开发接口参考文档

> 基于 2026-05-26 调研整理，来源：官方 GitHub、Mintlify 文档、Claude Design 集成指南

---

## 1. 概览

Hyperframes 是 HeyGen 开源的 HTML 视频渲染框架。用 HTML/CSS/GSAP 定义场景和动画，渲染为 MP4。

| 项目 | 规格 |
|------|------|
| 许可证 | Apache 2.0 |
| 运行时 | Node.js >= 22 |
| 依赖 | FFmpeg、Chrome（自动下载） |
| GPU | 不需要（可选 `--gpu` 硬件编码加速） |
| 安装 | `npm install -g hyperframes` 或 `npx` 使用 |
| 默认输出 | 1920×1080, 30fps, MP4 |

---

## 2. CLI 命令参考

### 2.1 项目创建

```bash
# 初始化新项目
npx hyperframes init my-video --example blank --resolution portrait

# 可用模板: blank, warm-grain, play-mode, swiss-grid, vignelli
# 分辨率预设: landscape(1920x1080), portrait(1080x1920), 4k, square
# 可选: --tailwind --video input.mp4 --audio narration.mp3
```

### 2.2 开发预览

```bash
# 实时预览（热重载）
npx hyperframes preview --port 3002
```

### 2.3 渲染输出

```bash
# 基本渲染
npx hyperframes render

# 完整参数
npx hyperframes render \
  --output output.mp4 \
  --format mp4 \           # mp4 | webm | mov | png-sequence
  --fps 30 \               # 24 | 30 | 60
  --quality standard \     # draft | standard | high
  --resolution portrait \  # 或 landscape | 4k 等预设
  --crf 23 \               # 编码质量 0-51（越低越好）
  --video-bitrate 10M \    # 目标比特率
  --workers 4 \            # 并行 worker 数 1-8
  --gpu \                  # 启用硬件编码
  --docker \               # 容器内确定性渲染
  --variables '{"title":"标题"}' \  # 模板变量
  --quiet                  # 静默模式
```

### 2.4 质量检查

```bash
# 结构检查
npx hyperframes lint --json

# 布局检查（检测溢出等）
npx hyperframes inspect --json --samples 9

# 关键帧截图
npx hyperframes snapshot --frames 5
# 或指定时间点
npx hyperframes snapshot --at "0,2.5,5,7.5,10"
```

### 2.5 内置 TTS

```bash
# 内置语音合成（Kokoro-82M，本地运行）
npx hyperframes tts "这是一段旁白文本" --output narration.mp3 --voice af_heart --speed 1.0

# 列出可用音色
npx hyperframes tts --list
```

### 2.6 音频转写（字幕生成）

```bash
# 音频转写为带时间戳的字幕
npx hyperframes transcribe --model base --language zh

# 支持格式: whisper JSON, SRT, VTT
```

### 2.7 辅助工具

```bash
npx hyperframes doctor       # 检查环境依赖
npx hyperframes info --json  # 项目元信息（分辨率、时长、元素数）
npx hyperframes catalog      # 浏览可用的 blocks 和 components
```

### 2.8 Lambda 分布式渲染（可选）

```bash
npx hyperframes lambda deploy --region us-east-1
npx hyperframes lambda render ./project --width 1920 --height 1080 --fps 30 --wait
npx hyperframes lambda render-batch ./project --batch data.jsonl --max-concurrent 50
```

---

## 3. HTML 场景结构

### 3.1 基本结构

```html
<!DOCTYPE html>
<html>
<head>
  <script src="https://cdn.jsdelivr.net/npm/gsap@3/dist/gsap.min.js"></script>
</head>
<body>
  <!-- 根容器 -->
  <div id="main"
       data-composition-id="main"
       data-width="1080"
       data-height="1920"
       data-start="0"
       data-duration="30">

    <!-- 场景 1 -->
    <div class="scene clip" id="s1"
         data-start="0"
         data-duration="5"
         data-track-index="0">
      <div class="scene-content">
        <img src="assets/scene_01.png" style="width:100%;height:100%;object-fit:cover;">
        <div class="subtitle">今天我们来看一条重磅消息</div>
      </div>
    </div>

    <!-- 场景 2 -->
    <div class="scene clip" id="s2"
         data-start="5"
         data-duration="6"
         data-track-index="0"
         style="visibility:hidden;">
      <div class="scene-content">
        <img src="assets/scene_02.png" style="width:100%;height:100%;object-fit:cover;">
        <div class="subtitle">这项技术突破意味着...</div>
      </div>
    </div>

    <!-- 旁白音轨 -->
    <audio id="narration-1" data-start="0" data-duration="5"
           data-track-index="1" data-volume="1.0"
           src="assets/scene_01_audio.mp3"></audio>

    <audio id="narration-2" data-start="5" data-duration="6"
           data-track-index="1" data-volume="1.0"
           src="assets/scene_02_audio.mp3"></audio>

    <!-- 背景音乐（可选） -->
    <audio id="bgm" data-start="0" data-duration="30"
           data-track-index="2" data-volume="0.15"
           src="assets/bgm.mp3"></audio>
  </div>

  <script>
    const tl = gsap.timeline();

    // 场景 1: Ken Burns 效果
    tl.from("#s1 img", { scale: 1.1, duration: 5, ease: "sine.inOut" }, 0);
    tl.from("#s1 .subtitle", { y: 30, autoAlpha: 0, duration: 0.5, ease: "power3.out" }, 0.3);

    // 场景切换
    tl.set("#s2", { autoAlpha: 1 }, 5);
    tl.set("#s1", { autoAlpha: 0 }, 5);

    // 场景 2: 淡入 + 缩放
    tl.from("#s2 img", { scale: 1.05, duration: 6, ease: "sine.inOut" }, 5);
    tl.from("#s2 .subtitle", { y: 30, autoAlpha: 0, duration: 0.5, ease: "power3.out" }, 5.3);

    window.__timelines = { main: tl };
  </script>
</body>
</html>
```

### 3.2 关键 data 属性

| 属性 | 作用 | 值 |
|------|------|---|
| `data-composition-id` | 合成 ID，须与 `window.__timelines` 的 key 匹配 | 字符串 |
| `data-width` / `data-height` | 画布分辨率 | 整数（像素） |
| `data-start` | 元素起始时间（秒） | 浮点数 |
| `data-duration` | 元素持续时间（秒） | 浮点数 |
| `data-track-index` | 轨道索引（视频、音频分轨） | 整数 |
| `data-volume` | 音频音量 | 0.0 - 1.0 |

### 3.3 场景规则

- 每个场景必须有 `class="scene clip"` + 全部 data 属性
- 场景时间窗必须**首尾相连无间隙**（`data-start` 连续）
- 非首场景初始 `style="visibility:hidden;"`
- 场景切换用 `tl.set("#sN", { autoAlpha: 1/0 })`，**不要用** `visibility`
- `window.__timelines["main"] = tl` 必须匹配 `data-composition-id`

---

## 4. 动画模式参考

### 4.1 Ken Burns（图片平移缩放）

```javascript
// 缓慢推进
tl.from("#s1 img", { scale: 1.08, duration: 5, ease: "sine.inOut" }, 0);

// 缓慢后退
tl.to("#s1 img", { scale: 1.05, duration: 5, ease: "sine.inOut" }, 0);

// 平移
tl.from("#s1 img", { x: 30, duration: 5, ease: "sine.inOut" }, 0);
```

### 4.2 文字动画

```javascript
// 淡入上移
tl.from(".title", { y: 40, autoAlpha: 0, duration: 0.6, ease: "power3.out" }, 0.3);

// 逐字出现
tl.from(".char", { autoAlpha: 0, stagger: 0.05, duration: 0.3 }, 0.5);
```

### 4.3 转场效果

大部分使用硬切（~95%），关键时刻用 shader 转场：

```javascript
HyperShader.init({
  bgColor: "#000000",
  scenes: ["s3", "s4"],
  timeline: tl,
  transitions: [
    { time: 10.0, shader: "cross-warp-morph", duration: 0.5 }
  ]
});
```

可用 shader：`cross-warp-morph`、`cinematic-zoom`、`whip-pan`、`light-leak`、`glitch` 等

### 4.4 Ease 曲线

避免全部用 `power2.out`，混合使用：
- `sine.inOut` — 平滑（Ken Burns）
- `power3.out` — 入场
- `expo.out` — 强调
- `back.out(1.6)` — 弹性

---

## 5. 音频集成

```html
<!-- 旁白音轨（track 1） -->
<audio id="narration" data-start="0" data-duration="5"
       data-track-index="1" data-volume="1.0"
       src="narration.mp3"></audio>

<!-- 背景音乐（track 2，低音量） -->
<audio id="bgm" data-start="0" data-duration="30"
       data-track-index="2" data-volume="0.15"
       src="bgm.mp3"></audio>
```

- 多音轨通过不同 `data-track-index` 叠加
- 旁白通常 `data-volume="1.0"`，BGM `0.1-0.2`
- 音频文件支持 MP3、WAV、M4A

---

## 6. 字幕

通过 HTML 文字层实现，用 GSAP 控制显隐时间：

```html
<div class="subtitle" id="sub1" style="
  position: absolute; bottom: 80px; left: 50%;
  transform: translateX(-50%);
  font-size: 36px; color: white;
  text-shadow: 2px 2px 4px rgba(0,0,0,0.8);
  visibility: hidden;
">今天我们来看一条重磅消息</div>
```

```javascript
tl.set("#sub1", { autoAlpha: 1 }, 0.3);
tl.set("#sub1", { autoAlpha: 0 }, 4.8);
```

也可用内置 `transcribe` 命令从音频自动生成字幕时间码。

---

## 7. 确定性渲染规则

以下写法**禁止使用**（会导致每次渲染结果不同）：

| 禁止 | 替代方案 |
|------|---------|
| `Math.random()` | GSAP tween + seed |
| `Date.now()` / `performance.now()` | `tl.time()` |
| `setInterval` / `setTimeout` | GSAP timeline 时间控制 |
| `repeat: -1`（无限循环） | `repeat: Math.ceil(duration / cycle) - 1` |

---

## 8. 项目配置文件

### hyperframes.json

```json
{
  "registry": "https://raw.githubusercontent.com/heygen-com/hyperframes/main/registry",
  "paths": {
    "blocks": "compositions",
    "components": "compositions/components",
    "assets": "assets"
  }
}
```

---

## 9. 与我们项目的集成设计

### 9.1 ComposerProvider（Hyperframes 实现）的工作流

```
Timeline + ImageAsset[] + AudioAsset[]
    │
    ▼
生成 index.html（从 Timeline 构建场景 + GSAP 动画）
    │
    ▼
npx hyperframes lint --json（结构校验）
    │
    ▼
npx hyperframes render --output output.mp4 --fps 30 --quality standard
    │
    ▼
output.mp4 + thumbnail.jpg
```

### 9.2 HTML 生成策略

两种方案：

**方案 A：模板引擎（推荐 MVP）**
- 预定义 HTML 模板，用 Jinja2/Mustache 填充 Timeline 数据
- 模板包含固定的动画模式（Ken Burns、淡入等）
- 可控、快速、不依赖 AI 生成

**方案 B：AI 生成 HTML**
- 将 Timeline + 风格要求传给 TextProvider，让 AI 写 HTML/GSAP 代码
- 效果更丰富但结果不稳定，需要 lint 校验 + 可能多次重试
- 适合二期作为高级功能

### 9.3 关键参数映射

```python
# Timeline → Hyperframes HTML 的映射
scene_html = f'''
<div class="scene clip" id="s{scene.id}"
     data-start="{scene.start_time}"
     data-duration="{scene.duration}"
     data-track-index="0">
  <div class="scene-content">
    <img src="{scene.image_path}" ...>
    <div class="subtitle">{scene.subtitle_text}</div>
  </div>
</div>

<audio id="narration-{scene.id}"
       data-start="{scene.start_time}"
       data-duration="{scene.audio_duration}"
       data-track-index="1" data-volume="1.0"
       src="{scene.audio_path}"></audio>
'''
```

---

## 参考链接

- GitHub 仓库：https://github.com/heygen-com/hyperframes
- CLI 文档：https://hyperframes.mintlify.app/packages/cli
- Claude 集成指南：https://github.com/heygen-com/hyperframes/blob/main/docs/guides/claude-design-hyperframes.md
- npm 包：https://www.npmjs.com/package/hyperframes
- 官网：https://hyperframes.video/
