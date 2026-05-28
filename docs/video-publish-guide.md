# 视频自动发布 — 操作指南

> 你需要做什么：注册账号、申请权限、填写配置。开发实现由系统完成。

---

## 平台总览

| 平台 | 难度 | 你需要准备的 | 每日上限 | 预计开通时间 |
|------|------|-------------|---------|------------|
| YouTube | 简单 | Google 账号 + 手机验证 | 6 个视频 | 当天 |
| Instagram Reels | 中等 | Business 账号 + Facebook Page + Meta 审核 | 100 个视频 | 1-3 周 |
| Bilibili | 简单 | B站账号 + 浏览器 Cookie | 5-10 个视频 | 当天 |
| 抖音 | 较难 | 企业营业执照 + 开放平台审核 | 无明确限制 | 1-2 周 |
| 快手 | 较难 | 企业营业执照 + 开放平台审核 | 无明确限制 | 1-2 周 |

---

## 1. YouTube

### 步骤

1. 打开 [Google Cloud Console](https://console.cloud.google.com/)，用你的 Google 账号登录
2. 创建一个新项目（名字随意，比如 "NewsVid"）
3. 在左侧菜单找到 **APIs & Services > Library**，搜索 **YouTube Data API v3**，点击启用
4. 进入 **APIs & Services > Credentials**，点击 **Create Credentials > OAuth client ID**
   - Application type 选 **Web application**
   - 记下 `Client ID` 和 `Client Secret`
5. 进入 **OAuth consent screen**，将应用状态从 "Testing" 改为 **"In production"**（否则 token 7 天过期）
6. 在 YouTube 上验证你的账号：打开 [youtube.com/verify](https://youtube.com/verify)，验证手机号（否则视频限 15 分钟）
7. 首次运行时，系统会打开浏览器让你授权，之后自动续期

### 填入配置

在 Settings 页面的 YouTube 区域填写：
- **Client ID**: 第 4 步获取的 Client ID
- **Client Secret**: 第 4 步获取的 Client Secret

### 注意

- 默认每天最多上传 6 个视频（可申请提升配额）
- 新上传的视频会经过 YouTube 自动版权检测

---

## 2. Instagram Reels

### 前置条件

- 你的 Instagram 账号必须是 **Business 账号**（个人账号和 Creator 账号都不行）
- 必须关联一个 **Facebook Page**

### 步骤

1. 将 Instagram 账号转为 Business 账号：Instagram > 设置 > 账号 > 切换到专业账号 > 选择"商家"
2. 创建或关联 Facebook Page：在 Facebook 创建一个 Page，然后在 Instagram 设置中关联
3. 打开 [Meta Developer Portal](https://developers.facebook.com/)，创建一个新应用
4. 申请权限：`instagram_business_basic` + `instagram_business_content_publish`
5. 提交 **App Review**（Meta 人工审核，通常需要 1-3 周）
6. 审核通过后获取长期 Access Token

### 填入配置

- **User ID**: Instagram Business 账号 ID
- **Access Token**: Meta 长期访问令牌

### 特殊要求

- 视频必须通过**公开 URL** 上传（不能直接传文件）。系统会自动将视频临时托管到可访问地址。
- 视频时长必须在 **5-90 秒**之间

---

## 3. Bilibili

### 步骤

1. 用你的 B 站账号登录 [bilibili.com](https://www.bilibili.com)
2. 打开浏览器开发者工具（F12），切到 **Application > Cookies**
3. 找到并复制这三个 Cookie 值：
   - `SESSDATA`
   - `bili_jct`
   - `buvid3`
4. 在系统 Settings 中填入这三个值

### 填入配置

- **SESSDATA**: Cookie 值
- **bili_jct**: Cookie 值
- **buvid3**: Cookie 值

### 注意

- Cookie 约 **30 天过期**，过期后需要重新登录并更新
- 建议每天上传不超过 5-10 个视频，避免触发风控
- 没有官方 API，存在一定风险

---

## 4. 抖音

### 前置条件

- 需要**企业营业执照**（个人无法申请开发者）

### 步骤

1. 打开 [抖音开放平台](https://open.douyin.com)，注册开发者账号（需上传营业执照）
2. 创建应用，获取 `Client Key` 和 `Client Secret`
3. 申请 `video.create` 权限（需要单独审批）
4. 审核通过后，系统会引导用户授权

### 填入配置

- **Client Key**: 开放平台应用的 Client Key
- **Client Secret**: 开放平台应用的 Client Secret

### 无企业资质的替代方案

如果没有企业资质，系统支持通过浏览器自动化上传（基于 social-auto-upload）：
1. 在本机安装 Playwright：`pip install playwright && playwright install chromium`
2. 首次运行时扫码登录抖音网页版
3. 之后自动上传（速度较慢，每个视频约 1-2 分钟）

---

## 5. 快手

### 前置条件

- 需要**企业营业执照**

### 步骤

1. 打开 [快手开放平台](https://open.kuaishou.com)，注册应用
2. 获取 `App ID` 和 `App Secret`
3. 完成用户授权流程

### 填入配置

- **App ID**: 开放平台应用 ID
- **App Secret**: 开放平台应用密钥

### 无企业资质的替代方案

同抖音，支持 Playwright 浏览器自动化方案。

---

## 视频规格说明

系统输出的视频已自动适配全平台要求，你无需做额外处理：

| 参数 | 值 |
|------|------|
| 格式 | MP4 |
| 分辨率 | 1080x1920 竖屏 (可在 Settings 中修改) |
| 帧率 | 30fps |
| 文件大小 | 通常 50-200MB |

如果某个平台有特殊时长要求（如 Instagram Reels 最长 90 秒），系统会在发布前自动检查并提示。
