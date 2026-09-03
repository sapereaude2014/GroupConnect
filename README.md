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

## 💬 The Experience

In real-world group chats, discussions happen organically before anyone calls an AI assistant:

```text
Alice: "Hiking this Saturday?"
Bob:   "Sure, I can drive."
Carol: "Let's meet at 8:00 AM then?"
Alice: "@AI Please take note of this in our schedule."

AI:    "Got it, recorded in schedule.md:
       • Event: Hiking trip
       • Time: Saturday 08:00 AM
       • Transportation: Bob will drive"
```

> **No one wrote a lengthy prompt. No one copied and pasted chat history. The AI simply read what just happened in the chat and updated the workspace.**

---

## 🎯 Standard Bots vs GroupConnect

```text
❌ Standard Group Bots (Discards non-@ messages)
Team chatting ───(Discarded)───> Context Lost ───(@AI tagged)───> "What were you talking about?"

✅ GroupConnect (Silent Context + Local Workspace Execution)
Team chatting ───(Silent Sliding Window)───> Context Captured ───(@AI tagged)───> Updates Local Files
```

Local CLI agents like **Anthropic Claude Code (`claude`)**, **Google Antigravity (`agy`)**, **OpenAI Codex (`codex`)**, and **OpenCode (`opencode`)** run on your machine with full access to your local files and tools.

**GroupConnect packages this connection and context logic into a ready-to-use lightweight runtime:**

```text
                 Group Chat (Natural Discussion)
                               │
                               ▼
                     ┌──────────────────┐
                     │   GroupConnect   │
                     │  Context Capture │
                     │  Agent Invocation│
                     └────────┬─────────┘
                              │
                              ▼
                       Local CLI Agent
               (Claude / Antigravity / Codex)
                              │
                     ┌────────┴────────┐
                     │                 │
                     ▼                 ▼
                Direct Reply       Workspace (Persistent Assets)
                                       │
                              ┌────────┼────────┐
                              ▼        ▼        ▼
                            Tasks    Docs    History
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

### 2. Templates (Workspace Reference Setups)
*Note: Templates are purely optional reference implementations. GroupConnect imposes zero restrictions on your workspace structure.*

Reference presets in [`templates/`](templates/) demonstrate how to organize local directories when turning a group chat into an ongoing workspace:
* 🏡 **[Family Assistant](templates/family_assistant/)**: Turning a family chat into a persistent ledger for health records, assets, and memory guidelines.
* 💼 **[Team Ops Assistant](templates/team_ops_assistant/)**: Turning a dev team chat into an active workspace for sprint tracking, incident SOPs, and searchable monthly JSONL archives.

---

## 🌐 Platform Context Matrix

| Platform (`platform`) | Status | Required Setting for Silent Group Context | Context Support |
| :--- | :--- | :--- | :--- |
| **`telegram`** | 🟢 Built-in | Set `/setprivacy -> Disable` in `@BotFather`. | 🌟 Full (No public IP needed) |
| **`discord`** | 🟢 Built-in | Enable `Message Content Intent` in Discord Developer Portal. | 🌟 Full (REST & Webhook) |
| **`slack`** | 🟢 Built-in | Subscribe to `message.channels` and `app_mention` in Slack App. | 🌟 Full (Events API) |
| **`feishu`** (Lark) | 🟢 Built-in | Request `im:message.group_msg` permission in Feishu Developer Console. | 🌟 Full (Requires Webhook) |
| **`wecom`** (WeChat Work) | 🟢 Built-in | **None (Unsupported)**: WeChat protocol does not push unmentioned group messages. | ⚠️ Mention-only |

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

---

## 🛠 Built-in Slash Commands

* `/status` — View current session, engine status, sliding buffer depth, and whitelist info.
* `/stop` — Preemptively terminate in-flight agent tasks immediately.
* `/new` or `/clear` — Reset session and clear sliding context buffer.
* `/help` — Display help information.

---

## 📄 License

Distributed under the [MIT License](LICENSE).
