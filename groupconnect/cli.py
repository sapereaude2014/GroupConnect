"""
CLI Entry point for GroupConnect Gateway.
Supports interactive initialization wizard (--init) and standard startup.
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
    """Interactive CLI setup wizard to generate config.json effortlessly."""
    print("=" * 60)
    print("🚀 Welcome to GroupConnect Setup Wizard!")
    print("=" * 60)

    token = input("1. Enter your Telegram Bot Token (from @BotFather): ").strip()
    while not token:
        token = input("   Token cannot be empty. Please enter your Bot Token: ").strip()

    bot_username = input("2. Enter your Bot Username (without @, e.g. my_group_bot): ").strip().lstrip("@")
    if not bot_username:
        bot_username = "my_group_bot"

    print("\n3. Select your local CLI Agent Harness:")
    print("   [1] Google Antigravity (agy)")
    print("   [2] Anthropic Claude Code (claude)")
    print("   [3] OpenAI Codex (codex)")
    print("   [4] OpenCode (opencode)")
    engine_choice = input("   Choose engine [1-4, default: 1]: ").strip() or "1"
    engine_map = {"1": "antigravity", "2": "claude", "3": "codex", "4": "opencode"}
    engine_type = engine_map.get(engine_choice, "antigravity")

    ws_dir = input("\n4. Enter local workspace path to attach [default: ./workspace]: ").strip() or "./workspace"

    whitelist_chat = input("\n5. (Optional) Allowed Telegram Group Chat ID [leave empty to allow all]: ").strip()
    allowed_chat_ids = [int(whitelist_chat)] if (whitelist_chat and whitelist_chat.lstrip("-").isdigit()) else []

    config_data = {
        "platform": "telegram",
        "bot_token": token,
        "bot_username": bot_username,
        "bot_name": "GroupConnect",
        "workspace_dir": ws_dir,
        "engine_type": engine_type,
        "max_history_len": 30,
        "timeout_secs": 180,
        "session_idle_timeout_mins": 30,
        "max_chunk_size": 3800,
        "typing_interval_secs": 4.0,
        "allowed_chat_ids": allowed_chat_ids,
        "allowed_user_ids": [],
        "allowed_usernames": []
    }

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

    config = GatewayConfig.from_file(args.config)
    engine = GroupConnectEngine(config)

    def shutdown(sig, frame):
        logger.info("Shutdown signal received, closing engine...")
        engine.is_running = False
        engine.adapter.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        asyncio.run(engine.start())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
