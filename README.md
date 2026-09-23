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
               │  │ (TypeSafe Jev / Gen-LLM)│  │
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
- **Coordinated teamwork**: Phrases like "*Assistant A and Assistant B both take a look at this plan*" seamlessly awaken the addressed bots together to contribute from their respective areas of expertise.

### 3. 🧠 True Group Memory & Multimodal Ingestion
- **Instant recovery on restart**: Maintains an in-memory sliding window and rehydrates seamlessly across daemon restarts from local JSONL logs;
- **Automatic attachment ingestion**: Photos, invoices, and documents shared in chat are saved directly to `workspace/inbox/attachments/`, allowing CLI agents to inspect files with absolute local paths;
- **Zero cold-start delay**: Keeps worker processes warm for instant command execution.

### 4. 🛡️ Default-Deny Security & Instant Kill (`/stop`)
- **Safe lockdown by default**: Strict sender whitelisting ensures unauthorized users cannot run local commands;
- **Instant task cancellation**: Send `/stop` anytime to immediately terminate running agent process trees.

### 5. ⚡ Sub-Second Decision Speed with Zero Extra Token Costs
- **Single arbiter + Local IPC relay**: A single primary bot evaluates incoming messages and broadcasts decisions over high-speed Unix sockets—zero redundant model calls;
- **Dual-paradigm decision engines**: Native support for **TypeSafe Jev** discriminative routing (100–200ms latency, free output tokens) as well as any **General LLM (`OpenAI`, `DeepSeek`, `Qwen`, `Gemini`, `Claude`)**;
- **Batteries-included with YAML hot-reloading**: Noise filtering, dialogue continuation, and multi-bot dispatch rules are built in; just declare each bot's `role` and `aliases` in `groupconnect.yaml`, with optional `zero_at.rules` overrides that hot-reload automatically.

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

Requires Python 3.10+ and lightweight dependencies (no database required):

```bash
git clone https://github.com/sapereaude2014/GroupConnect.git
cd GroupConnect
pip install -e .
```

Ensure your chosen CLI agent (e.g., `claude`, `agy`, `codex`, or `opencode`) is installed and authenticated locally.

### 2. Interactive Setup Wizard

Run the streamlined 5-step setup wizard:

```bash
groupconnect init
```

The wizard automatically detects installed local agents, performs real-time Telegram Token connectivity checks, inspects Group Privacy Mode, and generates a minimal `groupconnect.yaml` (< 15 lines) with Zero-@ pre-configured.

### 3. System Health Check (Doctor)

Run the built-in diagnostic tool before starting up:

```bash
groupconnect doctor
```
Verifies Python version, Telegram Bot API connectivity, Group Privacy Mode permissions, Agent authentication, workspace filesystem read/write, and Zero-@ LLM classifier reachability — providing exact fix commands for any failure.

### 4. Run

**Foreground Mode**:
```bash
groupconnect run
```

**Terminal Sandbox Simulator (Test Zero-@ routing without sending real chat messages)**:
```bash
groupconnect test
```

**Background Running & Production Daemon**:

*Quick Background Run*:
```bash
nohup groupconnect run > groupconnect.log 2>&1 &
```

*Production Supervision (Systemd / Supervisor)*:
GroupConnect is designed as a standard foreground runner. For production deployments, manage it using your system process supervisor:

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

---

## ⚙️ Unified Configuration: `groupconnect.yaml`

The single configuration file generated by `groupconnect init` covering 90%+ of use cases:

```yaml
# 1. Messaging Channel (telegram, discord, slack, feishu, wecom)
channel:
  platform: telegram
  token: ${TELEGRAM_BOT_TOKEN}  # Supports env var expansion or plaintext

# 2. Local CLI Agent Harness
agent:
  engine: codex                 # codex, claude, antigravity, opencode, teleagent
  workspace: ~/workspace        # Mounted workspace directory

# 3. Autonomous Zero-@ Perception
zero_at:
  enabled: true                 # Batteries-included with 4s silence window & built-in router
  api_key: ${JEV_API_KEY}       # Optional if already present in environment
```

