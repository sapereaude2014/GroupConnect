# GroupConnect

<p align="center">
  <b>A Group-Context Gateway for Local CLI Agents (Antigravity, Claude Code, Codex, OpenCode)</b><br>
  专为群聊设计的本地 CLI Agent 静默上下文感知与常驻运行网关
</p>

<p align="center">
  <img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License" />
  <img src="https://img.shields.io/badge/python-3.9+-green.svg" alt="Python" />
  <img src="https://img.shields.io/badge/dependency-httpx_only-brightgreen.svg" alt="Zero Bloat" />
  <img src="https://img.shields.io/badge/telegram-Bot_API-blue.svg" alt="Telegram" />
  <img src="https://img.shields.io/badge/harness-Antigravity_|_Claude_|_Codex_|_OpenCode-orange.svg" alt="Supported Harnesses" />
</p>

---

## 📖 项目简介

GroupConnect 是一个专为群聊协作设计的轻量级网关，用于将群聊平台（首发深度支持 Telegram）连接到本地运行的各类 CLI Agent（已支持 **Google Antigravity `agy`**、**Anthropic Claude Code `claude`**、**OpenAI Codex `codex`** 及 **OpenCode `opencode`**）。

通过静默滑动窗口与多模态自动化管道，GroupConnect 让本地 CLI Agent 能够自然感知群内前文讨论背景，自动下载落盘多模态附件，并提供低延迟的常驻执行与即时打断能力。

---

## 👥 典型场景对比

在真实群聊协作中，群成员之间的自然讨论往往不包含 `@bot`。普通机器人由于缺乏静默上下文感知，在被唤醒时容易丢失前文：

```
┌────────────────────────────────────────────────────────────────────────┐
│ 💬 真实群聊场景                                                         │
│                                                                        │
│ Alice: "这套新方案第 3 节关于并发锁的逻辑有点问题，你看了吗？"            │
│ Bob:   "看了，没考虑超时和重试，高并发下可能会死锁。"                  │
│ Alice: "@bot 帮我们分析一下刚才讨论的死锁风险，并把改进方案写入 docs/方案.md"│
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
          ┌─────────────────────────┴─────────────────────────┐
          ▼                                                   ▼
❌ 普通群聊 Bot (未 @ 消息直接丢弃)                  ✅ GroupConnect (静默感知与本地执行)
---------------------------------------             ---------------------------------------
• 表现："请问你要分析什么死锁？请提供前文。"        • 表现：自动提取滑动窗口前文背景，调用本地
• 结果：上下文丢失，必须手动复制粘贴前文             Tool 直接修改 `docs/方案.md` 并汇报
```

---

## ✨ 核心特性

* 🧠 **群聊静默滑动窗口 (Silent Sliding Window)**：在群成员日常交流时不主动打扰，后台自动维护最近 $N$ 条群聊消息（`max_history_len` 可自由配置，默认 30 条）；被唤醒时自动注入讨论背景，连续追问时仅同步增量新消息。
* 📎 **多模态附件自动落盘 (Multimodal Auto-Inbox)**：群内发送的照片、语音和文档自动下载保存至工作区的 `inbox/attachments/` 目录，并在提示词中提供本地绝对路径供视觉与分析工具直接读取。
* 🔥 **常驻引擎工作池 (Resident Worker Pool)**：支持通过全双工 `stream-json` 管道保持 Agent 进程常驻，消除冷启动延迟；支持空闲超时自动回收。
* 🛑 **抢占式强杀 (`/stop`)**：收到 `/stop` 指令时无需排队等待处理锁，通过 POSIX 独立进程组（`os.killpg`）立即终止当前任务及所有子进程。
* 🛡️ **双重白名单看门狗 (Security Gatekeeper)**：支持群聊与私聊成员白名单鉴权；被拉入未授权群聊时自动退出，陌生人私聊直接拦截。
* 📖 **移动端即时预览 (Telegraph Instant View)**：提供长篇文档转译为 Telegraph 页面工具，在 Telegram 移动端内支持 0 秒免密原生弹窗阅读。

---

## 🧩 支持的本地 CLI Harness

