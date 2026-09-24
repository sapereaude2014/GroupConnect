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

- **Zero-@ Autonomous Perception**: Converse naturally — the bot reads context to decide when to answer, stays silent during chitchat, and yields to humans on open questions (4s grace window).
- **Multi-Bot Collaboration**: Deploy specialized bots in one chat. Understands dispatch ("A, ask B to run tests" → only A responds) and parallel ("A and B both look at this" → both respond).
- **True Group Memory**: Sliding context buffer rehydrated from disk on restart; photos and documents auto-saved to workspace for agent inspection.
- **Default-Deny Security**: Strict sender whitelisting; `/stop` instantly kills running agent processes.
- **Lightweight Intent Classifier**: Built-in routing rules with hot-reloadable YAML slots, waking your heavy local CLI agent only when needed. Supports TypeSafe Jev (100–200ms) and standard LLM protocols (`openai` / `anthropic` / `gemini`) with custom `base_url`.
- **Zero-Token Fast Lane**: Regex-matched natural language phrases (e.g. "开卧室灯") bypass LLM entirely for instant local script execution.

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

## ⚙️ Configuration: `groupconnect.yaml`

Each bot entry binds its own chat `platform`, credentials (`token`), and local execution `agent`. Write 1 entry for a single bot, or append more entries for multi-bot collaboration or multi-platform hosting (the first bot on each platform acts as the Arbiter):

```yaml
bots:
  - name: "Code Assistant"
    username: "coder_bot"
    platform: telegram
    token: ${CODER_BOT_TOKEN}     # Use ${ENV_VAR} for secrets — keeps config file safe for Git
    role: "Code authoring and bug fixes"
    aliases: ["coder", "dev"]
    agent:
      engine: codex             # codex | claude | antigravity | opencode | teleagent
      workspace: ~/workspace

  # Append another entry for same-group collaboration or cross-platform bots:
  # - name: "Arch Reviewer"
  #   username: "reviewer_bot"
  #   platform: telegram
  #   token: "987654321:BBG..."
  #   role: "Architecture review and code auditing"
  #   aliases: ["reviewer", "lead"]
  #   agent:
  #     engine: claude
  #     workspace: ~/workspace

zero_at:
  enabled: true                 # Uses Jev classifier (100–200ms) by default and auto-reads JEV_API_KEY from environment
```

### Classifier Configuration (Optional)

`classifier` is optional (defaults to **Jev** and automatically reads `JEV_API_KEY` from your environment). Configure it only when switching to another LLM protocol or a custom endpoint:

```yaml
zero_at:
  enabled: true
  classifier:
    engine: openai                        # Protocol: jev (default) | openai | anthropic | gemini
    model: deepseek-chat                  # Classifier model ID
    base_url: https://api.deepseek.com/v1 # Optional: custom API Base URL (defaults to official protocol endpoint)
    # api_key: ""                         # Optional: if omitted, auto-reads JEV_API_KEY / OPENAI_API_KEY / ANTHROPIC_API_KEY / GEMINI_API_KEY
```

### Custom Slash Commands & Pattern Fast Lane

`custom_commands` register as slash commands (e.g. `/backup`) alongside built-in ones. `pattern_commands` match natural language phrases without a `/` prefix, bypassing the LLM entirely:

```yaml
custom_commands:
  - command: backup
    description: "Backup workspace"
    script: "scripts/backup.sh"
    lock: true
    schedule:
      weekday: 6
      hour: 4

pattern_commands:
  - pattern: '^(开|关)(灯|空调)(\d{1,2})?$'
    script: "scripts/device.py"
    # pass_args: true (default) and lock: true (default) — no need to declare
```

See [`groupconnect.example.yaml`](groupconnect.example.yaml) for all options.

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
