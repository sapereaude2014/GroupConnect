# GroupConnect

<p align="center">
  <b>专为群聊设计的本地 CLI Agent 静默上下文感知与常驻运行网关</b><br>
  （支持 Telegram、Discord、Slack、飞书 Feishu、企业微信 WeCom；支持 Claude Code、Antigravity、Codex、OpenCode）
</p>

<p align="center">
  <a href="README.md"><b>English</b></a> | <a href="README_CN.md"><b>中文文档</b></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License" />
  <img src="https://img.shields.io/badge/python-3.9+-green.svg" alt="Python" />
  <img src="https://img.shields.io/badge/dependency-httpx_only-brightgreen.svg" alt="Zero Bloat" />
  <img src="https://img.shields.io/badge/security-默认安全锁定-brightgreen.svg" alt="Security" />
  <img src="https://img.shields.io/badge/channels-Telegram_|_Discord_|_Slack_|_Feishu_|_WeCom-blue.svg" alt="Supported Channels" />
  <img src="https://img.shields.io/badge/harness-Claude_|_Antigravity_|_Codex_|_OpenCode-orange.svg" alt="Supported Harnesses" />
</p>

---

## 📖 项目简介

**GroupConnect** 是一个专为群聊协作设计的轻量级网关，用于将主流群聊平台（深度支持 **Telegram**、**Discord**、**Slack**、**飞书 Feishu**、**企业微信 WeCom**）连接到本地运行的各类 CLI Agent（支持 **Anthropic Claude Code `claude`**、**Google Antigravity `agy`**、**OpenAI Codex `codex`** 及 **OpenCode `opencode`**）。

传统机器人只在被 `@` 时才接收单条消息，彻底丢失群聊讨论背景。GroupConnect 在后台静默维护最近讨论上下文，群内发送的多模态文件自动落盘到本地工作区，支持动态成员鉴权，在**默认拒绝（Default-Deny）**的安全策略下提供零冷启动的低延迟常驻执行。

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

## ✨ 核心通用特性（核心卖点）

* 🧠 **群聊静默滑动窗口与增量追问 (Silent Sliding Window & Delta Sync)**：群内成员正常交流时不发消息打扰，后台自动维护最近 $N$ 条讨论记录（默认 30 条）；被 `@` 唤醒时自动注入背景，连续追问时仅同步增量新消息。
* 🔥 **零冷启动常驻引擎 (Zero Cold-Start Worker Pool)**：保持 Agent 进程在后台常驻运行，消除每次调用的冷启动延迟，保持多轮会话记忆。
* 📎 **多模态附件自动落盘 (Multimodal Auto-Inbox)**：群内发送的照片、语音和文档自动下载保存至工作区的 `inbox/attachments/` 目录，并在提示词中直接提供本地绝对物理路径供视觉和文档工具读取。
* ⏹️ **即时打断 (`/stop`)**：当 Agent 陷入长循环或执行出错时，发送 `/stop` 指令无需排队等待，立即安全终止本地当前运行的任务树。
* 🛡️ **默认安全锁定与灵活成员鉴权 (Secure-by-Default & Granular Access)**：遵循默认拒绝策略保护本地命令与文件。支持按 `@username` 授权；提供 `allow_group_members_dm` 开关（可自由配置是否允许群成员免配置私聊）。

---

## 🌐 平台通道上下文权限与限制

| 平台类型 (`platform`) | 实现状态 | 静默群上下文必需配置 | 静默群上下文能力 |
| :--- | :--- | :--- | :--- |
| **`telegram`** | 🟢 已内置 | 在 `@BotFather` 中执行 `/setprivacy` 设为 `Disable`。 | 🌟 完整支持（免公网 IP） |
| **`discord`** | 🟢 已内置 | 在 Discord 开发者后台开启 `Message Content Intent` 特权。 | 🌟 完整支持（REST & Webhook） |
| **`slack`** | 🟢 已内置 | 在 Slack App 中订阅 `message.channels` 与 `app_mention` 事件。 | 🌟 完整支持（Events API） |
| **`feishu`** (飞书) | 🟢 已内置 | 在飞书开放平台申请 `im:message.group_msg`（获取群组所有消息）权限。 | 🌟 完整支持（需 Webhook 回调） |
| **`wecom`** (企业微信) | 🟢 已内置 | **无（无法获取）**：微信官方协议严格限制，不下发群内未 `@` 的消息。 | ⚠️ 仅限 `@` 提问（无前文感知） |

---

## 🧩 支持的本地 CLI Harness

| 引擎类型 (`engine_type`) | 调起指令 | 说明 |
| :--- | :--- | :--- |
| `claude` | `claude -p` | 官方 Anthropic Claude Code CLI，支持会话恢复与上下文执行 |
| `antigravity` (默认) | `agy` | 全双工 `stream-json` 管道常驻工作池（零冷启动） |
| `codex` | `codex exec` | OpenAI Codex CLI 非交互式 JSONL 事件流与图片附件直传 |
| `opencode` | `opencode run` | OpenCode CLI 无头任务执行与多轮 Session 管理 |

