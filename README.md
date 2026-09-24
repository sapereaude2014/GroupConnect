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
- **Instant Device Control**: Say "开卧室灯" to trigger local scripts directly — millisecond response, no AI round-trip.

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

## ⚙️ Configuration: `<workspace>/.agents/groupconnect.yaml` (One Config Per Workspace)

Place `groupconnect.yaml` inside `<workspace>/.agents/groupconnect.yaml`: **each workspace acts as a self-contained collaborative scenario**, carrying its own `security` (group allowlist), `zero_at` (arbitration rules), `tuning` (isolated IPC directory), and `bots` roster wherever the workspace directory moves. All bots under `bots:` automatically inherit the workspace root and `.agents/souls/` directory without repeating paths. Secrets use `${ENV_VAR}` from `.agents/.env` or global `~/.config/groupconnect/.env` (see [`.env.example`](.env.example)):

```yaml
# Auto-inferred when placed at <workspace>/.agents/groupconnect.yaml
workspace: ~/workspace

bots:
  - id: coder_bot
    name: "Code Assistant"
    platform: telegram
    token: "${CODER_BOT_TOKEN}"   # Use ${ENV_VAR} for secrets — keeps config file safe for Git
    role_summary: "Code authoring and bug fixes"
    aliases: ["coder", "dev"]
    agent:
      engine: codex               # codex | claude | antigravity | opencode | teleagent
      bin: /usr/local/bin/codex   # Optional: explicit binary path (defaults to PATH lookup)
      # model: gpt-5              # Optional: model override
      timeout_secs: 1800          # Optional: per-turn execution timeout in seconds
      session_idle_timeout_mins: 120

  # Append another entry for same-workspace collaboration or cross-platform bots:
  # - id: reviewer_bot
  #   name: "Arch Reviewer"
  #   platform: telegram
  #   token: "${REVIEWER_BOT_TOKEN}"
  #   role_summary: "Architecture review and code auditing"
  #   aliases: ["reviewer", "lead"]
  #   agent:
  #     engine: claude

zero_at:
  enabled: true                 # Uses Jev classifier (100–200ms) by default and auto-reads JEV_API_KEY
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

### Custom Slash Commands & Pattern Fast Lane (Per-Bot)

Declare `custom_commands` and `pattern_commands` directly under the target bot in `bots:`. `custom_commands` register as slash commands (e.g. `/backup`) with mutex locks, health pre-checks, and cron schedules; `pattern_commands` match natural language phrases without a `/` prefix, bypassing the LLM entirely:

```yaml
bots:
  - name: "Code Assistant"
    # ...
    custom_commands:
      - command: backup
        description: "Backup workspace"
        script: "~/.local/bin/my-backup"
        ack_message: "📦 Running backup..."
        success_message: "✅ Backup finished in {duration}s"
        lock: true
        arbiter_only_on_broadcast: true
        schedule:
          weekday: 6
          hour: 4

    pattern_commands:
      - pattern: '^(开|关)(灯|空调)(\d{1,2})?$'
        script: "~/.local/bin/device.py"
```

### Security & Crash Recovery

Default-deny security and crash recovery require no configuration to work, but can be tuned:

```yaml
security:
  allow_open_access: false       # Default: reject all unknown chats and users
  allow_group_members_dm: true   # Allow whitelisted group members to DM the bot
  # allowed_chat_ids: [-100123456789]
  # allowed_user_ids: [123456789]

tuning:
  resume_unanswered_secs: 300   # Re-dispatch unanswered messages within this window on restart (0 to disable)
  max_history_len: 30           # Sliding context buffer size
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
