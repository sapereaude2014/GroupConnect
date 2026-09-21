"""
Autonomous Routing (免@自主感知唤醒) for GroupConnect.

Architecture: Single-Arbiter + Symmetric Observers.
- Exactly ONE bot process (the arbiter, e.g. primary_bot) performs all
  semantic decisions (alias bypass / Flash-Lite tri-state classification).
- The decision is broadcast ONCE via the existing CrossBotRelay IPC.
- Both processes run the SAME observer code: if target_bot == self -> arm a
  countdown window; any other human message during the window cancels it;
  otherwise dispatch with reply anchoring.

Semantic content (aliases, roles, prompt template, windows, budget) is 100%
externalized in rules/autonomous_config.json + rules/router_prompt.txt.
"""

from .router import AutonomousController, AutonomousConfig

__all__ = ["AutonomousController", "AutonomousConfig"]
