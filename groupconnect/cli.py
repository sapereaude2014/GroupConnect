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
from typing import Optional

from groupconnect.adapters.base import ADAPTER_METADATA
from groupconnect.channels.base import CHANNEL_METADATA
from groupconnect.core.config import GatewayConfig
from groupconnect.engine import GroupConnectEngine


def setup_logging(level: str = "INFO") -> None:
    log_format = "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO), format=log_format)


def run_init_wizard(target_config_path: Optional[str] = None) -> None:
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

    # 6. Smart Config Path Resolution (Prevents accidental overwrites)
    default_filename = f"config.{platform}.json"
    if target_config_path and target_config_path != "config.json":
        chosen_path = target_config_path
    else:
        save_prompt = input(f"\n6. Save configuration filename [default: {default_filename}]: ").strip()
        chosen_path = save_prompt or default_filename

    # Write Config File
    with open(chosen_path, "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=2, ensure_ascii=False)

    print(f"\n✅ Configuration saved to {os.path.abspath(chosen_path)}!")
    print("👉 You can now start GroupConnect by running:")
    print(f"   python3 -m groupconnect.cli --config {chosen_path}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="GroupConnect: Group-Context Gateway for Local CLI Agents")
    parser.add_argument("-c", "--config", default=None, help="Path to config JSON file")
    parser.add_argument("--init", action="store_true", help="Run interactive setup wizard to generate config")
    parser.add_argument("--log-level", default="INFO", help="Logging level (DEBUG, INFO, WARNING, ERROR)")
    args = parser.parse_args()

    if args.init:
        run_init_wizard(args.config)
        return

    setup_logging(args.log_level)
    logger = logging.getLogger("groupconnect.cli")

    config_file = args.config
    if not config_file:
        if os.path.exists("config.json"):
            config_file = "config.json"
        else:
            # Check for any config.*.json
            import glob
            configs = glob.glob("config.*.json")
            if len(configs) == 1:
                config_file = configs[0]
                logger.info(f"Auto-detected configuration file: {config_file}")
            elif len(configs) > 1:
                print("Found multiple configuration files:")
                for i, c in enumerate(configs, 1):
                    print(f"  [{i}] {c}")
                pick = input(f"Select config [1-{len(configs)}, default: 1]: ").strip() or "1"
                try:
                    config_file = configs[int(pick) - 1]
                except Exception:
                    config_file = configs[0]
            else:
                config_file = "config.json"

    if not os.path.exists(config_file):
        print(f"⚠️ Config file '{config_file}' not found.")
        choice = input("Would you like to run the interactive setup wizard now? [Y/n]: ").strip().lower()
        if choice in ("", "y", "yes"):
            run_init_wizard(config_file)
            if not os.path.exists(config_file):
                sys.exit(1)
        else:
            logger.error("Please create a configuration file or run with --init.")
            sys.exit(1)

    try:
        config = GatewayConfig.from_file(config_file)
    except Exception as e:
        logger.error(f"Failed to load configuration file {config_file}: {e}")
        sys.exit(1)

    engine = GroupConnectEngine(config)

    async def _runner():
        loop = asyncio.get_running_loop()
        stop_event = asyncio.Event()

        def _signal_handler():
            logger.info("Received termination signal. Gracefully shutting down...")
            engine.is_running = False
            if hasattr(engine.adapter, "close"):
                engine.adapter.close()
            stop_event.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _signal_handler)
            except NotImplementedError:
                pass

        engine_task = asyncio.create_task(engine.start())
        stop_wait_task = asyncio.create_task(stop_event.wait())

        done, pending = await asyncio.wait([engine_task, stop_wait_task], return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
        if hasattr(engine.adapter, "close"):
            engine.adapter.close()
        logger.info("GroupConnect Gateway stopped cleanly.")

    try:
        asyncio.run(_runner())
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received. Stopping gateway...")


if __name__ == "__main__":
    main()
