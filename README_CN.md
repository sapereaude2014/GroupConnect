<h1 align="center">GroupConnect</h1>

<p align="center">
  <b>把群聊连接到本地 CLI Agent 及其工作区。</b><br>
  （连接 Telegram、Discord、Slack、飞书 Feishu、企业微信 WeCom；适配 Claude Code、Antigravity、Codex、OpenCode）
</p>

<p align="center">
  <a href="README.md"><b>English</b></a> | <a href="README_CN.md"><b>中文文档</b></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License" />
  <img src="https://img.shields.io/badge/python-3.9+-green.svg" alt="Python" />
  <img src="https://img.shields.io/badge/dependency-httpx_only-brightgreen.svg" alt="Zero Bloat" />
  <img src="https://img.shields.io/badge/security-默认安全锁定-brightgreen.svg" alt="Security" />
  <img src="https://img.shields.io/badge/channels-Telegram_|_Discord_|_Slack_|_Feishu_|_WeCom-blue.svg" alt="Supported Channels" />
  <img src="https://img.shields.io/badge/harness-Claude_|_Antigravity_|_Codex_|_OpenCode-orange.svg" alt="Supported Harnesses" />
</p>

---

## 💬 全新免@自主感知体验 (Zero-@ Experience)

在真实群聊中，大家总是自然讨论，无需机械化地输入指令，更不需要频繁手动 `@bot`：

```text
Alice:  "周六去爬山吧？"
Bob:    "可以，我负责开车。"
Carol:  "那就早上八点集合？"
Alice:  "谁来把行程记到日程里"

助理:   "已更新至 schedule.md：
        • 事项：周末爬山
        • 集合时间：周六 08:00
        • 车辆安排：Bob 负责开车"
```

> **注意：全程没有人手动 `@AI`，没有人重新写 Prompt，更没有复制粘贴聊天记录。助理通过自主感知引擎自动读懂了群聊上下文，在无需 `@` 的情况下自适应判断接单，并直接更新了本地工作区文件。**

---

## 🎯 传统 Bot vs GroupConnect

```text
❌ 传统群聊 Bot (依赖手动@、孤立无上下文、被唤醒时茫然不知所措)
群成员日常讨论 ───(未@直接丢弃)───> 丢失前文 ───(必须@Bot唤醒)───> "请问你们刚才在聊什么？"

✅ GroupConnect (免@自主感知 + 静默滑窗 + 本地工作区执行)
群成员日常讨论 ───(滑窗缓冲 + 语义裁决官)───> 意图自主识别 (Zero-@) ───> 智能唤醒并修改本地文件
```

像 **Anthropic Claude Code (`claude`)**、**Google Antigravity (`agy`)**、**OpenAI Codex (`codex`)** 和 **OpenCode (`opencode`)** 这类本地 CLI Agent 非常强大，因为它们能直接在你的电脑上读写文件、执行脚本。

**GroupConnect 将通道连接、静默上下文缓冲与免@自主感知融为一体，提供开箱即用的轻量级运行时：**

```text
                 群聊 (自然讨论流)
                         │
                         ▼
               ┌───────────────────────────────┐
               │         GroupConnect          │
               │  ┌─────────────────────────┐  │
               │  │ 静默群聊滑窗上下文       │  │
               │  └────────────┬────────────┘  │
               │               ▼               │
               │  ┌─────────────────────────┐  │
               │  │ 免@自主感知裁决官 (IPC) │  │
               │  │ (TypeSafe Jev / Gemini) │  │
               │  └────────────┬────────────┘  │
               └───────────────┼───────────────┘
                               │ (免@感知唤醒 或 直接呼叫)
                               ▼
                        本地 CLI Agent
                 (Claude / Antigravity / Codex)
                               │
                      ┌────────┴────────┐
                      │                 │
                      ▼                 ▼
                 即时回答           工作区 (长期资产沉淀)
                                        │
                               ┌────────┼────────┐
                               ▼        ▼        ▼
                             任务看板  业务文档  本地自动化
```

---

## 🧱 双层架构设计：Core 与 Templates

> **群聊提供上下文，Agent 负责行动，Workspace 负责沉淀结果。**

GroupConnect 严格区分 **连接层机制（Core）** 与 **工作区组织参考（Templates）**：