---

## 🧩 Advanced Topics

### 1. Multi-Bot Collaboration

To deploy multiple specialized bots in the same group, declare them directly in `groupconnect.yaml` under `bots`:

```yaml
channel:
  platform: telegram

bots:
  - name: coder_bot
    token: ${CODER_BOT_TOKEN}
    agent: codex
    role: "Code authoring, refactoring, and bug fixes"
    aliases: ["coder", "dev"]

  - name: reviewer_bot
    token: ${REVIEWER_BOT_TOKEN}
    agent: claude
    role: "Architecture review, code auditing, and compliance"
    aliases: ["reviewer", "lead"]

zero_at:
  enabled: true
```

Running `groupconnect run` automatically launches all defined bots concurrently within the same event loop. The first bot acts as Arbiter, coordinating dispatch without cross-talk. To run a specific bot in an isolated process, use `--bot <name>` (e.g. `groupconnect run --bot coder_bot`).

### 2. Classifier Engine & Routing Rule Hot-Reloading (`zero_at`)

#### A. Switching Classifier Engines (`zero_at.classifier`)
By default, GroupConnect uses **TypeSafe Jev** (`engine: jev`). You can seamlessly switch to any general LLM (OpenAI-compatible providers like DeepSeek / Qwen / Local Ollama, Google Gemini, or Anthropic Claude):

```yaml
zero_at:
  enabled: true
  classifier:
    engine: llm                           # jev (default) | llm | openai | gemini | anthropic
    model: deepseek-chat                  # e.g. jev-latest, gpt-4o-mini, deepseek-chat, gemini-2.5-flash-lite
    base_url: https://api.deepseek.com/v1 # Custom OpenAI-compatible endpoint (optional for native OpenAI/Gemini/Claude)
    api_key: ${DEEPSEEK_API_KEY}
```

#### B. Optional Group-Specific Boundary Tweaks (`zero_at.rules`)

Universal conversational rules (noise filtering, banter protection, dialogue continuation, automatic matching via each bot's `role`, and multi-bot dispatch vs parallel collaboration) **are built-in and active by default—95% of setups require zero rule configuration**.

If your group has custom conventions, override only the specific dimensions you need under `zero_at.rules` in `groupconnect.yaml` (unspecified dimensions automatically inherit built-in defaults, and changes hot-reload on save):

```yaml
zero_at:
  enabled: true
  rules:
    group: "Engineering team collaboration chat with specialized assistant bots"
    drop: "Casual human-to-human chitchat, memes, or topics unrelated to any assistant"
    # immediate: "Reply to {bot}'s earlier question, or direct operational commands matching: {role}"
    # wait: "Questions needing data, analysis, or recommendations matching: {role}"
    # parallel: "Sender explicitly asks {bot} ({role}) and another assistant to respond together"
```

---

## 🛠 Slash Commands & Custom Extensions

### Built-in Commands
* `/status` — View current session, engine status, sliding buffer depth, and whitelist info.
* `/stop` — Preemptively terminate in-flight agent tasks immediately.
* `/new` or `/clear` — Reset session and clear sliding context buffer.
* `/help` — Display help information and registered custom commands.

### Declarative Custom Commands (`custom_commands`)
GroupConnect supports declarative custom commands and background tasks configured directly in `groupconnect.yaml`. On startup, the gateway dynamically registers declared commands with platform menus (e.g. Telegram `setMyCommands`):

```yaml
custom_commands:
  - command: backup
    description: "Trigger workspace backup script"
    description_en: "Trigger workspace backup script"
    script: "scripts/backup.sh"
    ack_message: "📦 [{bot_name}] Backup job started..."
    success_message: "✅ [{bot_name}] Backup completed in {duration}s."
    error_message: "❌ [{bot_name}] Backup failed (Exit {returncode}): {stderr}"
    lock: true
    arbiter_only_on_broadcast: true
    schedule:
      weekday: 6
      hour: 4
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
