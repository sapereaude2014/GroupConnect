# GroupConnect

<p align="center">
  <b>让本地 CLI Agent 原生理解群聊上下文的极简 Runtime。</b><br>
  （连接 Telegram、Discord、Slack、飞书 Feishu、企业微信 WeCom；适配 Claude Code、Antigravity、Codex、OpenCode）
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

## 💬 真实场景体验

在真实群聊中，大家总是先自然讨论，最后才唤醒 AI：

```text
Alice:  "周六去爬山吧？"
Bob:    "可以，我负责开车。"
Carol:  "那就早上八点集合？"
Alice:  "@AI 帮我们记一下"

AI:     "好的，已为你记录：
        • 事项：周末爬山
        • 时间：周六 08:00
        • 分工：Bob 负责车辆"
```

> **没有人向 AI 重新写 Prompt，也没有人复制粘贴聊天记录。AI 只是自然读懂了刚才群里发生了什么。**

---

## 🎯 GroupConnect 解决什么问题？

像 **Anthropic Claude Code (`claude`)**、**Google Antigravity (`agy`)**、**OpenAI Codex (`codex`)** 和 **OpenCode (`opencode`)** 这类本地 CLI Agent 非常强大，因为它们能直接在你的电脑上读写文件、执行脚本。

但传统的群聊机器人只在被 `@` 时收到单条消息，彻底丢失了群聊讨论背景。

**GroupConnect 就是把这套繁琐胶水工程压缩成一个极简 Runtime：**
1. 在后台静默维护群聊最近的滑动上下文；
2. 当有人 `@` 机器人时，自动将群聊背景打包注入并调起本地 CLI Agent；
3. 群内发送的照片、语音和文档，自动秒级落盘到本地工作区；
4. 遇到任务长循环时，发送 `/stop` 毫秒级强杀当前进程树。

```text
          群聊平台 (Telegram / Discord / Slack / 飞书 / 企微)
                                   │
                                   ▼
                       GroupConnect (轻量 Runtime)
                 [ 静默滑动窗口 + 附件落盘 + 即时 /stop ]
                                   │
                                   ▼
                    本地 CLI Agent (开箱即用，自由替换)
                 ├── Anthropic Claude Code (`claude`)
                 ├── Google Antigravity (`agy`)
                 ├── OpenAI Codex (`codex`)
                 └── OpenCode (`opencode`)
                                   │
                                   ▼
                    本地工作区 (Workspace / Local Files)
```

---

## 🧱 干净利落的项目结构：Core 与 Templates

GroupConnect 严格区分 **运行时胶水（Core）** 与 **工作区组织范式（Templates）**：

### 1. Core（核心运行时）
* **静默滑动窗口与增量同步**：后台维护最近 $N$ 条（默认 30 条）群聊记录，连续追问时仅同步增量消息；
* **零冷启动进程池**：保持后台进程温热，消除启动延迟并保留多轮会话记忆；
* **多模态附件自动落盘**：群聊照片、单据自动存入 `workspace/inbox/attachments/` 并提供绝对物理路径；
* **即时打断 (`/stop`)**：不排队等待，毫秒级直接强杀当前运行的 Agent 任务树；
* **默认安全锁定 (Default-Deny)**：白名单为空时自动进入锁定模式，杜绝未经授权的 Shell 执行风险。

### 2. Templates（工作区文件组织范式）
[`templates/`](templates/) 目录下提供了两套参考实现，回答*“当群聊变成 Agent 的工作空间时，文件应该怎么组织”*：
* 🏡 **[家庭管家模板 (family_assistant)](templates/family_assistant/)**：包含家庭档案、健康台账、用药记录与单据归档规范；
* 💼 **[团队助理模板 (team_ops_assistant)](templates/team_ops_assistant/)**：包含敏捷任务看板、故障排查 SOP 与按月归档历史搜索工具。

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

## 🚀 30 秒极速上手

### 1. 安装

本项目无需数据库，仅需 Python 3.9+ 及 `httpx`：

```bash
git clone https://github.com/sapereaude2014/GroupConnect.git
cd GroupConnect
pip install -e .
```

确保你的 CLI Agent（如 `claude`、`agy`、`codex` 或 `opencode`）已在本地安装并完成鉴权。

### 2. 初始化配置

运行交互式配置向导：

```bash
groupconnect --init
```

向导会引导你选择接入平台和凭证，自动保存为 `config.<platform>.json`（例如 `config.telegram.json`）。

### 3. 运行服务

**前台调试运行**：
```bash
groupconnect -c config.telegram.json
```

**后台守护运行 (自动崩溃重启与状态管理)**：
```bash
# 启动指定服务
bash scripts/daemon.sh start config.telegram.json

# 查看所有运行中的机器人服务
bash scripts/daemon.sh status

# 停止指定服务
bash scripts/daemon.sh stop config.telegram.json
```

---

## 🛠 内置指令

* `/status` — 查看当前会话状态、常驻进程运行状态、群缓存深度与白名单信息；
* `/stop` — 即时停止当前正在执行的 Agent 任务；
* `/new` 或 `/clear` — 重置当前会话并清空群聊滑动缓存；
* `/help` — 查看使用帮助。

---

## 📄 开源许可证

本项目基于 [MIT License](LICENSE) 开源。
