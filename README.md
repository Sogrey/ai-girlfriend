# 3D 桌面 AI 女友

一个长期驻留在 Windows 桌面上的实时 3D AI 虚拟伴侣。

透明无边框窗口中的 VRM 角色，能看着你的鼠标、听你说话、开口回应并同步口型、做动作、表达情绪、换装、离开休息与召回——像一个真正"住"在电脑里的人。

---

## 技术栈

| 层 | 技术 |
|---|---|
| 桌面端 | Electron 34 + Three.js r174 + @pixiv/three-vrm 3.5 |
| AI 大模型 | DeepSeek 在线 API（默认）/ Ollama 本地（可切换） |
| 语音识别 | Faster-Whisper CUDA float16（本地 GPU 加速；显存/内存不足时自动四级降级保可用） |
| 语音合成 | 五家可切：Edge-TTS（免费）/ Azure / OpenAI / ElevenLabs（在线）/ **GPT-SoVITS（本地免 Key 离线，流式出声）** |
| 视觉（屏幕感知） | GLM-4V-Flash（智谱·免费）/ 任意 OpenAI 兼容视觉端点 |
| 口型同步 | Web Audio API 实时 FFT → VRM BlendShape |
| 后端 | Python 3.12 + WebSocket 8765 |
| 渲染 | 程序化骨骼动画（无动捕文件，纯数学驱动） |

---

## 快速启动（一键脚本）

### 前提条件

| 依赖 | 版本要求 | 检查命令 |
|---|---|---|
| Rust 工具链 | ≥ 1.80（stable） | `cargo --version` |
| Python | ≥ 3.10 | `python --version` |
| Node.js | ≥ 18（仅 three.js 等 npm 依赖） | `node --version` |
| NVIDIA GPU | CUDA 兼容（推荐 RTX 3060+） | `nvidia-smi` |

> **没有 GPU 也能跑**——Whisper 会自动回退到 CPU int8 模式，只是识别速度慢一些。

> **壳层说明（v2.0）**：自 Phase 46（2026-10-17）起 main 分支使用 **Tauri 2** 壳（src-tauri/，内存/体积更轻）；原 Electron 壳完整封存在 `electron` 分支，可随时切回。

### 首次安装（只需做一次）

```powershell
cd ai-girlfriend

# 1. 安装 Node 依赖（three.js 运行时资源）
npm install

# 2. 创建 Python 虚拟环境并安装后端依赖
python -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple
.venv\Scripts\python.exe -m pip install -r backend\requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 3. 安装 Rust 工具链（尚未安装时）
#    https://rustup.rs （首次编译 Tauri 壳约 5 分钟）
```

国内网络已配好镜像（pip → 清华源，Whisper 模型 → hf-mirror.com），正常网络环境下全程自动完成。

### 日常启动

**双击 `scripts\启动AI女友.bat` 即可。**

BAT 会检查 `.venv` 与 Rust 工具链后运行 Tauri 壳；Tauri 壳启动时自动接管 Python 后端：8765 端口已有监听则直接复用（可与其也实例并存），否则自动拉起 `backend\main.py`（日志在 `.temp\tauri-backend.log`），退出时自动树杀自己拉起的后端。

**手动分步启动**（调试用）：

```powershell
cd ai-girlfriend

# 方式一：一键（cargo run = Tauri 壳 + 自动后端）
cargo run --manifest-path src-tauri/Cargo.toml

# 方式二：分步（后端单独窗口看日志）
.venv\Scripts\python.exe backend\main.py    # 终端 1
cargo run --manifest-path src-tauri/Cargo.toml   # 终端 2（会复用 8765）
```

**调试技巧**：WebView2 开 CDP 口——设置环境变量 `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=9223` 后再启动，即可用 Chrome DevTools / node WS 探针连接 9223；壳自身日志直接打印在终端（含后端转发日志）。

---

## 唯一必做配置：填写 DeepSeek API Key

启动后角色会出现在桌面上，但 AI 对话需要填一个 API Key：

1. 鼠标移近角色 → 底部工具栏淡入
2. 点击 ⚙️ 设置
3. **AI 大模型** → 填写 DeepSeek API Key
4. 保存

