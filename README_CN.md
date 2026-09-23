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
               │  │ (TypeSafe Jev / 通用LLM)│  │
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
- **听得懂组合协同**：说“`助手 A 和助手 B 都来看看这个方案`”，被点名的多台机器人自动一起接单，各自发挥专长共同解答。

### 3. 🧠 真正的群聊记忆中枢（断点秒级续聊 + 多模态落盘）
- **断点秒级恢复**：后台常驻维护群聊滑动窗口，即使服务重启也能毫秒级恢复记忆，无缝连续追问；
- **图片与单据自动落盘**：发到群里的照片、发票、单据自动保存至本地工作区，CLI Agent 可以直接读取本地物理路径进行精准分析与沉淀；
- **零冷启动延迟**：保持后台进程温热，执行即时响应。

### 4. 🛡️ 安全第一与毫秒级即时打断
- **默认安全锁定 (Default-Deny)**：严格白名单机制，未授权成员无论怎么呼叫都无法执行本地命令；
- **一键即时打断 (`/stop`)**：任务执行过程中随时发送 `/stop` 毫秒级强杀进程树，安全尽在掌握。

### 5. ⚡ 毫秒级极速响应与 0 额外 Token 成本
- **单点裁决 + 本地广播**：单个主 Bot 进程裁决后通过本地极速 IPC 广播，多个 Bot 协同也仅调用一次判决模型，不花冤枉钱；
- **双模决策引擎架构**：默认支持 **TypeSafe Jev** 专用判别式小模型（100~200ms 极低延迟，输出 Token 永久免费），同时原生兼容任意 **通用大模型 (`OpenAI` / `DeepSeek` / `Qwen` / `Gemini` / `Claude`)**；
- **开箱即用与配置热加载**：噪音拦截、接话延续、主从/并行拆解等通用法则已全部内置；只需在 `groupconnect.yaml` 中声明机器人的 `role` 与 `aliases` 即可工作，支持按需通过 `zero_at.rules` 微调特定群规并秒级热生效。

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

本项目无需数据库，仅需 Python 3.10+ 及核心轻量依赖：

```bash
git clone https://github.com/sapereaude2014/GroupConnect.git
cd GroupConnect
pip install -e .
```

确保你的 CLI Agent（如 `claude`、`agy`、`codex` 或 `opencode`）已在本地安装并完成鉴权。

### 2. 交互式初始化向导

运行全新 5 步精炼向导：

```bash
groupconnect init
```

向导会自动探测本地已安装的 Agent 引擎、即时向 Telegram API 校验 Token 连通性、检测 Group Privacy Mode 状态，并自动生成开箱即用、仅 10 余行的 `groupconnect.yaml`。

### 3. 环境一键体检 (Doctor)

在启动前，运行内置诊断工具排查任何权限或网络隐患：

```bash
groupconnect doctor
```
系统将自动检测 Python 环境、Bot API 连通性、Telegram Privacy Mode 设置、Agent 登录鉴权状态、工作区读写权限以及 Zero-@ 决策引擎延迟，并为异常项提供精准的一键修复命令。

### 4. 运行服务

**前台运行**：
```bash
groupconnect run
```

**本地终端模拟沙盒 (无需发群消息即可测试 Zero-@ 决策)**：
```bash
groupconnect test
```

**后台守护运行 (自动崩溃重启与状态管理)**：
```bash
# 启动守护进程 (自动读取 groupconnect.yaml 与关联环境变量)
bash scripts/daemon.sh start

# 查看服务状态与日志
bash scripts/daemon.sh status

# 停止守护进程
bash scripts/daemon.sh stop
```

---

## ⚙️ 统一配置文件：`groupconnect.yaml`

初次运行 `groupconnect init` 生成的极简配置（覆盖 90% 以上的使用场景）：

```yaml
# 1. 聊天平台 (支持 telegram, discord, slack, feishu, wecom)
channel:
  platform: telegram
  token: ${TELEGRAM_BOT_TOKEN}  # 支持从环境变量注入或直接明文

# 2. 本地执行 Agent
agent:
  engine: codex                 # 支持: codex, claude, antigravity, opencode, teleagent
  workspace: ~/workspace        # 本地挂载的工作目录

# 3. 智能免 @ (Zero-@ 自动插话)
zero_at:
  enabled: true                 # 默认开箱即用，内置 4 秒静默防抢答与通用意图路由
  api_key: ${JEV_API_KEY}       # 留空则自动读取环境变量 JEV_API_KEY
```

