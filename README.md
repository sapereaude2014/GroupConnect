# GroupConnect

<p align="center">
  <b>A Group-Context Gateway for Local CLI Agents (Claude Code, Antigravity, Codex, OpenCode)</b><br>
  Connect your group chats to local CLI agents with silent sliding context, dynamic member security, and zero cold-start execution.
</p>

<p align="center">
  <a href="README.md"><b>English</b></a> | <a href="README_CN.md"><b>中文文档</b></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License" />
  <img src="https://img.shields.io/badge/python-3.9+-green.svg" alt="Python" />
  <img src="https://img.shields.io/badge/dependency-httpx_only-brightgreen.svg" alt="Zero Bloat" />
  <img src="https://img.shields.io/badge/channels-Telegram_|_Discord_&_Feishu_Planned-blue.svg" alt="Channels" />
  <img src="https://img.shields.io/badge/harness-Claude_|_Antigravity_|_Codex_|_OpenCode-orange.svg" alt="Supported Harnesses" />
</p>

---

## 📖 Overview

**GroupConnect** is a lightweight, decoupled gateway designed for group-native AI collaboration. It connects group messaging platforms (launching with deep Telegram support) to local CLI Agents running on your machine—including **Anthropic Claude Code (`claude`)**, **Google Antigravity (`agy`)**, **OpenAI Codex (`codex`)**, and **OpenCode (`opencode`)**.

Standard AI bots only listen to messages where they are explicitly tagged, losing the entire conversational background. GroupConnect silently maintains recent discussion context, automatically ingests media attachments into your local workspace, recognizes team members dynamically, and executes agent tasks with zero cold-start delay.

---

## 👥 Why GroupConnect?

In real-world group chats, team members discuss problems organically before calling an AI assistant:

```
┌────────────────────────────────────────────────────────────────────────┐
│ 💬 Real-World Team Chat                                                │
│                                                                        │
│ Alice: "Section 3 of the new proposal has a concurrency lock issue."   │
│ Bob:   "Right, it lacks timeouts and retries, which may deadlock."     │
│ Alice: "@bot Review the deadlock risk we discussed and update docs.md" │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
          ┌─────────────────────────┴─────────────────────────┐
          ▼                                                   ▼
❌ Standard Group Bots (Discards non-@ messages)      ✅ GroupConnect (Silent Context + Local Execution)
------------------------------------------------     ---------------------------------------------------
• "What deadlock are you referring to? Please paste   • Ingests the sliding context, invokes local tools
  the previous discussion."                             to modify `docs.md`, and reports the diff.
• User frustration from repeating context.            • Seamless and context-aware.
```

---

## ✨ Core Features (Platform-Agnostic)

* 🧠 **Silent Sliding Window**: Observes group discussions silently without spamming replies. When tagged, it automatically injects recent context (configurable depth, default 30 messages) so the agent immediately understands what the team was discussing.
* 👥 **Dynamic Member Access Control**: Authenticate users effortlessly by `@username` or automatically grant DM access to active members of authorized groups via dynamic membership checks.
* 📎 **Automatic Multimodal Inbox**: Photos, voice notes, and documents sent in chat are automatically downloaded to `inbox/attachments/` in your workspace and passed as absolute local paths for native visual and file tools.
* 🔥 **Zero Cold-Start Worker Pool**: Maintains persistent agent subprocesses to eliminate startup latency and preserve multi-turn conversational memory.
* ⏹️ **Instant `/stop` Interruption**: If an agent enters an unwanted loop or you need to abort a command immediately, sending `/stop` preemptively terminates the active process tree without waiting for locks.

---

## 🌐 Platform Channel Integrations

### 🟢 Telegram Channel (Built-in)
* **Auto-Leave Protection (`leaveChat`)**: Immediately leaves unauthorized groups if dragged in by strangers to protect local workspace files.
* **Smart Long-Message Splitting**: Gracefully splits responses exceeding Telegram's 4096-character limit along paragraph boundaries without cutting code blocks or words in half.
* **Markdown Fallback Protection**: Automatically strips formatting and retries as clean text if unclosed Markdown tags trigger Telegram parsing errors, guaranteeing 100% message delivery.
* **Telegraph Instant View**: Converts long-form research reports into zero-authentication Telegraph pages for 0-second native popup reading on mobile.