API Key 在 [platform.deepseek.com](https://platform.deepseek.com) 免费注册获取。填完后语音对话、文字聊天、意图动作全部立即可用。

> 未填 Key 时其余功能（3D 渲染、眼神追踪、换装、离开/返回、托盘快捷键）全部正常，只有 AI 对话会返回"请填写 API Key"的提示。

---

## 可选配置

### 换装模型

当前使用 three-vrm 官方示例模型（`assets/models/default.vrm`）。如需换成自己喜欢的角色：

1. 从 [VRoid Hub](https://hub.vroid.com) 下载 VRM 文件
2. 放入 `assets/costumes/`，按以下命名：

| 文件名 | 对应语音指令 |
|---|---|
| `costume_casual.vrm` | "换成日常装" |
| `costume_school.vrm` | "换成水手服" / "穿学生装" |
| `costume_stylish.vrm` | "换成时尚一点的" |
| `costume_gothic.vrm` | "穿洋装" |
| `costume_seed.vrm` | "换未来科技装" |

未放置文件的槽位会自动使用材质配色变体（功能完整，视觉为配色切换）。

### 切换到 Ollama 本地模型

设置面板 → AI 大模型 → Provider 改为 `Ollama`，填写 Ollama 地址和模型名。

需先安装并启动 [Ollama](https://ollama.com)：
```bash
ollama pull qwen3:4b
ollama serve
```

### 本地语音（GPT-SoVITS，免 Key 全离线）

Edge 在线语音被微软拦截、又不想填任何 Key 时的本地保底路线，用参考音频零样本克隆出她的嗓音：

1. 设置面板 → 语音合成 → 服务选 **GPT-SoVITS 本地** → 保存
2. 对话即用本地嗓音出声，全程不联网、零 Key（服务会**自动拉起**，详见下方）

- **自动恢复**：重开机/服务意外挂掉后，第一次对话会自动拉起本地语音服务（约 1~1.5 分钟，含冷启动 ~65s + 首句热身 ~30s），期间文字对话不受影响，第二次起明显变快
- **速度（流式）**：合成边生成边播，开口约 2~5 秒（不再整段等 ~15 秒）、句间衔接顺畅（偶有 1~2 秒小停顿）；冷启动首句仍需热身 ~30 秒；想更快填任一在线 Key 即可切回
- **换音色**：录一段 5~10 秒中文女声 wav → 设置面板填入"参考音频"路径与"参考音频对应文字"（逐字一致）→ 保存，立即换嗓；默认音色在 `assets/voices/ref_default.wav`
- **手动控制**（可选）：`scripts\启动GPT-SoVITS.bat` 用来实时看服务日志或手动重启服务；平时无需理会
- 本地环境已部署在 `D:\AI\GPT-SoVITS`（独立 venv + 预训练模型，不影响本项目环境）

### 修改角色人格

- **角色名 / 你的称呼**：设置面板 → 女友
- **性格 Prompt**：编辑 `prompts/system_prompt.txt`

### 屏幕感知（她想看看你的屏幕）

让她能看懂你的屏幕：报错弹窗、看写到一半的文档、看看你在看什么。推荐智谱免费视觉模型，注册即用不花钱：

1. 设置 → 视觉模型（屏幕感知）→ 填 API Key（[open.bigmodel.cn](https://open.bigmodel.cn) 注册 → GLM-4V-Flash 完全免费）；接口地址/模型保持默认
2. 两种用法：**点工具栏 👁** 立即截屏（输入框上方出现“已截图”提示，发送后她结合画面回答）；或者直接说“**你看一下我桌面这个报错 / 看看我现在屏幕上是什么**”，她会自动截屏看一眼再回答（语音说也行）

- **没配 Key 时**：会提示去设置里填 Key，不截屏；普通聊天完全不受影响（零探测零延迟）
- **隐私**：截图只发给你填的视觉模型接口，不落盘存储；聊天记录里只有你打的字（描述文本仅用于当轮回答）
- **自定义**：接口地址/模型可选填任何 OpenAI 兼容视觉端点（中转/通义/硅基流动等）；想追问细节在 👁 截图后把问题写在消息里即可

### 多角色（多个她，各有记忆）

在 `config/characters/` 下放一份 JSON 档案即多一个角色，每个角色有**独立的聊天历史、长期记忆与提醒清单**，互不干扰：

```json
// config/characters/xiaoxue.json
{
  "name": "小雪",
  "desc": "高冷学霸",
  "system_prompt": "你是小雪，说话简洁、偶尔毒舌但很可靠的学霸学姐。……（人设与输出 JSON 格式约束，可参考 prompts/system_prompt.txt 裁剪）",
  "model": "assets/characters/xiaoxue.vrm",
  "voice": { "gptsovits": { "ref_audio": "assets/voices/xue.wav", "ref_text": "（参考音频逐字文案）" } }
}
```

- **必填**：`name`；`system_prompt` 不填则沿用全局人设；`model`（专属 VRM 外观）与 `voice`（专属音色）按需选填
- **切换**：点工具栏 👥 选角色；或直接说"**叫小雪来**"（她也会按人设回应后切换）；选择会记住，重启后回到上次的她
- **默认角色**：小满不用配置（全局设置就是她的档案），现有聊天/记忆/提醒全部保留；`config/history-<id>.jsonl` 等是各角色的独立存储
- **共享**：所有角色共用同一个 LLM/Key 与视觉配置，只换人设、记忆与外观音色
- **不想手写 JSON？** 点 👥 后按「管理」（或设置 → 多角色管理…）：表单里新建/编辑/删除角色，人设可以"载入默认改造"，改完即存即生效（编辑当前角色的人设立即热更新，聊天不断流；删掉正在使用的角色会自动切回小满）
- **看她记住了什么**：管理面板每行有 🧠 计数，点开可查看该角色记住的关于你的事实，也能单独清除（只影响她，不影响别的角色与聊天记录）

---

## 操作指南

| 操作 | 效果 |
|---|---|
| 移动鼠标 | 角色看向鼠标（头部 + 颈部 + 眼球平滑跟随） |
| 鼠标靠近角色身体（全身范围） | 纵向功能栏淡入（角色右下角贴身竖排） |
| 点击角色头部 | 摸头 → 害羞 + 爱心粒子 + 随机语音 |
| 长按头部 | 同上（与拖拽互斥） |
| 按住角色拖动 | 移动窗口位置（重启后记住位置） |
| 🎤 按钮 | 开始/停止语音对话（VAD 自动断句） |
| 💬 按钮 | 文字聊天（她的回复支持 **加粗**、`代码` 与可点击链接，链接在系统默认浏览器打开） |
| 👁 按钮 | 截屏发问（屏幕感知，需在设置里填视觉 Key） |
| 👗 按钮 | 手动换装（5 套） |
| 👥 按钮 | 切换角色（多档案） |
| 👋 按钮 | 让她去休息 |
| ⚙️ 按钮 | 设置面板 |
| **Ctrl+Alt+G** | 召唤 / 隐藏（全局快捷键） |
| 点粉色爱心 | 召回休息中的角色 |
| 语音"回来" | 同上 |
| 托盘右键 | 唤醒/隐藏/换装/休息/设置/退出 |
| Ctrl+Shift+I | 开发者工具（调试） |

---

## 项目结构

```
ai-girlfriend/
├─ scripts/
│  └─ 启动AI女友.bat          ← 一键启动脚本
├─ electron/
│  ├─ main.js                 ← 主进程（窗口/托盘/快捷键/协议）
│  └─ preload.js              ← 安全 API 桥
├─ renderer/
│  ├─ app.js                  ← 装配入口
│  ├─ index.html              ← 页面
│  ├─ scene/                  ← Three.js 场景管理
│  ├─ avatar/                 ← VRM 角色 / 换装 / 粒子
│  ├─ animation/              ← 程序化动画状态机
│  ├─ emotion/                ← 表情 + 眨眼
│  ├─ lipsync/                ← Web Audio FFT 口型同步
│  ├─ interaction/            ← 眼神追踪 / 拖拽 / 语音 VAD
│  ├─ actions/                ← 动作分发器
│  ├─ ui/                     ← 工具栏 / 聊天 / 设置 / Toast
│  └─ styles/                 ← 样式
├─ backend/
│  ├─ main.py                 ← 后端入口
│  ├─ core/                   ← WebSocket 服务 / 配置 / 日程提醒引擎
│  ├─ llm/                    ← DeepSeek + Ollama 双 Provider
│  ├─ stt/                    ← Faster-Whisper CUDA 引擎
│  ├─ tts/                    ← 五家 Provider（Edge/Azure/OpenAI/ElevenLabs/GPT-SoVITS 本地）
│  ├─ conversation/           ← 统一对话管道
│  └─ actions/                 ← 意图校验 + 动作定义
├─ heart/
│  └─ heart.html              ← 爱心挂件窗口
├─ assets/
│  ├─ models/                 ← 默认 VRM 模型
│  ├─ costumes/               ← 5 套服装 VRM（按需放入）
│  └─ icons/                  ← 托盘图标
├─ config/
│  ├─ config.json             ← 默认配置（版本管理）
│  └─ user.json               ← 用户覆盖（设置面板写入，git 忽略）
├─ prompts/
│  └─ system_prompt.txt       ← 人格 System Prompt
├─ docs/
│  ├─ PRD.md                  ← 产品需求文档
│  ├─ 开发计划.md              ← 开发计划（已开发/待开发勾选）
│  ├─ 产品需求文档.html        ← PRD 浏览器版
│  └─ 开发计划.html            ← 进度看板浏览器版
└─ package.json
```

---

## 配置说明

所有配置集中在 `config/config.json`（默认值）+ `config/user.json`（用户覆盖，设置面板自动写入）。

关键配置项：

```json
{
  "llm": {
    "provider": "deepseek",          // 或 "ollama"
    "deepseek": { "api_key": "", "model": "deepseek-chat" },
    "ollama": { "base_url": "http://127.0.0.1:11434", "model": "qwen3:4b" }
  },
  "stt": {
    "model": "small",                // tiny/base/small/medium/large-v3
    "language": "zh",
    "vad_enabled": true
  },
  "tts": {
    "provider": "edge",                  // edge / azure / openai / elevenlabs / gptsovits（本地）
    "edge": { "voice": "zh-CN-XiaoxiaoNeural" },  // 晓晓/晓伊/云健/晓涵/晓梦
    "gptsovits": { "ref_audio": "assets/voices/ref_default.wav", "ref_text": "参考音频里说的话" }
  },
  "hotkey": "Control+Alt+G"
}
```

---

## 架构概览

```
┌─ Electron 主进程 ────────────┐     ┌─ Python Backend ─────────┐
│  窗口/托盘/快捷键/鼠标轮询     │     │  WebSocket :8765         │
│  app:// 协议服务本地资源       │◄───►│  ├─ DeepSeek / Ollama    │
└──────────┬───────────────────┘  WS │  ├─ Faster-Whisper CUDA  │
           │ IPC                     │  └─ Edge-TTS             │
┌──────────▼───────────────────┐  JSON└──────────────────────────┘
│  Renderer (Chromium)          │◄──────► HTTPS
│  Three.js + VRM 渲染           │       api.deepseek.com
│  程序化动画 / 表情 / 口型同步   │       hf-mirror.com (Whisper 模型)
│  眼神追踪 / 拖拽 / 语音 VAD     │       Edge-TTS 微软语音服务（可选）
│  工具栏 / 聊天 / 设置 / 提醒    │       本地 9880 GPT-SoVITS（可选）
└───────────────────────────────┘
```

---

## 常见问题

<details>
<summary><b>启动后角色没出现</b></summary>

角色会在**模型与纹理全部加载完成后才显示**（首次启动约 3–5 秒），这是有意设计——避免加载中的半成品画面闪现。如果超过 15 秒还没出现：
- 按 Ctrl+Alt+G 尝试唤醒
- 检查后端是否启动成功：BAT 窗口是否显示“后端已就绪”
- 按 Ctrl+Shift+I 打开开发者工具查看 console 报错
</details>

<details>
<summary><b>AI 对话报"API Key 未设置"</b></summary>

这是唯一的必做配置。提问后此提示会以她的红色气泡显示在聊天面板中，**气泡里的链接可直接点击**跳转浏览器。设置面板 → AI 大模型 → 填写 DeepSeek API Key → 保存。在 [platform.deepseek.com](https://platform.deepseek.com) 免费注册获取。
</details>

<details>
<summary><b>语音识别没反应</b></summary>

- 首次启动需要下载 Whisper 模型（small 约 460MB，经 hf-mirror 约 5 分钟），之后缓存秒载
- 确认麦克风已连接且浏览器有权限（Electron 会弹权限请求）
- 检查设置面板中 Whisper 模型和语言是否正确
</details>

<details>
<summary><b>没有 GPU / CUDA 报错</b></summary>

Whisper 会自动回退到 CPU int8 模式。如需强制指定，编辑 `config/config.json`：
```json
"stt": { "device": "cpu", "compute_type": "int8" }
```
</details>

<details>
<summary><b>想用本地模型跑（不联网）</b></summary>

设置面板 → Provider 改为 `Ollama`。需先安装 Ollama 并拉取模型：
```bash
ollama pull qwen3:4b
ollama serve
```
注意：本地模型质量取决于模型大小和显存。6GB 显存建议 4B 级别；24GB 可跑 27B+。
</details>

<details>
<summary><b>npm install 很慢或失败</b></summary>

项目已配 `.npmrc` 使用 npmmirror 国内镜像。如仍失败，检查网络或手动切换：
```bash
npm config set registry https://registry.npmmirror.com
```
</details>

<details>
<summary><b>点爱心召回后，角色要等一下才出现</b></summary>

正常行为：窗口隐藏期间显卡会回收角色纹理，召回时画面会先静默等待约 0.7 秒（这期间桌面看不到任何角色痕迹），等纹理重新就绪后再以完整形象淡入，避免出现“半透明、无面部纹理”的异常画面。
</details>

<details>
<summary><b>功能栏怎么唤出</b></summary>

两种方式：鼠标移近角色身体（悬停腿部/头部都算），或**直接把鼠标移到角色右侧贴身的功能栏区域**（隐藏状态下也可唤出）。功能栏为纵向竖排小按钮条，贴角色右下角，不占头顶空间。鼠标在功能栏和各面板上停留时它们不会消失；移开约 0.3 秒后自动淡出。
</details>

<details>
<summary><b>角色太占屏幕 / 想调整位置</b></summary>

- 角色默认脚底站在 Windows 任务栏上沿，右侧贴一条纵向功能栏
- 按住角色身体拖动可移动位置，**重启后自动恢复上次摆放位置**；托盘右键也可“位置复位”
- 重启后聊天记录自动回填（重启不忘上下文）
- 说“去休息吧”让她离开变成爱心
- Ctrl+Alt+G 随时召唤/隐藏
</details>

---

## 开发文档

| 文档 | 用途 |
|---|---|
| `docs/PRD.md` | 产品需求文档（Markdown 源，**实时维护**） |
| `docs/开发计划.md` | 开发计划（Markdown 源，**实时维护**） |
| `docs/测试用例清单.md` | 测试用例清单（Markdown 源，**实时维护**，测试结果打钩处） |
| `docs/测试用例看板.html` | 测试看板（浏览器内点选打钩、进度自动统计、结果一键复制回传） |
| `docs/产品需求文档.html` | PRD 浏览器版（带状态胶囊可视化，已同步 v1.1.0） |
| `docs/开发计划.html` | 进度看板（进度条 + 里程碑 + 验证记录，已同步 v1.1.0） |

---

## 环境要求

| 项目 | 最低 | 推荐 |
|---|---|---|
| OS | Windows 10 1903+ | Windows 11 |
| Node.js | 18 | 22+ |
| Python | 3.10 | 3.12 |
| GPU | 集显（CPU 回退） | NVIDIA RTX 3060+ 6GB |
| RAM | 8GB | 16GB+ |
| 网络 | DeepSeek 需联网 | 国内镜像全覆盖；语音可全离线（GPT-SoVITS） |

---

## License

Private / Personal Use

> AI生成
---

## 打包（NSIS 安装包）

```powershell
cargo tauri build          # 产物在 src-tauri/target/release/bundle/nsis/
# 或（装了 @tauri-apps/cli 时）
npm run tauri -- build
```

- 产物为 NSIS 安装包；`--no-bundle` 只编译单 exe（`src-tauri\target\release\ai-girlfriend.exe`）。
- Rust 壳体积极小（数 MB），页面资源与 three.js 由 `app://` 协议在运行时从**安装目录**读取——安装包需随附仓库的 renderer/heart/assets/prompts/node_modules/config（bundle 配置见 `src-tauri/tauri.conf.json`，同机安装版形态）。
- 语音/对话后端仍走本机 Python（`.venv` + GPT-SoVITS），用户密钥 `config/user.json` 与聊天记录绝不进包。
- 原 electron-builder 打包方案封存在 `electron` 分支。

## 分支说明

| 分支 | 壳层 | 说明 |
|---|---|---|
| `main` | **Tauri 2**（src-tauri/） | 未来主线：更轻的壳、更小的内存/体积 |
| `electron` | Electron 34（electron/） | Phase 1–45 形态完整封存，含 electron-builder 打包配置，可随时切回 |

> AI生成