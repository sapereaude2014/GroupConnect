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

- **免 @ 自主感知**：群聊中自然交流，机器人读懂上下文自动判断该不该接单，闲聊沉默，有疑问让群友先回。
- **多助手默契配合**：群里部署多个专职 bot，懂调度（"A 让 B 去查" → 只 A 接单）和并联（"你俩都看看" → 一起回）。
- **群聊上下文记忆**：重启不丢上下文，图片和文档自动保存到工作区供 Agent 读取。
- **默认安全锁定**：严格白名单，未授权用户无法触发任何命令；`/stop` 一键强杀进程。
- **智能路由引擎**：轻量分类器（Jev 200ms）先判断该不该回、谁来回，只在需要时才唤醒重型 Agent；支持 `openai` / `anthropic` / `gemini` 协议。
- **即时设备控制**：说"开卧室灯"等短句直接触发本地脚本，毫秒级响应，不经过任何 AI。

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

- **完整配置与全参数注释**：详见 [`groupconnect.example.yaml`](groupconnect.example.yaml)（涵盖多 Bot 协同、本地 Agent 绑定、自定义斜杠命令、正则快车道、Zero-@ 分类器与安全白名单）。
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
