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
4. 进入 **APIs & Services > Credentials**，点击 **Create Credentials > OAuth client ID**。Google 现在用一个 5 步向导引导你完成（如下）：
   1. **凭据类型** — 选择你要访问的数据类型（用户数据）
   2. **OAuth 权限请求页面** — 填应用名称、用户支持邮箱等基本信息
   3. **范围（可选）** — **直接点「保存并继续」跳过，无需添加任何范围**。系统会在首次运行授权时动态请求 YouTube 上传权限，不用在控制台预填
   4. **OAuth 客户端 ID** — Application type 选 **Web application（Web 应用）**；如要求填重定向 URI，先填 `http://localhost`
   5. **您的凭据** — 此步会显示 `Client ID` 和 `Client Secret`，**复制保存好**
5. 设置应用的「用户类型」和发布状态。入口：[Google Auth Platform > 目标对象 / Audience](https://console.cloud.google.com/auth/audience)（把 URL 里的 project 换成你的项目）：
   - **个人 Gmail 账号（绝大多数情况）→ 设为「外部（External）+ 正式版（In production）」**：在「目标对象」页把用户类型选 **外部**，再点 **「发布应用」** 把状态从 **测试（Testing）** 改为 **正式版 / 生产（In production）**。⚠️ 这步必做——否则拿到的 refresh_token 约 **7 天就失效**，需反复重授权。
   - **内部（Internal）** — 仅当你用 Google Workspace 组织账号、且 YouTube 频道也在同一组织下才可选：无需发布操作，token 长期有效。
6. 在 YouTube 上验证你的账号：打开 [youtube.com/verify](https://youtube.com/verify)，验证手机号（否则视频限 15 分钟）
7. **获取 Refresh Token**（关键，见下）

### 获取 Refresh Token

`Client ID` / `Client Secret` 只代表"应用身份"，并不代表"某个 YouTube 账号已授权"。真正能上传，必须先走一次 OAuth 授权拿到 **refresh_token**（长期有效，程序用它自动换取每小时过期的 access token）。本系统目前没有内置授权页，需手动获取一次：

**方法 A — Google OAuth Playground（推荐，无需写代码）**

1. 回 Google Cloud Console，给你的 OAuth 客户端的「已获授权的重定向 URI」**加上** `https://developers.google.com/oauthplayground` 并保存
2. 打开 [OAuth Playground](https://developers.google.com/oauthplayground)
3. 右上角齿轮 ⚙️ → 勾选 **Use your own OAuth credentials** → 填入你的 Client ID / Client Secret
4. 左侧「Input your own scopes」输入 `https://www.googleapis.com/auth/youtube.upload` → 点 **Authorize APIs**
5. 用目标 YouTube 账号登录并同意授权
   - 此时可能弹出 **「此应用未经 Google 验证」** 警告屏。这是正常的——未验证的应用申请敏感权限（youtube.upload）都会弹，**个人自用无需提交 Google 验证**。点「显示高级部分」→ 底部的 **「转至 {应用名}（不安全）」** 链接继续，再勾选同意 YouTube 上传权限即可。
6. 点 **Exchange authorization code for tokens**，右侧出现 **Refresh token**，复制
7. 填入下面的配置

> ⚠️ refresh_token 寿命取决于第 5 步设置的发布状态：**正式版（In production）→ 长期有效**；仍是**测试（Testing）→ 约 7 天失效**。务必确保应用已设为「外部 + 正式版」再获取，否则一周后要重来。

### 填入配置

在「发布管理」页 → YouTube 平台填写：
- **Client ID**: 第 4 步向导最后获取的 Client ID
- **Client Secret**: 第 4 步向导最后获取的 Client Secret
- **Refresh Token**: 上面「获取 Refresh Token」拿到的值（**必填**，否则无法上传）

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
3. 复制下列 Cookie 值（注意大小写，`SESSDATA`/`DedeUserID` 是大写）：

| Cookie | 发布时重要性 | 作用 |
|---|---|---|
| `SESSDATA` | 🔴 必填 | 登录态凭证 |
| `bili_jct` | 🔴 必填 | CSRF token，投稿所有 POST 接口都校验 |
| `DedeUserID` | 🟠 强烈建议 | 上传者 UID，风控会校验它与 SESSDATA 是否一致 |
| `buvid3` | 🟠 建议 | 设备指纹，过风控 |
| `buvid4` | 🟡 建议 | 新版设备指纹，配合 buvid3 更像真实浏览器 |
| `ac_time_value` | ⚪ 可选 | 登录态续期，长时间批量投稿减少掉登录 |

4. 打开「发布管理」页 → 「+ 添加平台」 → 选 Bilibili，填入上述 Cookie。最低要求 `SESSDATA` + `bili_jct`；为提高过审/过风控成功率，建议再带上 `DedeUserID` + `buvid3` + `buvid4`。

> 发布是写操作，与下载（读操作，看重画质鉴权）不同：`bili_jct` 是命脉（CSRF），`DedeUserID` 用于绑定上传者，因此比下载场景更重要。

### 填入配置

- **SESSDATA**: Cookie 值（必填）
- **bili_jct**: Cookie 值（必填）
- **DedeUserID**: 用户 UID（强烈建议）
- **buvid3** / **buvid4**: 设备指纹（建议）
- **ac_time_value**: 登录态续期（可选）

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
