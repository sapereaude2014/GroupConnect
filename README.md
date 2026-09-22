<h1 align="center">GroupConnect</h1>

<p align="center">
  <b>Connect group chats to local CLI agents and their workspaces.</b><br>
  A lightweight connection layer bridging Telegram, Discord, Slack, Feishu, and WeCom to Claude Code, Antigravity, Codex, and OpenCode.
</p>

<p align="center">
  <a href="README.md"><b>English</b></a> | <a href="README_CN.md"><b>中文文档</b></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License" />
  <img src="https://img.shields.io/badge/python-3.9+-green.svg" alt="Python" />
  <img src="https://img.shields.io/badge/dependency-httpx_only-brightgreen.svg" alt="Zero Bloat" />
  <img src="https://img.shields.io/badge/security-Default_Deny-brightgreen.svg" alt="Security" />
  <img src="https://img.shields.io/badge/channels-Telegram_|_Discord_|_Slack_|_Feishu_|_WeCom-blue.svg" alt="Supported Channels" />
  <img src="https://img.shields.io/badge/harness-Claude_|_Antigravity_|_Codex_|_OpenCode-orange.svg" alt="Supported Harnesses" />
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

> **Notice: Nobody tagged `@AI`. Nobody wrote a lengthy prompt or copied chat logs. The assistant autonomously perceived the intent from recent conversation context, stepped in without being `@mentioned`, and updated the local workspace.**

---

## 🎯 Traditional Bots vs GroupConnect

```text
❌ Traditional Group Bots (Blind, Isolated, and Tag-Dependent)
Group Chatting ───(Discarded)───> Context Lost ───(@Bot explicitly tagged)───> "Sorry, what were you talking about?"

✅ GroupConnect (Zero-@ Autonomous Perception + Workspace Execution)
Group Chatting ───(Sliding Context + Semantic Arbiter)───> Intent Recognized (Zero-@) ───> Updates Local Workspace
```

Local CLI agents like **Anthropic Claude Code (`claude`)**, **Google Antigravity (`agy`)**, **OpenAI Codex (`codex`)**, and **OpenCode (`opencode`)** run on your machine with full access to your local files and tools.

**GroupConnect packages connection, context buffering, and autonomous perception into a ready-to-use lightweight runtime:**

```text
                 Group Chat (Natural Discussion)
                               │
                               ▼
               ┌───────────────────────────────┐
               │         GroupConnect          │
               │  ┌─────────────────────────┐  │
               │  │ Silent Context Buffer   │  │
               │  └────────────┬────────────┘  │
               │               ▼               │
               │  ┌─────────────────────────┐  │
               │  │ Autonomous Arbiter (IPC)│  │
               │  │ (TypeSafe Jev / Gemini) │  │
               │  └────────────┬────────────┘  │
               └───────────────┼───────────────┘
                               │ (Zero-@ Perception or Direct Call)
                               ▼
                        Local CLI Agents
                 (Claude / Antigravity / Codex)
                               │
                      ┌────────┴────────┐
                      │                 │
                      ▼                 ▼
                 Direct Reply       Workspace (Persistent Local Assets)
                                        │
                               ┌────────┼────────┐
                               ▼        ▼        ▼
                             Tasks    Docs    Automations
```

---

## ✨ Key Features: Engineered for Natural Group Chat Workflows

> **Group chat coordinates, CLI Agents execute locally, Workspace persists knowledge.**

### 1. 🗣️ Zero-@ Autonomous Perception (Listens Like a Human Teammate)
- **No robotic `@bot` mentions required**: Converse naturally in group chats. GroupConnect reads conversation context to decide when it is genuinely expected to answer;
- **Strictly silent during interpersonal chitchat**: Social banter, casual chat, and private emotional exchanges are strictly ignored—eliminating accidental interruptions;
- **Polite silence & human preemption**: For open-ended questions or discussions, the bot pauses for 4 seconds to give humans room to answer first. If any human responds, the bot immediately cancels its pending reply.

### 2. 🤖 Multi-Bot Collaboration & Smart Dispatch (No Clashing)
- **Role-based specialization**: Host multiple specialized bots in one chat (e.g. an Ops bot for server infra, a Dev bot for code inspection, a Docs bot for task tracking), each responding only to their domain;
- **Understands dispatch hierarchy**: Phrases like "*Assistant A, ask Assistant B to run the test suite*" awaken ONLY Assistant A to orchestrate; Assistant B won't jump the gun;
- **Coordinated teamwork**: Phrases like "*Both of you take a look at this plan*" seamlessly awaken multiple bots to contribute from their respective areas of expertise.