| 引擎类型 (`engine_type`) | 调起指令 | 说明 |
| :--- | :--- | :--- |
| `antigravity` (默认) | `agy` | 支持全双工 `stream-json` 管道常驻会话池（零冷启动） |
| `claude` | `claude -p` | 支持 Anthropic Claude Code CLI 会话恢复与执行 |
| `codex` | `codex exec` | 支持 OpenAI Codex CLI 非交互式 JSONL 事件流与图片附件传入 |
| `opencode` | `opencode run` | 支持 OpenCode CLI 非交互式任务执行与多轮会话管理 |

---

## 🚀 极速上手 (只需 3 步)

### 1. 克隆与安装依赖

本项目无需数据库，仅需 Python 3.9+ 及 `httpx`：

```bash
git clone https://github.com/sapereaude2014/GroupConnect.git
cd GroupConnect
pip install -r requirements.txt
```

### 2. 初始化配置 (两种方式任选其一)

#### 方式 A：交互式向导快速生成（推荐）
```bash
python3 -m groupconnect.cli --init
```
*向导会依次询问您的 Telegram Bot Token、所选 CLI Agent 及本地工作区路径，10 秒内自动生成 `config.json`。*

#### 方式 B：手动编辑 `config.json`
```bash
cp config.example.json config.json
```
只需将 `workspace_dir` 指向您希望 Agent 读写代码或文档的**任意单个本地目录**（如 `~/my_project`），无需手动创建任何子文件夹：
```json
{
  "bot_token": "YOUR_TELEGRAM_BOT_TOKEN",
  "engine_type": "claude",
  "workspace_dir": "/path/to/your/project"
}
```

### 3. 启动服务

**前台运行**：
```bash
python3 -m groupconnect.cli --config config.json
```

**后台守护进程常驻 (Watchdog 自动自愈拉起)**：
```bash
./scripts/daemon.sh config.json groupconnect.log groupconnect.pid
```

---

## ⚙️ 配置参数说明

| 参数项 | 类型 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `platform` | string | `"telegram"` | 接入平台（目前支持 `"telegram"`） |
| `engine_type` | string | `"antigravity"` | 后端 Agent 类型（支持 `"antigravity"`, `"claude"`, `"codex"`, `"opencode"`） |
| `workspace_dir` | string | `"./workspace"` | Agent 挂载的本地工作区根目录（所有附件与日志自动在此创建） |
| `max_history_len` | int | `30` | 静默群聊滑动窗口保留的最大消息条数 |
| `timeout_secs` | int | `180` | 单次 Agent 执行最大超时时间（秒） |
| `session_idle_timeout_mins` | int | `30` | 常驻进程空闲自动回收时长（分钟，设为 0 表示不回收） |
| `max_chunk_size` | int | `3800` | 发送给 Telegram 的单条消息安全字符上限 |
| `typing_interval_secs` | float | `4.0` | 推理期间发送“正在输入”心跳指示的间隔（秒） |
| `allowed_chat_ids` | list | `[]` | 允许接入的群聊 ID 白名单（非白名单群聊自动退群） |
| `allowed_user_ids` | list | `[]` | 允许私聊的 Telegram User ID 白名单 |
| `allowed_usernames` | list | `[]` | 允许私聊的 Telegram Username 白名单 |

---

## 🛠 内置指令

* `/status`：查看当前会话状态、常驻进程运行状态、群缓存深度与白名单信息；
* `/stop`：抢占式立即停止当前正在执行的 Agent 任务；
* `/new` 或 `/clear`：重置当前会话并清空群聊滑动缓存；
* `/help`：查看使用帮助。

---

## 📂 场景模板说明 (可选参考)

`templates/` 目录下提供了两个开箱即用的工作区参考模板（**非必选**）：
* 🏡 **家庭管家模板 ([`templates/family_assistant/`](templates/family_assistant/))**：参考目录结构、家庭管理规则与 Telegraph 预览脚本。
* 💼 **团队助理模板 ([`templates/team_ops_assistant/`](templates/team_ops_assistant/))**：参考敏捷项目协作规则与任务跟进规范。

---

## 📄 开源许可证

本项目基于 [MIT License](LICENSE) 开源。
