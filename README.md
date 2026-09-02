# GroupConnect

<p align="center">
  <b>Give local CLI agents context from group chats.</b><br>
  Connect Telegram, Discord, Slack, Feishu, and WeCom to Claude Code, Antigravity, Codex, and OpenCode.
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

In real-world group chats, team members discuss organically before calling an AI assistant:

```text
Alice: "Hiking this Saturday?"
Bob:   "Sure, I can drive."
Carol: "Let's meet at 8:00 AM then?"
Alice: "@AI Please take note of this."

AI:    "Got it, recorded:
       • Event: Hiking trip
       • Time: Saturday 08:00 AM
       • Transportation: Bob will drive"
```

> **No one wrote a prompt. No one copied and pasted chat history. The AI simply read what just happened in the chat.**

---

## 🎯 Standard Bots vs GroupConnect

```text
❌ Standard Group Bots (Discards non-@ messages)
Alice / Bob chatting ───(Discarded)───> Context Lost ───(@AI tagged)───> "What were you talking about?"

✅ GroupConnect (Silent Context + Local Execution)
Alice / Bob chatting ───(Silent Sliding Window)───> Background Synced ───(@AI tagged)───> Instant Action
```

Local CLI agents like **Anthropic Claude Code (`claude`)**, **Google Antigravity (`agy`)**, **OpenAI Codex (`codex`)**, and **OpenCode (`opencode`)** run on your machine with full access to your local files and tools.

**GroupConnect is the ready-to-use connection layer bridging your group chats to your local CLI agents.**

```text
          Group Chat (Telegram / Discord / Slack / Feishu / WeCom)
                                     │
                                     ▼
                       GroupConnect (Connection Layer)
             [ Silent Sliding Window + Local Auto-Inbox + /stop ]
                                     │
                                     ▼
                       Local CLI Agent (Interchangeable)
                  ├── Anthropic Claude Code (`claude`)
                  ├── Google Antigravity (`agy`)
                  ├── OpenAI Codex (`codex`)
                  └── OpenCode (`opencode`)
                                     │
                                     ▼
                          Local Workspace & Files
```

---

## 🧱 Clean Division: Core vs Templates

GroupConnect separates **the connection layer (Core)** from **workspace organization (Templates)**:

### 1. Core (Connection Layer)
* **Silent Sliding Window & Delta Sync**: Tracks recent discussion in the background (default: 30 messages). When tagged, it injects the context and only syncs incremental messages on continuous follow-ups.
* **Zero Cold-Start Worker Pool**: Maintains warm subprocesses in the background for instant multi-turn memory without startup delay.
* **Multimodal Auto-Inbox**: Photos, voice notes, and documents sent in chat are automatically downloaded to `workspace/inbox/attachments/` and passed as absolute local paths.
* **Instant `/stop` Interruption**: Preemptively terminates active CLI agent process trees on `/stop` without waiting for queues or locks.
* **Default-Deny Security**: Safe lockdown mode by default, preventing unauthorized users from accessing your local machine.

### 2. Templates (Workspace Reference Implementations)
Reference presets in [`templates/`](templates/) demonstrate how to organize local directories when turning a group chat into an ongoing workspace:
* 🏡 **[Family Assistant](templates/family_assistant/)**: Organizing family health logs, assets, and reminders.
* 💼 **[Team Ops Assistant](templates/team_ops_assistant/)**: Organizing sprint backlogs, incident SOPs, and monthly JSONL discussion archives.

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
