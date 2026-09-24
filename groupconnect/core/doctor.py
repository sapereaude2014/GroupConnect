"""
GroupConnect Doctor: Full-Stack Health & Environment Diagnostics.
Performs automated verification of Python runtime, platform APIs, Telegram privacy mode,
Agent CLIs, local workspaces, and Zero-@ routing connectivity.
"""

import os
import shutil
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore

from groupconnect.core.config import GatewayConfig


class Colors:
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BLUE = "\033[94m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RESET = "\033[0m"


class Doctor:
    def __init__(self, config: Optional[Any] = None):
        if isinstance(config, list):
            self.configs: List[GatewayConfig] = config
            self.config: Optional[GatewayConfig] = config[0] if config else None
        elif config is not None:
            self.configs = [config]
            self.config = config
        else:
            self.configs = []
            self.config = None
        self.passes: int = 0
        self.warnings: int = 0
        self.failures: int = 0

    def print_item(self, status: str, message: str, fix_suggestion: Optional[str] = None) -> None:
        if status == "pass":
            self.passes += 1
            print(f"  {Colors.GREEN}✓{Colors.RESET} {message}")
        elif status == "warn":
            self.warnings += 1
            print(f"  {Colors.YELLOW}!{Colors.RESET} {message}")
            if fix_suggestion:
                print(f"    {Colors.DIM}↳ 建议: {fix_suggestion}{Colors.RESET}")
        else:
            self.failures += 1
            print(f"  {Colors.RED}✗{Colors.RESET} {message}")
            if fix_suggestion:
                print(f"    {Colors.RED}↳ 修复命令: {fix_suggestion}{Colors.RESET}")

    def run_diagnostics(self) -> int:
        print(f"\n{Colors.BOLD}🩺 GroupConnect 系统诊断 (Doctor){Colors.RESET}")
        print("=" * 60)

        self._check_python_env()

        if self.configs:
            for cfg in self.configs:
                self.config = cfg
                self._check_channel()
                self._check_agent()
            self.config = self.configs[0]
            self._check_workspace()
            self._check_zero_at()
        else:
            print(f"\n[{Colors.BOLD}配置状态{Colors.RESET}]")
            self.print_item("fail", "未找到有效的配置文件 (groupconnect.yaml)", "运行 groupconnect init 快速生成")

        print("=" * 60)
        summary = f"诊断结果: {self.passes} 项通过"
        if self.warnings > 0:
            summary += f", {self.warnings} 项警告"
        if self.failures > 0:
            summary += f", {self.failures} 项错误"

        if self.failures > 0:
            print(f"{Colors.RED}{summary}{Colors.RESET}\n")
            return 1
        elif self.warnings > 0:
            print(f"{Colors.YELLOW}{summary}{Colors.RESET}\n")
            return 0
        else:
            print(f"{Colors.GREEN}{summary}，系统状态健康！{Colors.RESET}\n")
            return 0

    def _check_python_env(self) -> None:
        print(f"\n[{Colors.BOLD}1. 核心运行环境{Colors.RESET}]")
        # Python Version
        py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        if sys.version_info >= (3, 10):
            self.print_item("pass", f"Python 版本: {py_ver} (>= 3.10)")
        else:
            self.print_item("warn", f"Python 版本: {py_ver} (建议 >= 3.10)")

        # Required modules
        for mod in ("httpx", "yaml"):
            try:
                __import__(mod)
                self.print_item("pass", f"依赖库 {mod}: 已就绪")
            except ImportError:
                self.print_item("fail", f"缺少核心依赖库 {mod}", f"pip install {mod}")

    def _check_channel(self) -> None:
        bot_label = f"{self.config.platform} · @{self.config.bot_username}" if self.config.bot_username else self.config.platform
        print(f"\n[{Colors.BOLD}2. 消息平台连通性 ({bot_label}){Colors.RESET}]")
        if not self.config.bot_token:
            self.print_item("fail", "未配置 Bot Token", "在 .env 文件中设置 Bot Token，yaml 中用 ${VAR} 引用")
            return

        # Check .env file
        if self.config.config_path:
            env_file = os.path.join(os.path.dirname(self.config.config_path), ".env")
            if os.path.isfile(env_file):
                self.print_item("pass", ".env 文件已就绪")
            else:
                self.print_item("warn", "未找到 .env 文件", f"参考 .env.example 创建 {env_file}")

        if self.config.platform == "telegram":
            last_err = None
            for attempt in range(2):
                try:
                    with httpx.Client(timeout=8.0) as client:
                        resp = client.get(f"https://api.telegram.org/bot{self.config.bot_token}/getMe")
                        if resp.status_code == 200:
                            res = resp.json().get("result", {})
                            uname = res.get("username", "unknown")
                            name = res.get("first_name", "unnamed")
                            bot_id = res.get("id")
                            self.print_item("pass", f"Telegram API 连通: @{uname} ({name}, ID: {bot_id})")

                            # Check Privacy Mode (can_read_all_group_messages)
                            can_read_all = res.get("can_read_all_group_messages", False)
                            if not can_read_all:
                                self.print_item(
                                    "warn",
                                    f"Telegram Group Privacy Mode 处于开启状态！",
                                    f"私聊 @BotFather 发送 /setprivacy -> 选择 @{uname} -> 点击 Disable。否则群内免@无法捕获普通消息。"
                                )
                            else:
                                self.print_item("pass", "Telegram Privacy Mode 已关闭 (可接收群聊全量上下文)")
                            return
                        elif resp.status_code in (401, 404):
                            self.print_item("fail", f"Telegram Token 无效 (HTTP {resp.status_code})", "请核对 BotFather 分发的 Token")
                            return
                        else:
                            self.print_item("warn", f"Telegram API 响应异常: HTTP {resp.status_code}")
                            return
                except Exception as e:
                    last_err = e
            self.print_item("warn", f"无法连接 Telegram API ({last_err})", "请检查网络或代理连通性")
        else:
            self.print_item("pass", f"平台 {self.config.platform} Token 已声明")

    def _check_agent(self) -> None:
        bot_label = f"{self.config.engine_type} · @{self.config.bot_username}" if self.config.bot_username else self.config.engine_type
        print(f"\n[{Colors.BOLD}3. 本地 Agent 驱动 ({bot_label}){Colors.RESET}]")
        engine = self.config.engine_type

        # Find binary
        bin_mapping = {
            "codex": self.config.codex_bin,
            "claude": self.config.claude_bin,
            "claude_code": self.config.claude_bin,
            "antigravity": self.config.agy_bin,
            "opencode": self.config.opencode_bin,
            "teleagent": self.config.teleworker_bin,
        }
        target_bin = bin_mapping.get(engine, engine)
        bin_path = shutil.which(target_bin) or (target_bin if os.path.isfile(target_bin) else None)

        if not bin_path:
            self.print_item("fail", f"未找到 Agent 可执行文件: '{target_bin}'", f"请安装并确认 '{target_bin}' 在 PATH 中")
            return

        self.print_item("pass", f"Agent 二进制已就绪: {bin_path}")

        # Check version / execution
        try:
            res = subprocess.run([bin_path, "--version"], capture_output=True, text=True, timeout=5)
            if res.returncode == 0:
                ver_line = res.stdout.strip().splitlines()[0] if res.stdout.strip() else "OK"
                self.print_item("pass", f"Agent 版本正常: {ver_line}")
            else:
                self.print_item("pass", f"Agent 可执行权限正常")
        except Exception:
            self.print_item("pass", f"Agent 可执行文件存在")

        # Check Auth
        if engine == "codex":
            auth_file = os.path.expanduser("~/.codex")
            if not os.path.exists(auth_file):
                self.print_item("warn", "Codex 认证凭证未检测到", "codex login")
            else:
                self.print_item("pass", "Codex 本地认证已存在")
        elif engine in ("claude", "claude_code"):
            auth_file = os.path.expanduser("~/.claude")
            if not os.path.exists(auth_file):
                self.print_item("warn", "Claude Code 认证凭证未检测到", "claude login")
            else:
                self.print_item("pass", "Claude Code 本地认证已存在")
        elif engine == "antigravity":
            auth_file = os.path.expanduser("~/.gemini")
            if not os.path.exists(auth_file):
                self.print_item("warn", "Antigravity 凭据未检测到 (~/.gemini)", "agy auth")
            else:
                self.print_item("pass", "Antigravity 本地认证已就绪")

    def _check_workspace(self) -> None:
        print(f"\n[{Colors.BOLD}4. 工作空间与存储{Colors.RESET}]")
        ws = self.config.workspace_dir
        if not os.path.exists(ws):
            try:
                os.makedirs(ws, exist_ok=True)
                self.print_item("pass", f"工作空间目录已自动创建: {ws}")
            except Exception as e:
                self.print_item("fail", f"无法创建工作空间目录 {ws}: {e}", f"chmod 755 {ws}")
                return
        else:
            self.print_item("pass", f"工作空间有效: {ws}")

        # Check writable
        probe_file = os.path.join(ws, ".write_test")
        try:
            with open(probe_file, "w") as f:
                f.write("probe")
            os.remove(probe_file)
            self.print_item("pass", "工作空间写入权限正常")
        except Exception as e:
            self.print_item("fail", f"工作空间不可写: {e}", f"chmod -R u+w {ws}")

        # Check IPC Dir
        ipc = self.config.ipc_dir
        if os.path.exists(ipc) and os.access(ipc, os.W_OK):
            self.print_item("pass", f"IPC 通信管道目录正常: {ipc}")
        else:
            self.print_item("warn", f"IPC 目录异常: {ipc}", f"mkdir -p {ipc} && chmod 777 {ipc}")

    def _check_zero_at(self) -> None:
        print(f"\n[{Colors.BOLD}5. 智能免 @ (Zero-@) 决策引擎{Colors.RESET}]")
        acfg = self.config.autonomous_config
        if not acfg or not acfg.enabled:
            self.print_item("warn", "Zero-@ 处于未启用状态", "在配置中添加 zero_at: true 开启智能群聊插话")
            return

        self.print_item("pass", f"Zero-@ 已启用 (静默窗口: {acfg.silence_secs}s, 上下文深度: {acfg.context_window_size})")

        # Provider Key check
        provider_name = acfg.active_provider
        api_key = acfg.api_key
        if not api_key:
            env_map = {
                "jev": "JEV_API_KEY",
                "openai": "OPENAI_API_KEY",
                "llm": "OPENAI_API_KEY",
                "anthropic": "ANTHROPIC_API_KEY",
                "gemini": "GEMINI_API_KEY",
            }
            expected_env = env_map.get(acfg.engine, "JEV_API_KEY")
            self.print_item(
                "fail",
                f"分类器 [{acfg.engine}] 缺少 API Key",
                f"配置环境变量 {expected_env} 或在 groupconnect.yaml 的 zero_at.classifier.api_key 中指定"
            )
        else:
            masked = api_key[:4] + "..." + api_key[-4:] if len(api_key) > 8 else "***"
            self.print_item("pass", f"分类器 [{acfg.engine}] API Key 已就绪 ({masked})")

        # Rules Check
        if acfg.rule_templates:
            self.print_item("pass", f"决策规则模板生效中 ({len(acfg.rule_templates)} 类规则)")
        else:
            self.print_item("warn", "使用内置兜底决策规则")
