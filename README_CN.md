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

- **免 @ 多级感知分流**：群聊中无需 `@`——喊昵称或固定短语直接响应，普通发言再由轻量小模型结合上下文判断：闲聊保持安静、专职问题精准派给对应 Bot（"A 让 B 去查" → 只叫 A）、复杂问题多 Bot 一起回（"你俩都看看"）。
- **多 Agent 混编与独立人设**：同一个群里可以同时接入 Claude Code、Antigravity、Codex、TeleAgent 等不同本地助手，各自拥有独立性格与专长，协同读写同一个工作区。
- **日常口令与定时任务直连**：像“开卧室灯”这样的固定口令或 `/backup` 菜单命令，可直接触发本地脚本并支持定时自动向群里汇报，毫秒级响应，不消耗大模型算力。
- **双向文件流转与断线补发**：群里的图片、语音、文档自动存进工作区供助手读取，助手生成的文件和长文报告也能直接发回群里；就算中途重启，断线期间漏接的消息也会自动补回。
- **默认白名单与随时打断**：默认只对白名单内的群组和成员响应，陌生人无法触发；任务跑偏时群里发一句 `/stop` 即可立刻中止。

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
