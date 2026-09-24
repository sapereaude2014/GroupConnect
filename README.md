<h1 align="center">GroupConnect</h1>

<p align="center">
  <b>Connect group chats to local CLI agents and their workspaces.</b><br>
  A lightweight connection layer bridging Telegram, Discord, Slack, Feishu, and WeCom to Claude Code, Antigravity, Codex, OpenCode, and TeleAgent.
</p>

<p align="center">
  <a href="README.md"><b>English</b></a> | <a href="README_CN.md"><b>中文文档</b></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License" />
  <img src="https://img.shields.io/badge/python-3.10+-green.svg" alt="Python" />
  <img src="https://img.shields.io/badge/dependency-httpx_only-brightgreen.svg" alt="Zero Bloat" />
  <img src="https://img.shields.io/badge/security-Default_Deny-brightgreen.svg" alt="Security" />
  <img src="https://img.shields.io/badge/channels-Telegram_|_Discord_|_Slack_|_Feishu_|_WeCom-blue.svg" alt="Supported Channels" />
  <img src="https://img.shields.io/badge/harness-Claude_|_Antigravity_|_Codex_|_OpenCode_|_TeleAgent-orange.svg" alt="Supported Harnesses" />
</p>

---

## 💬 The Zero-@ Experience

In real-world group chats, conversations flow naturally without anyone typing robot commands or `@mention` tags:

```text
Alice: "Hiking this Saturday?"
Bob:   "Sure, I can drive."
Carol: "Let's meet at 8:00 AM then?"
Alice: "Can someone log this into our schedule?"

Assistant: "Recorded in schedule.md:
           • Event: Saturday Hiking trip
           • Departure: 08:00 AM
           • Transportation: Bob will drive"
```

> **Nobody tagged `@AI`. Nobody wrote a lengthy prompt. The assistant autonomously perceived the intent from conversation context, stepped in without being `@mentioned`, and updated the local workspace.**

---

## ✨ Key Features

- **Zero-@ Perception & Lightweight Routing**: Converse naturally — a fast pre-classifier (Jev ~200ms by default, switchable to `openai` / `anthropic` / `gemini`) reads conversation context to decide whether and who should respond, staying silent during human chitchat and waking heavy local CLI agents only when needed.
- **Heterogeneous Multi-Bot Collaboration & Personas**: Run multiple specialized bots in one group or across platforms (each bound to its own engine like `Claude Code`, `Antigravity`, `Codex`, or `TeleAgent`, plus its own `souls/{username}.md` persona). Supports **targeted dispatch** ("A, let B check this" → only A responds) and **parallel consultation** ("Both of you take a look" → both respond).
- **Direct Script Triggers & Custom Commands**:
  - **Natural-Language Script Triggers (`pattern_commands`)**: Match fixed phrases (e.g., "turn on bedroom lights") via regex to execute local scripts in milliseconds without invoking any LLM;
  - **Custom `/Commands` & Scheduled Tasks (`custom_commands`)**: Register local scripts as native `/` menu commands (e.g., `/backup`) with pre-check hooks, concurrency locks, and scheduled group broadcasts.
- **Persistent Context, Bidirectional Files & Auto-Folding**: Restart-safe context buffer that **automatically re-dispatches unanswered messages after a restart**; group photos, audio, and documents are saved to the workspace for agents, agent-generated files upload back via `【SendFile: /path】`, and long replies auto-fold into Telegraph articles or expandable blockquotes.
- **Default-Deny Security & Process Control**: Rejects all unauthorized chats and users by default, supports live hot-reload of allowlists and routing rules, and `/stop` immediately kills the underlying agent process tree.

---

## 🌐 Platform Support

| Platform | Silent Context & Zero-@ | Required Setting |
| :--- | :--- | :--- |
| **Telegram** | 🌟 Full | `/setprivacy → Disable` in @BotFather |
| **Discord** | 🌟 Full | Enable `Message Content Intent` |
| **Slack** | 🌟 Full | Enable Socket Mode & subscribe `message.channels` / `message.groups` |
| **Feishu** | 🌟 Full | Request `im:message.group_msg` permission |
| **WeCom** | ⚠️ @-only | WeChat Work protocol doesn't push unmentioned messages |

---

## 🚀 Quick Start

```bash
git clone https://github.com/sapereaude2014/GroupConnect.git
cd GroupConnect
pip install -e .
groupconnect init      # Interactive 5-step wizard
groupconnect doctor    # Health check before first run
groupconnect run       # Start (Ctrl+C to stop)
```

<details>
<summary>📦 <b>Production Supervision (nohup / Systemd / Supervisor)</b> (Click to expand)</summary>

- **Quick Background Run**:
  ```bash
  nohup groupconnect run > groupconnect.log 2>&1 &
  ```

- **Systemd** (`/etc/systemd/system/groupconnect.service`):
  ```ini
  [Unit]
  Description=GroupConnect Gateway
  After=network.target

  [Service]
  Type=simple
  User=your_user
  WorkingDirectory=/path/to/workspace
  ExecStart=/usr/local/bin/groupconnect run
  Restart=always
  RestartSec=5s

  [Install]
  WantedBy=multi-user.target
  ```

- **Supervisor** (`/etc/supervisor/conf.d/groupconnect.conf`):
  ```ini
  [program:groupconnect]
  command=groupconnect run
  directory=/path/to/workspace
  user=your_user
  autostart=true
  autorestart=true
  startsecs=5
  ```
</details>

---

## ⚙️ Configuration

Run `groupconnect init` to generate a configuration interactively, or copy the reference templates:

```bash
cp groupconnect.example.yaml groupconnect.yaml
cp .env.example .env
```

- **Full Configuration Reference (with inline comments for every parameter)**: see [`groupconnect.example.yaml`](groupconnect.example.yaml) (multi-bot routing, local agent harnesses, custom slash commands, direct script triggers, Zero-@ classifier, and security allowlists).
- **Environment Variables & Secrets**: see [`.env.example`](.env.example).

---

## 🛠 Built-in Commands

| Command | Description |
|---|---|
| `/status` | Session, engine, buffer, and whitelist status |
| `/stop` | Instantly terminate running agent task |
| `/new` `/clear` | Reset session and context |
| `/help` | Show guide and registered custom commands |

---

## 📄 License

Distributed under the [MIT License](LICENSE).
