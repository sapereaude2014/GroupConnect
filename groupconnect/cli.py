"""
CLI Entry point for GroupAgent Gateway.
"""

import argparse
import asyncio
import logging
import os
import signal
import sys

from groupconnect.core.config import GatewayConfig
from groupconnect.engine import GroupAgentEngine


def setup_logging(level: str = "INFO") -> None:
    log_format = "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO), format=log_format)


def main() -> None:
    parser = argparse.ArgumentParser(description="GroupAgent: Group-Native Local Agent Gateway")
    parser.add_argument("-c", "--config", default="config.json", help="Path to config JSON file")
    parser.add_argument("--log-level", default="INFO", help="Logging level (DEBUG, INFO, WARNING, ERROR)")
    args = parser.parse_args()

    setup_logging(args.log_level)
    logger = logging.getLogger("groupconnect.cli")

    if not os.path.exists(args.config):
        logger.error(f"Config file not found: {args.config}. Create one from config.example.json.")
        sys.exit(1)

    config = GatewayConfig.from_file(args.config)
    engine = GroupAgentEngine(config)

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
