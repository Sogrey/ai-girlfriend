# ai-girlfriend 项目结构分析报告（REA 逆向视角）

> **报告性质**：本报告由 REA（Reverse Engineer Anything，[morluto/rea](https://github.com/morluto/rea)）静态逆向分析生成，分析对象为本项目的 Electron 应用骨架（package.json + electron/ + renderer/，27 个文件）。
> **生成时间**：2026-10-17 · REA 版本 6.5.0 · 耗时 34.8s
> **分析口径**：纯静态 AST 分析（25,374 个 AST 节点、18.7 万字节文本、214 条 findings），不执行任何代码。所有结论均可回溯至 Evidence 原文（graph 218 节点 / 349 边；语义图 15,699 节点 / 12,446 关系）。

---

## 一、应用概览

| 指标 | 数值 | 说明 |
|---|---|---|
| 相关文件 | 26 个 | 不含 node_modules |
| 解析成功的 JS 文件 | 24 个 | 解析失败 0 个 |
| BrowserWindow 窗口 | **2 个** | main.js 中 `@144:15-166:4` 与 `@197:16-210:4` 两处构造 |
| preload 入口 | 2 处 | 主窗口与第二窗口各一 |
| contextBridge API | 1 组（命名 `desktop`） | 暴露 **18 个成员** |
| IPC 操作总数 | 36 个 | 字面通道 18 个，动态通道 0 个 |
| 通道配对率 | **100%** | renderer 发送 14 个全部与 main 侧配对，歧义 0、失配 0 |
| 原生插件 / UtilityProcess | 0 / 0 | 纯 JS 应用，无 native addon |

**架构特征**：典型三层 Electron 结构（main → preload → renderer），双窗口（主窗口 + 置顶桌面宠物窗口），进程间通信双轨制——Electron 原生 IPC（结构化请求/响应）+ 进程内事件总线 `bus`（广播式事件流）。

---

## 二、Electron 进程架构（Evidence 直接观察）

```text
┌─────────────────────────────────────────────────┐
│ electron/main.js  (electron-main)               │
│  ├─ BrowserWindow @144  主窗口(mainWindow)       │
│  ├─ BrowserWindow @197  第二窗口(heartWindow)    │
│  ├─ ipcMain.on × 8   事件类通道                  │
│  ├─ ipcMain.handle × 6  请求-响应类通道          │
│  └─ bus(EventEmitter) 进程内事件总线 × 28 事件   │
├─────────────────────────────────────────────────┤
│ electron/preload.js  (electron-preload)          │
│  └─ contextBridge.exposeInMainWorld('desktop',   │
│       { …18 个成员 })                            │
├─────────────────────────────────────────────────┤
│ renderer/  (electron-renderer × 3 入口)          │
│  ├─ 交互层: VoiceController / MouseInteraction…  │
│  ├─ UI 层:   ChatPanel / ReminderPanel / Toolbar │
│  └─ 角色层:  CostumeManager 等                   │
│  外部依赖: three (Three.js, external:three)      │
└─────────────────────────────────────────────────┘
```

- **双 preload**：`preload_entrypoints=2`，两窗口各自挂载 preload 脚本。
- **显式 webPreferences 配置 8 项**：窗口构造中包含 8 处显式的 webPreferences 设置（含 preload 路径指定）；renderer 侧使用 `contextBridge` 且存在 `electron-renderer` 角色节点，符合 contextIsolation 隔离模式的特征。
- **sender 校验观察 = 0**：全部 18 个 IPC 通道中**未观察到**对 `event.senderFrame` / `event.sender` 的验证（`sender_validation_observations: 0`）。静态口径下这意味着 main 进程 handler 不区分调用来源——详见 §五 安全观察。

---

## 三、IPC 通道全景（22 个通道节点 / 18 个 handler）

### 3.1 主进程 ipcMain 侧注册（handle 请求-响应 + on 事件）

| 通道 | 注册方式 | 行号(Evidence) | 推断用途 |
|---|---|---|---|
| `config:get` | ipcMain.handle | main.js | 读取应用配置 |
| `config:update` | ipcMain.handle | main.js | 更新应用配置 |
| `window:info` | ipcMain.handle | main.js | 获取窗口位置/尺寸信息 |
| `screen:capture` | ipcMain.handle | main.js | **截屏捕获**（主进程 desktopCapturer 权限侧） |
| `app:setHeartMode` | ipcMain.handle | main.js | 设置宠物形态模式 |
| `app:setLaunchAtStartup` | ipcMain.handle | main.js | 开机自启开关 |
| `app:quit` | ipcMain.on | main.js | 退出应用 |
| `dev:openDevTools` | ipcMain.on | main.js | 打开开发者工具 |
| `window:show` | ipcMain.on | main.js | 显示主窗口 |
| `window:applyPos` | ipcMain.on | main.js | 宠物窗口应用位置 |
| `window:moveBy` | ipcMain.on | main.js | 宠物窗口增量位移（拖拽跟随） |
| `window:setIgnoreMouse` | ipcMain.on | main.js | 鼠标穿透开关 |
| `heart:clicked` | ipcMain.on | main.js | 宠物点击交互 |
| `heart:hover` | ipcMain.on | main.js | 宠物悬停交互 |

### 3.2 渲染进程 ipcRenderer 侧（on 监听 + 发送调用）

| 通道 | 方向 | 推断用途 |
|---|---|---|
| `app:awaken` | main → renderer | 唤醒/激活通知（如托盘或第二实例唤起） |
| `tray:action` | main → renderer | 托盘菜单动作分发 |
| `global-mouse` | main → renderer | 全局鼠标事件透传（窗口外交互感知） |
| `shortcut-toggle` | main → renderer | 全局快捷键切换通知 |

render 侧调用点观察：`electron.ipcRenderer.send × 8`、`electron.ipcRenderer.invoke × 6`，与上表 14 个通道一一对应（**paired_renderer_transmissions = 14/14**）。通道全部为字面量（`dynamic_channel_operations = 0`），无动态拼接通道——静态可追全量。

> 用途列为基于通道命名的推断（Observation 的 label 为 Evidence 直接事实，中文说明为解读）；行号锚点如 `@144`、`26:35` 均来自 Evidence 的 identity key。

### 3.3 preload 桥接层（contextBridge）

`electron/preload.js` 中 `contextBridge.exposeInMainWorld('desktop', {...})` 暴露 **18 个 API 成员**（Evidence: `context-bridge-api` 节点，key `main:desktop:7:0-40:2`）。renderer 侧统一经 `window.desktop.*` 访问主进程能力，与 §3.1/§3.2 的 18 个字面通道构成封闭的桥接面。

---

## 四、bus 事件总线（28 个事件，Evidence 直接观察）

主进程内共享的 `bus`（EventEmitter）承担"广播式"事件分发，观察到的注册表如下：

| 事件 | 分组 |
|---|---|
| `backend:connected` / `backend:status` / `backend:error` | 后端连接与状态 |
| `backend:ai_response` / `backend:llm_partial` | LLM 应答（含流式分片） |
| `backend:stt_result` / `backend:stt_partial` | 语音识别（含流式分片） |
| `backend:tts_audio` | TTS 音频帧 |
| `backend:reminder_added` / `backend:reminder_due` / `backend:reminder_removed` | 提醒生命周期 |
| `backend:send` / `backend:send_user` / `backend:message` | 消息发送 |
| `backend:request_screenshot` / `backend:screen_looking` | 屏幕感知链路 |
| `backend:character_switched` | 角色切换 |
| `character:select` / `character:menu_open` / `characters:manage` / `characters:updated` | 角色管理与 UI |
| `toast:show` / `panel:open` / `panel:close` | UI 反馈 |
| `settings:saved` | 配置落盘 |
| `action:request` / `avatar:proximity` / `chat:sys` / `screen:request` | 交互与画面请求 |

**通信骨架解读**：`backend:*` 系列完整覆盖 AI 服务的连接状态 → 对话（LLM 流式）→ 语音出（TTS）→ 语音入（STT）→ 提醒 → 屏幕感知全链路，与功能域划分高度一致；`panel:*`/`toast:*`/`character:*` 是 UI 面向的广播事件，典型的"主进程为枢纽、renderer 订阅消费"的扇出结构。

---

## 五、安全观察

1. **IPC 无来源校验**：`sender_validation_observations = 0` —— 静态观察范围内，主进程 handler 未验证调用方来源。当前双窗口均加载本地页面，风险有限；若未来任一窗口加载远程内容，建议在 `ipcMain.handle` 中校验 `event.senderFrame`。
2. **通道命名空间清晰**：`app:` / `window:` / `config:` / `heart:` / `screen:` / `backend:` 前缀分明，字面量通道全配对，可维护性好。
3. **无动态通道、无 native addon、无 UtilityProcess**：攻击面集中且静态可枚举。
4. **contextIsolation 特征存在**：renderer 走 contextBridge 而非直用 Node API，隔离模式符合 Electron 安全基线。

---

## 六、Evidence 局限性（REA 官方口径摘录）

- CommonJS/ESM 绑定关系从**静态语法**恢复，仅在已盘点工件内解析；
- Electron 关系派生自静态语法，**运行时注册、可达性、默认值与强制手段不在覆盖范围**；
- 图覆盖不完整，未获取的事实**显式保留为未知**（语义图未知项 5,293 个），不可解读为"不存在"；
- JS/HTML 按惰性文本解析，**bundle 引导代码从未执行**；
- 本分析排除 node_modules 与 backend（Python）目录，后端通信协议仅能从 bus 事件名侧写。

---

## 附：分析环境与复现命令

```bash
# 环境版本
rea --version        # 6.5.0

# 复现（排除 node_modules 的干净目录副本，27 文件）
rea analyze-javascript-application <应用目录绝对路径> --json
# 输出 26 MB Evidence JSON，本报告图表与统计全部出自该 Evidence
```

> 分析执行于本机（Windows 11 专业版），全程本地运行，无任何数据上传。

> AI生成
