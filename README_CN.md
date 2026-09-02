# GroupConnect

<p align="center">
  <b>把群聊连接到本地 CLI Agent 及其工作区。</b><br>
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
Alice:  "@AI 帮我们把行程记到日程里"

AI:     "好的，已更新至 schedule.md：
        • 事项：周末爬山
        • 时间：周六 08:00
        • 分工：Bob 负责车辆"
```

> **没有人向 AI 重新写 Prompt，也没有人复制粘贴聊天记录。AI 只是自然读懂了刚才群里发生了什么，并直接落盘到工作区。**

---

## 🎯 普通 Bot vs GroupConnect

```text
❌ 普通群聊 Bot (未 @ 消息直接丢弃)
群成员日常讨论 ───(未@直接丢弃)───> 丢失前文 ───(@AI唤醒)───> "请问你们刚才在聊什么？"

✅ GroupConnect (静默感知与本地工作区执行)
群成员日常讨论 ───(静默滑动窗口)───> 记忆前文 ───(@AI唤醒)───> 自动带入背景并修改本地文件
```

像 **Anthropic Claude Code (`claude`)**、**Google Antigravity (`agy`)**、**OpenAI Codex (`codex`)** 和 **OpenCode (`opencode`)** 这类本地 CLI Agent 非常强大，因为它们能直接在你的电脑上读写文件、执行脚本。

**GroupConnect 就是把这套连接与上下文处理逻辑做成一个即装即用的轻量运行时：**

```text
                 群聊 (自然讨论流)
                         │
                         ▼
               ┌──────────────────┐
               │   GroupConnect   │
               │  捕获静默群聊上下文 │
               │  唤醒本地 CLI Agent │
               └────────┬─────────┘
                        │
                        ▼
                 本地 CLI Agent
         (Claude / Antigravity / Codex)
                        │
               ┌────────┴────────┐
               │                 │
               ▼                 ▼
          即时回答           工作区 (长期资产沉淀)
                                 │
                        ┌────────┼────────┐
                        ▼        ▼        ▼
                      任务看板  业务文档  历史归档
```

---

## 🧱 双层架构设计：Core 与 Templates

> **群聊提供上下文，Agent 负责行动，Workspace 负责沉淀结果。**

GroupConnect 严格区分 **连接层机制（Core）** 与 **工作区组织参考（Templates）**：

### 1. Core（群聊 ➔ 上下文 ➔ Agent）
* **静默滑动窗口与增量同步**：后台维护最近 $N$ 条（默认 30 条）群聊记录，连续追问时仅同步增量新消息；
* **零冷启动进程池**：保持后台进程温热，消除启动延迟并保留多轮会话记忆；
* **多模态附件自动落盘**：群聊照片、单据自动存入 `workspace/inbox/attachments/` 并提供绝对物理路径；
* **即时打断 (`/stop`)**：不排队等待，毫秒级直接强杀当前运行的 Agent 任务树；
* **默认安全锁定 (Default-Deny)**：白名单为空时自动进入锁定模式，杜绝未经授权的 Shell 执行风险。

### 2. Templates（工作区组织参考）
> *注：Templates 并非 GroupConnect 的必需组件，GroupConnect 对你的工作区目录结构不做任何强行规定。模板仅作为展示同一机制在不同场景下的最佳实践参考。*

[`templates/`](templates/) 目录下提供了两套开箱即用的参考实现：
* 🏡 **[家庭管家模板 (family_assistant)](templates/family_assistant/)**：展示如何将家庭群聊转化为健康档案、资产记录与记忆守则的沉淀空间；
* 💼 **[团队助理模板 (team_ops_assistant)](templates/team_ops_assistant/)**：展示如何将研发群聊转化为敏捷任务看板、故障 SOP 与按月归档历史搜索工具。

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
