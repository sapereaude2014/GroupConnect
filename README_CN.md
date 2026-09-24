<h1 align="center">GroupConnect</h1>

<p align="center">
  <b>把群聊连接到本地 CLI Agent 及其工作区。</b><br>
  连接 Telegram、Discord、Slack、飞书、企业微信；适配 Claude Code、Antigravity、Codex、OpenCode、TeleAgent。
</p>

<p align="center">
  <a href="README.md"><b>English</b></a> | <a href="README_CN.md"><b>中文文档</b></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License" />
  <img src="https://img.shields.io/badge/python-3.10+-green.svg" alt="Python" />
  <img src="https://img.shields.io/badge/dependency-httpx_only-brightgreen.svg" alt="Zero Bloat" />
  <img src="https://img.shields.io/badge/security-默认安全锁定-brightgreen.svg" alt="Security" />
  <img src="https://img.shields.io/badge/channels-Telegram_|_Discord_|_Slack_|_Feishu_|_WeCom-blue.svg" alt="Supported Channels" />
  <img src="https://img.shields.io/badge/harness-Claude_|_Antigravity_|_Codex_|_OpenCode_|_TeleAgent-orange.svg" alt="Supported Harnesses" />
</p>

---

## 💬 全新免@自主感知体验

在真实群聊中，大家自然讨论，不需要手动 `@bot`：

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

> **全程没有人 `@AI`，没有人重写 Prompt。助理通过自主感知引擎读懂了群聊上下文，在无需 `@` 的情况下自适应判断接单，并直接更新了本地工作区文件。**

---

## ✨ 核心特性

- **多级过滤与免 @ 智能调度（按需唤醒，零算力浪费）**：
  群消息经过两级前置过滤，只在真正需要时才唤醒重型本地 Agent：
  - **第一级 · 规则与别名毫秒直判（0 Token）**：自动过滤“好的/收到”等日常附和；识别显式 `@` 或直呼 Bot 别名（如“管家，算下账”）时毫秒级直接命中目标 Bot，无需调用分类器；
  - **第二级 · 轻量分类器精准分流（~200ms）**：未点名的群聊消息由轻量模型（默认 Jev，支持 `openai` / `anthropic` / `gemini`）结合上下文与各 Bot 职责（`role`）裁决——真人闲聊自动静默、专职任务或指派语义（“A 让 B 去查” → 仅唤醒 A）**单点派单**、跨领域问题（“你俩都看看”）多 Bot **并联会诊**。
- **异构多 Agent 混编与独立人设**：
  同一群组或跨平台可同时挂载多个本地 CLI Agent（自由混用 `Claude Code`、`Antigravity`、`Codex`、`OpenCode`、`TeleAgent`），每个 Bot 加载独立人设文件（`souls/{username}.md`），协同读写本地工作区。
- **本地脚本直连与自定义指令（绕过 AI）**：
  - **自然语言直连脚本 (`pattern_commands`)**：说“开卧室灯”等固定短句，正则命中后毫秒级直接执行本地脚本，完全不经过大模型；
  - **自定义 `/指令` 与定时广播 (`custom_commands`)**：将备份、巡检等脚本注册为群聊 `/` 菜单命令（如 `/backup`），支持前置健康检查、防并发锁与定时自动执行广播。
- **工作区文件闭环与默认安全锁定**：
  - **双向文件与断线补发**：群内图片、语音、文档自动落盘工作区供 Agent 读取，Agent 生成的文件通过 `【SendFile: /path】` 自动回传群聊，超长回复自动折叠或转 Telegraph；重启后**自动补发断线期间漏接的消息**；
  - **白名单锁定与进程强控**：默认拦截一切未授权群组与用户，支持配置热重载；群内发送 `/stop` 立即强杀底层 Agent 进程树。

---

## 🌐 平台支持

| 平台 | 静默上下文与免@ | 必需配置 |
| :--- | :--- | :--- |
| **Telegram** | 🌟 完整支持 | @BotFather 中 `/setprivacy → Disable` |
| **Discord** | 🌟 完整支持 | 开启 `Message Content Intent` |
| **Slack** | 🌟 完整支持 | 开启 Socket Mode 并订阅 `message.channels` / `message.groups` |
| **飞书** | 🌟 完整支持 | 申请 `im:message.group_msg` 权限 |
| **企业微信** | ⚠️ 仅限 @ | 企微协议不下发未 @ 的群消息 |

---

## 🚀 快速上手

```bash
git clone https://github.com/sapereaude2014/GroupConnect.git
cd GroupConnect
pip install -e .
groupconnect init      # 交互式 5 步初始化
groupconnect doctor    # 启动前一键体检
groupconnect run       # 运行（Ctrl+C 停止）
```

<details>
<summary>📦 <b>生产环境守护配置 (nohup / Systemd / Supervisor)</b>（点击展开）</summary>

- **快速后台运行**：
  ```bash
  nohup groupconnect run > groupconnect.log 2>&1 &
  ```

- **Systemd** (`/etc/systemd/system/groupconnect.service`)：
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

- **Supervisor** (`/etc/supervisor/conf.d/groupconnect.conf`)：
  ```ini
  [program:groupconnect]
  command=groupconnect run
  directory=/path/to/workspace
  user=your_user
  autostart=true
  autorestart=true
  startsecs=5
  ```
</details>

---

## ⚙️ 配置说明

运行 `groupconnect init` 可交互式生成配置，或直接复制参考模板：

```bash
cp groupconnect.example.yaml groupconnect.yaml
cp .env.example .env
```

- **完整配置与全参数注释**：详见 [`groupconnect.example.yaml`](groupconnect.example.yaml)（涵盖多 Bot 协同、本地 Agent 绑定、自定义斜杠命令、自然语言脚本直连、Zero-@ 分类器与安全白名单）。
- **环境变量与密钥列表**：详见 [`.env.example`](.env.example)。

---

## 🛠 内置指令

| 指令 | 说明 |
|---|---|
| `/status` | 查看会话、引擎、缓存与白名单状态 |
| `/stop` | 即时打断正在执行的 Agent 任务 |
| `/new` `/clear` | 重置会话与上下文 |
| `/help` | 查看使用指南与已注册命令 |

---

## 📄 开源许可证

本项目基于 [MIT License](LICENSE) 开源。