### 1. Core（群聊 ➔ 上下文 ➔ Agent）
* **静默滑动窗口与重启回放**：后台维护最近 $N$ 条（默认 30 条）群聊记录，服务重启时毫秒级自动从本地 JSONL 日志中回放恢复滑动窗口，连续追问时仅同步增量新消息；
* **零冷启动进程池**：保持后台进程温热，消除启动延迟并保留多轮会话记忆；
* **多模态附件自动落盘**：群聊照片、单据自动存入 `workspace/inbox/attachments/` 并提供绝对物理路径；
* **即时打断 (`/stop`)**：不排队等待，毫秒级直接强杀当前运行的 Agent 任务树；
* **默认安全锁定 (Default-Deny)**：白名单为空时自动进入锁定模式，杜绝未经授权的 Shell 执行风险；
* **免@自主感知唤醒 (Autonomous Routing)**：单点裁决官 + 跨进程 IPC 广播架构。多 Bot 协同下无需每次手打 `@`，通过三级感知管线（L0 物理降噪 ➔ L1 别名直通 ➔ L2 语义判决）智能研判该不该回、由谁回，原生支持 **TypeSafe Jev**（百毫秒级决策模型，输出 Token 永久免费）与 **Google Gemini Flash-Lite**，配合双段计时窗口（1s 即时 / 4s 留白）与真人插话动态抢断。

### 2. Templates（工作区组织参考）
> *注：Templates 并非 GroupConnect 的必需组件，GroupConnect 对你的工作区目录结构不做任何强行规定。模板仅作为展示同一机制在不同场景下的最佳实践参考。*

[`templates/`](templates/) 目录下提供了两套开箱即用的参考实现：
* 🏡 **[家庭管家模板 (family_assistant)](templates/family_assistant/)**：展示如何将家庭群聊转化为健康档案、资产记录与记忆守则的沉淀空间；
* 💼 **[团队助理模板 (team_ops_assistant)](templates/team_ops_assistant/)**：展示如何将研发群聊转化为敏捷任务看板、故障 SOP 与按月归档历史搜索工具。

---

## 🤖 免@自主感知唤醒与多 Bot 协同 (Autonomous Routing)

在自然的群聊沟通中，每次都要手动 `@bot` 会极大地割裂交流体验。GroupConnect 内置了 **免@自主感知路由引擎**，支持多个专职 Bot 在群内静默感知，并在适当时机精准唤醒：

```text
群消息流入
   │
   ├─ L0: 物理降噪层 (0-Token)
   │      纯标点、纯表情、单字确认语 ("收到", "好的", "ok") -> 直接丢弃静默
   │
   ├─ L1: 别名直通层 (0-Token)
   │      单一别名命中 ("管家", "助理") -> 秒级直通唤醒
   │      多别名同时出现 -> 延迟送交 L2 (区分主使调度与并联协同语义)
   │      (内置自称/附和正则过滤网，杜绝自称和复读误触)
   │
   └─ L2: 小模型三态判决层 (单点裁决官调用)
          结合近期上下文滑窗，通过 TypeSafe Jev 或 Gemini Flash-Lite 判定：
          • 回复 Bot 提问/选项 -> 提问 Bot 接单 (1.0s 即时窗口)
          • 群成员日常闲聊/倾诉 -> 全员静默 (Drop)
          • 明确祈使指令 -> 专职 Bot 接单 (1.0s 即时窗口)
          • 开放客观疑问/推荐 -> 专职 Bot 接单 (4.0s 留白窗口)
          • 多智能体协同或指派 -> 区分主使调度 (仅调度者接单) 与并联协同 (全员齐答 immediate)
```

* **单点判决 + 对称执行 (Single-Arbiter)**：仅由单个指定的主 Bot 进程调阅轻量模型进行裁决，并通过本地 Unix Domain Socket (`CrossBotRelay`) 将裁决广播给同行 Bot。杜绝多次重复调用模型，成本与延迟最低；
* **双段窗口与真人抢断 (Human Preemption)**：明确指令 1.0 秒即时派发；客观提问预留 4.0 秒静默期（留足人类成员先相互回答的社交空间）。若在等待期内有人类成员发言接话，Bot 的回复计划立即熔断取消，绝不抢戏；
* **可插拔判决引擎（自描述注册表）**：开箱即用支持专为分类判断打造的 **TypeSafe Jev**（System-One 模型，70~500ms 极低延迟，输出 Token 永久免费），亦支持配置 **Google Gemini Flash-Lite** 作为备援后端。`classifier` 块为 provider 注册表结构：`active` 一行即总开关，`providers` 下每个后端条目自带 `engine`（`jev` 结构化 / `gemini` 自由文本 JSON）、模型、密钥与专属资源（`prompt_template` 仅归属 gemini 引擎）；
* **业务规则与代码完全解耦**：所有别名、职责定位、分类器注册表与名单完全外置于 `autonomous_config.json`，共享判决文案存放于 `rules_file` 单一事实源、全部引擎共用（参见参考配置 [`autonomous_config.example.json`](autonomous_config.example.json)），零代码侵入。

---

