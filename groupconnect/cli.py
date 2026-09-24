"""
GroupConnect CLI: Gateway Entrypoint, Initialization Wizard, Doctor, and Local Simulator.
"""

import argparse
import asyncio
import glob
import logging
import os
import shutil
import signal
import sys
from typing import List, Optional

import httpx

from groupconnect.adapters.base import ADAPTER_METADATA
from groupconnect.channels.base import CHANNEL_METADATA
from groupconnect.core.config import GatewayConfig, load_raw_config_file
from groupconnect.core.doctor import Doctor
from groupconnect.core.simulator import run_group_simulator
from groupconnect.engine import GroupConnectEngine

logger = logging.getLogger("groupconnect.cli")


def setup_logging(level: str = "INFO") -> None:
    log_format = "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO), format=log_format)


def detect_installed_agents() -> List[dict]:
    """Detects which supported CLI agent harnesses are installed on PATH."""
    candidates = [
        {"engine": "codex", "name": "Codex", "bins": ["codex"]},
        {"engine": "claude", "name": "Claude Code", "bins": ["claude"]},
        {"engine": "antigravity", "name": "Antigravity", "bins": ["agy", "antigravity"]},
        {"engine": "opencode", "name": "OpenCode", "bins": ["opencode"]},
        {"engine": "teleagent", "name": "TeleAgent", "bins": ["tele-worker", "teleagent"]},
    ]
    detected = []
    for c in candidates:
        found_bin = None
        for b in c["bins"]:
            p = shutil.which(b)
            if p:
                found_bin = p
                break
        detected.append({
            "engine": c["engine"],
            "name": c["name"],
            "bin": found_bin,
            "installed": found_bin is not None
        })
    return detected


