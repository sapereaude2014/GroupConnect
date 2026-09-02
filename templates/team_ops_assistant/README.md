# 💼 Team Ops & Agile Assistant Workspace Template

This template turns **GroupConnect** into an autonomous DevOps & Agile Assistant for software engineering teams. Point `workspace_dir` to your repository or this directory to enable intelligent group standups, incident triage, and historical discussion recall.

---

## 🚀 Key Capabilities in Action

### 1. Discussion Digestion & Task Sync
```
Alice: "We agreed to switch to Redis Cluster for session caching."
Bob:   "I'll handle the terraform provisioning by Thursday."
Alice: "@bot Summarize our decision and add Bob's task to current_sprint.md"
```
* **Result**: The agent extracts the consensus, adds `- [ ] Provision Redis Cluster via Terraform (@bob, Due: Thu)` into `tasks/current_sprint.md`, and confirms in chat with a 3-line summary.

### 2. Historical Discussion Recall (Beyond 30-Message Sliding Window)
```
Developer: "@bot What was the staging database port Alice posted last week?"
```
* **Result**: The agent invokes `python3 tools/search_history.py --query "database port" --days 14` to search the monthly JSONL logs in `inbox/chat_logs/`, finds the message, and answers accurately.

### 3. Multimodal Bug Triage
```
Developer drops an error stack screenshot into the group:
Developer: "@bot What caused this 500 error?"
```
* **Result**: The image is automatically saved to `inbox/attachments/`, the agent inspects the stack trace, locates the failing line in the local codebase, and replies with the diagnosis and fix snippet.

---

## 📁 Directory Structure

```
├── AGENTS.md                  # System prompt and operational rules
├── README.md                  # Workspace documentation
├── docs/                      # Technical docs, architecture SOPs
│   └── architecture_sop.md    # Architecture review guidelines
├── tasks/                     # Task management boards
│   ├── current_sprint.md      # Active sprint board
│   └── backlog.md             # Feature and tech-debt backlog
├── meetings/                  # Standup minutes and discussion digests
│   └── template.md            # Standard meeting note format
├── incidents/                 # Incident triage and post-mortems
│   └── template.md            # Incident post-mortem template
├── tools/                     # Automation helper utilities
│   └── search_history.py      # Historical chat log search utility
└── inbox/                     # Auto-created by GroupConnect
    ├── attachments/           # Shared images, logs, documents
    └── chat_logs/             # Monthly JSONL discussion logs
```
