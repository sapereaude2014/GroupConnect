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

- **免 @ 自然感知**：群成员像平常一样交流，机器人结合上下文自动判断该不该接单，闲聊时保持静默，开放性提问预留 4 秒让群友先回。
- **多助手默契配合**：群里同时部署多个专职 bot，听得懂主从调度（"A 让 B 去跑测试" → 只 A 接单）和组合协同（"A 和 B 都看看" → 两个都响应）。
- **群聊记忆中枢**：滑动上下文窗口从磁盘秒级恢复；图片和文档自动保存到工作区供 Agent 读取。
- **默认安全锁定**：严格白名单机制，未授权用户无法执行本地命令；`/stop` 一键强杀进程树。
- **轻量分诊分类器**：内置路由规则并支持 YAML 槽位热替换，仅在需要回复时才唤醒本地重型 Agent；支持 TypeSafe Jev（100~200ms）及主流大模型协议（`openai` / `anthropic` / `gemini`）与自定义 `base_url`。
- **0-Token 快车道**：正则匹配自然语言短句（如"开卧室灯"），直接执行本地脚本，完全绕过 LLM。

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

## ⚙️ 配置文件：`groupconnect.yaml`

每条 Bot 直接绑定自身所属的聊天平台（`platform`）、凭证（`token`）与本地执行 Agent（`agent`）。单 Bot 写 1 项，多 Bot 协同或跨平台部署直接往下追加即可（同平台首项默认作为主裁决官 Arbiter 负责调度）：

```yaml
bots:
  - name: "代码助手"
    username: "coder_bot"
    platform: telegram
    token: ${CODER_BOT_TOKEN}     # 用 ${ENV_VAR} 注入敏感信息，配置文件可安全入库
    role: "负责代码编写与 Bug 修复"
    aliases: ["码农", "coder"]
    # souls_dir: ~/souls        # 可选：从该目录加载 {username}.md 人设文件
    agent:
      engine: codex             # codex | claude | antigravity | opencode | teleagent
      workspace: ~/workspace

  # 如需同群多 Bot 协同（或跨平台托管其他 Bot），直接追加：
  # - name: "架构评审"
  #   username: "reviewer_bot"
  #   platform: telegram
  #   token: "987654321:BBG..."
  #   role: "负责架构审查与代码审计"
  #   aliases: ["评审", "reviewer"]
  #   agent:
  #     engine: claude
  #     workspace: ~/workspace

zero_at:
  enabled: true                 # 默认使用 Jev 分类器（100~200ms），自动读取系统环境变量 JEV_API_KEY
```

### 分类器配置（可选）

默认无需配置 `classifier`（自动使用 **Jev** 并从环境变量读取 `JEV_API_KEY`）。仅在需要切换为其他大模型协议或自定义接口地址时按需添加：

```yaml
zero_at:
  enabled: true
  classifier:
    engine: openai                        # 协议类型: jev (默认) | openai | anthropic | gemini
    model: deepseek-chat                  # 分类模型名称
    base_url: https://api.deepseek.com/v1 # 可选：自定义 API Base URL（不填则使用对应协议官方默认端点）
    # api_key: ""                         # 可选：不填则按 engine 自动读取环境变量 JEV_API_KEY / OPENAI_API_KEY / ANTHROPIC_API_KEY / GEMINI_API_KEY
```

### 自定义斜杠指令与快车道

`custom_commands` 注册后即为斜杠指令（如 `/backup`），与内置指令同类，会出现在 `/help` 和平台菜单中。`pattern_commands` 则是自然语言正则直通，无需 `/` 前缀，完全绕过 LLM：

```yaml
custom_commands:
  - command: backup
    description: "备份工作区"
    script: "scripts/backup.sh"
    lock: true
    schedule:
      weekday: 6
      hour: 4

pattern_commands:
  - pattern: '^(开|关)(灯|空调)(\d{1,2})?$'
    script: "scripts/device.py"
    # pass_args: true 和 lock: true 为默认值，无需声明
```

### 安全与崩溃恢复

默认即开即用（默认拦截、默认 5 分钟恢复窗口），按需微调：

```yaml
security:
  allow_open_access: false       # 默认：拦截所有未授权群组与用户
  allow_group_members_dm: true   # 允许白名单群成员私聊 Bot
  # allowed_chat_ids: [-100123456789]
  # allowed_user_ids: [123456789]

tuning:
  resume_unanswered_secs: 300   # 重启时补发 N 秒内未获回复的消息（0 关闭）
  max_history_len: 30           # 内存上下文滑动窗口轮数
```

完整字段见 [`groupconnect.example.yaml`](groupconnect.example.yaml)。

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