### 3. 🧠 True Group Memory & Multimodal Ingestion
- **Instant recovery on restart**: Maintains an in-memory sliding window and rehydrates seamlessly across daemon restarts from local JSONL logs;
- **Automatic attachment ingestion**: Photos, invoices, and documents shared in chat are saved directly to `workspace/inbox/attachments/`, allowing CLI agents to inspect files with absolute local paths;
- **Zero cold-start delay**: Keeps worker processes warm for instant command execution.

### 4. 🛡️ Default-Deny Security & Instant Kill (`/stop`)
- **Safe lockdown by default**: Strict sender whitelisting ensures unauthorized users cannot run local commands;
- **Instant task cancellation**: Send `/stop` anytime to immediately terminate running agent process trees.

### 5. ⚡ Sub-Second Decision Speed with Zero Extra Token Costs
- **Single arbiter + Local IPC relay**: A single primary bot evaluates incoming messages and broadcasts decisions over high-speed Unix sockets—zero redundant model calls;
- **Out-of-the-box ultrafast decision models**: Native support for TypeSafe Jev (100–200ms latency, free output tokens) with one-line fallback to Google Gemini Flash-Lite;
- **Plaintext configuration with hot-reloading**: All aliases, roles, and routing criteria live in JSON and Markdown rules, hot-reloading without daemon restarts.

---

## 🧱 Architecture Reference: Core vs Templates

GroupConnect cleanly separates **Connection Layer Mechanics (Core)** from **Workspace Reference Patterns (Templates)**:
* **Core (Chat ➔ Context ➔ Agent)**: Handles platform polling, zero-@ routing, sliding memory, file ingestion, and process scheduling;
* **Templates (Workspace Presets)**: Optional reference setups in [`templates/`](templates/):
  - 🏡 **[Family Assistant](templates/family_assistant/)**: Organizing personal files, health logs, and financial records;
  - 💼 **[Team Ops Assistant](templates/team_ops_assistant/)**: Agile sprint boards, incident SOPs, and searchable monthly archives.

---

## 🌐 Platform Context Matrix

| Platform (`platform`) | Status | Required Setting for Silent Group Context | Silent Context & Zero-@ Support |
| :--- | :--- | :--- | :--- |
| **`telegram`** | 🟢 Built-in | Set `/setprivacy -> Disable` in `@BotFather`. | 🌟 Full (Zero-@ Autonomous Wake enabled; built-in auto-Telegraph Instant View cards for long text/tables) |
| **`discord`** | 🟢 Built-in | Enable `Message Content Intent` in Discord Developer Portal. | 🌟 Full (Zero-@ Autonomous Wake enabled) |
| **`slack`** | 🟢 Built-in | Subscribe to `message.channels` and `app_mention` in Slack App. | 🌟 Full (Zero-@ Autonomous Wake enabled) |
| **`feishu`** (Lark) | 🟢 Built-in | Request `im:message.group_msg` permission in Feishu Developer Console. | 🌟 Full (Zero-@ Autonomous Wake enabled) |
| **`wecom`** (WeChat Work) | 🟢 Built-in | **None (Unsupported)**: WeChat protocol does not push unmentioned group messages. | ⚠️ Mention-only (Falls back to @-triggered mode) |

---

## 🚀 Quick Start (30 Seconds)

### 1. Install

Requires Python 3.9+ and `httpx` (no database required):

```bash
git clone https://github.com/sapereaude2014/GroupConnect.git
cd GroupConnect
pip install -e .
```

Ensure your chosen CLI agent (e.g., `claude`, `agy`, `codex`, or `opencode`) is installed and authenticated locally.

### 2. Configure

Run the interactive setup wizard:

```bash
groupconnect --init
```

The wizard prompts for your platform and credentials, saving to `config.<platform>.json` (e.g., `config.telegram.json`).

### 3. Run

**Foreground Mode**:
```bash
groupconnect -c config.telegram.json
```

**Background Daemon (Crash Auto-Restart & Status Management)**:
```bash
# Start bot in background
bash scripts/daemon.sh start config.telegram.json

# Check status of running bots
bash scripts/daemon.sh status

# Stop bot
bash scripts/daemon.sh stop config.telegram.json
```

### 4. Enable Autonomous Zero-@ Perception (Optional)

Allow the bot to infer intent from recent group context and reply intelligently without requiring explicit `@` mentions:

1. **Configure routing rules**:
   ```bash
   cp autonomous_config.example.json autonomous_config.json
   cp router_prompt.example.txt router_prompt.txt
   cp routing_rules.example.md routing_rules.md
   ```
   Configure zero-token aliases (`aliases`) and job boundaries (`roles`) in `autonomous_config.json`, then export your classifier API key (`JEV_API_KEY` for TypeSafe Jev or `GEMINI_ROUTER_API_KEY` for Google Gemini Flash-Lite). Point `classifier.rules_file` (default `routing_rules.md`) at your shared decision wording and adapt it to your group.

   The `classifier` block is a **self-describing provider registry**: `active` is the one-line switch for the live backend, and each entry under `providers` declares its own `engine` (`jev` for TypeSafe structured classification, `gemini` for Google AI Studio free-text JSON), `model`, `api_key_env`, `timeout_ms` and engine-specific resources — e.g. `prompt_template` supplies the gemini engine's prompt skeleton. Shared decision wording lives in `rules_file` (single source of truth) and is consumed by every engine, so switching backends never drifts judgment semantics. A one-line `active` change is hot-reloaded with zero restart.

2. **Restart the service**:
   ```bash
   bash scripts/daemon.sh restart config.telegram.json
   ```
   The bot will automatically enter perception mode, using the 3-tier pipeline (L0 noise filter ➔ L1 alias bypass ➔ L2 semantic classification) to decide when to answer.

### 5. Multi-Bot Collaboration (Optional)

When deploying multiple specialized bots in the same group, coordinate responses and prevent overlapping answers via local IPC:

1. **Share IPC and rules across bot configs**:
   Create dedicated config files pointing to the same `ipc_dir` and `autonomous_config_path`, designating one instance as the arbiter (`arbiter_bot`):
   ```json
   // config.ops.json (Arbiter instance: Ops & Decision)
   {
     "platform": "telegram",
     "bot_token": "YOUR_OPS_BOT_TOKEN",
     "bot_username": "ops_bot",
     "ipc_dir": "/tmp/groupconnect_ipc",
      "autonomous_config_path": "autonomous_config.json",
     "workspace_dir": "./workspace_ops",
     "engine_type": "antigravity"
   }
   ```
   ```json
   // config.chat.json (Worker instance: Planning & Assistant)
   {
     "platform": "telegram",
     "bot_token": "YOUR_CHAT_BOT_TOKEN",
     "bot_username": "chat_bot",
     "ipc_dir": "/tmp/groupconnect_ipc",
      "autonomous_config_path": "autonomous_config.json",
     "workspace_dir": "./workspace_chat",
     "engine_type": "claude"
   }
   ```

2. **Launch each bot daemon**:
   ```bash
   bash scripts/daemon.sh start config.ops.json
   bash scripts/daemon.sh start config.chat.json
   ```
   The arbiter evaluates intents once and coordinates task dispatch over Unix Socket (IPC) broadcasts, so multiple bots collaborate cleanly by role without talking over each other.

---

## 🛠 Slash Commands & Custom Extensions

### Built-in Commands
* `/status` — View current session, engine status, sliding buffer depth, and whitelist info.
* `/stop` — Preemptively terminate in-flight agent tasks immediately.
* `/new` or `/clear` — Reset session and clear sliding context buffer.
* `/help` — Display help information and registered custom commands.

### Declarative Custom Commands (`custom_commands`)
GroupConnect supports declarative custom commands and background tasks configured directly in `config.json`. On startup, the gateway dynamically registers declared commands with platform menus (e.g. Telegram `setMyCommands`):

```json
"custom_commands": [
  {
    "command": "backup",
    "description": "Trigger workspace backup script",
    "description_en": "Trigger workspace backup script",
    "script": "scripts/backup.sh",
    "ack_message": "📦 [{bot_name}] Backup job started...",
    "success_message": "✅ [{bot_name}] Backup completed in {duration}s.",
    "error_message": "❌ [{bot_name}] Backup failed (Exit {returncode}): {stderr}",
    "lock": true,
    "arbiter_only_on_broadcast": true,
    "schedule": {
      "weekday": 6,
      "hour": 4
    }
  }
]
```

* **`script`**: Path to executable script (supports `~` expansion);
* **`pass_args`**: Appends trailing arguments to the subprocess execution;
* **`check_args` / `check_success_message`**: Pre-flight inspection (e.g. status check before launching full routine);
* **`lock`**: Single-instance concurrency lock preventing duplicate overlapping runs;
* **`arbiter_only_on_broadcast`**: In multi-bot groups, only the Arbiter bot executes untargeted broadcast `/cmd`, while explicit `/cmd@bot` invokes that specific instance;
* **`schedule`**: Optional background weekly/daily scheduler running autonomously without external cron.

---

## 📄 License

Distributed under the [MIT License](LICENSE).