### 🟡 Planned Channels
* **Discord**: Rich Embed cards, thread-based conversation isolation.
* **Feishu / Lark**: Interactive cards and cloud document attachments.

---

## 🧩 Supported CLI Agents

| Engine (`engine_type`) | Binary Command | Features |
| :--- | :--- | :--- |
| `claude` | `claude -p` | Official Anthropic Claude Code CLI with session resumption |
| `antigravity` (default) | `agy` | High-performance full-duplex `stream-json` resident worker pool |
| `codex` | `codex exec` | OpenAI Codex CLI non-interactive execution with image attachment support |
| `opencode` | `opencode run` | OpenCode CLI headless automation and multi-turn session handling |

---

## 🚀 Quick Start (3 Steps)

### 1. Install

Requires Python 3.9+ and `httpx` (no heavy database required):

```bash
git clone https://github.com/sapereaude2014/GroupConnect.git
cd GroupConnect
pip install -r requirements.txt
```

Ensure your chosen CLI agent (e.g., `claude`, `agy`, `codex`, or `opencode`) is installed and authenticated locally.

### 2. Configure (Interactive Wizard)

Run the interactive setup wizard:

```bash
python3 -m groupconnect.cli --init
```

The wizard will prompt for your Telegram Bot Token (from `@BotFather`), your preferred CLI agent, and your local workspace directory, generating `config.json` in seconds.

*(Or copy `config.example.json` to `config.json` and edit it manually).*

### 3. Run

**Foreground (for development & testing)**:
```bash
python3 -m groupconnect.cli --config config.json
```

**Background Daemon (auto-restarts on crash for 24/7 reliability)**:
```bash
./scripts/daemon.sh config.json groupconnect.log groupconnect.pid
```

---

## ⚙️ Configuration Reference

| Parameter | Category | Default | Description |
| :--- | :--- | :--- | :--- |
| `platform` | Channel | `"telegram"` | Messaging platform (`"telegram"`) |
| `bot_token` | Channel | `""` | Telegram Bot API Token |
| `engine_type` | Engine | `"antigravity"` | Agent backend (`"antigravity"`, `"claude"`, `"codex"`, `"opencode"`) |
| `workspace_dir` | Core | `"./workspace"` | Target local directory for agent operations and inbox |
| `max_history_len` | Core | `30` | Number of recent group messages to track in sliding buffer |
| `timeout_secs` | Core | `180` | Maximum execution timeout per turn in seconds |
| `session_idle_timeout_mins` | Core | `30` | Minutes of inactivity before recycling warm worker processes |
| `max_chunk_size` | Channel | `3800` | Safe message chunk size to prevent platform character limit errors |
| `allowed_chat_ids` | Security | `[]` | Whitelisted Group Chat IDs (auto-leaves unlisted groups) |
| `allowed_user_ids` | Security | `[]` | Whitelisted Telegram User IDs for direct messaging |
| `allowed_usernames` | Security | `[]` | Whitelisted Telegram `@usernames` for direct messaging |

---

## 🛠 Built-in Slash Commands

* `/status` — View current session, engine status, sliding buffer depth, and authorization state.
* `/stop` — Preemptively interrupt in-flight agent tasks immediately.
* `/new` or `/clear` — Reset session and clear sliding context buffer.
* `/help` — Display help information.

---

## 📂 Workspace Templates (Optional)

Ready-to-use workspace presets are provided in [`templates/`](templates/):
* 🏡 **Family Assistant ([`templates/family_assistant/`](templates/family_assistant/))**: Family ledger rules, document archiving, and Telegraph publishing.
* 💼 **Team Ops Assistant ([`templates/team_ops_assistant/`](templates/team_ops_assistant/))**: Agile standup summaries, issue tracking, and discussion digestion.

---

## 📄 License

Distributed under the [MIT License](LICENSE).
