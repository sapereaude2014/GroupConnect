"""
CLI Entry point for GroupConnect Gateway.
Supports interactive initialization wizard (--init) for all 5 platforms and standard startup.
"""

import argparse
import asyncio
import json
import logging
import os
import signal
import sys

from groupconnect.core.config import GatewayConfig
from groupconnect.engine import GroupConnectEngine


def setup_logging(level: str = "INFO") -> None:
    log_format = "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO), format=log_format)


def run_init_wizard(config_path: str = "config.json") -> None:
    """Interactive CLI setup wizard to generate config.json for any supported platform."""
    print("=" * 60)
    print("🚀 Welcome to GroupConnect Multi-Platform Setup Wizard!")
    print("=" * 60)

    # 1. Select Platform
    print("1. Select your Messaging Platform:")
    print("   [1] Telegram (Default)")
    print("   [2] Discord")
    print("   [3] Slack")
    print("   [4] Feishu / Lark (飞书)")
    print("   [5] WeCom (企业微信)")
    platform_choice = input("   Choose platform [1-5, default: 1]: ").strip() or "1"
    platform_map = {
        "1": "telegram",
        "2": "discord",
        "3": "slack",
        "4": "feishu",
        "5": "wecom"
    }
    platform = platform_map.get(platform_choice, "telegram")

    config_data = {
        "platform": platform,
        "bot_name": "GroupConnect",
        "bot_username": "group_bot",
        "workspace_dir": "./workspace",
        "engine_type": "antigravity",
        "max_history_len": 30,
        "timeout_secs": 180,
        "session_idle_timeout_mins": 30,
        "max_chunk_size": 3800,
        "typing_interval_secs": 4.0,
        "allow_open_access": False,
        "allow_group_members_dm": True,
        "allowed_chat_ids": [],
        "allowed_user_ids": [],
        "allowed_usernames": []
    }

    # Platform Credentials
    if platform == "telegram":
        token = input("\n2. Enter Telegram Bot Token (from @BotFather): ").strip()
        while not token:
            token = input("   Token cannot be empty. Please enter your Bot Token: ").strip()
        config_data["bot_token"] = token
        username = input("   Enter Bot Username (without @, e.g. my_group_bot): ").strip().lstrip("@")
        config_data["bot_username"] = username or "my_group_bot"

    elif platform == "discord":
        token = input("\n2. Enter Discord Bot Token: ").strip()
        while not token:
            token = input("   Token cannot be empty. Please enter Discord Bot Token: ").strip()
        config_data["discord_bot_token"] = token
        config_data["bot_username"] = input("   Enter Bot Client ID / Username: ").strip() or "discord_bot"

    elif platform == "slack":
        token = input("\n2. Enter Slack Bot User OAuth Token (xoxb-...): ").strip()
        while not token:
            token = input("   Token cannot be empty. Please enter Slack Bot Token: ").strip()
        config_data["slack_bot_token"] = token
        config_data["bot_username"] = input("   Enter Slack Bot User ID / Name: ").strip() or "slack_bot"

    elif platform == "feishu":
        app_id = input("\n2. Enter Feishu App ID (cli_...): ").strip()
        app_secret = input("   Enter Feishu App Secret: ").strip()
        config_data["feishu_app_id"] = app_id
        config_data["feishu_app_secret"] = app_secret
        config_data["webhook_port"] = int(input("   Webhook listening port [default: 8088]: ").strip() or 8088)

    elif platform == "wecom":
        corp_id = input("\n2. Enter WeCom Corp ID (ww...): ").strip()
        corp_secret = input("   Enter WeCom App Secret: ").strip()
        agent_id = input("   Enter WeCom Agent ID [e.g. 1000002]: ").strip() or "1000002"
        config_data["wecom_corp_id"] = corp_id
        config_data["wecom_corp_secret"] = corp_secret
        config_data["wecom_agent_id"] = agent_id
        config_data["webhook_port"] = int(input("   Webhook listening port [default: 8089]: ").strip() or 8089)

    # 3. Select CLI Agent
    print("\n3. Select your local CLI Agent Harness:")
    print("   [1] Google Antigravity (agy - Default)")
    print("   [2] Anthropic Claude Code (claude)")
    print("   [3] OpenAI Codex (codex)")
    print("   [4] OpenCode (opencode)")
    engine_choice = input("   Choose engine [1-4, default: 1]: ").strip() or "1"
    engine_map = {"1": "antigravity", "2": "claude", "3": "codex", "4": "opencode"}
    config_data["engine_type"] = engine_map.get(engine_choice, "antigravity")

    # 4. Workspace Directory
    ws_dir = input("\n4. Enter local workspace path to attach [default: ./workspace]: ").strip() or "./workspace"
    config_data["workspace_dir"] = ws_dir

    # 5. Whitelist Setup
    admin_user = input("\n5. Enter your Admin Username / ID for initial allowlist [recommended]: ").strip()
    if admin_user:
        if admin_user.lstrip("-").isdigit():
            config_data["allowed_user_ids"] = [int(admin_user)]
        else:
            config_data["allowed_usernames"] = [admin_user.lstrip("@")]

    # Write Config File
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=2, ensure_ascii=False)

    print(f"\n✅ Configuration saved to {os.path.abspath(config_path)}!")
    print("👉 You can now start GroupConnect by running:")
    print(f"   python3 -m groupconnect.cli --config {config_path}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="GroupConnect: Group-Context Gateway for Local CLI Agents")
    parser.add_argument("-c", "--config", default="config.json", help="Path to config JSON file")
    parser.add_argument("--init", action="store_true", help="Run interactive setup wizard to generate config.json")
    parser.add_argument("--log-level", default="INFO", help="Logging level (DEBUG, INFO, WARNING, ERROR)")
    args = parser.parse_args()

    if args.init:
        run_init_wizard(args.config)
        return

    setup_logging(args.log_level)
    logger = logging.getLogger("groupconnect.cli")

    if not os.path.exists(args.config):
        print(f"⚠️ Config file '{args.config}' not found.")
        choice = input("Would you like to run the interactive setup wizard now? [Y/n]: ").strip().lower()
        if choice in ("", "y", "yes"):
            run_init_wizard(args.config)
            if not os.path.exists(args.config):
                sys.exit(1)
        else:
            logger.error(f"Please create {args.config} from config.example.json or run with --init.")
            sys.exit(1)

    try:
        config = GatewayConfig.from_file(args.config)
    except Exception as e:
        logger.error(f"Failed to load configuration file {args.config}: {e}")
        sys.exit(1)

    engine = GroupConnectEngine(config)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def handle_sigterm(*_):
        logger.info("Received termination signal. Gracefully shutting down...")
        engine.is_running = False
        if hasattr(engine.adapter, "close"):
            engine.adapter.close()
        loop.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, handle_sigterm)
        except NotImplementedError:
            pass

    try:
        loop.run_until_complete(engine.start())
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received. Stopping gateway...")
    finally:
        engine.is_running = False
        if hasattr(engine.adapter, "close"):
            engine.adapter.close()
        loop.close()
        logger.info("GroupConnect Gateway stopped cleanly.")


if __name__ == "__main__":
    main()
