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

## 🧱 The Two-Layer Architecture: Core & Templates

> **Group chats provide the context, Agents take action, and the Workspace preserves the results.**

GroupConnect cleanly separates **the connection runtime (Core)** from **workspace reference setups (Templates)**:

### 1. Core (Group Chat ➔ Context ➔ Agent)
* **Silent Sliding Window & Warm Rehydration**: Maintains recent group discussion in memory (default: 30 messages) and automatically rehydrates the sliding window from local JSONL logs upon restart. Syncs only incremental messages on continuous follow-ups.
* **Zero Cold-Start Worker Pool**: Keeps agent subprocesses warm in the background for instant execution and multi-turn conversational memory.
* **Multimodal Auto-Inbox**: Photos, voice notes, and documents sent in chat are automatically downloaded to `workspace/inbox/attachments/` and passed as absolute local paths.
* **Instant `/stop` Interruption**: Preemptively terminates active CLI agent process trees on `/stop` without waiting for queues or locks.
* **Default-Deny Security**: Safe lockdown mode by default, preventing unauthorized users from accessing your local machine.
* **Autonomous Multi-Bot Perception (Zero-@ Routing)**: Single Arbiter + Peer IPC Relay architecture. Automatically senses when an assistant should reply without explicit `@` mentions. Runs a 3-tier pipeline (L0 noise drop ➔ L1 alias bypass ➔ L2 semantic classification), supporting **TypeSafe Jev** (ultrafast System-One decision model with free output tokens) and **Google Gemini Flash-Lite**, with dual countdown windows (1s immediate / 4s silence) and human preemption.

### 2. Templates (Workspace Reference Setups)
*Note: Templates are purely optional reference implementations. GroupConnect imposes zero restrictions on your workspace structure.*

Reference presets in [`templates/`](templates/) demonstrate how to organize local directories when turning a group chat into an ongoing workspace:
* 🏡 **[Family Assistant](templates/family_assistant/)**: Turning a family chat into a persistent ledger for health records, assets, and memory guidelines.
* 💼 **[Team Ops Assistant](templates/team_ops_assistant/)**: Turning a dev team chat into an active workspace for sprint tracking, incident SOPs, and searchable monthly JSONL archives.

---

## 🤖 Autonomous Routing (Zero-@ Perception & Multi-Bot Collaboration)

In natural group conversations, constantly typing `@bot` creates friction. GroupConnect features an **Autonomous Routing Engine** that allows multiple specialized bots to listen and selectively awaken without being explicitly mentioned:

```text
Incoming Message
       │
       ├─ L0: Physical Noise Filter (0-Token)
       │      Empty text, pure emojis, or standard acknowledgments ("ok", "got it") -> Drop
       │
       ├─ L1: Alias Direct Bypass (0-Token)
       │      Direct keyword match ("assistant", "helper") -> Instant wake
       │      (Protected by regex against self-referencing and echoing)
       │
       └─ L2: Classifier Pipeline (Single Arbiter Decision)
              Evaluates recent sliding context with TypeSafe Jev or Gemini Flash-Lite:
              • Reply to Bot Question -> Target Bot (Immediate 1.0s window)
              • Interpersonal Chitchat -> Silence (Drop)
              • Imperative Instruction -> Target Bot (Immediate 1.0s window)
              • Open Question/Query   -> Target Bot (Silence 4.0s window)
```

* **Single Arbiter + Symmetric Observers**: Exactly one primary bot evaluates incoming messages and broadcasts decisions via Unix domain socket IPC (`CrossBotRelay`). Zero redundant model calls.
* **Dual Windows & Human Preemption**: Urgent commands trigger after a 1.0s window. Open questions wait for 4.0s of chat silence, leaving room for human members to discuss first. If another human speaks during the countdown, the bot's pending response is immediately cancelled.
* **Pluggable Backends**: Out-of-the-box support for **TypeSafe Jev** (specialized System-One decision model with sub-second latency and zero output token cost) and **Google Gemini Flash-Lite**.
* **Zero Secrets in Code**: Configuration and prompt templates are cleanly externalized in `autonomous_config.json` and `router_prompt.txt` at the repository root (see [`autonomous_config.example.json`](autonomous_config.example.json)).

---

## 🌐 Platform Context Matrix

| Platform (`platform`) | Status | Required Setting for Silent Group Context | Silent Context & Zero-@ Support |
| :--- | :--- | :--- | :--- |
| **`telegram`** | 🟢 Built-in | Set `/setprivacy -> Disable` in `@BotFather`. | 🌟 Full (Zero-@ Autonomous Wake enabled) |
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
   ```
   Configure zero-token aliases (`aliases`) and job boundaries (`roles`) in `autonomous_config.json`, then export your classifier API key (`JEV_API_KEY` for TypeSafe Jev or `GEMINI_ROUTER_API_KEY` for Google Gemini Flash-Lite).

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

## 🛠 Built-in Slash Commands

* `/status` — View current session, engine status, sliding buffer depth, and whitelist info.
* `/stop` — Preemptively terminate in-flight agent tasks immediately.
* `/new` or `/clear` — Reset session and clear sliding context buffer.
* `/help` — Display help information.

---

## 📄 License

Distributed under the [MIT License](LICENSE).
