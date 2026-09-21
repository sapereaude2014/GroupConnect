"""
Autonomous Routing (免@自主感知唤醒) for GroupConnect.

Architecture: Single-Arbiter + Symmetric Observers.
- Exactly ONE bot process (the arbiter, e.g. primary_bot) performs all
  semantic decisions (alias bypass / Flash-Lite tri-state classification).
- The decision is broadcast ONCE via the existing CrossBotRelay IPC.
- Both processes run the SAME observer code: if target_bot == self -> arm a
  countdown window; any other human message during the window cancels it;
  otherwise dispatch with reply anchoring.

Semantic content (aliases, roles, windows, budget, classifier provider
registry) is 100% externalized in autonomous_config.json. The classifier
block is a self-describing registry: 'active' selects the live backend,
each 'providers.<name>' entry declares its own engine (jev | gemini),
model, API key and engine-specific resources (e.g. prompt_template for
the gemini engine). Shared decision wording lives in routing_rules.md -
the single source of truth consumed by every engine.
"""

from .router import AutonomousController, AutonomousConfig

__all__ = ["AutonomousController", "AutonomousConfig"]