## 🌐 平台通道上下文权限与限制

| 平台类型 (`platform`) | 实现状态 | 静默群上下文必需配置 | 静默上下文与免@自主支持 |
| :--- | :--- | :--- | :--- |
| **`telegram`** | 🟢 已内置 | 在 `@BotFather` 中执行 `/setprivacy` 设为 `Disable`。 | 🌟 完整支持（支持免@自主感知唤醒） |
| **`discord`** | 🟢 已内置 | 在 Discord 开发者后台开启 `Message Content Intent` 特权。 | 🌟 完整支持（支持免@自主感知唤醒） |
| **`slack`** | 🟢 已内置 | 在 Slack App 中订阅 `message.channels` 与 `app_mention` 事件。 | 🌟 完整支持（支持免@自主感知唤醒） |
| **`feishu`** (飞书) | 🟢 已内置 | 在飞书开放平台申请 `im:message.group_msg`（获取群组所有消息）权限。 | 🌟 完整支持（支持免@自主感知唤醒） |
| **`wecom`** (企业微信) | 🟢 已内置 | **无（无法获取）**：微信官方协议严格限制，不下发群内未 `@` 的消息。 | ⚠️ 仅限 `@` 提问（无法开启免@感知） |

---

## 🚀 30 秒极速上手

### 1. 安装

本项目无需数据库，仅需 Python 3.9+ 及 `httpx`：

```bash
git clone https://github.com/sapereaude2014/GroupConnect.git
cd GroupConnect
pip install -e .
```

确保你的 CLI Agent（如 `claude`、`agy`、`codex` 或 `opencode`）已在本地安装并完成鉴权。

### 2. 初始化配置

运行交互式配置向导：

```bash
groupconnect --init
```

向导会引导你选择接入平台和凭证，自动保存为 `config.<platform>.json`（例如 `config.telegram.json`）。

### 3. 运行服务

**前台调试运行**：
```bash
groupconnect -c config.telegram.json
```

**后台守护运行 (自动崩溃重启与状态管理)**：
```bash
# 启动指定服务
bash scripts/daemon.sh start config.telegram.json

# 查看所有运行中的机器人服务
bash scripts/daemon.sh status

# 停止指定服务
bash scripts/daemon.sh stop config.telegram.json
```

### 4. 开启免 `@` 自主感知唤醒 (可选)

无需在群内手动 `@Bot`，让机器人结合上下文自动感知意图并智能回复：

1. **配置感知规则模板**：
   ```bash
   cp autonomous_config.example.json autonomous_config.json
   cp router_prompt.example.txt router_prompt.txt
   cp routing_rules.example.md routing_rules.md
   ```
   在 `autonomous_config.json` 中配置别名（`aliases`）与职责描述（`roles`），将 `classifier.rules_file`（默认 `routing_rules.md`）指向共享判决文案并按本群实际改写。`classifier` 块为自描述注册表：`active` 一行即总开关，`providers` 下各后端自带 `engine`、模型、密钥与所属文件（`prompt_template` 仅归属 gemini 引擎），切换后端改一行 `active` 即可，热加载零重启。

2. **重启服务生效**：
   ```bash
   bash scripts/daemon.sh restart config.telegram.json
   ```
   重启后，机器人将自动运行三级感知管线（L0 降噪 ➔ L1 别名直通 ➔ L2 语义判决），结合滑动窗口智能判断是否接单回复。

### 5. 多 Bot 协同运行 (可选)

在同一群聊中部署多个专职 Bot 时，可通过本地 IPC 机制实现协同调度与防抢答：

1. **配置共享 IPC 与规则**：
   为每个 Bot 创建独立配置文件，指向相同的 `ipc_dir` 与 `autonomous_config_path`，并指定其中一个实例作为裁决官（`arbiter_bot`）：
   ```json
   // config.ops.json (裁决官实例，兼任运维/家务)
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
   // config.chat.json (从属工作实例，兼任助理/规划)
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

2. **分别启动各 Bot 服务**：
   ```bash
   bash scripts/daemon.sh start config.ops.json
   bash scripts/daemon.sh start config.chat.json
   ```
   裁决官实例单点调用判决模型，通过 Unix Socket（IPC）广播分派任务，各 Bot 依各自职责精准响应、互不抢答。

---

## 🛠 内置指令

* `/status` — 查看当前会话状态、常驻进程运行状态、群缓存深度与白名单信息；
* `/stop` — 即时停止当前正在执行的 Agent 任务；
* `/new` 或 `/clear` — 重置当前会话并清空群聊滑动缓存；
* `/help` — 查看使用帮助。

---

## 📄 开源许可证

本项目基于 [MIT License](LICENSE) 开源。
