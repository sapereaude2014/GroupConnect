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

- **Zero-@ Autonomous Perception**: Converse naturally — the bot reads context to decide when to respond, stays silent during chitchat, and yields to humans on open questions.
- **Multi-Bot Collaboration**: Deploy multiple specialized bots in one chat. Understands dispatch ("A, let B handle it" → only A responds) and parallel ("A and B, both look at this" → both respond).
- **Group Context Memory**: Restart-safe context buffer; photos and documents auto-saved to workspace for agent access.
- **Default-Deny Security**: Strict sender whitelist; `/stop` instantly kills running agent processes.
- **Smart Routing Engine**: A lightweight classifier (Jev, 200ms) decides whether and who should respond — only waking the heavy AI agent when truly needed. Supports `openai` / `anthropic` / `gemini` protocols.
- **Instant Device Control**: Say "turn on bedroom lights" to trigger local scripts directly — millisecond response, no AI round-trip.

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

- **Full Configuration Reference (with inline comments for every parameter)**: see [`groupconnect.example.yaml`](groupconnect.example.yaml) (multi-bot routing, local agent harnesses, custom slash commands, regex fast lanes, Zero-@ classifier, and security allowlists).
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