def run_init_wizard(target_path: Optional[str] = None) -> None:
    """Streamlined 5-step interactive setup wizard."""
    print("=" * 65)
    print("🚀 欢迎使用 GroupConnect 配置向导 (Init Wizard)")
    print("=" * 65)
    print("只需回答 5 个问题，即可自动生成精炼配置并启用 Zero-@ 智能群聊。\n")

    # 1. Platform Selection
    channels = list(CHANNEL_METADATA.values())
    print("① 选择群聊接入平台:")
    for idx, c in enumerate(channels, 1):
        print(f"   [{idx}] {c.display_name}")
    p_choice = input(f"   选择平台 [1-{len(channels)}, 默认: 1]: ").strip() or "1"
    try:
        p_idx = int(p_choice) - 1
        if not (0 <= p_idx < len(channels)):
            p_idx = 0
    except ValueError:
        p_idx = 0
    selected_channel = channels[p_idx]
    platform = selected_channel.name

    # 2. Token Prompt & Live Verification
    print(f"\n② 请输入 {selected_channel.display_name} Bot Token:")
    bot_token = input("   Token: ").strip()

    bot_username = "my_assistant_bot"
    bot_name = "GroupConnect Assistant"
    privacy_mode_warn = False

    if platform == "telegram" and bot_token:
        print("   🔍 正在连接 Telegram API 验证 Token...")
        try:
            with httpx.Client(timeout=6.0) as client:
                r = client.get(f"https://api.telegram.org/bot{bot_token}/getMe")
                if r.status_code == 200:
                    info = r.json().get("result", {})
                    bot_username = info.get("username", bot_username)
                    bot_name = info.get("first_name", bot_name)
                    print(f"   ✓ 验证成功: @{bot_username} ({bot_name})")
                    if not info.get("can_read_all_group_messages", False):
                        privacy_mode_warn = True
                else:
                    print(f"   ⚠️ Token 校验返回 HTTP {r.status_code}，请稍后在配置中复核。")
        except Exception as e:
            print(f"   ⚠️ 临时网络连通提示: {e} (已保留输入的 Token)")

    # 3. Agent Detection & Selection
    agents = detect_installed_agents()
    print("\n③ 选择接入的本地 Agent 引擎:")
    recommended_idx = 0
    for idx, a in enumerate(agents, 1):
        tag = f"已就绪: {a['bin']}" if a["installed"] else "未检测到"
        print(f"   [{idx}] {a['name']:<14} ({tag})")
        if a["installed"] and recommended_idx == 0:
            recommended_idx = idx

    default_choice = str(recommended_idx or 1)
    a_choice = input(f"   选择引擎 [1-{len(agents)}, 默认: {default_choice}]: ").strip() or default_choice
    try:
        a_idx = int(a_choice) - 1
        if not (0 <= a_idx < len(agents)):
            a_idx = 0
    except ValueError:
        a_idx = 0
    selected_agent = agents[a_idx]

    # 4. Workspace Directory
    ws_dir = input("\n④ Agent 挂载的本地工作空间路径 [默认: ./workspace]: ").strip() or "./workspace"
    ws_dir = os.path.expanduser(ws_dir)
    os.makedirs(ws_dir, exist_ok=True)

    # 5. Zero-@ Autonomous Routing
    print("\n⑤ 开启免 @ 智能插话 (Zero-@ 决策引擎)?")
    zero_choice = input("   开启智能插话 [Y/n, 默认: Y]: ").strip().lower()
    enable_zero = zero_choice not in ("n", "no")

    jev_key = os.environ.get("JEV_API_KEY", "")
    if enable_zero:
        if jev_key:
            print("   ✓ 检测到环境变量 JEV_API_KEY 已存在，将直接复用。")
        else:
            k_input = input("   请输入 JEV_API_KEY (可回车留空，后续在环境变量或配置中添加): ").strip()
            if k_input:
                jev_key = k_input

    # Generate groupconnect.yaml
    out_file = target_path or "groupconnect.yaml"
    if not out_file.endswith((".yaml", ".yml")):
        out_file = "groupconnect.yaml"

    yaml_lines = [
        "# ================================================================",
        "# GroupConnect Configuration File",
        "# ================================================================",
        "",
        "# 1. Bot 与本地执行 Agent (多 Bot 协同或跨平台部署直接在列表下继续追加)",
        "bots:",
        f'  - name: "{bot_name}"',
        f'    username: "{bot_username}"',
        f"    platform: {platform}",
        f'    token: "{bot_token}"',
        '    role: "通用主力助手，负责解答问题与执行工作区任务"',
        "    aliases: []",
        "    agent:",
        f"      engine: {selected_agent['engine']}",
        f'      workspace: "{ws_dir}"',
        "",
        "# 2. 智能免 @ (Zero-@ 决策路由，默认读取系统环境变量 JEV_API_KEY)",
        "zero_at:",
        f"  enabled: {'true' if enable_zero else 'false'}",
    ]
    if enable_zero and jev_key and not os.environ.get("JEV_API_KEY"):
        yaml_lines.extend([
            "  classifier:",
            "    engine: jev",
            f'    api_key: "{jev_key}"',
        ])

    yaml_lines.extend([
        "",
        "# 4. 安全访问控制 (可选白名单)",
        "security:",
        "  allow_open_access: false",
        "  allow_group_members_dm: true",
        "  # allowed_chat_ids: [-100123456789]",
        "  # allowed_usernames: [\"admin\"]",
        "",
    ])

    with open(out_file, "w", encoding="utf-8") as f:
        f.write("\n".join(yaml_lines))

    print(f"\n✅ 配置文件已生成: {os.path.abspath(out_file)}")

    if privacy_mode_warn:
        print("\n" + "!" * 65)
        print("⚠️  重要提醒: Telegram 群内免@插话设置")
        print(f"当前 Bot 的 Privacy Mode 为开启状态。")
        print(f"👉 请私聊 @BotFather 发送 /setprivacy -> 选择 @{bot_username} -> Disable")
        print("关闭后，Bot 才能在群组中接收普通消息以实现智能免@分析。")
        print("!" * 65)

    print("\n👉 接下来您可以：")
    print(f"   • 诊断环境: groupconnect doctor -c {out_file}")
    print(f"   • 终端模拟: groupconnect test -c {out_file}")
    print(f"   • 启动网关: groupconnect run -c {out_file}\n")


def resolve_config_path(explicit_path: Optional[str]) -> str:
    """Finds the active configuration file, preferring CWD then ~/.config/groupconnect."""
    if explicit_path:
        return os.path.expanduser(explicit_path)

    env_cfg = os.environ.get("GROUPCONNECT_CONFIG")
    if env_cfg and os.path.exists(os.path.expanduser(env_cfg)):
        return os.path.expanduser(env_cfg)

    # Priority 1: CWD groupconnect.yaml / groupconnect.yml
    for name in ("groupconnect.yaml", "groupconnect.yml"):
        if os.path.exists(name):
            return name

    # Priority 2: CWD config.json / config.*.json
    if os.path.exists("config.json"):
        return "config.json"

    matches = glob.glob("config.*.json")
    if matches:
        return matches[0]

    # Priority 3: XDG ~/.config/groupconnect/groupconnect.yaml
    for p in ("~/.config/groupconnect/groupconnect.yaml", "~/.config/groupconnect/groupconnect.yml"):
        expanded = os.path.expanduser(p)
        if os.path.exists(expanded):
            return expanded

    return "groupconnect.yaml"


