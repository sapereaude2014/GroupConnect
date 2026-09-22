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

## ✨ 核心特性：专为真实群聊打造的 Agent 体验

> **群聊负责沟通协作，Agent 负责本地行动，工作区负责沉淀资产。**

### 1. 🗣️ 免 @ 自然感知交互（像真人一样懂“读空气”）
- **告别死板的手动艾特**：群成员在群里像平常一样自然交流，机器人结合上下文自动判断该不该接单，无需机械化手打 `@机器人`；
- **闲聊私聊绝不插话**：日常吐槽、私聊交流坚决保持静默，绝不乱搭腔，杜绝机器人打扰日常私密交谈；
- **礼貌留白与真人抢断**：遇到开放性提问或探讨，预留 4 秒留白让群友先聊；一旦有人类成员接话，机器人自动取消回复，绝不抢戏。

### 2. 🤖 多助手默契配合（分工明确，告别抢话，支持团队协同）
- **各自专业各自答**：群里可以同时部署多个专职助手（例如“运维助手”监控告警，“开发助手”检索代码，“文档助手”整理日程），各司其职互不干扰；
- **听得懂主从调度**：说“`助手 A 让助手 B 去跑测试`”，只有助手 A 接单并调度，助手 B 绝不会因为听到自己名字就提前抢跑；
- **听得懂全员召集**：说“`你们两个都来看看这个方案`”，多台机器人自动一起接单，各自发挥专长共同解答。

### 3. 🧠 真正的群聊记忆中枢（断点秒级续聊 + 多模态落盘）
- **断点秒级恢复**：后台常驻维护群聊滑动窗口，即使服务重启也能毫秒级恢复记忆，无缝连续追问；
- **图片与单据自动落盘**：发到群里的照片、发票、单据自动保存至本地工作区，CLI Agent 可以直接读取本地物理路径进行精准分析与沉淀；
- **零冷启动延迟**：保持后台进程温热，执行即时响应。

### 4. 🛡️ 安全第一与毫秒级即时打断
- **默认安全锁定 (Default-Deny)**：严格白名单机制，未授权成员无论怎么呼叫都无法执行本地命令；
- **一键即时打断 (`/stop`)**：任务执行过程中随时发送 `/stop` 毫秒级强杀进程树，安全尽在掌握。

### 5. ⚡ 毫秒级极速响应与 0 额外 Token 成本
- **单点裁决 + 本地广播**：单个主 Bot 进程裁决后通过本地极速 IPC 广播，多个 Bot 协同也仅调用一次判决模型，不花冤枉钱；
- **原生支持超快免费决策模型**：开箱即用支持 TypeSafe Jev 决策模型（100~200ms 极低延迟，输出 Token 永久免费），亦支持一键配置 Google Gemini Flash-Lite 作为备援；
- **规则纯文本热加载**：所有别名、角色定义、判定规则全部写在 Markdown 和 JSON 文件中，随改随生效，零代码侵入。

---

## 🧱 架构设计参考：Core 与 Templates

GroupConnect 严格区分 **连接层机制（Core）** 与 **工作区组织参考（Templates）**：
* **Core（群聊 ➔ 上下文 ➔ Agent）**：负责平台连接、免@感知、群聊记忆、附件落盘与进程调度；
* **Templates（工作区组织参考）**：[`templates/`](templates/) 目录下提供了两套开箱即用的工作区组织参考（纯可选）：
  - 🏡 **[家庭管家模板 (family_assistant)](templates/family_assistant/)**：展示如何将家庭群聊转化为健康档案、资产记录与生活备忘的沉淀空间；
  - 💼 **[团队助理模板 (team_ops_assistant)](templates/team_ops_assistant/)**：展示如何将研发群聊转化为敏捷任务看板、故障 SOP 与按月归档搜索工具。

---

## 🌐 平台通道上下文权限与限制

| 平台类型 (`platform`) | 实现状态 | 静默群上下文必需配置 | 静默上下文与免@自主支持 |
| :--- | :--- | :--- | :--- |
| **`telegram`** | 🟢 已内置 | 在 `@BotFather` 中执行 `/setprivacy` 设为 `Disable`。 | 🌟 完整支持（支持免@自主感知唤醒；内置长文/表格自动转 Telegraph 原生卡片防刷屏） |
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

## 🛠 斜杠指令与自定义扩展

### 内置通用指令
* `/status` — 查看当前会话状态、常驻进程运行状态、群缓存深度与白名单信息；
* `/stop` — 即时打断当前正在执行的 Agent 任务；
* `/new` 或 `/clear` — 重置当前会话并清空群聊滑动缓存；
* `/help` — 查看使用指南与已注册的自定义命令。

### 声明式自定义指令与定时任务 (`custom_commands`)
支持在 `config.json` 中声明自定义运维脚本与后台定时任务。启动时网关会自动向平台菜单（如 Telegram API `setMyCommands`）同步各实例专属指令：

```json
"custom_commands": [
  {
    "command": "backup",
    "description": "执行工作区资产备份脚本",
    "description_en": "Trigger workspace backup script",
    "script": "scripts/backup.sh",
    "ack_message": "📦 [{bot_name}] 正在执行备份任务，请稍候...",
    "success_message": "✅ [{bot_name}] 备份已完成（耗时 {duration}s）。",
    "error_message": "❌ [{bot_name}] 备份失败 (Exit {returncode}): {stderr}",
    "lock": true,
    "arbiter_only_on_broadcast": true,
    "schedule": {
      "weekday": 6,
      "hour": 4
    }
  }
]
```

* **`script`**：脚本或执行程序路径（支持 `~` 路径自动展开）；
* **`pass_args`**：是否将用户指令后携带的参数追加至脚本调用；
* **`check_args` / `check_success_message`**：执行前状态探针巡检（如服务健康则直接返回状态说明，跳过完整耗时流程）；
* **`lock`**：单命令并发排他锁，杜绝重入与并发冲突；
* **`arbiter_only_on_broadcast`**：在多 Bot 协同群聊中，群内发送不带后缀的广播 `/cmd` 时仅由裁决官（Arbiter）响应，而显式带后缀的 `/cmd@bot` 精准由该 Bot 单独接单；
* **`schedule`**：可选后台周期定时调度器（如每周日凌晨 4 点），脱离外部 cron 自包含运行。

---

## 📄 开源许可证

本项目基于 [MIT License](LICENSE) 开源。
