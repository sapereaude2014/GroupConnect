# GroupConnect

<p align="center">
  <b>Give CLI agents context from the group chat.</b><br>
  A lightweight, zero-bloat runtime connecting Telegram, Discord, Slack, Feishu, and WeCom to Claude Code, Antigravity, Codex, and OpenCode.
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

In real group chats, discussions happen organically before anyone calls an AI:

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

> **No one wrote a prompt. No one copied and pasted history. The AI simply read what just happened in the chat.**

---

## 🎯 What is GroupConnect?

Local CLI agents like **Anthropic Claude Code (`claude`)**, **Google Antigravity (`agy`)**, **OpenAI Codex (`codex`)**, and **OpenCode (`opencode`)** are powerful because they have full access to your local files and shell tools.

However, standard group chat bots only receive the single message where they are tagged, completely losing conversational context.

**GroupConnect is the minimal glue runtime that bridges this gap:**
1. It silently tracks recent group discussions in a lightweight sliding window.
2. When tagged, it injects the recent conversation background and invokes your local CLI agent.
3. It downloads photos, voice notes, and documents directly to your local workspace.
4. It lets you interrupt run-away agent tasks instantly with `/stop`.

```text
          Group Chat (Telegram / Discord / Slack / Feishu / WeCom)
                                     │
                                     ▼
                       GroupConnect (Lightweight Runtime)
                  [ Sliding Context + Local File Inbox + /stop ]
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

GroupConnect separates **runtime glue** from **workspace structure**:

### 1. Core (The Runtime)
* **Silent Sliding Context**: Maintains the last $N$ messages (default: 30) in memory. Syncs only incremental messages on continuous follow-ups.
* **Zero Cold-Start Worker Pool**: Keeps agent subprocesses warm in the background for instant execution and multi-turn memory.
* **Multimodal Auto-Inbox**: Photos and files sent in chat are saved to `workspace/inbox/attachments/` and passed as absolute local paths.
* **Instant `/stop`**: Preemptively kills active CLI agent process trees on `/stop` without waiting for queues or locks.
* **Secure-by-Default**: Default-deny lockdown mode prevents unauthorized users from executing commands on your machine.

### 2. Templates (How to Organize Your Workspace)
Reference templates in [`templates/`](templates/) demonstrate how to organize local directories when turning a group chat into an ongoing workspace:
* 🏡 **[Family Assistant](templates/family_assistant/)**: Organizing family health logs, assets, and reminders.
* 💼 **[Team Ops Assistant](templates/team_ops_assistant/)**: Organizing sprint backlogs, incident SOPs, and monthly JSONL discussion archives.

---

## 🌐 Platform Context Matrix

| Platform (`platform`) | Status | Required Setting for Silent Group Context | Context Support |
| :--- | :--- | :--- | :--- |
| **`telegram`** | 🟢 Built-in | Set `/setprivacy -> Disable` in `@BotFather`. | 🌟 Full (No public IP needed) |
| **`discord`** | 🟢 Built-in | Enable `Message Content Intent` in Discord Portal. | 🌟 Full (REST & Webhook) |
| **`slack`** | 🟢 Built-in | Subscribe to `message.channels` and `app_mention` in Slack App. | 🌟 Full (Events API) |
| **`feishu`** (Lark) | 🟢 Built-in | Request `im:message.group_msg` permission in Feishu Console. | 🌟 Full (Requires Webhook) |
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

Ensure your CLI agent (e.g., `claude`, `agy`, `codex`, or `opencode`) is authenticated locally.

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
# Start in background
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