def main() -> None:
    common_parser = argparse.ArgumentParser(add_help=False)
    common_parser.add_argument("-c", "--config", default=None, help="Path to config file (groupconnect.yaml / config.json)")
    common_parser.add_argument("--bot", default=None, help="Specific bot name to run (for multi-bot configs)")
    common_parser.add_argument("--log-level", default="INFO", help="Logging level (DEBUG, INFO, WARNING, ERROR)")

    parser = argparse.ArgumentParser(
        prog="groupconnect",
        parents=[common_parser],
        description="GroupConnect: Group-Native, Context-Aware Local Agent Gateway"
    )

    # Legacy flags for compatibility
    parser.add_argument("--init", action="store_true", help="Run interactive setup wizard")
    parser.add_argument("--doctor", action="store_true", help="Run system diagnostics")
    parser.add_argument("--test", action="store_true", help="Run terminal group sandbox simulator")

    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")
    
    # Subcommands
    subparsers.add_parser("init", parents=[common_parser], help="Run interactive setup wizard")
    subparsers.add_parser("doctor", parents=[common_parser], help="Check system health, platform connectivity, and Agent status")
    subparsers.add_parser("test", parents=[common_parser], help="Simulate group chat in terminal to verify Zero-@ routing")
    subparsers.add_parser("run", parents=[common_parser], help="Start the GroupConnect Gateway")

    args = parser.parse_args()

    cmd = args.command or ("init" if args.init else "doctor" if args.doctor else "test" if args.test else "run")

    if cmd == "init":
        run_init_wizard(args.config)
        return

    config_path = resolve_config_path(args.config)

    if cmd == "doctor":
        cfgs: List[GatewayConfig] = []
        if os.path.exists(config_path):
            try:
                if args.bot:
                    cfgs = [GatewayConfig.from_file(config_path, bot_name=args.bot)]
                else:
                    cfgs = GatewayConfig.load_all_from_file(config_path)
            except Exception as e:
                print(f"⚠️ 解析配置文件 '{config_path}' 时出错: {e}")
        doc = Doctor(cfgs)
        sys.exit(doc.run_diagnostics())

    if not os.path.exists(config_path):
        print(f"⚠️ 未找到配置文件 '{config_path}'。")
        choice = input("是否立即运行向导生成配置？ [Y/n]: ").strip().lower()
        if choice in ("", "y", "yes"):
            run_init_wizard(config_path)
            if not os.path.exists(config_path):
                sys.exit(1)
        else:
            sys.exit(1)

    # Load configuration
    try:
        if args.bot:
            configs = [GatewayConfig.from_file(config_path, bot_name=args.bot)]
        else:
            configs = GatewayConfig.load_all_from_file(config_path)
    except Exception as e:
        logger.error(f"Failed to load config from {config_path}: {e}", exc_info=True)
        sys.exit(1)

    if cmd == "test":
        asyncio.run(run_group_simulator(configs[0]))
        return

    # cmd == "run"
    setup_logging(args.log_level)
    run_gateway(configs)


def run_gateway(configs: List[GatewayConfig]) -> None:
    """Launches one or more bot engines concurrently."""
    engines = [GroupConnectEngine(cfg) for cfg in configs]
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    engine_tasks: List[asyncio.Task] = []

    def _shutdown() -> None:
        for eng in engines:
            eng.is_running = False
            if hasattr(eng, "channel"):
                eng.channel.is_running = False
        for t in engine_tasks:
            if not t.done():
                t.cancel()

    def _sig_handler(sig, frame):
        logger.info(f"Received signal {sig}. Initiating graceful shutdown...")
        loop.call_soon_threadsafe(_shutdown)

    signal.signal(signal.SIGINT, _sig_handler)
    signal.signal(signal.SIGTERM, _sig_handler)

    async def _start_all():
        if len(engines) > 1:
            logger.info(f"Starting Multi-Bot Gateway with {len(engines)} bot instances...")
        for eng in engines:
            engine_tasks.append(asyncio.create_task(eng.start()))
        await asyncio.gather(*engine_tasks, return_exceptions=True)

    try:
        loop.run_until_complete(_start_all())
    except KeyboardInterrupt:
        logger.info("Interrupted by user.")
    finally:
        loop.close()


if __name__ == "__main__":
    main()
