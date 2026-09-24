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

- **免 @ 自主感知与轻量路由**：群聊中自然交流，前置轻量分类器（默认 Jev ~200ms，支持切换 `openai` / `anthropic` / `gemini`）先读懂上下文判断该不该接单、由谁接单——闲聊保持沉默，确需处理时才唤醒重型本地 Agent。
- **异构多 Bot 协同与独立人设**：同群或跨平台可部署多个专职 Bot（各自可绑定不同的本地引擎如 `Claude Code`、`Antigravity`、`Codex`、`TeleAgent` 及独立人设 `souls/{username}.md`），自动支持**定向调度**（"A 让 B 去查" → 只 A 接单）与**并联会诊**（"你俩都看看" → 同时回复）。
- **正则快车道与自定义斜杠命令**：
  - **零延迟快车道 (`pattern_commands`)**：说“开卧室灯”等短句直接命中正则调用本地脚本，毫秒级响应，完全绕过 LLM；
  - **斜杠命令与定时广播 (`custom_commands`)**：将本地脚本注册为平台 `/` 菜单指令（如 `/backup`），内置健康预检、防并发互斥锁与定时巡检广播。
- **持久化上下文、双向文件与长文折叠**：重启不丢上下文并**自动补发断线期间漏接的消息**；群内图片、语音、文档自动落盘工作区供 Agent 读取，Agent 生成的图表与报告可通过 `【SendFile: /path】` 自动回传群聊，超长回复自动折叠或发布为 Telegraph 页面。
- **默认安全锁定与进程强控**：默认拦截所有未授权群组与用户，支持白名单与路由规则热重载；群内发送 `/stop` 一键强杀底层正在运行的 Agent 进程树。
- **全栈体检与终端沙盒**：内置 `init` 交互向导、`doctor` 全链路诊断（自动核查平台连通性、Telegram 隐私模式与本地二进制）及 `test` 终端群聊模拟器。

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
groupconnect init      # 交互式 5 步生成配置
groupconnect doctor    # 启动前全链路健康体检
groupconnect test      # 可选：在终端沙盒模拟群聊与免 @ 分流
groupconnect run       # 启动网关（Ctrl+C 停止）
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