---

## 🧩 进阶功能 (Advanced Topics)

### 1. 多 Bot 协同运行 (Multi-Bot Collaboration)

在同一个群聊中协同部署多个专职 Bot 时，无需手工配置复杂的 IPC 管道或分别启动多个进程，直接在 `groupconnect.yaml` 中通过 `bots` 列表声明即可：

```yaml
channel:
  platform: telegram

bots:
  - name: coder_bot
    token: ${CODER_BOT_TOKEN}
    agent: codex
    role: "负责代码编写、重构与 Bug 修复"
    aliases: ["码农", "coder"]

  - name: reviewer_bot
    token: ${REVIEWER_BOT_TOKEN}
    agent: claude
    role: "负责架构设计、代码审查与安全合规"
    aliases: ["评审", "reviewer"]

zero_at:
  enabled: true
```

运行 `groupconnect run` 时，系统将自动在同一进程事件循环中并发运行所有 Bot，并自动选举首个 Bot 为决策裁决官（Arbiter），通过内部事件总线协作分发、绝不抢话。如需在独立进程中运行指定 Bot，只需添加 `--bot <name>` 参数（如 `groupconnect run --bot coder_bot`）。

### 2. 分类器引擎切换与路由规则热加载 (`zero_at`)

#### A. 切换分类器引擎 (`zero_at.classifier`)
默认使用 **TypeSafe Jev** 极速判别式模型（`engine: jev`）。你也可以切换为任意通用大模型（支持 OpenAI 兼容接口如 DeepSeek / Qwen / 本地 Ollama、Google Gemini 或 Anthropic Claude）：

```yaml
zero_at:
  enabled: true
  classifier:
    engine: llm                           # 可选: jev (默认) | llm | openai | gemini | anthropic
    model: deepseek-chat                  # 如 jev-latest, gpt-4o-mini, deepseek-chat, gemini-2.5-flash-lite
    base_url: https://api.deepseek.com/v1 # 通用 OpenAI 兼容接口地址 (使用官方 OpenAI/Gemini/Claude 时可省略)
    api_key: ${DEEPSEEK_API_KEY}
```

#### B. 按需微调群聊路由边界 (`zero_at.rules`)

通用对话法则（噪音过滤、昵称调侃防误触、对话延续、根据 `role` 职责自动匹配、主从调度与并行协同）**已在代码底座中全部内置生效，95% 场景无需额外配置**。

如果群聊有特殊约定（例如特定群背景说明或特殊的闲聊过滤边界），可直接在 `groupconnect.yaml` 中按需覆写对应维度（未声明的维度自动继承内置默认规则，保存文件即自动热加载）：

```yaml
zero_at:
  enabled: true
  rules:
    group: "研发团队内部协作群，配置了多名专职助手"
    drop: "群成员之间的日常寒暄、玩笑打趣或与助手职责无关的话题"
    # immediate: "回复 {bot} 刚才的提问，或匹配其职责的直接指令：{role}"
    # wait: "需要查询数据、知识或客观建议，且匹配职责：{role}"
    # parallel: "发送者明确要求 {bot} ({role}) 与其他助手同时回答"
```

---

## 🛠 斜杠指令与自定义扩展

### 内置通用指令
* `/status` — 查看当前会话状态、常驻进程运行状态、群缓存深度与白名单信息；
* `/stop` — 即时打断当前正在执行的 Agent 任务；
* `/new` 或 `/clear` — 重置当前会话并清空群聊滑动缓存；
* `/help` — 查看使用指南与已注册的自定义命令。

### 声明式自定义指令与定时任务 (`custom_commands`)
支持在 `groupconnect.yaml` 中声明自定义运维脚本与后台定时任务。启动时网关会自动向平台菜单（如 Telegram API `setMyCommands`）同步各实例专属指令：

```yaml
custom_commands:
  - command: backup
    description: "执行工作区资产备份脚本"
    description_en: "Trigger workspace backup script"
    script: "scripts/backup.sh"
    ack_message: "📦 [{bot_name}] 正在执行备份任务，请稍候..."
    success_message: "✅ [{bot_name}] 备份已完成（耗时 {duration}s）。"
    error_message: "❌ [{bot_name}] 备份失败 (Exit {returncode}): {stderr}"
    lock: true
    arbiter_only_on_broadcast: true
    schedule:
      weekday: 6
      hour: 4
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
