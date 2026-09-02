"""
CLI Entry point for GroupConnect Gateway.
Supports dynamic initialization wizard (--init) for any registered platform and standard startup.
"""

import argparse
import asyncio
import json
import logging
import os
import signal
import sys

from groupconnect.adapters.base import ADAPTER_METADATA
from groupconnect.channels.base import CHANNEL_METADATA
from groupconnect.core.config import GatewayConfig
from groupconnect.engine import GroupConnectEngine


def setup_logging(level: str = "INFO") -> None:
    log_format = "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO), format=log_format)


def run_init_wizard(config_path: str = "config.json") -> None:
    """Interactive CLI setup wizard dynamically populated from Channel & Adapter registries."""
    print("=" * 60)
    print("🚀 Welcome to GroupConnect Dynamic Setup Wizard!")
    print("=" * 60)

    # 1. Dynamically list all registered platforms
    channels = list(CHANNEL_METADATA.values())
    print("1. Select your Messaging Platform:")
    for idx, c in enumerate(channels, 1):
        print(f"   [{idx}] {c.display_name}")

    p_choice = input(f"   Choose platform [1-{len(channels)}, default: 1]: ").strip() or "1"
    try:
        p_idx = int(p_choice) - 1
        if not (0 <= p_idx < len(channels)):
            p_idx = 0
    except ValueError:
        p_idx = 0

    selected_channel = channels[p_idx]
    platform = selected_channel.name

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

    # 2. Dynamically prompt for fields declared by the selected channel
    print(f"\n2. Configure {selected_channel.display_name} settings:")
    for f in selected_channel.fields:
        prompt_text = f"   • {f.label}"
        if f.default is not None:
            prompt_text += f" [default: {f.default}]"
        prompt_text += ": "
        val = input(prompt_text).strip()
        if not val and f.default is not None:
            val = str(f.default)
        if f.is_int:
            try:
                config_data[f.key] = int(val) if val else int(f.default or 0)
            except ValueError:
                config_data[f.key] = int(f.default or 0)
        else:
            config_data[f.key] = val

    # 3. Dynamically list all registered agent adapters
    adapters = list(ADAPTER_METADATA.values())
    print("\n3. Select your local CLI Agent Harness:")
    for idx, a in enumerate(adapters, 1):
        print(f"   [{idx}] {a.display_name}")

    a_choice = input(f"   Choose engine [1-{len(adapters)}, default: 1]: ").strip() or "1"
    try:
        a_idx = int(a_choice) - 1
        if not (0 <= a_idx < len(adapters)):
            a_idx = 0
    except ValueError:
        a_idx = 0

    config_data["engine_type"] = adapters[a_idx].name

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