---

## 🚀 极速上手 (只需 3 步)

### 1. 克隆与安装依赖

本项目无需数据库，仅需 Python 3.9+ 及 `httpx`：

```bash
git clone https://github.com/sapereaude2014/GroupConnect.git
cd GroupConnect
pip install -r requirements.txt
```

### 2. 初始化配置 (交互式向导)

运行交互式配置向导：

```bash
python3 -m groupconnect.cli --init
```

向导会自动根据你选的平台生成对应的配置文件，默认为 `config.<platform>.json`（例如 `config.telegram.json`、`config.feishu.json`、`config.discord.json`），绝不相互覆盖。

### 3. 运行服务

**前台运行指定平台**：
```bash
python3 -m groupconnect.cli --config config.telegram.json
```

**后台守护运行 (进程崩溃自动重启，保障 7×24 小时在线)**：
```bash
./scripts/daemon.sh config.telegram.json logs/tg.log pids/tg.pid
```

**多平台并发运行 (共享同一个工作区大脑)**：
```bash
./scripts/daemon.sh config.telegram.json logs/tg.log pids/tg.pid
./scripts/daemon.sh config.feishu.json logs/feishu.log pids/feishu.pid
./scripts/daemon.sh config.discord.json logs/discord.log pids/discord.pid
```

---

## ⚙️ 配置参数说明

| 参数项 | 分类 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `platform` | 平台通道 | `"telegram"` | 接入平台（支持 `"telegram"`, `"discord"`, `"slack"`, `"feishu"`, `"wecom"`） |
| `bot_token` | 平台通道 | `""` | Telegram Bot API 访问密钥 |
| `discord_bot_token` | 平台通道 | `""` | Discord Bot Token |
| `slack_bot_token` | 平台通道 | `""` | Slack Bot User OAuth Token (`xoxb-...`) |
| `feishu_app_id` | 平台通道 | `""` | 飞书应用 App ID (`cli_...`) |
| `feishu_app_secret` | 平台通道 | `""` | 飞书应用 App Secret |
| `wecom_corp_id` | 平台通道 | `""` | 企业微信 Corp ID (`ww...`) |
| `wecom_corp_secret` | 平台通道 | `""` | 企业微信应用 Secret |
| `wecom_agent_id` | 平台通道 | `""` | 企业微信应用 Agent ID |
| `engine_type` | 引擎适配 | `"antigravity"` | 后端 Agent 类型（支持 `"claude"`, `"antigravity"`, `"codex"`, `"opencode"`） |
| `workspace_dir` | 通用核心 | `"./workspace"` | Agent 挂载的本地工作区目录（附件与日志自动在此创建） |
| `max_history_len` | 通用核心 | `30` | 静默群聊滑动窗口保留的最大消息条数 |
| `timeout_secs` | 通用核心 | `180` | 单次 Agent 执行最大超时时间（秒） |
| `session_idle_timeout_mins` | 通用核心 | `30` | 常驻进程空闲自动回收时长（分钟，设为 0 表示不回收） |
| `max_chunk_size` | 平台通道 | `3800` | 发送给 Telegram 的单条消息安全字符上限 |
| `allow_open_access` | 安全鉴权 | `false` | 是否允许完全开放访问（为 `false` 时白名单为空会自动进入锁定模式） |
| `allow_group_members_dm` | 安全鉴权 | `true` | 是否允许授权群内的成员免配置直接私聊 Bot（设为 `false` 则仅限指定用户私聊） |
| `allowed_chat_ids` | 安全鉴权 | `[]` | 允许接入的群聊 ID 白名单（非白名单群聊自动退群） |
| `allowed_user_ids` | 安全鉴权 | `[]` | 允许私聊的 User ID 白名单 |
| `allowed_usernames` | 安全鉴权 | `[]` | 允许私聊的 Username 白名单 |

---

## 🛠 内置指令

* `/status`：查看当前会话状态、常驻进程运行状态、群缓存深度与白名单信息；
* `/stop`：即时停止当前正在执行的 Agent 任务；
* `/new` 或 `/clear`：重置当前会话并清空群聊滑动缓存；
* `/help`：查看使用帮助。

---

## 📂 场景模板说明 (可选参考)

`templates/` 目录下提供了两个开箱即用的工作区参考模板（**非必选**）：
* 🏡 **家庭管家模板 ([`templates/family_assistant/`](templates/family_assistant/))**：包含家庭档案管理、多模态单据归档及 Telegraph 即时预览转译工具。
* 💼 **团队助理模板 ([`templates/team_ops_assistant/`](templates/team_ops_assistant/))**：包含敏捷讨论要点提炼、历史记录检索与任务跟进规范。

---

## 📄 开源许可证

本项目基于 [MIT License](LICENSE) 开源。
